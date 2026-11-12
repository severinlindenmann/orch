"""Claude one-shot collector: stream-json lines -> orch.activity/1 events."""

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from orch import hider
from orch.collect_claude import StreamJsonMapper, collect, map_stream
from orch.collect_execjson import detail_name
from orch.record import RecordWriter, read_detail, read_run

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "workspace/tests/fixtures/w2b/claude"
SCHEMA = json.loads((ROOT / "contracts/activity.schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker())
CTX = dict(run="r_cl00001", ticket="t_inv7c2", harness="claude", at="2026-11-16T09:00:00Z")
SECRET = "KEYVALUE-abc123XYZ-secret"


def lines(name):
    return (FIX / name).read_bytes().splitlines()


def mapper(**kwargs):
    return StreamJsonMapper(CTX["run"], CTX["ticket"], CTX["harness"], now=lambda: CTX["at"], **kwargs)


def use(tid, name="Bash", inp=None, parent=None, at="2026-11-16T09:00:01.000Z"):
    block = dict(type="tool_use", id=tid, name=name, input=inp if inp is not None else {"command": "ls"})
    return json.dumps(
        dict(type="assistant", message=dict(content=[block]), parent_tool_use_id=parent, timestamp=at)
    )


def result(tid, content="ok", error=None, parent=None, at="2026-11-16T09:00:03.000Z"):
    block = dict(type="tool_result", tool_use_id=tid, content=content)
    if error is not None:
        block["is_error"] = error
    return json.dumps(
        dict(type="user", message=dict(content=[block]), parent_tool_use_id=parent, timestamp=at)
    )


def steps(events):
    return [e for e in events if e["kind"] == "step"]


@pytest.mark.parametrize("name", ["read-and-fail.jsonl", "helper-denial.jsonl"])
def test_fixtures_validate(name):
    events = map_stream(lines(name), CTX)
    assert events
    for event in events:
        VALIDATOR.validate(event)
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))


def test_real_capture():
    events = map_stream(lines("read-and-fail.jsonl"), CTX)
    kinds = [(e["kind"], e["outcome"] is not None) for e in events]
    assert kinds == [
        ("run.state", False),
        ("step", False),
        ("step", True),
        ("step", False),
        ("usage", False),
        ("step", True),
        ("run.state", False),  # the closing sentence of the agent
        ("usage", False),
        ("run.state", False),
    ]
    read_start, read_end, bash_start, bash_end = steps(events)
    assert read_start["id"] == read_end["id"] and read_start["id"].startswith("toolu_")
    assert read_start["used"] == dict(kind="tool", name="Read", action=None, source="builtin", version=None)
    assert read_start["text"] == "Read notes.txt"
    assert read_start["detail"] is None
    assert read_end["outcome"]["ok"] is True and read_end["outcome"]["ms"] == 93
    assert bash_end["outcome"]["ok"] is False
    assert bash_end["outcome"]["error"].startswith("Exit code 1")
    assert bash_end["text"] == "Attempt to print a file that does not exist"
    name = detail_name(CTX["run"], "step", bash_end["id"], CTX["ticket"])
    assert bash_end["detail"] == f"detail/{CTX['run']}/{name}.json"
    assert all(e["session"] == "00000002-0000-4000-8000-000000000002" for e in events[1:])
    assert events[-2]["data"]["tokens_in"] == 4 + 24629 + 47004 and events[-2]["data"]["tokens_out"] == 345
    assert events[-1]["data"]["state"] == "idle"
    assert events[4]["data"]["window"] == "five_hour" and events[4]["data"]["used"] == 0.1
    say = events[6]
    assert say["data"]["say"] == say["text"] and say["text"].startswith("The file")


def test_pairs_one_step_each():
    events = list(
        mapper().events([use("t1"), use("t2", "Read", {"file_path": "/a/b.txt"}), result("t2"), result("t1")])
    )
    started = [e for e in steps(events) if e["outcome"] is None]
    finished = [e for e in steps(events) if e["outcome"] is not None]
    assert [e["id"] for e in started] == ["t1", "t2"]
    assert [e["id"] for e in finished] == ["t2", "t1"]


def test_errors_are_failed_steps():
    events = list(mapper().events([use("t1"), result("t1", "boom\nsecond line", error=True)]))
    assert events[-1]["outcome"]["ok"] is False
    assert events[-1]["outcome"]["error"] == "boom"
    ok = list(mapper().events([use("t1"), result("t1", error=False)]))
    assert ok[-1]["outcome"] == dict(ok=True, error=None, ms=2000)


