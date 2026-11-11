"""`orch record hook`: the narrow hook entry of the record (contracts/activity.md, vectors hook_entry)."""

import base64
import io
import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from orch import hider, record, record_hook, runs, tickets

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "contracts/vectors/activity-v1.json").read_text())
USED = {"kind": "tool", "name": "Read", "action": None, "source": "builtin", "version": None}
SECRET = "KEYVALUE-abc123XYZ-secret"


@pytest.fixture
def live(proj, monkeypatch):
    t = tickets.create(proj, "Hook me", "human:t")
    rec = runs.claim(proj, t["id"], "agent:x", "claude", pid=os.getpid())
    monkeypatch.setenv("ORCH_RUN", rec["run"])
    monkeypatch.setenv("ORCH_TICKET", t["id"])
    with hider.use_hider(hider.Hider({"deploy-key": SECRET})):
        yield proj, rec["run"], t["id"]


def line(**kw):
    value = {"kind": "step", "id": "toolu_01X", "text": "Read a.pdf", "used": USED, "outcome": None}
    value.update(kw)
    return json.dumps(value)


def lost_notes(root, unattributed=False):
    pattern = "hook-lost-unattributed-*.jsonl" if unattributed else "hook-lost-2*.jsonl"
    return "".join(p.read_text() for p in (root / ".orch/record/alerts").glob(pattern))


def lost_lines(root):
    return lost_notes(root, unattributed=True).splitlines()


def lost_text(root):
    return lost_notes(root) + lost_notes(root, unattributed=True)


def events(root, run):
    return record.read_run(root, run).value


def test_step_is_written_as_hook_for_the_env_run(live):
    root, run, tid = live
    got = record_hook.hook(root, line(via="core", run=run))
    assert got["via"] == "hook" and got["run"] == run and got["ticket"] == tid and got["seq"] == 1
    assert [e["id"] for e in events(root, run)] == ["toolu_01X"]


@pytest.mark.parametrize("vector", VECTORS["hook_entry"], ids=lambda v: v["name"])
def test_vectors(live, vector):
    root, run, _ = live
    raw = dict(
        vector["line"],
        run=run,
        text="x",
        used=USED if vector["line"]["kind"] == "step" else None,
        **(
            {"data": {"used": 0.4, "window": "5h", "status": "ok"}}
            if vector["line"]["kind"] == "usage"
            else {}
        ),
    )
    if vector["stored"] == "refused":
        with pytest.raises(record_hook.NotRecorded):
            record_hook.hook(root, json.dumps(raw))
        assert record.read_run(root, run).status == "unavailable"  # nothing at all was written
    else:
        got = record_hook.hook(root, json.dumps(raw))
        assert {k: got[k] for k in vector["stored"] if k != "run"} == {
            k: v for k, v in vector["stored"].items() if k != "run"
        }


def test_forged_events(live):
    root, run, _ = live
    for forged in (
        line(kind="run.state"),
        line(kind="ask"),
        line(kind="task.done"),
        line(kind="key.use"),
        line(run="r_other0001"),
        line(ticket="t_other0001"),
        "not json",
        "[1]",
        '"x"',
        "",
        line(payload="x"),
    ):
        with pytest.raises(record_hook.NotRecorded):
            record_hook.hook(root, forged)
    # bad ids and fields: the writer refuses, nothing is written
    for bad in (line(id=5), line(agent="x y"), line(text="a\x00b")):
        with pytest.raises(record.RecordRefused):
            record_hook.hook(root, bad)
    assert record.read_run(root, run).status == "unavailable"


def test_forged_pointer_seq_and_flags_are_dropped(live):
    root, run, _ = live
    got = record_hook.hook(
        root, line(detail="detail/r_other0001/" + "a" * 32 + ".json", seq=99, conflict=True, detail_lost=True)
    )
    assert got["seq"] == 1 and got["detail"] is None and "conflict" not in got and "detail_lost" not in got


def test_run_namespace_ids_are_rehashed(live):
    root, run, _ = live
    got = record_hook.hook(root, line(id=f"{run}:7"))
    assert got["id"].startswith("x_") and len(got["id"]) == 34
    assert record_hook.hook(root, line(id=None))["id"] == f"h_{run}:2"


def test_no_run_env_is_a_plain_noop(proj, monkeypatch):
    monkeypatch.delenv("ORCH_RUN", raising=False)
    monkeypatch.delenv("ORCH_TICKET", raising=False)
    with pytest.raises(record_hook.NotRecorded, match="Not inside"):
        record_hook.hook(proj, line())
    assert not (proj / ".orch/record").exists()


@pytest.mark.parametrize("which", ["wrong_run", "wrong_ticket", "unknown_ticket", "dead"])
def test_run_must_be_live_and_match(live, monkeypatch, which):
    root, run, tid = live
    if which == "wrong_run":
        monkeypatch.setenv("ORCH_RUN", "r_zzzzzz")
    elif which == "wrong_ticket":
        other = tickets.create(root, "Other", "human:t")
        monkeypatch.setenv("ORCH_TICKET", other["id"])
    elif which == "unknown_ticket":
        monkeypatch.setenv("ORCH_TICKET", "t_nothere1")
    else:
        monkeypatch.setattr(runs, "state", lambda rec, at=None: "dead")
    with pytest.raises(record_hook.NotRecorded, match="not active"):
        record_hook.hook(root, line())
    assert not (root / ".orch/record/runs").exists()


def test_no_hider_refuses_and_writes_nothing(proj, monkeypatch):
    t = tickets.create(proj, "No hider", "human:t")
    rec = runs.claim(proj, t["id"], "agent:x", "claude", pid=os.getpid())
    monkeypatch.setenv("ORCH_RUN", rec["run"])
    monkeypatch.setenv("ORCH_TICKET", t["id"])
    monkeypatch.setattr(hider, "_registered", None)
    with pytest.raises(record_hook.NotRecorded, match="key hiding"):
        record_hook.hook(proj, line())
    assert not (proj / ".orch/record/runs").exists()
    assert "hider_off" in lost_notes(proj)


