"""Each doctor check detects its problem on a fixture, and says ok / cannot_check otherwise."""

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
    assert [c for c in out if c["name"] == mod.NAME][0]["verdict"] == "cannot_check" and len(out) == 10


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


def test_hook_lines_missing(proj):
    assert one(proj, "hook_lines_missing")["verdict"] == "ok"
    d = proj / ".orch" / "record" / "alerts"
    d.mkdir(parents=True)
    (d / "hook-lost-2026-11-14.jsonl").write_text(
        '{"at":"2026-11-14T10:00:00Z","run":"r_abc12345","reason":"hooks_missing"}\n'
    )
    c = one(proj, "hook_lines_missing")
    assert c["verdict"] == "problem" and "hooks_missing" in c["evidence"][0]


def test_relay_unreachable(proj):
    assert one(proj, "relay_unreachable")["verdict"] == "ok"
    box = proj / ".orch" / "outbox"
    box.mkdir()
    m = box / "m_1.json"
    m.write_text("{}")
    os.utime(m, (time.time() - 3600, time.time() - 3600))
    c = one(proj, "relay_unreachable")
    assert c["verdict"] == "problem" and "oldest for 60 min" in c["evidence"][0]


def test_relay_send_failures_in_the_log(proj):
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
