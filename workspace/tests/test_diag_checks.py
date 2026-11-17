"""Each doctor check detects its problem on a fixture, and says ok / cannot_check otherwise."""

import json
import os
import time

import pytest
from diag_fixtures import claim_dead, reset_diag, stuck

from orch import diag, diag_checks, diag_collect, runs, tickets


@pytest.fixture
def proj(proj, monkeypatch):
    (proj / ".orch").mkdir(exist_ok=True)
    reset_diag(monkeypatch)
    return proj


def snap(proj, scope=None, now=None):
    now = now or time.time()
    col = diag_collect.collect_all(proj, scope or {}, now)
    return {"now": now, "collected": col, "events": list(diag_collect.recent_events(proj, now - 86400))}


def one(proj, name, scope=None, now=None):
    s = snap(proj, scope, now)
    (c,) = [c for c in diag_checks.run_all(s) if c["name"] == name]
    assert set(c) == {"name", "verdict", "fact", "evidence"} and c["verdict"] in (
        "problem",
        "ok",
        "cannot_check",
    )
    return c


def test_all_checks_are_registered_and_one_file_each():
    names = {m.NAME for m in diag_checks.modules()}
    assert names == {
        "run_gone_ticket_working", "dead_lock_holder", "no_heartbeat", "waiting_for_permission",
        "ticket_op_refused", "hook_lines_missing", "relay_unreachable", "clock_skew", "disk_low",
        "diag_dropped",
    }  # fmt: skip


def test_a_check_that_raises_is_cannot_check_and_the_rest_still_run(proj, monkeypatch):
    mod = next(iter(diag_checks.modules()))
    monkeypatch.setattr(mod, "check", lambda s: 1 / 0)
    out = diag_checks.run_all(snap(proj))
    assert [c for c in out if c["name"] == mod.NAME][0]["verdict"] == "cannot_check" and len(
        out
    ) == 9  # relay is off: its check has nothing to say


def test_run_gone_ticket_working(proj):
    assert one(proj, "run_gone_ticket_working")["verdict"] == "ok"
    tid = stuck(proj)
    c = one(proj, "run_gone_ticket_working")
    assert c["verdict"] == "problem" and tid in c["evidence"][0] and "no run record" in c["evidence"][0]
    claim_dead(proj, tid)
    assert "process gone" in one(proj, "run_gone_ticket_working")["evidence"][0]


def test_a_fresh_working_ticket_gets_the_grace(proj):
    stuck(proj, minutes_ago=0.1)
    assert one(proj, "run_gone_ticket_working")["verdict"] == "ok"


def test_dead_lock_holder_uses_the_start_time_not_only_the_pid(proj):
    tid = stuck(proj)
    rec = claim_dead(proj, tid)
    c = one(proj, "dead_lock_holder")
    assert c["verdict"] == "problem" and any("held by pid" in e for e in c["evidence"])
    # a lock whose pid is alive (this test) but with ANOTHER start time is a reused pid: dead too
    lock = runs.run_dir(proj) / "tickets" / f"{tid}.lock"
    lock.write_text(f"{os.getpid()} 2001-01-01T00:00:00Z", encoding="utf-8")
    rec["pid"] = os.getpid()
    rec["pid_started"] = "2001-01-01T00:00:00Z"
    runs._write(proj, rec)
    assert any("held by pid" in e for e in one(proj, "dead_lock_holder")["evidence"])
    lock.write_text(runs.procs.own_token(), encoding="utf-8")  # our own live token
    rec["pid_started"] = runs.procs.pid_started(os.getpid())
    runs._write(proj, rec)
    assert one(proj, "dead_lock_holder")["verdict"] == "ok"


def test_no_heartbeat_says_progress_unknown_not_hung(proj):
    tid = stuck(proj)
    rec = runs._new_record(tid, "agent:claude", "claude", "oneshot", tickets.load(proj, tid), None, proj)
    rec["pid"] = os.getpid()
    rec["pid_started"] = runs.procs.pid_started(os.getpid())
    rec["renewed_at"] = rec["started_at"] = runs._iso(time.time() - 3600)
    runs._write(proj, rec)
    c = one(proj, "no_heartbeat")
    assert c["verdict"] == "problem" and "progress unknown" in c["fact"] and "hung" not in c["fact"].lower()
    rec["renewed_at"] = runs._iso(time.time())
    runs._write(proj, rec)
    assert one(proj, "no_heartbeat")["verdict"] == "ok"