def test_cli_never_blocks_the_agent_but_strict_refuses(live, monkeypatch, capsys):
    root, run, _ = live
    record_hook.cli(root, io.StringIO(line(kind="run.state")))
    assert "not allowed" in capsys.readouterr().err
    with pytest.raises(record_hook.Refused):
        record_hook.cli(root, io.StringIO(line(kind="run.state")), strict=True)
    monkeypatch.setattr(hider, "_registered", None)
    with hider.use_hider(hider.Hider({"k": SECRET})):
        pass
    monkeypatch.setattr(record_hook, "_writer", lambda r: (_ for _ in ()).throw(record.RecordOff("off")))
    record_hook.cli(root, io.StringIO(line()))
    assert "off" in capsys.readouterr().err


def test_dedupe_with_a_collector_line(live):
    root, run, tid = live
    hook_ev = record_hook.hook(root, line(outcome={"ok": True, "error": None, "ms": 5}))
    collector = dict(hook_ev, via="log", seq=1)
    collector.pop("seq")
    with hider.use_hider(hider.Hider({"deploy-key": SECRET})):
        assert record.registered_writer(root).append(collector) is None  # same id/kind/finished: hl dedupe
    assert len(events(root, run)) == 1
    assert (
        record_hook.hook(root, line(outcome={"ok": True, "error": None, "ms": 5})) is None
    )  # hook repeat too
    # another origin keeps its own key
    denial = dict(json.loads(line(kind="denial", used=USED, outcome={"ok": False, "error": "no", "ms": 1})))
    record_hook.hook(root, json.dumps(denial))
    other = dict(collector, kind="denial", via="core", outcome=denial["outcome"], used=USED)
    with hider.use_hider(hider.Hider({"deploy-key": SECRET})):
        assert record.registered_writer(root).append(other) is not None


def test_secret_values_never_reach_the_record(live):
    root, run, _ = live
    forms = [
        SECRET,
        base64.b64encode(SECRET.encode()).decode(),
        base64.urlsafe_b64encode(SECRET.encode()).decode(),
    ]
    forms.append(SECRET.encode().hex())
    for n, form in enumerate(forms):
        record_hook.hook(
            root,
            line(
                id=f"toolu_{n}",
                text=f"Run with {form}",
                data={"note": f"token {form}"},
                outcome={"ok": False, "error": f"failed {form}", "ms": 1},
                payload={"input": {"command": f"curl -H {form}"}, "output": f"leaked {form}"},
            ),
        )
    blob = b"".join(p.read_bytes() for p in (root / ".orch/record").rglob("*") if p.is_file())
    assert b"[hidden: " in blob
    for form in forms:
        assert form.encode() not in blob, form


def test_unknown_tool_names_are_plain_text(live):
    root, run, _ = live
    got = record_hook.hook(
        root,
        line(
            id="toolu_9",
            used={
                "kind": "mcp",
                "name": "weird.tool-name",
                "action": None,
                "source": "harness",
                "version": None,
            },
        ),
    )
    assert got is not None
    with pytest.raises(record.RecordRefused):
        record_hook.hook(root, line(id="toolu_10", used={"kind": "nonsense", "name": "x"}))


def test_timing_structural_one_run_file_only(live, monkeypatch):
    root, run, _ = live
    for n in range(300):
        record_hook.hook(root, line(id=f"toolu_pre{n}"))
    other = "r_other0001"
    with hider.use_hider(hider.Hider({"deploy-key": SECRET})):
        record.registered_writer(root).append(
            dict(
                json.loads(line(id="o1")),
                run=other,
                ticket="t_other0001",
                via="hook",
                seq=1,
                v=1,
                session=None,
                agent="main",
                parent=None,
                at="2026-11-16T09:12:05Z",
                harness="claude",
                coverage="full",
                detail=None,
            )
        )
    seen = []
    real = record._open

    def spy(ws, rel, *a, **k):
        seen.append(rel)
        return real(ws, rel, *a, **k)

    monkeypatch.setattr(record, "_open", spy)
    monkeypatch.setattr(record, "list_runs", lambda *a, **k: pytest.fail("scans every run"))
    t0 = time.perf_counter()
    record_hook.hook(root, line(id="toolu_last"))
    elapsed = time.perf_counter() - t0
    assert not any(rel[:2] == ("runs", other + ".jsonl") for rel in seen)
    assert elapsed < 0.5  # generous: loaded CI machine; the writer reads this one run file only


def test_cli_hook_command_exit_zero(live, monkeypatch, capsys):
    from orch import cli

    root, run, _ = live
    monkeypatch.setattr("sys.stdin", io.StringIO(line(kind="run.state") + "\n"))
    assert cli.main(["record", "hook"]) == 0
    assert "not allowed" in capsys.readouterr().err
    monkeypatch.setattr("sys.stdin", io.StringIO(line(kind="run.state") + "\n"))
    assert cli.main(["record", "hook", "--strict"]) == 2
    monkeypatch.setattr("sys.stdin", io.StringIO(line(id="toolu_cli") + "\n"))
    assert cli.main(["record", "hook"]) == 0
    assert [e["id"] for e in events(root, run)] == ["toolu_cli"]


def collector_line(run, tid, seq):
    return dict(
        json.loads(line(id=f"{run}:{seq}", used=USED)),
        run=run,
        ticket=tid,
        via="log",
        v=1,
        session=None,
        agent="main",
        parent=None,
        at="2026-11-16T09:12:05Z",
        harness="claude",
        coverage="full",
        detail=None,
    )


