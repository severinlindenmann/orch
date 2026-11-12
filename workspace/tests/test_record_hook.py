"""`orch record hook`: the narrow hook entry of the record (contracts/activity.md, vectors hook_entry)."""

import base64
import io
import json
import os
import re
import sys
import time
import urllib.parse
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
    kind = vector["line"]["kind"]
    helper = {"kind": "helper", "name": "Helper", "action": None, "source": "harness", "version": None}
    raw = dict(
        vector["line"],
        run=run,
        text="x",
        used=USED if kind == "step" else helper if kind.startswith("helper.") else None,
        **({"agent": "h_1", "parent": "main"} if kind.startswith("helper.") else {}),
        **({"data": {"used": 0.4, "window": "5h", "status": "ok"}} if kind == "usage" else {}),
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
    monkeypatch.setattr(
        record_hook, "record_writer", lambda r: (_ for _ in ()).throw(record.RecordOff("off"))
    )
    record_hook.cli(root, io.StringIO(line()))
    assert "off" in capsys.readouterr().err


def test_dedupe_with_a_collector_line(live):
    root, run, tid = live
    hook_ev = record_hook.hook(root, line(outcome={"ok": True, "error": None, "ms": 5}))
    assert hook_ev["outcome"] == {"ok": None, "error": None, "ms": None}  # a hook never says how a call ended
    collector = dict(hook_ev, via="log", outcome={"ok": True, "error": None, "ms": 5})
    collector.pop("seq")
    with hider.use_hider(hider.Hider({"deploy-key": SECRET})):
        got = record.registered_writer(root).append(collector)  # same id/kind/finished: the log line wins
        assert got is not None and got["replaced_hook"] is True and "conflict" not in got
        assert record.registered_writer(root).append(collector) is None  # a log repeat
    assert [(e["via"], e["outcome"]["ok"]) for e in events(root, run)] == [("log", True)]
    assert (
        record_hook.hook(root, line(outcome={"ok": True, "error": None, "ms": 5})) is None
    )  # a hook line after the log's: dropped
    # a hook may not say a call was denied (record.HOOK_KINDS, N1b); another origin keeps its own key
    no = {"ok": False, "error": "no", "ms": 1}
    with pytest.raises(record_hook.NotRecorded):
        record_hook.hook(root, line(kind="denial", used=USED, outcome=no))
    other = dict(collector, kind="denial", via="core", outcome=no, used=USED)
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
    # fixed time of day: the cap is per run AND DAY, a base near midnight UTC split the lines over two days
    base = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    for n in range(record._LOST_RUN_LINES + 20):
        record.note_lost(root, run, "invalid", now=base + timedelta(minutes=n))
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
        stored = record.registered_writer(root).append(collector)
    assert stored["id"] == first["id"] and stored["replaced_hook"] is True  # the same hashed id: one call
    assert [e["via"] for e in events(root, run) if e["id"] == first["id"]] == ["log"]


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
    helper = {"kind": "helper", "name": "Helper", "action": None, "source": "harness", "version": None}
    got = record_hook.hook(
        root, line(kind="helper.start", agent="h_1", parent="main", used=helper, files=["a.py"])
    )
    assert got["kind"] == "helper.start" and "files" not in got


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
    # finished, provisional: a hook line is the agent's word, it never says how the call ended (H1)
    assert post["kind"] == "step" and post["outcome"] == {"ok": None, "error": None, "ms": None}
    for got in (pre, post):
        assert got["via"] == "hook" and got["harness"] == "claude" and got["session"] == SID
        assert got["run"] == run and got["ticket"] == tid and got["agent"] == "main"
        assert got["used"] == READ and got["text"] == "Read notes.txt" and got["files"] == ["notes.txt"]
    detail = record.read_detail(root, run, post["detail"].rsplit("/", 1)[1][:-5]).unwrap()
    assert detail["id"] == TOOL_ID and detail["input"] == {"file_path": "notes.txt"}
    assert detail["output"] == {"type": "text", "file": {"filePath": "notes.txt", "content": "hello"}}
    assert record_hook.hook(root, tool_hook("PostToolUse")) is None  # delivered twice: one line
    model = cli_record.run_model(run, events(root, run))
    assert [(u["name"], u["result"]) for u in model["uses"]] == [("Read", "unknown")]  # one call, one use
    assert "/elsewhere" not in (root / f".orch/record/runs/{run}.jsonl").read_text()  # nothing else is kept


def test_hook_and_collector_of_one_tool_call_the_logs_lines_replace_the_hooks(tool_run):
    """The hook lines come first (as the call happens); the log's lines of that call replace them, started and
    finished alike (N1: a hook line is the agent's word): how the call really ended, its time, its detail."""
    from orch import cli_record, collect_claude

    root, run, tid = tool_run
    record_hook.hook(root, tool_hook("PreToolUse"))
    record_hook.hook(root, tool_hook("PostToolUse"))
    ctx = dict(run=run, ticket=tid, harness="claude", workspace=str(root))
    stats = collect_claude.collect([use_line(), result_line()], record.registered_writer(root), ctx)
    assert stats["written"] == 2 and stats["deduped"] == 0
    assert (stats["tool_calls"], stats["hook_seen"]) == (1, 1)  # the hook's started line said the same
    assert [(e["id"], e["via"], e["outcome"] is not None) for e in run_lines(root, run)] == [
        (TOOL_ID, "hook", False),
        (TOOL_ID, "hook", True),
        (TOOL_ID, "log", False),
        (TOOL_ID, "log", True),
    ]
    seen = events(root, run)
    assert [(e["via"], e["outcome"] and e["outcome"]["ok"]) for e in seen] == [("log", None), ("log", True)]
    assert not any("conflict" in e for e in seen)
    detail = record.read_detail(root, run, seen[1]["detail"].rsplit("/", 1)[1][:-5]).unwrap()
    assert detail["output"] == "hello"  # the log's detail replaced the hook's
    assert [u["result"] for u in cli_record.run_model(run, seen)["uses"]] == ["ok"]
    assert record_hook.hook(root, tool_hook("PostToolUse")) is None  # a late hook end after the log: dropped
    assert record_hook.hook(root, tool_hook("PreToolUse")) is None  # and a late started line


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
        ("step", "log", None),  # the log's started line replaced the hook's
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


def test_the_wrapper_records_the_agents_stream_its_lines_replace_the_hooks(tool_run, tmp_path, monkeypatch):
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
        ("log", False),
        ("log", True),
    ]  # the collector's lines replace the hook's (the started one and the provisional end)
    from_log = [e for e in lines if e["via"] == "log"]
    assert [e["kind"] for e in from_log] == ["run.state", "step", "step", "usage", "run.state"]
    assert all(e["run"] == run and e["ticket"] == tid and e["harness"] == "claude" for e in lines)
    assert [e["files"] for e in lines if e["id"] == TOOL_ID] == [["notes.txt"]] * 4
    shown = [e for e in events(root, run) if e["id"] == TOOL_ID]
    assert [(e["via"], e["outcome"] and e["outcome"]["ok"]) for e in shown] == [("log", None), ("log", True)]
    assert not any("conflict" in e for e in shown)
    assert "hooks_missing" not in lost_notes(root) and "hooks_off" not in lost_notes(root)
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