def test_no_heartbeat_leaves_out_a_live_session_that_waits_at_its_prompt(proj):
    """r-1117-1015-ws: ten helpers waiting for checks or the person (live state idle) were listed all day."""
    tid = stuck(proj)
    rec = runs._new_record(tid, "agent:claude", "claude", "live", tickets.load(proj, tid), None, proj)
    rec["pid"] = os.getpid()
    rec["pid_started"] = runs.procs.pid_started(os.getpid())
    rec["renewed_at"] = rec["started_at"] = runs._iso(time.time() - 3600)
    for waiting in ("idle", "attention"):
        rec["live"] = {"state": waiting, "since": runs._iso(time.time() - 3000)}
        runs._write(proj, rec)
        assert one(proj, "no_heartbeat")["verdict"] == "ok"
    rec["live"] = {"state": "working", "since": runs._iso(time.time() - 3000)}
    runs._write(proj, rec)
    assert one(proj, "no_heartbeat")["verdict"] == "problem"


def test_waiting_for_permission(proj):
    tid = stuck(proj)
    rec = runs._new_record(tid, "agent:claude", "claude", "live", tickets.load(proj, tid), None, proj)
    rec["pid"] = os.getpid()
    rec["pid_started"] = runs.procs.pid_started(os.getpid())
    rec["live"] = {"state": "attention", "since": runs._iso(time.time() - 600)}
    runs._write(proj, rec)
    assert one(proj, "waiting_for_permission")["verdict"] == "problem"
    rec["live"] = {"state": "idle", "since": rec["live"]["since"]}
    runs._write(proj, rec)
    assert one(proj, "waiting_for_permission")["verdict"] == "ok"


def test_ticket_op_refused_repeatedly(proj):
    for _ in range(2):
        diag.log("ticket.op_refused", "warn", root=proj, ticket="t_aaaaaa", op="done", guard="closed_ticket")
    assert one(proj, "ticket_op_refused")["verdict"] == "ok"
    diag.log("ticket.op_refused", "warn", root=proj, ticket="t_aaaaaa", op="done", guard="closed_ticket")
    c = one(proj, "ticket_op_refused")
    assert c["verdict"] == "problem" and "t_aaaaaa done: refused 3x" in c["evidence"][0]


def _refused_at(proj, at: float, guard: str, ticket="t_bbbbbb"):
    d = diag._folder(proj)
    line = {"v": 1, "at": diag_collect._iso(at), "src": "cli", "lvl": "info", "ev": "ticket.op_refused",
            "ticket": ticket, "kv": {"op": "op", "guard": guard}}  # fmt: skip
    diag._append(d, "cli", diag_collect._iso(at)[:10], (json.dumps(line) + "\n").encode())


def test_ticket_op_refused_clears_an_hour_after_the_writer_stopped(proj):
    """r-1117-1015-ws: refusals on a closed ticket that stopped at 01:00 still showed at 10:15."""
    now = time.time()
    for m in (200, 185, 170, 155, 140):
        _refused_at(proj, now - m * 60, "closed_ticket")
    assert one(proj, "ticket_op_refused", now=now)["verdict"] == "ok"
    for m in (30, 20, 10):
        _refused_at(proj, now - m * 60, "closed_ticket")
    c = one(proj, "ticket_op_refused", now=now)
    assert c["verdict"] == "problem"
    assert c["evidence"] == ["t_bbbbbb: refused 3x in the last hour (guard closed_ticket)"]


def test_ticket_op_refused_does_not_count_write_conflicts_or_mix_guards(proj):
    now = time.time()
    for m in (30, 20, 10):
        _refused_at(proj, now - m * 60, "conflict")
    _refused_at(proj, now - 60, "Refused")
    _refused_at(proj, now - 50, "closed_ticket")
    assert one(proj, "ticket_op_refused", now=now)["verdict"] == "ok"


def test_hook_lines_missing(proj):
    assert one(proj, "hook_lines_missing")["verdict"] == "ok"
    d = proj / ".orch" / "record" / "alerts"
    d.mkdir(parents=True)
    (d / "hook-lost-2026-11-14.jsonl").write_text(
        '{"at":"2026-11-14T10:00:00Z","run":"r_abc12345","reason":"hooks_missing"}\n'
    )
    c = one(proj, "hook_lines_missing")
    assert c["verdict"] == "problem" and "hooks_missing" in c["evidence"][0]


