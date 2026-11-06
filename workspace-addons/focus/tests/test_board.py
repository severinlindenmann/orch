import json
from pathlib import Path

import jsonschema
import pytest

from orch_focus import events as ev
from orch_focus.adapters.claude import ClaudeMapper
from orch_focus.board import Board, TicketWatcher, _ts

FIX = Path(__file__).parent / "fixtures"
SCHEMA = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/addons/focus/run-event.schema.json").read_text()
)
RUN, TID = "r_8k2m9z", "t_inv7c2"


def valid(e):
    jsonschema.validate(e, SCHEMA)


def claude_events():
    m = ClaudeMapper(RUN, TID)
    out = []
    for line in (FIX / "claude-run.jsonl").read_text().splitlines():
        out += m.feed(json.loads(line))
    return out


def generic_events():
    w = TicketWatcher(RUN, TID)
    out = []
    for snap in json.loads((FIX / "generic-ticket-run.json").read_text()):
        out += w.feed(snap)
    return out


def test_generic_run_validates_and_gives_the_board_without_a_mapper():
    events = generic_events()
    for e in events:
        valid(e)
    assert [e["kind"] for e in events] == ["task.start", "task.done", "ask"]
    b = Board.from_events(events)
    snap = b.snapshot()
    assert [(t["check"], t["state"]) for t in snap["tasks"]] == [("c1", "done")]
    assert snap["tasks"][0]["evidence"] == "48 passed"
    assert [a["q"] for a in snap["asks"]] == ["q3"]
    b.resolve_asks(json.loads((FIX / "generic-ticket-run.json").read_text())[-1])
    assert b.snapshot()["asks"] == []


def test_ticket_watcher_prime_remembers_without_events():
    snaps = json.loads((FIX / "generic-ticket-run.json").read_text())
    w = TicketWatcher(RUN, TID)
    assert w.feed(snaps[2], prime=True) == []
    assert w.feed(snaps[2]) == []
    assert w.feed(snaps[3]) == []  # the answered question is not a new ask


def test_claude_run_validates_and_maps_helpers_usage_denial():
    events = claude_events()
    for e in events:
        valid(e)
    kinds = [e["kind"] for e in events]
    assert kinds.count("helper.start") == 1 and kinds.count("helper.end") == 1
    assert "usage" in kinds and "denial" in kinds
    helper_steps = [e for e in events if e["agent"] == "h_1" and e["kind"].startswith("tool.")]
    assert helper_steps and helper_steps[0]["text"] == "Read colors.css"
    failed = [e for e in events if e["kind"] == "tool.end" and not e["data"]["ok"]]
    assert failed and failed[0]["data"]["ms"] == 5000
    usage = next(e for e in events if e["kind"] == "usage")
    assert usage["data"]["status"] == "warning" and usage["data"]["used"] == pytest.approx(0.82)
    assert events[-1]["data"]["state"] == "idle" and events[-1]["data"]["denials"] == 1


def test_claude_board_state_and_long_job():
    events = claude_events()
    b = Board.from_events(events)
    snap = b.snapshot(now=0)
    assert snap["usage"]["status"] == "warning" and snap["denials"][0]["tool"] == "WebFetch"
    assert snap["helpers"] == [] and snap["jobs"] == [] and snap["state"] == "idle"
    # an open tool call older than 10 s is a long job
    b2 = Board()
    start = next(e for e in events if e["kind"] == "tool.start")
    b2.apply(start)
    assert b2.snapshot(now=_ts(start["at"]) + 5)["jobs"] == []
    jobs = b2.snapshot(now=_ts(start["at"]) + 40)["jobs"]
    assert jobs and jobs[0]["seconds"] == 40


def test_ok_usage_is_not_shown():
    b = Board()
    m = ClaudeMapper(RUN, TID)
    for e in m.feed(
        {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "utilization": 0.1}}
    ):
        b.apply(e)
    assert b.snapshot()["usage"] is None


def test_commands_are_redacted():
    events = claude_events()
    start = next(e for e in events if e["kind"] == "tool.start")
    assert "abc123secretvalue" not in json.dumps(start)
    assert "[hidden]" in start["data"]["command"]
    assert ev.redact("cat .orch/secrets/key") == "cat [hidden]"
    assert "ghp_" not in ev.redact("push with ghp_" + "a" * 30)


def test_event_log_roundtrip_cap_and_half_line(tmp_path):
    log = ev.EventLog(tmp_path, RUN)
    events = generic_events()
    log.append(*events)
    got, off = log.read()
    assert got == events
    with open(log.path, "ab") as f:
        f.write(b'{"v":1,"kind":"ta')  # half-written line waits
    assert log.read(off) == ([], off)
    assert oct(log.path.stat().st_mode & 0o777) == "0o600"
    ev.CAP_BYTES, old = 10, ev.CAP_BYTES
    try:
        log.append(events[0])
    finally:
        ev.CAP_BYTES = old
    assert log.path.with_name(log.path.name + ".1").exists()


def test_unknown_kind_refused_by_make_and_skipped_by_reader(tmp_path):
    with pytest.raises(ValueError):
        ev.make(RUN, TID, "main", "nope", "x", "ticket")
    log = ev.EventLog(tmp_path, RUN)
    log.path.parent.mkdir(parents=True)
    log.path.write_text('{"kind":"future.thing"}\nnot json\n')
    assert log.read()[0] == []


def test_evidence_in_task_done_is_redacted():
    w = TicketWatcher(RUN, TID)
    secret = "ghp_" + "a" * 30
    c = {
        "id": "c1",
        "text": "x",
        "done": True,
        "evidence": [{"type": "note", "ref": "r", "text": f"token {secret}"}],
    }
    out = w.feed({"checklist": [c], "questions": []})
    assert secret not in json.dumps(out) and "[hidden]" in out[0]["data"]["evidence"]