def _hook_event(run, tid, **kw):
    """A line as `orch record hook` hands it to the writer (via hook, no id: the writer gives h_<run>:<n>)."""
    return {**collector_line(run, tid, 0), "id": None, "via": "hook", **kw}


def test_later_turn_ids_stay_unique_with_deduped_lines_and_hook_lines_in_between(tool_run, monkeypatch):
    """M2: a collector's id counter also counts the lines dedupe drops, so its `<run>:<n>` ids run ahead of
    the file's seqs; hook lines land while it writes. The next turn still never reuses an id."""
    from orch import run_record

    root, run, tid = tool_run
    record_hook.hook(root, tool_hook("PreToolUse"))
    record_hook.hook(root, tool_hook("PostToolUse"))
    no_uuid = json.dumps({"type": "result", "is_error": False})  # a default id <run>:<n>
    # turn 1: a replayed started line is a repeat (dropped): the next id <run>:6 is ahead of its seq 5
    lines = [use_line(), result_line(), use_line(), no_uuid]
    first = run_record.collect_turn(root, run, tid, "claude", root, lines)
    assert first["deduped"] == 1 and first["written"] == 3
    assert [e["seq"] for e in run_lines(root, run) if e["id"] == f"{run}:6"] == [5]
    real = record_hook.record_writer(root)

    class Interleaved:  # turn 2: a hook line lands before every collector line
        def append(self, event, **kw):
            real.append(_hook_event(run, tid))
            return real.append(event, **kw)

        def __getattr__(self, name):  # the rest (the spool drain before numbering) is the real writer's
            return getattr(real, name)

    monkeypatch.setattr(record_hook, "record_writer", lambda r: Interleaved())
    second = run_record.collect_turn(root, run, tid, "claude", root, [no_uuid])
    assert second["written"] == 1 and second["deduped"] == 0  # not taken for a repeat of the first turn's
    ids = [e["id"] for e in run_lines(root, run) if e["id"].startswith(f"{run}:")]
    assert len(ids) == 2 and len(set(ids)) == 2
    keys = [(e["id"], e["kind"], e["outcome"] is not None, e["via"]) for e in run_lines(root, run)]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("error", [record.RecordUnavailable("io"), record.RecordBusy("busy")])
def test_a_record_that_cannot_be_read_as_written_gets_nothing_from_the_turn(tool_run, monkeypatch, error):
    """M2: the ids are numbered from the run file as written; when it cannot be read, nothing is numbered
    from a guess (ids restarting at 1 would collide), and the skipped turn leaves a trace."""
    from orch import run_record

    root, run, tid = tool_run
    record_hook.hook(root, tool_hook("PreToolUse"))
    before = run_lines(root, run)
    monkeypatch.setattr(record, "run_lines", lambda *a, **k: (_ for _ in ()).throw(error))
    no_uuid = json.dumps({"type": "result", "is_error": False})
    assert run_record.collect_turn(root, run, tid, "claude", root, [no_uuid]) is None
    assert run_lines(root, run) == before
    rows = [json.loads(x) for x in lost_notes(root).splitlines()]
    assert [(r["reason"], r.get("error")) for r in rows] == [("collector_error", type(error).__name__)]


def test_a_tampered_record_gets_nothing_and_no_second_trace(tool_run, monkeypatch):
    from orch import run_record

    root, run, tid = tool_run
    monkeypatch.setattr(
        record, "run_lines", lambda *a, **k: (_ for _ in ()).throw(record.RecordTampered("link"))
    )
    assert run_record.collect_turn(root, run, tid, "claude", root, [use_line()]) is None
    assert lost_notes(root) == ""  # the integrity alert is the trace
    assert record.read_run(root, run).status == "unavailable"


def test_run_lines_reads_the_file_as_written(tool_run):
    root, run, _ = tool_run
    assert record.run_lines(root, run) == []  # no run file yet
    record_hook.hook(root, tool_hook("PreToolUse"))
    record_hook.hook(root, tool_hook("PreToolUse"))  # a repeat: not written
    record_hook.hook(root, line(id="toolu_other"))
    assert [e["seq"] for e in record.run_lines(root, run)] == [1, 2]


@pytest.mark.parametrize("failure", [KeyError("seq"), OSError("disk full"), ImportError("x")])
def test_a_collector_that_breaks_never_stops_the_run_and_leaves_one_trace(tool_run, monkeypatch, failure):
    """M1: anything but a refusal of the record leaves `collector_error` with the type (never the message)."""
    from orch import run_record

    root, run, tid = tool_run
    monkeypatch.setattr(run_record, "collect_turn", lambda *a: (_ for _ in ()).throw(failure))
    for _ in range(3):
        runs._record_turn(root, run, tid, "claude", root, use_line())  # no exception
    rows = [json.loads(x) for x in lost_notes(root).splitlines()]
    assert [(r["run"], r["reason"], r["error"]) for r in rows] == [
        (run, "collector_error", type(failure).__name__)
    ]
    assert "disk full" not in lost_notes(root)


