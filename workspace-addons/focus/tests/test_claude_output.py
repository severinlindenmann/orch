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