def test_hook_default_id_never_takes_a_collector_id(live):
    """H1: an id-less hook line must not pre-claim <run>:<seq>, the next collector line's id."""
    root, run, tid = live
    first = record_hook.hook(root, line(id=None))
    assert first["id"] == f"h_{run}:1" and not first["id"].startswith(f"{run}:")
    with hider.use_hider(hider.Hider({"deploy-key": SECRET})):
        got = record.registered_writer(root).append(collector_line(run, tid, 2))
    assert got is not None and got["id"] == f"{run}:2"  # the collector line is still written
    assert [e["via"] for e in events(root, run)] == ["hook", "log"]
    # a caller-sent id in the hook's own namespace is hashed like a run-namespace id
    sent = record_hook.hook(root, line(id=f"h_{run}:9"))
    assert sent["id"].startswith("x_")


def test_call_from_outside_the_claims_process_tree_is_refused(proj, monkeypatch):
    """H2: the same ORCH_RUN/ORCH_TICKET set by a process that is not inside the run writes nothing."""
    import subprocess
    import sys

    t = tickets.create(proj, "Elsewhere", "human:t")
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        rec = runs.claim(proj, t["id"], "agent:x", "claude", pid=other.pid)
        monkeypatch.setenv("ORCH_RUN", rec["run"])
        monkeypatch.setenv("ORCH_TICKET", t["id"])
        with hider.use_hider(hider.Hider({"deploy-key": SECRET})):
            with pytest.raises(record_hook.NotRecorded, match="not from inside"):
                record_hook.hook(proj, line())
    finally:
        other.kill()
        other.wait()
    assert not (proj / ".orch/record/runs").exists()
    assert lost_notes(proj) == ""  # nothing under the run id the caller named
    rows = [json.loads(x) for x in lost_lines(proj)]
    assert [(r["run"], r["reason"]) for r in rows] == [(None, "other_run")] and rec["run"] not in lost_text(
        proj
    )


def test_too_large_entry_still_leaves_an_audit_line(live, capsys):
    """M1: never drop the line; the detail is what is lost."""
    root, run, _ = live
    big = io.StringIO("x" * (record_hook.MAX_LINE + 10))
    record_hook.cli(root, big)
    got = events(root, run)
    assert len(got) == 1 and got[0]["kind"] == "step" and got[0]["detail"] is None
    raw = (root / f".orch/record/runs/{run}.jsonl").read_text()
    assert '"detail_lost":true' in raw.replace(" ", "")
    assert capsys.readouterr().err == ""
    # a big but readable line (4 MB payload) is also written, detail lost
    payload = {"input": "i" * (4 * 1024**2), "output": "o"}
    record_hook.cli(root, io.StringIO(line(id="toolu_big", payload=payload) + "\n"))
    assert events(root, run)[-1]["id"] == "toolu_big"


def test_lost_entries_leave_a_rate_limited_trace(live, proj):
    root, run, _ = live
    for _ in range(3):
        with pytest.raises(record_hook.NotRecorded):
            record_hook.hook(root, line(kind="run.state"))
    with pytest.raises(record_hook.NotRecorded):
        record_hook.hook(root, "not json")
    rows = [json.loads(x) for x in lost_notes(root).splitlines()]
    assert sorted((r["run"], r["reason"]) for r in rows) == [
        (run, "invalid")
    ]  # one per run and reason per minute
    assert rows[0]["schema"] == "orch.record-lost/1" and set(rows[0]) == {
        "v",
        "schema",
        "at",
        "run",
        "reason",
    }
    # a later minute writes again
    record.note_lost(root, run, "invalid", now=datetime.now(UTC) + timedelta(minutes=2))
    assert len(lost_notes(root).splitlines()) == 2


def test_no_run_leaves_no_trace(proj, monkeypatch):
    monkeypatch.delenv("ORCH_RUN", raising=False)
    monkeypatch.delenv("ORCH_TICKET", raising=False)
    with pytest.raises(record_hook.NotRecorded):
        record_hook.hook(proj, line())
    assert not (proj / ".orch/record").exists()


def test_harness_and_time_come_from_the_process_not_the_caller(live):
    root, run, _ = live
    got = record_hook.hook(root, line(harness="codex", at="2001-01-01T00:00:00Z", coverage="full"))
    assert got["harness"] in ("generic", "claude") and got["harness"] != "codex"
    assert got["at"] != "2001-01-01T00:00:00Z"


def test_every_failure_ends_quietly_unless_strict(live, monkeypatch, capsys):
    root, run, _ = live

    def boom(*a, **k):
        raise OSError("disk exploded")

    monkeypatch.setattr(record_hook, "hook", boom)
    record_hook.cli(root, io.StringIO(line()))  # no exception
    assert capsys.readouterr().err.startswith("orch: ")
    with pytest.raises(record_hook.Refused):
        record_hook.cli(root, io.StringIO(line()), strict=True)


@pytest.mark.parametrize("which", ["wrong_run", "unknown_ticket", "dead"])
def test_unproven_callers_cannot_write_traces_under_a_run(live, monkeypatch, which):
    """An unproven caller names a run id by its own word: nothing is written under it, whatever the reason."""
    root, run, tid = live
    if which == "wrong_run":
        monkeypatch.setenv("ORCH_RUN", "r_zzzzzz")
    elif which == "unknown_ticket":
        monkeypatch.setenv("ORCH_TICKET", "t_nothere1")
    else:
        monkeypatch.setattr(runs, "state", lambda rec, at=None: "dead")
    for _ in range(3):
        with pytest.raises(record_hook.NotRecorded):
            record_hook.hook(root, line())
    assert lost_notes(root) == ""
    rows = [json.loads(x) for x in lost_lines(root)]
    assert [(r["run"], r["reason"]) for r in rows] == [(None, "not_active")]  # one per reason per minute
    assert not (root / ".orch/record/runs").exists()