def test_helper_mcp_skill_denial():
    events = map_stream(lines("helper-denial.jsonl"), CTX)
    by = {(e["kind"], e["id"], e["outcome"] is not None): e for e in events if e["id"].startswith("toolu_")}
    start, end = by[("helper.start", "toolu_01Hk", False)], by[("helper.end", "toolu_01Hk", True)]
    assert start["agent"] == end["agent"] == "h_1" and start["parent"] == "main"
    assert start["used"]["kind"] == "helper" and start["text"] == "checking colours"
    child = by[("step", "toolu_02In", False)]
    assert child["agent"] == "h_1" and child["parent"] == "main"
    mcp = by[("step", "toolu_03Mc", False)]
    assert mcp["used"] == dict(kind="mcp", name="docs", action="lookup", source="harness", version=None)
    skill = by[("step", "toolu_04Sk", False)]
    assert skill["used"] == dict(kind="skill", name="pdf-report", action=None, source="harness", version=None)
    denial = by[("denial", "toolu_05Wf", True)]
    assert denial["outcome"]["ok"] is False and denial["used"]["name"] == "WebFetch"
    assert "WebFetch" in denial["text"]
    final = [e for e in events if e["kind"] == "run.state"][-1]
    assert final["data"]["state"] == "failed"


def test_unknown_types_counted_not_silent():
    m = mapper()
    for line in (
        '{"type":"system","subtype":"hook_started"}',
        '{"type":"system","subtype":"hook_started"}',
        '{"type":"future_thing"}',
        '{"type":"user","message":{"content":"plain text"}}',
    ):
        assert m.feed(line) == []
    assert m.ignored == {"system/hook_started": 2, "future_thing": 1, "user/content": 1}
    m.feed(use("t1", "Task", {"description": "x"}))
    assert m.feed(result("never-started")) == [] and m.orphans == 1


def test_unknown_block_makes_next_step_partial():
    m = mapper()
    m.feed(json.dumps(dict(type="assistant", message=dict(content=[dict(type="server_tool_use")]))))
    first = m.feed(use("t1"))[0]
    assert first["coverage"] == "partial"
    assert m.feed(use("t2"))[0]["coverage"] == "full"


@pytest.mark.parametrize(
    "line", ["", "not json", "[]", b"\xff", "null", "42", '{"type":', '{"type":"user","message":[]}']
)
def test_garbled_lines(line):
    m = mapper()
    assert m.feed(line) == []
    assert m.feed(use("t1"))[0]["id"] == "t1"  # still usable afterwards