def test_a_refused_record_leaves_no_collector_trace(tool_run, monkeypatch):
    from orch import run_record

    root, run, tid = tool_run
    monkeypatch.setattr(
        run_record, "collect_turn", lambda *a: (_ for _ in ()).throw(record.RecordTampered("link"))
    )
    runs._record_turn(root, run, tid, "claude", root, use_line())
    assert lost_notes(root) == ""


def test_the_lost_trace_keeps_only_a_plain_type_name(tool_run):
    root, run, _ = tool_run
    record.note_lost(root, run, "collector_error", error="has spaces: and a message")
    assert [set(json.loads(x)) for x in lost_notes(root).splitlines()] == [
        {"v", "schema", "at", "run", "reason"}
    ]


def test_a_forged_hook_success_never_hides_the_logs_failure(tool_run):
    """H1: the agent can send any line to `orch record hook` (it is inside the run's process tree) and can
    read its real tool-call ids from its transcript. A forged success never suppresses the log's failure."""
    from orch import cli_record, collect_claude

    root, run, tid = tool_run
    forged = line(
        id=TOOL_ID, used=READ, text="Read notes.txt", files=["notes.txt"],
        outcome={"ok": True, "error": None, "ms": 1}, payload={"input": "forged", "output": "forged"},
    )  # fmt: skip
    stored = record_hook.hook(root, forged)  # the generic path: whatever it sends, the end is provisional
    assert stored["outcome"] == {"ok": None, "error": None, "ms": None}
    ctx = dict(run=run, ticket=tid, harness="claude", workspace=str(root))
    failed = dict(type="tool_result", tool_use_id=TOOL_ID, content="Exit code 1\nboom", is_error=True)
    end = json.dumps(dict(type="user", session_id=SID, uuid="u-2", message=dict(content=[failed])))
    stats = collect_claude.collect([use_line(), end], record.registered_writer(root), ctx)
    assert stats["written"] == 2  # the log's started line (the forged line is finished) and its failed end
    finished = [e for e in events(root, run) if e["outcome"] is not None]
    assert [(e["via"], e["outcome"]["ok"], e["outcome"]["error"]) for e in finished] == [
        ("log", False, "Exit code 1")
    ]
    detail = record.read_detail(root, run, finished[0]["detail"].rsplit("/", 1)[1][:-5]).unwrap()
    assert detail["output"] == "Exit code 1\nboom"  # the forged detail is gone with its line
    assert [u["result"] for u in cli_record.run_model(run, events(root, run))["uses"]] == ["failed"]
    assert record_hook.hook(root, forged) is None  # sent again after the log: dropped


def test_a_forged_started_line_never_hides_what_the_call_did(tool_run):
    """N1: the agent sends a started line for its real tool-call id naming another tool, text and files (a
    Bash `rm -rf build/` as "Read notes.txt"). Both lines are kept, the log's with `conflict`; readers
    believe it."""
    from orch import cli_record, collect_claude

    root, run, tid = tool_run
    record_hook.hook(root, line(id=TOOL_ID, used=READ, text="Read notes.txt", files=["notes.txt"]))
    bash = {"command": "rm -rf build/"}
    failed = dict(type="tool_result", tool_use_id=TOOL_ID, content="Exit code 1", is_error=True)
    end = json.dumps(dict(type="user", session_id=SID, uuid="u-2", message=dict(content=[failed])))
    ctx = dict(run=run, ticket=tid, harness="claude", workspace=str(root))
    writer = record.registered_writer(root)
    stats = collect_claude.collect([use_line(TOOL_ID, "Bash", bash), end], writer, ctx)
    assert (stats["written"], stats["tool_calls"], stats["hook_seen"]) == (2, 1, 0)  # not this call's line
    seen = [(e["via"], e["used"]["name"], e["text"], e.get("conflict")) for e in events(root, run)]
    assert seen == [
        ("hook", "Read", "Read notes.txt", None),
        ("log", "Bash", "Run rm -rf build/", True),
        ("log", "Bash", "Run rm -rf build/", True),  # a hook line of the call is compared, finished or not
    ]
    model = cli_record.run_model(run, events(root, run))
    assert [(u["name"], u["result"]) for u in model["uses"]] == [("Bash", "failed")]


def test_run_model_reports_the_logs_result_on_a_conflict(tool_run):
    """A hook end that says how the call ended (another writer, an older file) and disagrees with the log:
    both lines are kept with `conflict`, and the counts take the log's result, whichever came last."""
    from orch import cli_record

    root, run, tid = tool_run
    writer = record.registered_writer(root)
    done = {"ok": True, "error": None, "ms": 1}
    writer.append(collector_line(run, tid, 0) | {"id": "toolu_c", "via": "hook", "outcome": done})
    failed = {"ok": False, "error": "Exit code 1", "ms": 9}
    got = writer.append(collector_line(run, tid, 0) | {"id": "toolu_c", "outcome": failed})
    assert got["conflict"] is True
    seen = events(root, run)
    assert [(e["via"], e["outcome"]["ok"]) for e in seen] == [("hook", True), ("log", False)]
    assert [u["result"] for u in cli_record.run_model(run, seen)["uses"]] == ["failed"]
    assert [u["result"] for u in cli_record.run_model(run, seen[::-1])["uses"]] == ["failed"]


@pytest.mark.parametrize("forged_pre", [True, False])
def test_a_forged_hook_end_never_beats_the_logs_started_line(tool_run, forged_pre):
    """N1a: the call never finishes in the log (an interrupted turn). The agent sends a provisional end (and
    maybe a started line) naming another tool, text and files. The log's started line carries `conflict`
    (a hook end is compared with it too), counts believe it (result unknown), and a hook end sent after it
    is dropped."""
    from orch import cli_record, collect_claude

    root, run, tid = tool_run
    forged = dict(id=TOOL_ID, used=READ, text="Read notes.txt", files=["notes.txt"])
    if forged_pre:
        record_hook.hook(root, line(**forged))
    end = record_hook.hook(root, line(**forged, outcome={"ok": True, "error": None, "ms": 1}))
    assert end["outcome"] == {"ok": None, "error": None, "ms": None}
    ctx = dict(run=run, ticket=tid, harness="claude", workspace=str(root))
    bash = {"command": "rm -rf build/"}
    collect_claude.collect([use_line(TOOL_ID, "Bash", bash)], record.registered_writer(root), ctx)
    seen = events(root, run)
    assert [(e["via"], e["used"]["name"], e["outcome"] is not None, e.get("conflict")) for e in seen] == [
        *([("hook", "Read", False, None)] if forged_pre else []),
        ("hook", "Read", True, None),
        ("log", "Bash", False, True),
    ]
    for order in (seen, seen[::-1]):
        uses = cli_record.run_model(run, order)["uses"]
        assert [(u["name"], u["result"]) for u in uses] == [("Bash", "unknown")]
    assert record_hook.hook(root, line(**forged, outcome={"ok": True, "error": None, "ms": 2})) is None