def test_the_lost_trace_trims_loudly_never_silently(live):
    root, run, _ = live
    base = datetime.now(UTC)
    for n in range(record._LOST_RUN_LINES + 20):
        record.note_lost(root, run, "invalid", now=base + timedelta(minutes=2 * n))
    rows = [json.loads(x) for x in lost_notes(root).splitlines()]
    assert len(rows) == record._LOST_RUN_LINES + 1
    assert rows[-1]["reason"] == "trimmed" and rows[-1]["run"] == run
    # another run still gets its own lines (one run cannot suppress another's traces)
    record.note_lost(root, "r_other0001", "invalid", now=base)
    assert json.loads(lost_notes(root).splitlines()[-1])["run"] == "r_other0001"


def test_the_lost_file_cap_leaves_one_global_trimmed_marker(live, monkeypatch):
    root, run, _ = live
    monkeypatch.setattr(record, "_LOST_FILE_BYTES", 400)
    base = datetime.now(UTC)
    for n in range(12):
        record.note_lost(root, f"r_other{n:04d}", "invalid", now=base)
    rows = [json.loads(x) for x in lost_notes(root).splitlines()]
    assert sum(1 for r in rows if r["reason"] == "trimmed" and r["run"] is None) == 1
    assert rows[-1]["reason"] == "trimmed"


def test_the_tool_call_id_is_the_event_id_so_hook_and_collector_dedupe(live):
    root, run, tid = live
    got = record_hook.hook(root, line(id="toolu_01RawID", outcome={"ok": True, "error": None, "ms": 1}))
    assert got["id"] == "toolu_01RawID"  # the raw tool-call id, not h_<run>:<seq>
    unsafe = "toolu/with space&odd"
    first = record_hook.hook(root, line(id=unsafe, outcome={"ok": True, "error": None, "ms": 1}))
    assert first["id"].startswith("x_") and len(first["id"]) == 34
    collector = collector_line(run, tid, 9) | {"id": unsafe, "outcome": {"ok": True, "error": None, "ms": 1}}
    with hider.use_hider(hider.Hider({"deploy-key": SECRET})):
        assert record.registered_writer(root).append(collector) is None  # the same hashed id: deduped


def _claim_file(root):
    return next((root / ".orch/run/tickets").glob("t_*.json"))


def test_pid_must_match_the_recorded_start_time(live, monkeypatch):
    """A pid is accepted only on a positive start-time match (pid reuse: unknown is not a match)."""
    from orch import procs

    root, run, tid = live
    assert record_hook.hook(root, line(id="toolu_ok")) is not None  # stored and current start times match
    path = _claim_file(root)
    claim = json.loads(path.read_text())
    assert claim.get("pid_started")
    monkeypatch.setattr(procs, "pid_started", lambda pid: None)  # current start time unreadable
    with pytest.raises(record_hook.NotRecorded, match="not from inside"):
        record_hook.hook(root, line(id="toolu_a"))
    monkeypatch.undo()
    monkeypatch.setenv("ORCH_RUN", run)
    monkeypatch.setenv("ORCH_TICKET", tid)
    claim.pop("pid_started")  # claim without a recorded start time
    path.write_text(json.dumps(claim))
    with pytest.raises(record_hook.NotRecorded, match="not from inside"):
        record_hook.hook(root, line(id="toolu_b"))
    claim["pid_started"] = "Thu Jan  1 00:00:00 1970"  # a different start time: the pid was reused
    path.write_text(json.dumps(claim))
    with pytest.raises(record_hook.NotRecorded, match="not (from inside|active)"):
        record_hook.hook(root, line(id="toolu_c"))
    assert [e["id"] for e in events(root, run)] == ["toolu_ok"]


def test_other_origins_cannot_send_the_hook_default_namespace(live):
    root, run, tid = live
    sent = f"h_{run}:5"
    with hider.use_hider(hider.Hider({"deploy-key": SECRET})):
        got = record.registered_writer(root).append(collector_line(run, tid, 1) | {"id": sent})
    assert got["id"] == "x_" + __import__("hashlib").sha256(sent.encode()).hexdigest()[:32]


def _main(monkeypatch, *argv, stdin=""):
    from orch import cli

    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return cli.main(["record", "hook", *argv])


def test_exit_zero_before_the_parser_the_guard_and_the_notices(live, monkeypatch, capsys):
    """Exit 2 from a PreToolUse hook blocks the tool call: nothing may refuse before record_hook runs."""
    from orch import chat, humanproof

    root, run, _ = live

    def refuse_all(*a, **k):
        raise record_hook.Refused("The Chat helper cannot do that.")

    monkeypatch.setattr(chat, "guard", refuse_all)  # a Chat helper run: the guard would refuse the command
    monkeypatch.setattr(humanproof, "cli_notices", lambda root: ["ONE-TIME NOTICE"])
    assert _main(monkeypatch, stdin=line(id="toolu_guard") + "\n") == 0
    cap = capsys.readouterr()
    assert "ONE-TIME NOTICE" not in cap.err + cap.out
    assert [e["id"] for e in events(root, run)] == ["toolu_guard"]
    assert _main(monkeypatch, "--bogus-option", "x", stdin=line() + "\n") == 0  # no argparse error
    monkeypatch.setenv("ORCH_ROOT", str(root / "does" / "not" / "exist"))  # a bad ORCH_ROOT
    assert _main(monkeypatch, stdin=line() + "\n") == 0
    assert capsys.readouterr().err.startswith("orch: ")
    assert _main(monkeypatch, "--strict", stdin=line() + "\n") == 2


