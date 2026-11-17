"""ORCH-266: the live page's state says which tickets wait in line and why none starts; snapshots carry none."""

from __future__ import annotations

from orch import (
    addons,  # noqa: F401 - imported first, so the isolation fixture fakes its real home
    runs_live,
)

from orch_dashboard import data
from orch_dashboard.state_cache import StateCache

LINE = {"waiting": ["t_aaaaaa"], "why": "the computer is very busy", "limit": None}


def test_live_state_carries_the_line_and_snapshots_do_not(ws, act_orch, monkeypatch):
    monkeypatch.setattr(runs_live, "line_status", lambda root: LINE)
    assert data.load_state(ws, orch_bin=str(act_orch), with_settings=True)["start_line"] == LINE
    assert data.load_state(ws, orch_bin=str(act_orch), with_addons=False)["start_line"] is None


def test_a_broken_line_read_shows_nothing(ws, monkeypatch):
    def boom(root):
        raise OSError("unreadable")

    monkeypatch.setattr(runs_live, "line_status", boom)
    assert data.start_line(ws) is None


def test_the_reason_is_read_fresh_while_tickets_wait(ws, monkeypatch):
    cache = StateCache(ws, None)
    monkeypatch.setattr(runs_live, "line_status", lambda root: LINE)
    cache._store({"rev": "r1", "start_line": LINE}, None)
    assert cache._served()[0]["rev"] == "r1"  # unchanged: same revision
    monkeypatch.setattr(runs_live, "line_status", lambda root: {**LINE, "why": None})
    served = cache._served()[0]
    assert (
        served["start_line"]["why"] is None and served["rev"] != "r1"
    )  # the load passed: the page renders again
    cache._store({"rev": "r2", "start_line": None}, None)  # nothing waits: not read again on each poll
    monkeypatch.setattr(runs_live, "line_status", lambda root: LINE)
    assert cache._served()[0]["start_line"] is None
