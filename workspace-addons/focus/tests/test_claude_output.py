"""The Claude reader keeps the last lines of a shell step's output (data.output) and never leaks a secret (R5.2)."""

import json
from pathlib import Path

import jsonschema

from orch_focus import events as ev
from orch_focus.adapters.claude import ClaudeMapper, output_tail

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/addons/focus/run-event.schema.json").read_text()
)
RUN, TID = "r_8k2m9z4q", "t_inv7c2"
GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3"
SK = "sk-" + "proj1234567890abcdefXYZ"
PEM = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\nabcdefghijklmnop\n-----END PRIVATE KEY-----"


def run(name, inp, result, is_error=False):
    m = ClaudeMapper(RUN, TID)
    t = "2026-11-05T09:12:05Z"
    out = m.feed(
        {
            "type": "assistant",
            "timestamp": t,
            "message": {"content": [{"type": "tool_use", "id": "toolu_1", "name": name, "input": inp}]},
        }
    )
    out += m.feed(
        {
            "type": "user",
            "timestamp": "2026-11-05T09:12:08Z",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1", "content": result, "is_error": is_error}
                ]
            },
        }
    )
    for e in out:
        jsonschema.validate(e, SCHEMA)
    return out


def test_bash_output_keeps_line_breaks_and_text_stays_one_line():
    start, end = run("Bash", {"command": "pytest -q"}, "collected 3\n...\n3 passed in 0.1s")
    assert start["data"]["command"] == "pytest -q"
    assert end["data"]["output"] == "collected 3\n...\n3 passed in 0.1s"
    assert "\n" not in end["text"] and end["text"] == "collected 3 ... 3 passed in 0.1s"


def test_only_the_last_40_lines_and_4000_characters():
    many = "\n".join(f"line {i}" for i in range(100))
    out = run("Bash", {"command": "x"}, many)[1]["data"]["output"]
    assert (
        out.splitlines()[0] == "line 60" and out.splitlines()[-1] == "line 99" and len(out.splitlines()) == 40
    )
    wide = "\n".join("w" * 500 for _ in range(30))
    out = run("Bash", {"command": "x"}, wide)[1]["data"]["output"]
    assert len(out) <= 4000 and out.endswith("w" * 500)


def test_a_result_given_as_blocks_keeps_its_lines():
    end = run("Bash", {"command": "x"}, [{"type": "text", "text": "a\nb"}])[1]
    assert end["data"]["output"] == "a\nb"


def test_other_tools_and_empty_output_have_no_output_field():
    assert "output" not in run("Read", {"file_path": "/x/a.py"}, "print(1)\nprint(2)")[1]["data"]
    assert "output" not in run("Bash", {"command": "true"}, "")[1]["data"]


def test_planted_secrets_never_reach_the_event_file(tmp_path):
    result = f"start\nexport TOKEN={GH}\nkey is {SK} ok\n{PEM}\nfinish"
    events = run("Bash", {"command": f"curl -H 'Authorization: Bearer {GH}' x"}, result, is_error=True)
    log = ev.EventLog(tmp_path, RUN)
    log.append(*events)
    raw = log.path.read_text()
    for secret in (GH, SK, "MIIEvQIBADANBgkq", "abcdefghijklmnop"):
        assert secret not in raw
    end = events[1]
    lines = end["data"]["output"].split("\n")
    assert lines[0] == "start" and lines[-1] == "finish"
    assert all(ln.startswith("[hidden") for ln in lines[1:-1])
    assert any(ln.startswith("[hidden: ") and ":" in ln for ln in lines[1:-1])
    assert GH not in end["text"]


def test_a_key_that_began_before_the_last_40_lines_stays_hidden():
    body = "\n".join(f"{'QWERTYUIOPasdfghjkl' * 3}{i}" for i in range(60))
    pem = f"-----BEGIN RSA PRIVATE KEY-----\n{body}\n-----END RSA PRIVATE KEY-----\nthe end"
    out = run("Bash", {"command": "x"}, pem)[1]["data"]["output"]
    assert "QWERTY" not in out and out.splitlines()[-1] == "the end"


def test_a_scan_that_cannot_run_shows_no_output(monkeypatch):
    import orch.secretscan as ss

    monkeypatch.setattr(ss, "find", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert output_tail("a\nb") is None


# --- the live path: core record lines (activity.md) -> run events, with the step's detail file ---
from orch_focus import record


def step(done=True, name="Bash", detail=True):
    e = {"v": 1, "id": "toolu_x1", "seq": 3, "run": "r_abc12345", "agent": "main", "at": "2026-11-15T10:00:00Z",
         "ticket": TID, "via": "log", "checked": True, "kind": "step", "text": "Run the tests",
         "used": {"kind": "tool", "name": name, "action": None, "source": "builtin", "version": None},
         "files": [], "outcome": {"ok": True, "ms": 1200} if done else None}  # fmt: skip
    if detail:
        e["detail"] = "detail/r_abc12345/" + "0" * 32 + ".json"
    return e


def end_of(e, detail):
    out = record.to_events(
        e, TID, "r_abc12345", detail, None
    )  # source is log/hook here, not in the adapter enum
    return out[0]


def test_record_step_gets_command_and_output_from_its_detail():
    d = {
        "input": {"command": "pytest -q"},
        "output": {"stdout": "collected 2\n2 passed", "stderr": "warn: slow"},
    }
    e = end_of(step(), d)
    assert e["kind"] == "tool.end"
    assert e["data"]["command"] == "pytest -q"
    assert e["data"]["output"] == "collected 2\n2 passed\nwarn: slow"


def test_record_detail_secrets_are_hidden_and_never_reach_the_event_file(tmp_path):
    d = {"input": {"command": f"curl -H 'Authorization: Bearer {GH}' x"},
         "output": {"stdout": f"start\nexport TOKEN={GH}\nkey {SK}\n{PEM}\nfinish", "stderr": ""}}  # fmt: skip
    e = end_of(step(), d)
    log = ev.EventLog(tmp_path, "r_abc12345")
    log.append(e)
    raw = log.path.read_text()
    for secret in (GH, SK, "MIIEvQIBADANBgkq", "abcdefghijklmnop"):
        assert secret not in raw
    lines = e["data"]["output"].split("\n")
    assert lines[0] == "start" and lines[-1] == "finish"
    assert all(ln.startswith("[hidden") for ln in lines[1:-1])


def test_record_step_without_detail_or_for_another_tool_has_no_output():
    assert "output" not in end_of(step(), None)["data"]
    assert "output" not in end_of(step(name="Read"), None)["data"]
    assert record.to_events(step(done=False), TID, "r_abc12345")[0]["kind"] == "tool.start"


def test_feed_fetches_the_detail_only_for_a_finished_bash_step(monkeypatch, tmp_path):
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)

        class R:
            returncode = 0
            stdout = json.dumps({"input": {"command": "ls"}, "output": {"stdout": "a\nb"}}).encode()

        return R()

    monkeypatch.setattr(record, "_run", fake_run)
    f = record.RecordFeed(tmp_path, "/bin/orch", "r_abc12345", TID)
    assert f._detail(step(done=False)) is None and f._detail(step(name="Read")) is None and not calls
    assert f._detail(step())["input"]["command"] == "ls"
    assert (
        calls[0][-5:] == ["--run", "r_abc12345", "--detail", "toolu_x1", "--json"][-5:]
        or "--detail" in calls[0]
    )