def test_an_exception_inside_the_hook_still_exits_zero(live, monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError("disk exploded")

    monkeypatch.setattr(record_hook, "cli", boom)
    assert _main(monkeypatch, stdin=line() + "\n") == 0
    assert capsys.readouterr().err.startswith("orch: ")
    assert _main(monkeypatch, "--strict", stdin=line() + "\n") == 2


@pytest.mark.parametrize(
    "failure", [record_hook.Refused("x"), RuntimeError("x"), SystemExit(2), KeyboardInterrupt()]
)
def test_every_failure_kind_exits_zero_never_reraises(live, monkeypatch, capsys, failure):
    """A SystemExit (sys.exit, parser.error) or KeyboardInterrupt must not leave as exit 2."""

    def boom(*a, **k):
        raise failure

    monkeypatch.setattr(record_hook, "cli", boom)
    assert _main(monkeypatch, stdin=line() + "\n") == 0
    assert capsys.readouterr().err.startswith("orch: ")
    assert _main(monkeypatch, "--strict", stdin=line() + "\n") == 2
    monkeypatch.setattr("orch.cli._find_root", boom)  # the root lookup itself exits
    assert _main(monkeypatch, stdin=line() + "\n") == 0


def test_the_parser_route_keeps_the_exit_zero_rule(live, monkeypatch):
    """Reached only when a global flag precedes `record` (main's early branch takes the exact form)."""
    import argparse

    from orch import cli_record

    root, run, _ = live
    args = argparse.Namespace(cmd="record", sub="hook", strict=False)
    monkeypatch.setattr("sys.stdin", io.StringIO(line(kind="run.state") + "\n"))
    assert cli_record.dispatch(args, root) is True  # refused line: exit 0
    monkeypatch.setattr("sys.stdin", io.StringIO(line(kind="run.state") + "\n"))
    with pytest.raises(record_hook.Refused):
        cli_record.dispatch(argparse.Namespace(cmd="record", sub="hook", strict=True), root)
    monkeypatch.setattr("sys.stdin", io.StringIO(line(id="toolu_flag") + "\n"))
    assert cli_record.dispatch(args, root) is True
    assert [e["id"] for e in events(root, run)] == ["toolu_flag"]


def test_the_watchdog_is_cancelled_before_the_first_write(live, monkeypatch):
    root, run, _ = live
    order = []
    real = record.RecordWriter.append

    def spy(self, *a, **k):
        order.append("append")
        return real(self, *a, **k)

    monkeypatch.setattr(record.RecordWriter, "append", spy)
    record_hook.hook(root, line(id="toolu_w"), before_write=lambda: order.append("cancel"))
    assert order == ["cancel", "append"]
    order.clear()
    with pytest.raises(record_hook.NotRecorded):  # a trace write is a write too
        record_hook.hook(root, line(kind="run.state"), before_write=lambda: order.append("cancel"))
    assert order[:1] == ["cancel"]


def test_the_watchdog_ends_a_hung_hook_quietly(live, tmp_path):
    """stdin held open: the hook process exits 0 at the hard timeout, leaving no lock or torn line."""
    import subprocess
    import sys

    root, run, _ = live
    code = (
        "import sys; from orch import workcheck; workcheck.HARD_TIMEOUT = 0.5\n"
        "from orch.cli import main; raise SystemExit(main(['record', 'hook']))"
    )
    env = {**os.environ, "ORCH_ROOT": str(root)}
    p = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, env=env, cwd=root)
    try:
        assert p.wait(timeout=30) == 0
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
        p.stdin.close()
    runs_dir = root / ".orch/record/runs"
    assert not runs_dir.exists() or not list(runs_dir.glob("*.lock"))
    assert record.read_run(root, run).status in ("ok", "unavailable")


def _helper(proj, monkeypatch):
    gid = tickets.ensure_general(proj, "phone:Marco")
    rec = runs.claim(proj, gid, "agent:helper", "claude", pid=os.getpid())
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ORCH_TICKET", gid)
    monkeypatch.setenv("ORCH_RUN", rec["run"])
    return gid, rec["run"]


def test_a_chat_helper_records_only_into_its_own_run(proj, monkeypatch):
    from orch import chat

    gid, own = _helper(proj, monkeypatch)
    assert chat.is_helper(proj)
    with hider.use_hider(hider.Hider({"deploy-key": SECRET})):
        assert record_hook.hook(proj, line(id="toolu_own"))["run"] == own
        # another run's id with the helper's ticket: not a claim that belongs together
        other = tickets.create(proj, "Parent", "human:t")
        parent = runs.claim(proj, other["id"], "agent:x", "claude", pid=os.getpid())
        monkeypatch.setenv("ORCH_RUN", parent["run"])
        with pytest.raises(record_hook.NotRecorded, match="not active"):
            record_hook.hook(proj, line(id="toolu_forged"))
        # the parent's own pair, from a process that is not the helper's (env changed by the helper itself)
        monkeypatch.setenv("ORCH_TICKET", other["id"])
        assert not chat.is_helper(
            proj
        )  # the env is the same-user boundary; the process-tree proof still applies
    assert [e["id"] for e in events(proj, own)] == ["toolu_own"]


def test_a_held_run_lock_spools_the_hook_line_within_two_seconds(live):
    """A PreToolUse hook must never freeze the agent: a busy lock waits 1 s, then the line is spooled."""
    root, run, _ = live
    record_hook.hook(root, line(id="toolu_first"))  # the run file and folders exist
    lock = root / ".orch/record/runs" / f"{run}.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)  # somebody else's fresh lock
    try:
        t0 = time.perf_counter()
        got = record_hook.hook(root, line(id="toolu_busy"))
        elapsed = time.perf_counter() - t0
    finally:
        os.close(fd)
        lock.unlink()
    assert elapsed < 2 and got["pending"] is True and got["seq"] is None
    assert len(list((root / ".orch/record/pending" / run).glob("*.json"))) == 1