def test_one_bad_spooled_entry_never_stops_the_runs_record(tool_run, monkeypatch):
    """N2: entries in pending/<run>/ that cannot be read, checked or committed are skipped with an alert;
    the good ones are committed and the next turn is written (its _so_far drain never raises)."""
    from orch import run_record

    root, run, tid = tool_run
    writer = record.registered_writer(root)
    writer.append(collector_line(run, tid, 0) | {"id": "toolu_first"})
    lock = root / ".orch/record/runs" / f"{run}.lock"
    os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))  # somebody else's fresh lock
    for tid_ in ("toolu_a", "toolu_b"):
        got = writer.append(collector_line(run, tid, 0) | {"id": tid_}, lock_wait=0.05)
        assert got["pending"] is True
    lock.unlink()
    pending = root / ".orch/record/pending" / run
    (pending / "00000000000000000001_text.json").write_text("not json")
    (pending / "00000000000000000002_list.json").write_text("[]")
    (pending / "00000000000000000003_dir.json").mkdir()
    real = record.RecordWriter._commit

    def commit(self, event, *a, **kw):
        if event["id"] == "toolu_a":
            raise ValueError("an entry that breaks inside the commit")
        return real(self, event, *a, **kw)

    monkeypatch.setattr(record.RecordWriter, "_commit", commit)
    for _ in range(2):  # every later turn too
        run_record.collect_turn(root, run, tid, "claude", root, [use_line(), result_line()])
    ids = [e["id"] for e in run_lines(root, run)]
    assert ids[:2] == ["toolu_first", "toolu_b"] and "toolu_a" not in ids and ids.count(TOOL_ID) == 2
    alerts = "".join(p.read_text() for p in (root / ".orch/record/alerts").glob("2*.jsonl"))
    assert '"target":"folder"' in alerts and '"reason":"swapped"' in alerts


def test_the_logs_detail_replaces_the_hooks_atomically(tool_run, monkeypatch):
    """N5: the log's detail is written to a temporary file and renamed over the hook's. Up to the rename the
    hook's file is untouched (never half-written); a failed rename is no crash: the log line is detail_lost,
    the hook's orphaned payload goes (N5 rule), and no temporary file stays behind."""
    from orch import collect_claude

    root, run, tid = tool_run
    record_hook.hook(root, tool_hook("PreToolUse"))
    post = record_hook.hook(root, tool_hook("PostToolUse"))
    path = root / ".orch/record" / post["detail"]
    before = path.read_bytes()
    real, at_rename = os.replace, []

    def failing(src, dst, *a, **kw):
        if str(dst).endswith(path.name):
            at_rename.append(path.read_bytes())  # the new payload is complete in the temporary file by now
            raise OSError(5, "rename failed")
        return real(src, dst, *a, **kw)

    monkeypatch.setattr(record.os, "replace", failing)
    ctx = dict(run=run, ticket=tid, harness="claude", workspace=str(root))
    collect_claude.collect([use_line(), result_line()], record.registered_writer(root), ctx)
    assert at_rename == [before]
    end = [e for e in run_lines(root, run) if e["via"] == "log" and e["outcome"] is not None]
    assert [(e["detail"], e.get("detail_lost")) for e in end] == [(None, True)]
    assert not path.exists() and not [p for p in path.parent.iterdir() if p.name.startswith("tmp_")]


def test_a_provisional_hook_end_after_the_logs_failure_is_dropped(tool_run):
    from orch import collect_claude

    root, run, tid = tool_run
    ctx = dict(run=run, ticket=tid, harness="claude", workspace=str(root))
    failed = dict(type="tool_result", tool_use_id=TOOL_ID, content="Exit code 2", is_error=True)
    end = json.dumps(dict(type="user", session_id=SID, uuid="u-2", message=dict(content=[failed])))
    collect_claude.collect([use_line(), end], record.registered_writer(root), ctx)
    assert record_hook.hook(root, tool_hook("PostToolUse")) is None
    assert [(e["via"], e["outcome"]["ok"]) for e in events(root, run) if e["outcome"]] == [("log", False)]


def test_an_edit_hook_keeps_no_copy_of_the_whole_file(tool_run):
    """M3: Claude's PostToolUse tool_response of an Edit carries the whole old file and a patch."""
    root, run, _ = tool_run
    edit = {"file_path": "notes.txt", "old_string": "a", "new_string": "b"}
    response = {
        "filePath": "notes.txt", "oldString": "a", "newString": "b", "replaceAll": False,
        "originalFile": "WHOLE FILE BEFORE " * 50, "structuredPatch": [{"lines": ["-a", "+b"]}],
        "userModified": False,
    }  # fmt: skip
    post = record_hook.hook(
        root, tool_hook("PostToolUse", tid="toolu_edit", name="Edit", inp=edit, tool_response=response)
    )
    detail = record.read_detail(root, run, post["detail"].rsplit("/", 1)[1][:-5]).unwrap()
    assert detail["output"] == {"filePath": "notes.txt"} and detail["input"] == edit
    blob = b"".join(p.read_bytes() for p in (root / ".orch/record").rglob("*") if p.is_file())
    assert b"originalFile" not in blob and b"WHOLE FILE BEFORE" not in blob and b"structuredPatch" not in blob


