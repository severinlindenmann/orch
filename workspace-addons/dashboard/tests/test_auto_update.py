"""Automatic update in the dashboard: the switch op, the "Got it" on the Home note, the person's clicks that keep
an update from starting, and the background look that hands them to orch."""

from __future__ import annotations

import pytest
from orch import addons  # noqa: F401 - imported first, so the isolation fixture fakes its real home

from orch_dashboard import actions, update


def test_switch_op_is_a_plain_config_set_and_needs_on_or_off():
    assert actions.build_argv("update.auto", {"on": True})[:4] == ["config", "set", "update.auto", "on"]
    assert actions.build_argv("update.auto", {"on": False})[:4] == ["config", "set", "update.auto", "off"]
    with pytest.raises(actions.BadRequest):
        actions.build_argv("update.auto", {"on": "yes"})
    assert actions.needs_session("update.auto")  # a watch-only page cannot turn it on


def test_got_it_clears_the_note_only_with_a_page_session(ws):
    from orch import autoupdate

    autoupdate._write(
        "auto-update-note.json", {"state": "updated", "at": __import__("time").time(), "to": "orch 17"}
    )
    assert autoupdate.note() is not None
    with pytest.raises(actions.NeedsPerson):
        actions.run_op(ws, actions.SELF, "update.note.dismiss", {}, session=False)
    assert actions.run_op(ws, actions.SELF, "update.note.dismiss", {}, session=True)[0] == 200
    assert autoupdate.note() is None


def test_note_reaches_the_live_page_state(ws, act_orch):
    import time

    from orch import autoupdate

    from orch_dashboard.data import load_state

    autoupdate._write(
        "auto-update-note.json",
        {"state": "updated", "at": time.time(), "from": "orch 16", "to": "orch 17", "changes": ["A"]},
    )
    s = load_state(ws, orch_bin=str(act_orch), with_settings=True)
    assert s["auto_update_note"]["to"] == "orch 17" and s["auto_update_note"]["changes"] == ["A"]
    assert (
        load_state(ws, orch_bin=str(act_orch), with_addons=False)["auto_update_note"] is None
    )  # no snapshot


def test_a_click_under_way_is_passed_to_the_look(ws, monkeypatch):
    from orch import autoupdate

    seen = []
    monkeypatch.setattr(
        autoupdate, "tick", lambda root, start, last_click=None, clicking=False: seen.append(clicking) or "x"
    )
    with update.click():
        update.tick_once(ws, actions.SELF, dict)
    update.tick_once(ws, actions.SELF, dict)
    assert seen == [True, False]
    assert update._clicks["last"] > 0


def test_the_look_starts_the_detached_update_with_the_persons_environment(ws, monkeypatch):
    from orch import autoupdate

    started = []

    def fake_start(argv, orch_bin, cwd, env):
        started.append((argv, cwd, env))
        return 4242

    monkeypatch.setattr(autoupdate, "tick", lambda root, start, **k: f"pid {start()}")
    assert update.tick_once(ws, actions.SELF, lambda: {"HOME": "/h"}, start=fake_start) == "pid 4242"
    assert started == [(["update"], ws, {"HOME": "/h"})]


def test_a_broken_look_never_stops_the_dashboard(ws, monkeypatch):
    from orch import autoupdate

    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(autoupdate, "tick", boom)
    assert update.tick_once(ws, actions.SELF, dict) == "error"


def test_update_info_carries_the_switch(monkeypatch):
    from orch import updateinfo

    monkeypatch.setattr(updateinfo, "info", lambda use_cache=True: {"installed": {}, "newest": None})
    assert update.update_info()["auto"]["on"] is False


def test_a_note_written_while_the_page_is_open_shows_without_a_workspace_change(ws):
    """The note lives in the orch home: the cached state must not hide it until a ticket changes."""
    import time

    from orch import autoupdate

    from orch_dashboard.state_cache import StateCache

    cache = StateCache(ws, None)
    cache._store({"rev": "r1", "auto_update_note": None}, None)
    assert cache._served()[0]["auto_update_note"] is None
    autoupdate._write("auto-update-note.json", {"state": "updated", "at": time.time(), "to": "orch 17"})
    served = cache._served()[0]
    assert served["auto_update_note"]["to"] == "orch 17" and served["rev"] != "r1"  # the page renders again
    cache._store({"rev": "r2"}, None)  # a snapshot: no note key, none added
    assert "auto_update_note" not in cache._served()[0]