def test_helper_env_with_the_parent_claim_among_ancestors_writes_only_its_own_run(proj, monkeypatch):
    """The claim comes from the environment (ORCH_RUN/ORCH_TICKET), not from whatever pid is an ancestor."""
    gid = tickets.ensure_general(proj, "phone:Marco")
    parent_t = tickets.create(proj, "Parent", "human:t")
    parent = runs.claim(
        proj, parent_t["id"], "agent:x", "claude", pid=os.getpid()
    )  # this process: an ancestor
    helper = runs.claim(proj, gid, "agent:helper", "claude", pid=os.getpid())
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ORCH_TICKET", gid)
    monkeypatch.setenv("ORCH_RUN", helper["run"])
    with hider.use_hider(hider.Hider({"deploy-key": SECRET})):
        assert record_hook.hook(proj, line(id="toolu_h"))["run"] == helper["run"]
    assert [e["id"] for e in events(proj, helper["run"])] == ["toolu_h"]
    assert record.read_run(proj, parent["run"]).status == "unavailable"  # the parent's log is untouched


def test_files_from_the_caller_are_normalised_and_kept(live):
    root, run, _ = live
    files = [
        f"{root}/src/app.py",
        "docs/readme.md",
        f"{root}/../outside.txt",
        "/etc/passwd",
        "../up.txt",
        f"{root}/src/app.py",
        "a\\b",
        *[f"{root}/f{n}" for n in range(1, 10)],
    ]
    got = record_hook.hook(root, line(files=files))
    assert got["via"] == "hook"
    assert got["files"] == ["src/app.py", "docs/readme.md", *[f"f{n}" for n in range(1, 7)]]
    assert events(root, run)[0]["files"] == got["files"]


@pytest.mark.parametrize("files", ["src/app.py", None, {"a": "b"}])
def test_files_not_a_list_is_not_stored(live, files):
    root, run, _ = live
    assert "files" not in record_hook.hook(root, line(files=files))


def test_files_on_another_hook_kind_are_not_stored(live):
    root, run, _ = live
    got = record_hook.hook(
        root, line(kind="denial", outcome={"ok": False, "error": "No", "ms": None}, files=["a.py"])
    )
    assert got["kind"] == "denial" and "files" not in got


def test_files_filter_keeps_them_and_refused_kinds_stay_refused():
    assert record.hook_entry_filter({"kind": "step", "files": ["a.py", "/abs"]})["files"] == ["a.py", "/abs"]
    with pytest.raises(record.RecordRefused):
        record.hook_entry_filter({"kind": "run.state", "files": ["a.py"]})


def test_a_file_path_that_changes_under_the_hider_is_dropped(live):
    root, run, _ = live
    got = record_hook.hook(root, line(files=[f"{root}/src/app.py", f"{root}/{SECRET}.txt"]))
    assert got["files"] == ["src/app.py"]


# ---------------------------------------------------------------- the tool's own hook payload (W2b 1.7)

TOOL_ID = "toolu_01ReadNotes"
SID = "7f3c2a9e-1b4d-4c6e-9a21-5d0e8f7b3c11"
READ = {"kind": "tool", "name": "Read", "action": None, "source": "builtin", "version": None}


def tool_hook(event, tid=TOOL_ID, name="Read", inp=None, **extra):
    """What the tool's PreToolUse/PostToolUse hook sends on stdin; the wiring passes it on unchanged."""
    raw = {
        "session_id": SID,
        "transcript_path": "/elsewhere/transcript.jsonl",
        "cwd": "/elsewhere",
        "permission_mode": "default",
        "hook_event_name": event,
        "tool_name": name,
        "tool_input": {"file_path": "notes.txt"} if inp is None else inp,
        "tool_use_id": tid,
    }
    if event == "PostToolUse":
        raw["tool_response"] = {"type": "text", "file": {"filePath": "notes.txt", "content": "hello"}}
    return json.dumps({**raw, **extra})


def use_line(tid=TOOL_ID, name="Read", inp=None, uuid="u-1"):
    block = dict(type="tool_use", id=tid, name=name, input={"file_path": "notes.txt"} if inp is None else inp)
    return json.dumps(dict(type="assistant", session_id=SID, uuid=uuid, message=dict(content=[block])))


def result_line(tid=TOOL_ID, content="hello", uuid="u-2"):
    block = dict(type="tool_result", tool_use_id=tid, content=content)
    return json.dumps(dict(type="user", session_id=SID, uuid=uuid, message=dict(content=[block])))


def run_lines(root, run):
    """The run file as written (not the reader's dedupe view)."""
    return [json.loads(x) for x in (root / f".orch/record/runs/{run}.jsonl").read_text().splitlines()]


@pytest.fixture
def tool_run(live, monkeypatch):
    monkeypatch.setenv("ORCH_AGENT", "claude")  # what the wrapper sets for its agent (runs.wrap)
    return live