def test_a_big_read_result_is_cut_and_other_results_are_text():
    from orch import collect_claude

    big = {"type": "text", "file": {"filePath": "a.txt", "content": "x" * 100_000, "numLines": 1}}
    out = collect_claude.hook_output(big)
    assert out["file"]["filePath"] == "a.txt" and out["file"]["numLines"] == 1
    assert len(out["file"]["content"]) < 33_000 and out["file"]["content"].endswith("more characters]")
    assert collect_claude.hook_output([{"type": "text", "text": "from mcp"}, {"type": "image"}]) == "from mcp"
    assert collect_claude.hook_output("plain") == "plain" and collect_claude.hook_output(7) is None
    bash = {"stdout": "ok", "stderr": "", "interrupted": False, "isImage": False, "secretInternal": {"x": 1}}
    assert collect_claude.hook_output(bash) == {"stdout": "ok", "stderr": "", "interrupted": False}
    many = collect_claude.hook_output({"filenames": [f"f{n}" for n in range(500)], "numFiles": 500})
    assert len(many["filenames"]) == 100 and many["numFiles"] == 500


def test_a_description_that_is_not_text_is_still_one_line(tool_run):
    root, run, _ = tool_run
    got = record_hook.hook(root, tool_hook("PreToolUse", tid="toolu_d", name="Bash", inp={"description": 42}))
    assert got["text"] == "42"
    nested = tool_hook("PreToolUse", tid="toolu_e", name="Bash", inp={"description": {"a": "b\nc"}})
    assert "\n" not in record_hook.hook(root, nested)["text"]


def test_the_collectors_hook_events_are_the_wired_ones():
    from orch import adapters, collect_claude

    assert set(collect_claude.HOOK_EVENTS) == set(adapters.load("claude")["record_hooks"])


def test_settings_that_switch_the_hooks_off_leave_a_trace(tool_run, tmp_path):
    """M4: the agent can write its folder's tool settings; from its next turn on, the record hooks are off."""
    from orch import run_record

    root, run, tid = tool_run
    work = tmp_path / "copy"
    (work / ".claude").mkdir(parents=True)
    (work / ".claude" / "settings.json").write_text(json.dumps({"disableAllHooks": True}))
    run_record.collect_turn(root, run, tid, "claude", work, [use_line(), result_line()])
    rows = [json.loads(x) for x in lost_notes(root).splitlines()]
    assert [(r["run"], r["reason"]) for r in rows] == [(run, "hooks_off")]


def test_tool_calls_without_any_hook_line_leave_a_trace(tool_run, tmp_path):
    from orch import run_record

    root, run, tid = tool_run
    stats = run_record.collect_turn(root, run, tid, "claude", tmp_path, [use_line(), result_line()])
    assert (stats["tool_calls"], stats["hook_seen"]) == (1, 0)
    assert [json.loads(x)["reason"] for x in lost_notes(root).splitlines()] == ["hooks_missing"]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no FIFOs here")
def test_the_settings_check_never_blocks_on_a_fifo(tmp_path):
    from orch import collect_claude

    (tmp_path / ".claude").mkdir()
    os.mkfifo(tmp_path / ".claude" / "settings.local.json")
    (tmp_path / ".claude" / "settings.json").write_text("not json")
    t0 = time.perf_counter()
    assert collect_claude.hooks_disabled(tmp_path, ".claude/settings.local.json") is False
    assert time.perf_counter() - t0 < 2


def test_a_live_run_gives_its_agent_the_tool_name_the_hook_needs(tool_run, tmp_path, monkeypatch):
    """M5: live runs get the record hooks too (hooks_doc); without ORCH_AGENT every tool call would be a lost
    note, so the live wrapper must set it like the oneshot one."""
    import signal

    root, run, tid = tool_run
    monkeypatch.setattr(runs, "_on_term", lambda *a: None)
    # the wrapper ignores SIGINT: not in the test process
    monkeypatch.setattr(signal, "signal", lambda *a: None)
    seen = tmp_path / "env.json"
    code = f"import json, os; open({str(seen)!r}, 'w').write(json.dumps(dict(os.environ)))"
    runs.wrap_live(root, run, tid, "claude", [sys.executable, "-c", code], None)
    env = json.loads(seen.read_text())
    assert (env["ORCH_AGENT"], env["ORCH_RUN"], env["ORCH_TICKET"]) == ("claude", run, tid)


def test_a_turn_spooled_behind_a_busy_lock_never_shares_ids_with_the_next(tool_run, monkeypatch):
    """N2: the run lock is busy while turn 1 is written, so its lines wait in pending/<run>/. Turn 2 numbers
    its ids after those spooled lines are committed (record.run_lines drains them under the lock first)."""
    from orch import run_record

    root, run, tid = tool_run
    lock = root / ".orch/record/runs" / f"{run}.lock"
    real = run_record._so_far

    def then_busy(*a):
        got = real(*a)
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))  # somebody else's fresh lock
        return got

    monkeypatch.setattr(run_record, "LOCK_WAIT", 0.05)
    monkeypatch.setattr(run_record, "_so_far", then_busy)
    no_uuid = json.dumps({"type": "result", "is_error": False})  # default ids <run>:<n>
    first = run_record.collect_turn(root, run, tid, "claude", root, [no_uuid, no_uuid])
    assert first["written"] == 2 and len(list((root / ".orch/record/pending" / run).glob("*.json"))) == 2
    lock.unlink()
    monkeypatch.setattr(run_record, "_so_far", real)
    second = run_record.collect_turn(root, run, tid, "claude", root, [no_uuid])
    assert second["written"] == 1 and second["deduped"] == 0  # not taken for a repeat of a spooled line
    assert [e["id"] for e in run_lines(root, run)] == [f"{run}:1", f"{run}:2", f"{run}:3"]
    assert not list((root / ".orch/record/pending" / run).glob("*.json"))


def test_a_log_end_without_its_own_detail_removes_the_hooks(tool_run):
    """N5: the log's detail is lost (too large): the hook's provisional payload must not stay behind with no
    line the reader keeps pointing at it."""
    from orch import collect_claude

    root, run, tid = tool_run
    record_hook.hook(root, tool_hook("PreToolUse"))
    post = record_hook.hook(root, tool_hook("PostToolUse"))
    hook_detail = root / ".orch/record" / post["detail"]
    assert hook_detail.is_file()
    ctx = dict(run=run, ticket=tid, harness="claude", workspace=str(root))
    big = result_line(content="x" * (1024**2 + 10))
    collect_claude.collect([use_line(), big], record.registered_writer(root), ctx)
    end = [e for e in events(root, run) if e["outcome"] is not None]
    assert [(e["via"], e["detail"], e.get("detail_lost")) for e in end] == [("log", None, True)]
    assert not hook_detail.exists()


