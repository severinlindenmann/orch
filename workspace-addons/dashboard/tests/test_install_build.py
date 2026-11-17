"""Release or development build (issue 957): the dashboard says where this orch came from."""

from __future__ import annotations

from orch import addons  # imported first, so the isolation fixture fakes its real home

from orch_dashboard import update


def test_build_is_read_once_and_given_to_the_page(monkeypatch):
    from orch import updateinfo

    calls = []
    monkeypatch.setattr(update, "_BUILD", [])
    monkeypatch.setattr(addons, "build", lambda: calls.append(1) or "development")
    monkeypatch.setattr(updateinfo, "info", lambda use_cache=True: {"installed": {}, "newest": None})
    assert update.build() == "development" and update.build() == "development" and len(calls) == 1
    assert update.update_info()["build"] == "development"


def test_no_orch_gives_no_build(monkeypatch):
    monkeypatch.setattr(update, "_BUILD", [])

    def broken():
        raise RuntimeError("no orch")

    monkeypatch.setattr(addons, "build", broken)
    assert update.build() is None


def test_start_update_refuses_another_target(tmp_path, monkeypatch):
    monkeypatch.setattr(update, "pagelaunch", object())
    started = []
    code, _ = update.start_update(
        tmp_path, "orch", {}, start=lambda argv, **kw: started.append(argv) or 1, to="x"
    )
    assert code == 400 and not started


def test_the_live_state_carries_the_build_and_a_snapshot_does_not(ws, act_orch, monkeypatch):
    from orch_dashboard.data import load_state

    monkeypatch.setattr(update, "_BUILD", ["development"])
    assert load_state(ws, orch_bin=str(act_orch), with_settings=True)["build"] == "development"
    assert load_state(ws, orch_bin=str(act_orch), with_addons=False)["build"] is None