def test_pre_and_post_tool_use_of_one_call_make_one_step_with_its_detail(tool_run):
    from orch import cli_record

    root, run, tid = tool_run
    pre = record_hook.hook(root, tool_hook("PreToolUse"))
    post = record_hook.hook(root, tool_hook("PostToolUse"))
    assert pre["id"] == post["id"] == TOOL_ID  # the tool's own tool_use_id, never h_<run>:<seq>
    assert (pre["kind"], pre["outcome"], pre["detail"]) == ("step", None, None)
    assert post["kind"] == "step" and post["outcome"] == {"ok": True, "error": None, "ms": None}
    for got in (pre, post):
        assert got["via"] == "hook" and got["harness"] == "claude" and got["session"] == SID
        assert got["run"] == run and got["ticket"] == tid and got["agent"] == "main"
        assert got["used"] == READ and got["text"] == "Read notes.txt" and got["files"] == ["notes.txt"]
    detail = record.read_detail(root, run, post["detail"].rsplit("/", 1)[1][:-5]).unwrap()
    assert detail["id"] == TOOL_ID and detail["input"] == {"file_path": "notes.txt"}
    assert detail["output"]["file"]["content"] == "hello"
    assert record_hook.hook(root, tool_hook("PostToolUse")) is None  # delivered twice: one line
    model = cli_record.run_model(run, events(root, run))
    assert [(u["name"], u["result"]) for u in model["uses"]] == [("Read", "ok")]  # one call, one use
    assert "/elsewhere" not in (root / f".orch/record/runs/{run}.jsonl").read_text()  # nothing else is kept


def test_hook_and_collector_of_one_tool_call_leave_one_record_line_each(tool_run):
    from orch import collect_claude

    root, run, tid = tool_run
    record_hook.hook(root, tool_hook("PreToolUse"))
    record_hook.hook(root, tool_hook("PostToolUse"))
    ctx = dict(run=run, ticket=tid, harness="claude", workspace=str(root))
    stats = collect_claude.collect([use_line(), result_line()], record.registered_writer(root), ctx)
    assert stats["written"] == 0 and stats["deduped"] == 2  # same id, kind and state: the hook's line stays
    assert [(e["id"], e["via"], e["outcome"] is not None) for e in run_lines(root, run)] == [
        (TOOL_ID, "hook", False),
        (TOOL_ID, "hook", True),
    ]


def test_a_denied_call_is_a_started_step_and_the_logs_denial(tool_run):
    from orch import collect_claude

    root, run, tid = tool_run
    bash = {"command": "rm -rf build"}
    record_hook.hook(root, tool_hook("PreToolUse", tid="toolu_denied", name="Bash", inp=bash))
    # the person said no: the tool sends no PostToolUse; its result line names the denial
    denied = {"tool_name": "Bash", "tool_use_id": "toolu_denied", "tool_input": bash}
    end = json.dumps({"type": "result", "uuid": "u-end", "is_error": False, "permission_denials": [denied]})
    ctx = dict(run=run, ticket=tid, harness="claude", workspace=str(root))
    collect_claude.collect([use_line("toolu_denied", "Bash", bash), end], record.registered_writer(root), ctx)
    got = [(e["kind"], e["via"], e["outcome"]) for e in events(root, run) if e["id"] == "toolu_denied"]
    assert got == [
        ("step", "hook", None),
        ("denial", "log", {"ok": False, "error": "Not allowed by this workspace", "ms": None}),
    ]


@pytest.mark.parametrize(
    "name, used",
    [
        ("mcp__files__read_doc", {"kind": "mcp", "name": "files", "action": "read_doc", "source": "harness"}),
        ("Strange<Tool>", {"kind": "tool", "name": "StrangeTool", "action": None, "source": "builtin"}),
        (None, {"kind": "tool", "name": "Tool", "action": None, "source": "builtin"}),
    ],
)
def test_an_unknown_tool_is_still_one_step_with_its_id(tool_run, name, used):
    root, run, _ = tool_run
    got = record_hook.hook(root, tool_hook("PreToolUse", tid="toolu_x1", name=name, inp={}))
    assert got["kind"] == "step" and got["id"] == "toolu_x1" and got["used"] == {**used, "version": None}
    assert "files" not in got  # only the file tools name files


@pytest.mark.parametrize(
    "payload",
    [
        tool_hook("Stop"),  # not a tool call
        tool_hook("UserPromptSubmit"),
        tool_hook("PreToolUse", tid=""),  # no tool-call id: Pre and Post could never be put together
        tool_hook("PostToolUse", tid=5),
        json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Read"}),
        json.dumps({"tool_name": "Read", "tool_use_id": TOOL_ID}),
    ],
)
def test_a_payload_that_is_not_a_tool_call_is_not_recorded(tool_run, payload):
    root, run, _ = tool_run
    with pytest.raises(record_hook.NotRecorded, match="not valid"):
        record_hook.hook(root, payload)
    assert record.read_run(root, run).status == "unavailable"
    assert "invalid" in lost_notes(root)


@pytest.mark.parametrize("agent", [None, "codex"])
def test_a_tool_payload_needs_an_agent_whose_output_orch_reads(tool_run, monkeypatch, agent):
    root, run, _ = tool_run
    if agent is None:
        monkeypatch.delenv("ORCH_AGENT")
    else:
        monkeypatch.setenv("ORCH_AGENT", agent)
    with pytest.raises(record_hook.NotRecorded, match="not valid"):
        record_hook.hook(root, tool_hook("PreToolUse"))
    assert record.read_run(root, run).status == "unavailable"


def test_a_helper_start_is_left_to_the_log(tool_run):
    root, run, _ = tool_run
    with pytest.raises(record_hook.NotRecorded, match="helper") as e:
        record_hook.hook(root, tool_hook("PreToolUse", name="Task", inp={"description": "Look around"}))
    assert e.value.reason is None and lost_text(root) == ""  # not a loss: the log numbers the helper
    assert record.read_run(root, run).status == "unavailable"


def test_the_hook_command_takes_the_tools_payload_on_stdin(tool_run, monkeypatch, capsys):
    root, run, _ = tool_run
    assert _main(monkeypatch, stdin=tool_hook("PreToolUse") + "\n") == 0
    assert _main(monkeypatch, stdin=tool_hook("PostToolUse") + "\n") == 0
    assert capsys.readouterr().err == ""
    got = [(e["id"], e["outcome"] is not None) for e in events(root, run)]
    assert got == [(TOOL_ID, False), (TOOL_ID, True)]