def test_a_hooks_tool_input_is_cut_too():
    """N7: a Write or MultiEdit input holds whole files; the hook's detail keeps each text cut."""
    from orch import collect_claude

    big = {"file_path": "a.txt", "content": "x" * 100_000, "edits": [{"old_string": "a"}] * 300, "n": 3}
    line_ = collect_claude.hook_line(
        {"hook_event_name": "PostToolUse", "tool_use_id": "toolu_w", "tool_name": "Write", "tool_input": big}
    )
    inp = line_["payload"]["input"]
    assert len(inp["content"]) < 33_000 and inp["content"].endswith("more characters]")
    assert len(inp["edits"]) == 100 and inp["edits"][0] == {"old_string": "a"} and inp["n"] == 3
    deep: dict = {}
    node = deep
    for _ in range(100):
        node["x"] = {}
        node = node["x"]
    assert "[cut: nested too deep]" in json.dumps(collect_claude.hook_input(deep))


def test_the_persons_own_settings_that_switch_the_hooks_off_leave_a_trace(tool_run, tmp_path, monkeypatch):
    """N4: the person's own tool settings (under the home) can switch the hooks off too. The home is this
    test's own temp folder (HOME and USERPROFILE set here, not only by conftest): the developer's real
    ~/.claude/settings.json is never written."""
    from conftest import _REAL_HOME_FN

    from orch import run_record

    root, run, tid = tool_run
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    user = Path.home() / ".claude"
    # hard stop before any write: the settings folder must be inside this test's temp folder
    assert user.resolve().is_relative_to(tmp_path.resolve()), user
    assert not user.resolve().is_relative_to((_REAL_HOME_FN() / ".claude").resolve())
    user.mkdir()
    (user / "settings.json").write_text(json.dumps({"disableAllHooks": True}))
    run_record.collect_turn(root, run, tid, "claude", tmp_path / "copy", [use_line(), result_line()])
    rows = [json.loads(x) for x in lost_notes(root).splitlines()]
    assert [(r["run"], r["reason"]) for r in rows] == [(run, "hooks_off")]


def test_a_failing_hooks_check_after_a_recorded_turn_is_not_a_collector_error(tool_run, monkeypatch):
    """N8: the turn was recorded; a check after it that breaks is no collector_error."""
    from orch import run_record

    root, run, tid = tool_run
    monkeypatch.setattr(run_record, "_hooks_off", lambda *a: (_ for _ in ()).throw(OSError("x")))
    runs._record_turn(root, run, tid, "claude", root, "\n".join([use_line(), result_line()]))
    assert len([e for e in events(root, run) if e["via"] == "log"]) == 2
    assert [json.loads(x)["reason"] for x in lost_notes(root).splitlines()] == ["hooks_missing"]


@pytest.mark.parametrize(
    "argv",
    [
        ["record", "--json", "hook", "--bogus"],
        ["record", "--by", "agent:x", "hook"],
        ["record", "hook", "--json", "-x", "extra", "words"],
    ],
)
def test_malformed_hook_argv_still_exits_zero_with_one_stderr_line(live, monkeypatch, capsys, argv):
    """L4: any form of `orch record ... hook` is the hook (no parser): exit 0, nothing on stdout, one line."""
    from orch import cli

    monkeypatch.setattr("sys.stdin", io.StringIO("not json\n"))
    assert cli.main(argv) == 0
    cap = capsys.readouterr()
    assert cap.out == "" and len(cap.err.splitlines()) == 1 and cap.err.startswith("orch: ")


def test_only_the_hook_form_skips_the_parser():
    from orch import is_record_hook

    assert is_record_hook(["record", "hook"]) and is_record_hook(["record", "--json", "--by", "x", "hook"])
    for argv in (
        ["record", "query", "--detail", "hook"],
        ["record", "--by", "hook", "tail"],
        ["ticket", "record", "hook"],
        ["record"],
        [],
    ):
        assert not is_record_hook(argv), argv


@pytest.mark.parametrize(
    "argv",
    [
        ["record", "hook"], ["record", "--json", "hook", "--bogus"], ["record", "--by", "agent:x", "hook"],
        ["record", "hook", "--strict"], ["record", "--by"], ["record", "--by", "hook", "tail"],
        ["record", "query", "--detail", "hook"], ["--json", "record", "hook"], ["ticket", "record", "hook"],
        ["record"], [], ["record", "-x", "hook"], ["record", "--", "hook"],
    ],
)  # fmt: skip
def test_the_console_entry_knows_the_same_hook_form(argv):
    """orch_entry (stdlib only, never imports orch) keeps its own copy of the rule: the two must agree."""
    import orch_entry
    from orch import is_record_hook

    assert orch_entry.is_record_hook(argv) is is_record_hook(argv)


def test_the_console_entry_under_test_is_this_source():
    """orch_entry.py is copied into the environment (not an editable link): a stale copy would test the old
    entry. After a change to src/orch_entry.py, reinstall (uv sync --reinstall-package orch-workspace)."""
    import orch_entry

    src = ROOT / "workspace/src/orch_entry.py"
    assert Path(orch_entry.__file__).read_bytes() == src.read_bytes(), (
        f"{orch_entry.__file__} is stale; run: uv sync --reinstall-package orch-workspace"
    )