def test_make_redacts_every_data_string():
    secret = "ghp_" + "b" * 30
    e = ev.make(RUN, TID, "main", "tool.end", "ok", "adapter", other=secret, nested={"a": [secret]})
    assert secret not in json.dumps(e)


def test_secret_crossing_char_80_is_hidden_in_step_text():
    secret = "ghp_" + "c" * 30
    cmd = "echo " + "x" * 70 + " " + secret
    assert cmd.index(secret) < 80 < cmd.index(secret) + len(secret)
    m = ClaudeMapper(RUN, TID)
    line = {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": cmd}}]},
    }
    out = m.feed(line)
    assert "ghp_" not in json.dumps(out)


def test_read_after_rotation_resets_offset(tmp_path):
    log = ev.EventLog(tmp_path, RUN)
    events = generic_events()
    log.append(*events)
    _, off = log.read()
    old = ev.CAP_BYTES
    ev.CAP_BYTES = 10
    try:
        log.append(events[0])  # rotates, then writes one line to the fresh file
    finally:
        ev.CAP_BYTES = old
    got, off2 = log.read(off)
    assert got == [events[0]] and off2 < off
    assert oct(log.path.with_name(log.path.name + ".1").stat().st_mode & 0o777) == "0o600"
    assert oct(log.path.parent.stat().st_mode & 0o777) == "0o700"


def test_bad_event_does_not_break_the_fold():
    good = generic_events()
    bad = [
        {"kind": "task.start", "text": "x", "data": {}},
        {"kind": "helper.end", "data": {}},
        {"kind": "usage", "data": {}},
    ]
    b = Board.from_events([good[0], *bad, good[1]])
    assert [t["check"] for t in b.snapshot()["tasks"]] == ["c1"]


def _tool_use(name, inp):
    return {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": "t1", "name": name, "input": inp}]},
    }


def test_secret_across_every_limit_is_hidden_on_every_producer_path():
    secret = "ghp_" + "d" * 30

    def across(n):
        pad = "x" * (n - 10)
        return pad + " " + secret

    outs = []
    m = ClaudeMapper(RUN, TID)
    outs += m.feed(_tool_use("Bash", {"command": across(120)}))  # step text limit 120
    outs += m.feed(
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": across(200)}]},
        }
    )
    outs += m.feed(_tool_use("Task", {"description": across(120)}))  # helper text limit 120
    outs += m.feed(_tool_use("Read", {"file_path": "/a/" + across(120)}))
    outs += m.feed(
        {
            "type": "rate_limit_event",
            "rate_limit_info": {"status": "allowed_warning", "rateLimitType": across(32)},
        }
    )
    outs += m.feed({"type": "result", "permission_denials": [{"tool_name": across(64)}]})
    w = TicketWatcher(RUN, TID)
    c = {
        "id": "c1",
        "text": across(500),
        "done": True,
        "evidence": [{"type": "note", "ref": "r", "text": across(200)}],
    }
    outs += w.feed({"checklist": [c], "questions": [{"id": "q1", "text": across(500), "answer": None}]})
    assert outs
    assert "ghp_" not in json.dumps(outs)
    for e in outs:
        valid(e)


def test_huge_value_is_redacted_fast():
    import time

    big = "a" * (5 * 1024 * 1024)
    t0 = time.time()
    e = ev.make(RUN, TID, "main", "tool.end", big, "adapter", command=big, other=big + ".orch/secrets")
    assert time.time() - t0 < 1.0
    assert len(e["text"]) <= 500 and len(e["data"]["command"]) <= 500
    t0 = time.time()
    ev.redact("x" * (5 * 1024 * 1024))
    ev.redact(("path/.orch" + "x") * 200000)
    assert time.time() - t0 < 2.0


def test_secret_at_the_cap_is_hidden():
    secret = "ghp_" + "e" * 30
    e = ev.make(RUN, TID, "main", "tool.end", "x" * 490 + " " + secret + "y" * 5000, "adapter")
    assert "ghp_" not in json.dumps(e)


def test_symlinked_log_is_not_followed(tmp_path):
    log = ev.EventLog(tmp_path, RUN)
    log.path.parent.mkdir(parents=True)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    log.path.symlink_to(victim)
    with pytest.raises(OSError):
        log.append(generic_events()[0])
    assert victim.read_text() == "keep"
    assert log.read() == ([], 0)


def test_symlinked_runs_folder_is_refused(tmp_path):
    real = tmp_path / "elsewhere"
    real.mkdir()
    d = tmp_path / ".orch" / "addons" / "focus"
    d.mkdir(parents=True)
    (d / "runs").symlink_to(real)
    with pytest.raises(OSError):
        ev.EventLog(tmp_path, RUN).append(generic_events()[0])
    assert list(real.iterdir()) == []


def test_pem_block_across_the_window_is_hidden():
    body = "\n".join("A" * 64 for _ in range(32))  # about 2 KB
    pem = f"-----BEGIN PRIVATE KEY-----\n{body}\n-----END PRIVATE KEY-----"
    for limit in (200, 500):
        v = "x" * (limit - 50) + " " + pem + " tail"
        out = ev.clip(v, limit)
        assert "AAAA" not in out and "BEGIN PRIVATE" not in out
        # end marker cut off entirely
        cut = "x" * (limit - 50) + " -----BEGIN RSA PRIVATE KEY-----\n" + body
        assert "AAAA" not in ev.clip(cut, limit)
    e = ev.make(RUN, TID, "main", "tool.end", "y" * 450 + " " + pem, "adapter", note="z" * 450 + " " + pem)
    assert "AAAA" not in json.dumps(e)