@pytest.mark.skipif(os.name == "nt", reason="no process-tree proof on Windows yet (TODO W2b 1.7: VM proof)")
def test_the_generated_command_reaches_the_hook_and_is_proven_inside_the_run(tool_run, subprocess_home):
    """The exact line from the run's settings, run by a shell below this run's process as the tool runs it: it
    passes the run check and stops only at the writer (a child has no registered hider and no keys here)."""
    import subprocess

    from orch import adapters

    root, run, _ = tool_run
    cmd = adapters.reminder_doc("claude", root)["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    r = subprocess.run(
        cmd, shell=True, cwd=root, input=tool_hook("PreToolUse"), capture_output=True, text=True, timeout=60,
        env={**os.environ, "ORCH_ROOT": str(root)},
    )  # fmt: skip
    assert r.returncode == 0 and r.stderr == "orch: Recording is off until key hiding is ready.\n"
    assert "hider_off" in lost_notes(root)  # a proven caller: the trace is under the run
    assert record.read_run(root, run).status == "unavailable"  # nothing raw, nothing at all


# ---------------------------------------------------------------- the oneshot wrapper feeds its collector


def _fake_agent(tmp_path, root):
    """An agent that prints a stream-json run (init, one Read and its result, the end) and saves the ORCH_*
    variables it was given."""
    stream = [
        {"type": "system", "subtype": "init", "session_id": SID, "uuid": "u-init"},
        json.loads(use_line(inp={"file_path": f"{root}/notes.txt"})),
        json.loads(result_line()),
        {"type": "result", "subtype": "success", "is_error": False, "session_id": SID, "uuid": "u-end",
         "num_turns": 1, "usage": {"input_tokens": 3, "output_tokens": 4}},
    ]  # fmt: skip
    out, seen = tmp_path / "stream.jsonl", tmp_path / "agent-env.json"
    out.write_text("".join(json.dumps(x) + "\n" for x in stream))
    script = tmp_path / "agent.py"
    script.write_text(
        "import json, os, sys\n"
        "env = {k: v for k, v in os.environ.items() if k[:5] == 'ORCH_'}\n"
        f"open({str(seen)!r}, 'w').write(json.dumps(env))\n"
        f"sys.stdout.write(open({str(out)!r}).read())\n"
    )
    return [sys.executable, str(script)], seen


def test_the_wrapper_records_the_agents_stream_and_the_hook_lines_win(tool_run, tmp_path, monkeypatch):
    root, run, tid = tool_run
    monkeypatch.setattr(runs, "_on_term", lambda *a: None)  # no SIGTERM handler left in the test process
    inp = {"file_path": f"{root}/notes.txt"}
    record_hook.hook(root, tool_hook("PreToolUse", inp=inp))  # the tool's hooks fire during the call
    record_hook.hook(root, tool_hook("PostToolUse", inp=inp))
    before = {k for k in os.environ if k.startswith("ORCH_") and k != "ORCH_VIA"}
    argv, seen = _fake_agent(tmp_path, root)
    assert runs.wrap(root, run, tid, "claude", argv) == 0
    lines = run_lines(root, run)
    assert [(e["via"], e["outcome"] is not None) for e in lines if e["id"] == TOOL_ID] == [
        ("hook", False),
        ("hook", True),
    ]  # the collector's two lines of that call were dropped: one line each
    from_log = [e for e in lines if e["via"] == "log"]
    assert [e["kind"] for e in from_log] == ["run.state", "usage", "run.state"]  # what only the log says
    assert all(e["run"] == run and e["ticket"] == tid and e["harness"] == "claude" for e in lines)
    assert [e["files"] for e in lines if e["id"] == TOOL_ID] == [["notes.txt"], ["notes.txt"]]
    env = json.loads(seen.read_text())
    assert (env["ORCH_RUN"], env["ORCH_TICKET"], env["ORCH_AGENT"]) == (run, tid, "claude")
    assert set(env) == before | {"ORCH_RUN", "ORCH_TICKET", "ORCH_AGENT", "ORCH_ROOT"}  # nothing new to forge


def test_the_wrapper_records_nothing_while_key_hiding_is_not_ready(proj, tmp_path, monkeypatch):
    from orch import run_record

    t = tickets.create(proj, "No hider", "human:t")
    rec = runs.claim(proj, t["id"], "agent:x", "claude", pid=os.getpid())
    monkeypatch.setattr(hider, "_registered", None)
    monkeypatch.setattr(runs, "_on_term", lambda *a: None)
    real, results = run_record.collect_turn, []
    monkeypatch.setattr(run_record, "collect_turn", lambda *a: results.append(real(*a)))
    argv, _ = _fake_agent(tmp_path, proj)
    assert runs.wrap(proj, rec["run"], t["id"], "claude", argv) == 0
    assert results == [None]  # the collector was asked and wrote nothing (never raw)
    assert not (proj / ".orch/record/runs").exists()


def test_a_later_turn_never_reuses_an_earlier_turns_ids(tool_run, tmp_path):
    from orch import run_record

    root, run, tid = tool_run
    no_uuid = json.dumps({"type": "result", "is_error": False})  # default ids <run>:<seq>
    first = run_record.collect_turn(root, run, tid, "claude", root, [no_uuid])
    second = run_record.collect_turn(root, run, tid, "claude", root, [no_uuid])
    assert first["written"] == second["written"] == 1  # the second turn's line is not taken for a repeat
    assert len({e["id"] for e in run_lines(root, run)}) == 2
    assert run_record.collect_turn(root, run, tid, "codex", root, [no_uuid]) is None  # no collector