@pytest.mark.parametrize(
    "code",
    [
        "sys.argv = ['orch', 'record', '--json', 'hook', '--bogus']",
        "sys.modules['orch.cli'] = None; sys.argv = ['orch', 'record', 'hook']",  # a broken install
    ],
)
def test_the_hook_process_exits_zero_whatever_breaks(tmp_path, code):
    """L4: as the tool runs it (`python -m orch ...`): exit 0, empty stdout, one stderr line."""
    import subprocess

    env = {k: v for k, v in os.environ.items() if not k.startswith("ORCH_RUN") and k != "ORCH_TICKET"}
    run_main = f"import runpy, sys; {code}; runpy.run_module('orch', run_name='__main__', alter_sys=True)"
    r = subprocess.run(
        [sys.executable, "-c", run_main], cwd=tmp_path, input="not json\n", capture_output=True, text=True,
        env=env, timeout=60,
    )  # fmt: skip
    assert (r.returncode, r.stdout) == (0, "") and len(r.stderr.splitlines()) == 1, r.stderr
    assert r.stderr.startswith("orch: ")
    strict = run_main.replace("'hook'", "'hook', '--strict'")
    r = subprocess.run(
        [sys.executable, "-c", strict], cwd=tmp_path, input="not json\n", capture_output=True, text=True,
        env=env, timeout=60,
    )  # fmt: skip
    assert r.returncode == 2 and r.stdout == "" and r.stderr.startswith("Refused: ")


def _console_entry():
    """The `orch` console script's target, as installed (what the hook wiring's `orch record hook` runs)."""
    from importlib.metadata import entry_points

    found = list(entry_points(group="console_scripts", name="orch"))
    assert found and {ep.value for ep in found} == {"orch_entry:main"}, found
    return found[0]


def _hook_env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ORCH_RUN") and k != "ORCH_TICKET"}
    return {**env, **extra}


BAD_FLAG = ["record", "--json", "hook", "--bogus"]


@pytest.mark.parametrize("strict", [False, True])
def test_the_console_entry_with_a_broken_install_still_exits_zero(tmp_path, strict):
    """L4b: the wiring runs the console script (orch_entry:main), not `python -m orch`: its own guard turns a
    broken orch.cli into exit 0, empty stdout, one stderr line (2 only with --strict)."""
    import subprocess

    import orch_entry

    ep = _console_entry()
    assert ep.load() is orch_entry.main
    argv = ["orch", *BAD_FLAG, *(["--strict"] if strict else [])]
    code = (
        "import sys; from importlib.metadata import entry_points; "
        "main = list(entry_points(group='console_scripts', name='orch'))[0].load(); "
        f"sys.modules['orch.cli'] = None; sys.argv = {argv!r}; sys.exit(main())"
    )
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, input="not json\n", capture_output=True, text=True,
        env=_hook_env(), timeout=60,
    )  # fmt: skip
    assert (r.returncode, r.stdout) == (2 if strict else 0, ""), r.stderr
    assert len(r.stderr.splitlines()) == 1 and r.stderr.startswith("Refused: " if strict else "orch: ")


def _installed_script():
    import shutil

    found = shutil.which("orch", path=str(Path(sys.executable).parent))
    if found is None:
        pytest.skip("no installed `orch` script next to this interpreter")
    return found


@pytest.mark.parametrize("case", ["plain", "broken", "updating", "hung"])
def test_the_installed_orch_script_never_fails_a_hook(tmp_path, case):
    """L4b, through the installed `orch` script itself with a bad flag: exit 0, nothing on stdout, at most one
    stderr line, whether orch.cli works, cannot be imported, hangs on import (the watchdog runs before it),
    or an update is in progress (never exit 3, never an import of a half-installed orch)."""
    import subprocess

    script = _installed_script()
    extra = {}
    if case in ("broken", "hung"):
        site = tmp_path / "site"
        site.mkdir()
        body = {
            "broken": "import sys\nsys.modules['orch.cli'] = None\n",
            "hung": (
                "import sys, time\n"
                "class _Hang:\n"
                "    def find_spec(self, name, path=None, target=None):\n"
                "        if name == 'orch.cli':\n"
                "            time.sleep(60)\n"
                "        return None\n"
                "sys.meta_path.insert(0, _Hang())\n"
            ),
        }[case]
        (site / "sitecustomize.py").write_text(body)
        extra["PYTHONPATH"] = str(site)
    elif case == "updating":
        import orch_entry

        home = tmp_path / "toolhome"
        home.mkdir()
        orch_entry.marker_path(home).write_text(str(os.getpid()))  # a live update owner
        extra["ORCH_HOME"] = str(home)
    t0 = time.monotonic()
    r = subprocess.run(
        [script, *BAD_FLAG], cwd=tmp_path, input="not json\n", capture_output=True, text=True,
        env=_hook_env(**extra), timeout=60,
    )  # fmt: skip
    assert (r.returncode, r.stdout) == (0, ""), r.stderr
    assert len(r.stderr.splitlines()) <= 1, r.stderr
    if case != "hung":
        assert r.stderr.startswith("orch: "), r.stderr
    else:
        assert time.monotonic() - t0 < 30  # the watchdog, not the 60 s import


@pytest.mark.skipif(os.name == "nt", reason="no process-tree proof on Windows yet (TODO W2b 1.7: VM proof)")
def test_the_installed_orch_script_records_a_tool_call(proj, subprocess_home, tmp_path, monkeypatch):
    """T2: the installed `orch` script, as the wiring runs it, really writes. A tool's Pre- and PostToolUse
    payloads from inside a live run land in the run record: exit 0, nothing on stdout, nothing on stderr (not
    the guard's "nothing was recorded"). The other console tests pass whether the hook records or not. A child
    builds its hider from the workspace's key store (one key = key hiding ready), so the workspace is a test
    one under ~/.orch-test with the test home from subprocess_home (both removed by exact path)."""
    import shutil
    import subprocess
    import tempfile

    from conftest import _REAL_HOME_FN

    from orch import keystore

    script = _installed_script()
    base = _REAL_HOME_FN() / ".orch-test"
    root = Path(tempfile.mkdtemp(prefix="pytest-hook-", dir=base))
    try:
        keystore.add(root, "deploy-key", "token", SECRET)
        t = tickets.create(root, "Hook me", "human:t")
        rec = runs.claim(root, t["id"], "agent:x", "claude", pid=os.getpid())  # the child's ancestor
        home = tmp_path / "account"
        home.mkdir()
        env = _hook_env(
            ORCH_ROOT=str(root), ORCH_RUN=rec["run"], ORCH_TICKET=t["id"], ORCH_AGENT="claude",
            HOME=str(home), USERPROFILE=str(home),
        )  # fmt: skip
        inp = {"file_path": "notes.txt", "note": SECRET}
        for event in ("PreToolUse", "PostToolUse"):
            r = subprocess.run(
                [script, "record", "hook"], cwd=root, input=tool_hook(event, inp=inp) + "\n",
                capture_output=True, text=True, env=env, timeout=60,
            )  # fmt: skip
            assert (r.returncode, r.stdout) == (0, ""), r.stderr
            assert "nothing was recorded" not in r.stderr and r.stderr == "", (event, r.stderr)
        seen = events(root, rec["run"])
        assert [(e["id"], e["via"], e["outcome"] is not None) for e in seen] == [
            (TOOL_ID, "hook", False),
            (TOOL_ID, "hook", True),
        ]
        detail = record.read_detail(root, rec["run"], seen[1]["detail"].rsplit("/", 1)[1][:-5]).unwrap()
        assert detail["input"] == {"file_path": "notes.txt", "note": "[hidden: deploy-key]"}  # store's hider
        kept = "".join(p.read_text() for p in (root / ".orch/record").rglob("*") if p.is_file())
        assert SECRET not in kept and not lost_text(root)  # nothing raw, nothing set aside
    finally:
        if root.name.startswith("pytest-hook-") and root.parent == base:  # only our own temp folder
            shutil.rmtree(root, ignore_errors=True)


