"""The Manager (ORCH-147): one hidden, always-on helper session per workspace, next to Chat."""

import json
import os
import time

import pytest

from orch import manager, runs, runs_live, tend, tickets
from orch.errors import Refused


def _live(proj, tid, state="idle", age_min=120):
    rec = runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    rec["live"] = {"state": state, "since": runs._iso(time.time() - age_min * 60)}
    runs._write(proj, rec)
    return rec


def test_the_manager_is_made_once_and_hidden(proj, run):
    assert tickets.manager_id(proj) is None
    tid = tickets.ensure_manager(proj, "human:t")
    assert tickets.ensure_manager(proj, "human:t") == tid
    t = tickets.load(proj, tid)
    assert t["manager"] is True and t["title"] == "Manager" and not t.get("key")
    assert tickets.is_manager(proj, tid) and not tickets.is_general(proj, tid)
    assert tid not in [x["id"] for x in tickets.list_all(proj)]
    assert tid in [x["id"] for x in tickets.list_all(proj, include_general=True)]
    listed = json.loads(run("ticket", "list", "--all", "--json")[1])
    assert tid not in [x["id"] for x in listed]
    assert tickets.general_id(proj) is None  # the Manager is never taken for the Chat ticket


def test_the_manager_file_stays_out_of_git(proj):
    tid = tickets.ensure_manager(proj, "human:t")
    ignore = (proj / ".orch" / ".gitignore").read_text(encoding="utf-8")
    assert f"tickets/{tid}.json" in ignore


@pytest.mark.parametrize("status", ["done", "review", "dropped", "open", "active"])
def test_the_manager_is_never_finished_or_moved(proj, status):
    tid = tickets.ensure_manager(proj, "human:t")
    with pytest.raises(Refused, match="Manager is not a ticket"):
        tickets.set_status(proj, tid, status, "human:t")


def test_idle_close_and_the_watcher_leave_the_manager_alone(proj, run, monkeypatch):
    closed = []
    monkeypatch.setattr(runs_live, "_close", lambda root, rec, interrupt: closed.append(rec["ticket"]))
    monkeypatch.setattr(runs_live, "start_waiting", lambda root: None)
    monkeypatch.delenv("ORCH_RUN_IDLE_SECONDS", raising=False)
    mid = tickets.ensure_manager(proj, "human:t")
    _live(proj, mid, "idle", 600)
    other = json.loads(run("ticket", "new", "Make a report", "--json", "--by", "human:t")[1])["id"]
    _live(proj, other, "idle", 61)
    assert runs_live.cleanup(proj) == [other]
    assert closed == [other]
    assert mid not in [r["ticket"] for r in tend.plan(proj)]


def test_the_manager_takes_no_slot_and_never_waits_in_line(proj, run, monkeypatch):
    mid = tickets.ensure_manager(proj, "human:t")
    _live(proj, mid, "working", 1)
    assert mid not in [r["ticket"] for r in runs_live.live_all(proj)]
    monkeypatch.setattr(runs_live, "_full", lambda root: 1)  # every slot is taken
    other = json.loads(run("ticket", "new", "Make a report", "--json", "--by", "human:t")[1])["id"]
    with pytest.raises(runs.Busy):
        runs_live.start_live(proj, other, "human:t", "claude", fresh=False, take_over=False, busy_text="x")
    runs.release(proj, mid, runs.read(proj, mid)["run"])
    reached = []

    def claimed(*a, **k):
        reached.append(a[1])
        raise RuntimeError("stop here")

    monkeypatch.setattr(runs, "claim_routed", claimed)
    with pytest.raises(RuntimeError, match="stop here"):
        runs_live.start_live(proj, mid, "human:t", "claude", fresh=False, take_over=False, busy_text="x")
    assert reached == [mid]


def test_the_manager_works_in_the_workspace_never_a_copy(proj, monkeypatch):
    from orch import worktrees

    mid = tickets.ensure_manager(proj, "human:t")
    monkeypatch.setattr(worktrees, "route", lambda *a: pytest.fail("the Manager is never routed to a copy"))
    rec, notes = runs.claim_routed(proj, mid, "human:t", "claude", "live", pid=os.getpid())
    assert runs.workdir_for(proj, rec, mid) == proj and notes == []


def test_the_manager_prompt_names_its_role(proj):
    mid = tickets.ensure_manager(proj, "human:t")
    text = manager.prompt(proj, tickets.load(proj, mid), "- human:t: hello")
    assert "Manager" in text and mid in text and "hello" in text
    assert "never finish it" in text


def test_start_makes_it_and_starts_live_once(proj, monkeypatch):
    started = []

    def fake_start(root, tid, by, fresh=False, mode=None, **kw):
        started.append((tid, fresh, mode))
        return {"run": "r_x", "notes": []}

    monkeypatch.setattr(runs, "start", fake_start)
    monkeypatch.setattr(runs, "running", lambda root, tid: bool(started))
    stops = []
    monkeypatch.setattr(runs_live, "stop", lambda root, tid, hold=False: stops.append(tid) or True)
    d = manager.start(proj, "human:t")
    mid = tickets.manager_id(proj)
    assert d["started"] and d["ticket"] == mid and started == [(mid, False, "live")]
    assert d["attach"] == f"orch run attach {mid}"
    again = manager.start(proj, "human:t")
    assert again["started"] is False and len(started) == 1  # already on: nothing happens
    fresh = manager.start(proj, "human:t", fresh=True)
    assert fresh["fresh"] and stops == [mid] and started[-1] == (mid, True, "live")


def test_cli_status_before_and_after(proj, run, monkeypatch):
    code, out, _ = run("manager", "status")
    assert code == 0 and "No Manager yet" in out
    tickets.ensure_manager(proj, "human:t")
    d = json.loads(run("manager", "status", "--json")[1])
    assert d["ticket"] == tickets.manager_id(proj) and d["running"] is False
    code, out, _ = run("manager", "stop")
    assert code == 0 and "not on" in out