def test_truncated_stream_keeps_started_steps():
    full = lines("read-and-fail.jsonl")
    cut = full[:10] + [full[10][: len(full[10]) // 2]]
    m = mapper()
    events = list(m.events(cut))
    assert m.bad_lines == 1
    assert events[-1]["kind"] == "step" and events[-1]["outcome"] is not None  # the 6 whole lines still count


def test_ids_stable_and_unsafe_ids_stay_raw_for_the_writer():
    unsafe = "bad/id"
    stream = [use(unsafe), result(unsafe), use("z" * 161), use("ok_1")]
    first, second = list(mapper().events(stream)), list(mapper().events(stream))
    assert first == second
    assert first[0]["id"] == first[1]["id"] == unsafe  # never pre-hashed: the writer hashes once
    hashed = "x_" + hashlib.sha256(unsafe.encode()).hexdigest()[:32]
    assert (
        first[1]["detail"]
        == f"detail/{CTX['run']}/{detail_name(CTX['run'], 'step', hashed, CTX['ticket'])}.json"
    )
    assert first[3]["id"] == "ok_1"


def test_unsafe_id_dedupes_with_a_hook_line_through_the_writer(store):
    ws, writer = store
    unsafe = "bad/id"
    collect([use(unsafe), result(unsafe)], writer, CTX)
    done = [e for e in mapper().events([use(unsafe), result(unsafe)]) if e["outcome"]][0]
    hook = dict(done, via="hook", detail=None)
    assert writer.append(hook) is None  # after the log's line: dropped (the log wins, same hashed id)
    finished = [e for e in read_run(ws, CTX["run"]).unwrap() if e["kind"] == "step" and e["outcome"]]
    assert len(finished) == 1
    assert finished[0]["id"] == "x_" + hashlib.sha256(unsafe.encode()).hexdigest()[:32]


@pytest.mark.parametrize(
    "interrupt, code", [(None, "tool_failed"), (False, "tool_failed"), (True, "interrupted")]
)
def test_a_failure_hook_maps_to_a_failed_end_with_a_fixed_code(interrupt, code):
    from orch.collect_claude import hook_line

    raw = {
        "hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "tool_use_id": "toolu_f1",
        "tool_input": {"command": "rm -rf build"}, "error": "Exit code 1\n" + "x" * 50_000,
    }  # fmt: skip
    if interrupt is not None:
        raw["is_interrupt"] = interrupt
    got = hook_line(raw)
    assert got["outcome"] == {"ok": False, "error": code, "ms": None}  # never the error text
    assert (got["id"], got["kind"], got["text"]) == ("toolu_f1", "step", "Run rm -rf build")
    assert got["payload"]["input"] == {"command": "rm -rf build"}
    out = got["payload"]["output"]  # the error text, cut like any hook output (hidden by the writer)
    assert out.startswith("Exit code 1\n") and out.endswith("more characters]") and len(out) < 33_000
    pre = hook_line(dict(raw, hook_event_name="PreToolUse"))
    post = hook_line(dict(raw, hook_event_name="PostToolUse"))
    assert pre["outcome"] is None and "payload" not in pre
    assert post["outcome"] == {"ok": None, "error": None, "ms": None}  # a success never says it ended well


def test_result_events_get_stable_ids_from_the_line():
    done = json.dumps({"type": "result", "uuid": "u9", "is_error": False, "usage": {"output_tokens": 1}})
    one = ClaudeMapperFor(seq_start=0).feed(done)
    two = ClaudeMapperFor(seq_start=50).feed(done)
    assert (
        [e["id"] for e in one] == [e["id"] for e in two] == [f"{CTX['run']}:u9:usage", f"{CTX['run']}:u9:end"]
    )
    denied = json.dumps(
        {"type": "result", "uuid": "u9", "permission_denials": [{"tool_name": "X"}, {"tool_name": "Y"}]}
    )
    ids = [e["id"] for e in ClaudeMapperFor(seq_start=7).feed(denied) if e["kind"] == "denial"]
    assert ids == [f"{CTX['run']}:u9:denial:0", f"{CTX['run']}:u9:denial:1"]
    init = json.dumps({"type": "system", "subtype": "init", "session_id": "s-1", "uuid": "u0"})
    mp = ClaudeMapperFor(seq_start=3)
    assert mp.feed(init)[0]["id"] == f"{CTX['run']}:s-1:init:u0"


def ClaudeMapperFor(**kw):
    return StreamJsonMapper(CTX["run"], CTX["ticket"], "claude", now=lambda: CTX["at"], **kw)


def test_helper_numbering_resumes_and_is_capped():
    task = use("t1", "Task", {"description": "x"})
    assert ClaudeMapperFor(helper_start=2).feed(task)[0]["agent"] == "h_3"
    capped = ClaudeMapperFor(helper_start=9999).feed(task)[0]
    assert capped["kind"] == "step" and capped["agent"] == "main"


def test_collect_uses_the_real_clock_and_keeps_ms(store):
    ws, writer = store
    stream = [use("t1", at="x"), result("t1", at="y")]  # no usable line times
    collect(stream, writer, CTX)
    events = read_run(ws, CTX["run"]).unwrap()
    assert not any(e["at"] == CTX["at"] for e in events)
    assert events[-1]["outcome"]["ms"] is not None and events[-1]["outcome"]["ms"] >= 0


def test_ignored_counts_are_capped_and_bad_content_counted():
    m = mapper()
    m.feed(json.dumps({"type": "t" * 80}))
    m.feed(json.dumps({"type": "assistant", "message": {"content": "text"}}))
    m.feed(json.dumps({"type": "user", "message": []}))
    assert all(len(k) <= 40 for k in m.ignored)
    assert m.ignored["assistant/content"] == 1 and m.ignored["user/content"] == 1


def test_hider_on_events():
    m = mapper(hider=lambda s: s.replace("SECRET", "[hidden]"))
    assert m.hidden and not mapper().hidden
    events = m.feed(use("t1", "Bash", {"command": "echo SECRET"})) + m.feed(
        result("t1", "SECRET\nx", error=True)
    )
    assert events[0]["text"] == "Run echo [hidden]"
    assert events[1]["outcome"]["error"] == "[hidden]"


def test_detail_carries_input_and_output_unhidden_for_the_writer():
    m = mapper()
    m.feed_with_detail(use("t1", "Bash", {"command": f"echo {SECRET}"}))
    ((event, detail),) = m.feed_with_detail(result("t1", f"out {SECRET}"))
    assert detail == dict(input={"command": f"echo {SECRET}"}, output=f"out {SECRET}")
    started, _ = m.feed_with_detail(use("t2"))[0]
    assert started["detail"] is None


@pytest.fixture
def store(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws, RecordWriter(ws, hider=hider.Hider({"deploy-key": SECRET}))


def test_collect_into_writer_hides_secrets_and_replay_dedupes(store):
    ws, writer = store
    stream = [
        use("t1", "Bash", {"command": f"echo {SECRET}", "description": f"say {SECRET}"}),
        result("t1", f"leaked {SECRET}\nline2", error=True),
        json.dumps({"type": "result", "is_error": False, "usage": {"input_tokens": 1, "output_tokens": 2}}),
    ]
    stats = collect(stream, writer, CTX)
    assert stats["written"] == 4 and stats["deduped"] == 0
    events = read_run(ws, CTX["run"]).unwrap()
    blob = json.dumps(events)
    assert SECRET not in blob and "[hidden: deploy-key]" in blob
    finished = [e for e in events if e["kind"] == "step" and e["outcome"]]
    assert len(finished) == 1 and finished[0]["detail"]
    detail = read_detail(ws, CTX["run"], finished[0]["detail"].rsplit("/", 1)[1][:-5])
    text = json.dumps(detail.unwrap())
    assert SECRET not in text and "[hidden: deploy-key]" in text
    for path in (ws / ".orch").rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text()
    # replaying the same stream adds nothing
    again = collect(stream, writer, CTX)
    assert again["written"] == 0 and again["deduped"] == 4
    assert len(read_run(ws, CTX["run"]).unwrap()) == 4


def test_resume_process_does_not_collide_and_uuid_ids_are_stable():
    say = json.dumps(dict(type="assistant", uuid="u-1", message=dict(content=[dict(type="text", text="Hi")])))
    first = StreamJsonMapper(CTX["run"], CTX["ticket"], "claude", now=lambda: CTX["at"])
    second = StreamJsonMapper(CTX["run"], CTX["ticket"], "claude", now=lambda: CTX["at"], seq_start=40)
    done = json.dumps({"type": "result", "is_error": False})
    assert first.feed(say)[0]["id"] == second.feed(say)[0]["id"] == f"{CTX['run']}:u-1:0"
    assert first.feed(done)[0]["id"] == f"{CTX['run']}:2"
    assert second.feed(done)[0]["id"] == f"{CTX['run']}:42"


# --- files (activity.md, Files) ---
def test_real_capture_files_relative_to_the_workspace():
    events = map_stream(lines("read-and-fail.jsonl"), dict(CTX, workspace="/work/proj"))
    read_start, read_end, bash_start, bash_end = steps(events)
    assert read_start["files"] == read_end["files"] == ["notes.txt"]
    assert "files" not in bash_start and "files" not in bash_end
    for event in events:
        VALIDATOR.validate(event)
    # without a workspace root an absolute path cannot be placed: dropped, nothing else changes
    plain = map_stream(lines("read-and-fail.jsonl"), CTX)
    assert not any("files" in e for e in plain)
    assert plain == [{k: v for k, v in e.items() if k != "files"} for e in events]


@pytest.mark.parametrize(
    "name,inp,files",
    [
        ("Read", {"file_path": "/ws/src/a.py"}, ["src/a.py"]),
        ("Edit", {"file_path": "/ws/src/a.py", "old_string": "x", "new_string": "y"}, ["src/a.py"]),
        ("Write", {"file_path": "/ws/out/new.md", "content": "/ws/other.md"}, ["out/new.md"]),
        ("NotebookEdit", {"notebook_path": "/ws/nb/a.ipynb"}, ["nb/a.ipynb"]),
        ("Glob", {"pattern": "**/*.py", "path": "/ws/src"}, ["src"]),
        ("Grep", {"pattern": "TODO", "path": "/ws/src/x/"}, ["src/x"]),
        ("Grep", {"pattern": "TODO", "path": "src"}, ["src"]),
        ("Read", {"file_path": "/etc/passwd"}, None),
        ("Read", {"file_path": "/ws/../secret.txt"}, None),
        ("Read", {"file_path": "/wsx/a.py"}, None),
        ("Read", {"file_path": "/ws"}, None),
        ("Read", {"file_path": 42}, None),
        ("Glob", {"pattern": "**/*.py"}, None),
        ("Bash", {"command": "cat /ws/a.py", "file_path": "/ws/a.py"}, None),
        ("mcp__fs__read", {"path": "/ws/a.py"}, None),
        ("Skill", {"skill": "x", "path": "/ws/a.py"}, None),
    ],
)
def test_file_tools_fill_files(name, inp, files):
    m = mapper(workspace="/ws")
    started = m.feed(use("t1", name, inp))[0]
    finished = m.feed(result("t1"))[0]
    for event in (started, finished):
        assert event.get("files") == files
        VALIDATOR.validate(event)


def test_helper_never_gets_files():
    m = mapper(workspace="/ws")
    started = m.feed(use("t1", "Task", {"description": "x", "file_path": "/ws/a.py"}))[0]
    assert started["kind"] == "helper.start" and "files" not in started


def test_collect_passes_the_workspace_to_the_writer(store):
    ws, writer = store
    stream = [
        use("t1", "Read", {"file_path": f"{ws}/src/app.py"}),
        result("t1"),
        use("t2", "Read", {"file_path": f"{ws}/keys/{SECRET}"}),
        result("t2"),
    ]
    collect(stream, writer, dict(CTX, workspace=str(ws)))
    events = steps(read_run(ws, CTX["run"]).unwrap())
    assert [e["files"] for e in events] == [["src/app.py"], ["src/app.py"], [], []]
    assert SECRET not in json.dumps(events)


STREAM2 = [use("toolu_a", "Read", {"file_path": "a.py"}), use("toolu_b", "Read", {"file_path": "b.py"})]


def test_collect_counts_and_skips_an_invalid_event(store, monkeypatch):
    from orch import record

    ws, writer = store
    real = RecordWriter._commit
    calls = []

    def commit(self, event, *a, **k):
        calls.append(event["id"])
        if len(calls) == 1:
            raise record.RecordInvalid("too large")
        return real(self, event, *a, **k)

    monkeypatch.setattr(RecordWriter, "_commit", commit)
    stats = collect(STREAM2, writer, CTX)
    assert stats["invalid"] == 1 and stats["written"] == 1


@pytest.mark.parametrize("error", ["tampered", "unavailable"])
def test_collect_stops_loudly_on_tampered_or_unavailable(store, monkeypatch, error):
    from orch import record

    ws, writer = store
    exc = record.RecordTampered("swapped") if error == "tampered" else record.RecordUnavailable("io")

    def commit(self, *a, **k):
        raise exc

    monkeypatch.setattr(RecordWriter, "_commit", commit)
    with pytest.raises(type(exc)):
        collect(STREAM2, writer, CTX)


def test_collect_busy_goes_to_the_spool_and_the_run_continues(store, monkeypatch):
    from orch import record

    ws, writer = store

    def busy(*a, **k):
        raise record.RecordBusy("busy")

    monkeypatch.setattr(record, "_lock", busy)
    stats = collect(STREAM2, writer, CTX)
    assert stats["invalid"] == 0 and stats["written"] == 2
    assert len(list((record.record_dir(ws) / "pending" / CTX["run"]).iterdir())) == 2


def test_collect_spool_failure_keeps_the_real_cause(store, monkeypatch):
    from orch import record

    ws, writer = store
    monkeypatch.setattr(record, "_lock", lambda *a, **k: (_ for _ in ()).throw(record.RecordBusy("busy")))
    monkeypatch.setattr(
        record, "_open", lambda *a, **k: (_ for _ in ()).throw(record.RecordUnavailable("io"))
    )
    with pytest.raises(record.RecordUnavailable):
        collect(STREAM2, writer, CTX)


def _seed(ws, writer):
    collect([use("t0", "Read", {"file_path": "seed.py"})], writer, CTX)
    return ws / ".orch" / "record" / "runs" / f"{CTX['run']}.jsonl"


def _alerts(ws):
    return "".join(p.read_text() for p in (ws / ".orch" / "record" / "alerts").glob("*") if p.is_file())


def test_collect_real_hardlinked_run_file_raises_tampered(store):
    import os

    from orch.record import RecordTampered

    ws, writer = store
    run_file = _seed(ws, writer)
    twin = run_file.with_name("twin.copy")
    try:
        os.link(run_file, twin)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("no hardlinks here")
    before = twin.read_bytes()
    with pytest.raises(RecordTampered) as caught:
        collect(STREAM2, writer, CTX)
    assert caught.value.reason == "hardlink"
    assert twin.read_bytes() == before and run_file.read_bytes() == before  # nothing written through the link
    assert '"reason":"hardlink"' in _alerts(ws)


def test_collect_real_symlinked_run_file_raises_tampered(store, tmp_path):
    from orch.record import RecordTampered

    ws, writer = store
    run_file = _seed(ws, writer)
    outside = tmp_path / "outside.jsonl"
    outside.write_text("")
    run_file.unlink()
    try:
        run_file.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("no symlinks here")
    with pytest.raises(RecordTampered):
        collect(STREAM2, writer, CTX)
    assert outside.read_text() == ""
    assert '"schema":"orch.record-alert/1"' in _alerts(ws) and '"reason":"link"' in _alerts(ws)