def test_every_lost_reason_is_named_in_the_contract():
    """N6: no strict validator of orch.record-lost/1 exists; the contract names every reason written."""
    text = (ROOT / "contracts/activity.md").read_text()
    for reason in (*record.LOST_REASONS, *record.UNPROVEN_REASONS, "trimmed"):
        assert reason in text, reason


# --- G1 H3: the hider derives every escaped form; hide and backstop use the same set ---
_QUOTED = 'p@ss"w0rd\\ZZ-9'  # a quote and a backslash
_PEM = "\n".join(
    [
        "-----BEGIN KEY-----",
        "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC",
        "abcdEFGHijklMNOPqrstUVWXyz0123456789",
        "-----END KEY-----",
    ]
)


def _variants(value):
    """Forms of a key a tool, a shell or a JSON layer can print (the search test looks for every one)."""
    raw = value.encode()
    forms = {value, json.dumps(value)[1:-1], json.dumps(value, ensure_ascii=False)[1:-1]}
    forms.add(json.dumps(json.dumps(value))[1:-1][1:-1])  # JSON inside JSON
    forms.add(value.replace("\\", "\\\\").replace('"', '\\"'))  # shell style backslash escapes
    forms.add(urllib.parse.quote(value, safe=""))
    forms.add(urllib.parse.quote_plus(value))
    for pad in range(3):
        enc = base64.b64encode(b"\0" * pad + raw).decode().rstrip("=")
        forms.add(enc[(8 * pad + 5) // 6 : 8 * (pad + len(raw)) // 6])
    forms.add(raw.hex())
    # twice escaped: non-ASCII as \\u00e4, and a "/" written \/ at the first level and escaped again
    forms.add(json.dumps(json.dumps({"p": value}))[1:-1].split('\\"p\\": \\"', 1)[1].rsplit('\\"}', 1)[0])
    forms.add(json.dumps(json.dumps(value, ensure_ascii=False), ensure_ascii=False)[1:-1][1:-1])
    forms.add(json.dumps(json.dumps(value).replace("/", "\\/"))[1:-1][1:-1])
    forms.add(re.sub(r'([$`"\\])', r"\\\1", value))  # shell double quotes
    return {f for f in forms if len(f) >= 8}


def _record_blob(root):
    return b"".join(p.read_bytes() for p in (root / ".orch/record").rglob("*") if p.is_file())


def _record_strings(root):
    """Every decoded string value and key of every JSON line under .orch/record/."""
    found = []

    def walk(value):
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(k)
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    for p in (root / ".orch/record").rglob("*"):
        if p.is_file():
            content = p.read_text()
            for text in content.splitlines() or [content]:
                try:
                    walk(json.loads(text))
                except ValueError:
                    found.append(text)
    return found


_UNICODE = 'pä/ss"w0rd\\é+/ZZ-9$`'


@pytest.mark.parametrize("secret", [_QUOTED, _PEM, _UNICODE], ids=["quote-backslash", "pem", "unicode-slash"])
def test_escaped_and_encoded_forms_never_reach_the_record_folder(proj, monkeypatch, secret):
    t = tickets.create(proj, "Hook me", "human:t")
    rec = runs.claim(proj, t["id"], "agent:x", "claude", pid=os.getpid())
    monkeypatch.setenv("ORCH_RUN", rec["run"])
    monkeypatch.setenv("ORCH_TICKET", t["id"])
    forms = sorted(_variants(secret))
    assert len(forms) >= 6
    with hider.use_hider(hider.Hider({"deploy-key": secret})):
        for n, form in enumerate(forms):
            record_hook.hook(
                proj,
                line(
                    id=f"toolu_{n}",
                    text="Run with " + form.replace("\n", " "),
                    data={"note": f"token {form}"},
                    outcome={"ok": False, "error": f"failed {form}", "ms": 1},
                    payload={
                        "input": {"command": f"curl -H {form}", form: "as a key"},
                        "output": f"leaked {form}",
                    },
                ),
            )
    blob = _record_blob(proj)
    assert b"[hidden: " in blob
    strings = _record_strings(proj)
    for form in forms:
        assert form.encode() not in blob, form
        assert json.dumps(form)[1:-1].encode() not in blob, form  # as the file spells a string holding it
        assert not any(form in s for s in strings), form


def test_the_decoded_value_check_catches_what_the_serialized_check_misses():
    """Removing Hider.leaks from the writer's backstop must fail this: a hider whose scan of the serialized
    line sees nothing (as when an escape form was not derived) still cannot get a key into a line."""

    class Blind(hider.Hider):
        def hide_text(self, s):
            return s if s.startswith("{") else super().hide_text(s)

    blind = Blind({"deploy-key": SECRET})
    obj = {"text": f"x {SECRET}", "data": {SECRET: 1}}
    line = record._json(obj)
    assert blind.hide_text(line) == line  # the serialized check alone passes it
    with pytest.raises(record.RecordInvalid):
        record._hidden_line(blind, obj)
    assert record._hidden_line(blind, {"text": "clean"}) == b'{"text":"clean"}'
