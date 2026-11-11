"""`orch record hook`: the narrow hook entry of the record (contracts/activity.md, vectors hook_entry)."""

import base64
import io
import json
import os
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