def test_relay_unreachable(proj, monkeypatch):
    monkeypatch.setattr(diag_collect, "addon_on", lambda root, name: name == "relay")
    assert one(proj, "relay_unreachable")["verdict"] == "ok"
    box = proj / ".orch" / "outbox"
    box.mkdir()
    m = box / "m_1.json"
    m.write_text("{}")
    os.utime(m, (time.time() - 3600, time.time() - 3600))
    c = one(proj, "relay_unreachable")
    assert c["verdict"] == "problem" and "oldest for 60 min" in c["evidence"][0]


def test_relay_send_failures_in_the_log(proj, monkeypatch):
    monkeypatch.setattr(diag_collect, "addon_on", lambda root, name: name == "relay")
    for _ in range(3):
        diag.log("relay.send_failed", "warn", root=proj, what="proposal", reason="URLError")
    assert one(proj, "relay_unreachable")["verdict"] == "problem"


def test_clock_skew(proj):
    assert one(proj, "clock_skew")["verdict"] == "cannot_check"  # nothing to compare
    stuck(proj, minutes_ago=-60)  # updated an hour in the FUTURE
    c = one(proj, "clock_skew")
    assert c["verdict"] == "problem" and "in the future" in c["evidence"][0]


def test_disk_low(proj, monkeypatch):
    assert one(proj, "disk_low")["verdict"] == "ok"
    monkeypatch.setattr(
        diag_collect.shutil, "disk_usage", lambda p: type("U", (), {"free": 1024, "total": 10**9})()
    )
    assert one(proj, "disk_low")["verdict"] == "problem"


def test_diag_dropped(proj):
    assert one(proj, "diag_dropped")["verdict"] == "ok"
    diag._drop("write")
    c = one(proj, "diag_dropped")
    assert c["verdict"] == "problem" and "1 dropped" in c["evidence"][0]


def test_diag_dropped_only_counts_the_last_hour(proj):
    """r-1117-1015-ws: a burst of dropped dashboard events at 08:30 kept the check red at 10:15."""
    now = time.time()
    d = diag._folder(proj)
    for ago, n in ((7200, 40), (5400, 2)):
        at = diag_collect._iso(now - ago)
        line = {"v": 1, "at": at, "src": "ui", "lvl": "warn", "ev": "diag.dropped", "kv": {"count": n}}
        diag._append(d, "ui", at[:10], (json.dumps(line) + "\n").encode())
    c = one(proj, "diag_dropped", now=now)
    assert c["verdict"] == "ok" and "42 earlier today" in c["fact"]
    at = diag_collect._iso(now - 120)
    line = {"v": 1, "at": at, "src": "ui", "lvl": "warn", "ev": "diag.dropped", "kv": {"count": 5}}
    diag._append(d, "ui", at[:10], (json.dumps(line) + "\n").encode())
    c = one(proj, "diag_dropped", now=now)
    assert c["verdict"] == "problem" and c["evidence"] == [f"5 dropped in the last hour, last {at}"]


def test_optional_parts_stay_invisible_while_off(proj, run):
    """R1.1: with the relay off nothing of `orch diag` names an optional part: not the checks, the state, the
    report files, the text of `inspect`, nor the skill an agent reads."""
    import json as _json
    from pathlib import Path

    from orch import cli_diag, diag_report, skills

    tid = stuck(proj)
    (proj / ".orch" / "outbox").mkdir()  # even leftovers of a relay that was once on are not looked at
    (proj / ".orch" / "outbox" / "m_1.json").write_text("{}")
    texts = [_json.dumps(cli_diag.inspect(proj, tid)), cli_diag._text_inspect(cli_diag.inspect(proj, tid))]
    folder = Path(diag_report.make(proj, ticket=tid)["path"])
    texts += [p.read_text(encoding="utf-8") for p in folder.rglob("*") if p.is_file()]
    src = skills.packaged_skills_dir() / "orch-diagnose"
    texts += [p.read_text(encoding="utf-8") for p in src.rglob("*") if p.is_file()]
    for t in texts:
        low = t.lower()
        assert not any(w in low for w in ("relay", "phone", "publish")), [
            w for w in ("relay", "phone", "publish") if w in low
        ]
