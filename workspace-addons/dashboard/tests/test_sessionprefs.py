"""ORCH-361: pins and own names of sessions in the new Focus, kept in the workspace (not per browser, issue 1351)."""

import json
import threading
import urllib.request

import pytest

from orch_dashboard import actions, sessionprefs, sessions
from orch_dashboard.server import make_server

A, B = "t_pinaaaa1", "t_pinbbbb2"


def test_pins_and_names_are_kept_in_the_workspace(tmp_path):
    sessionprefs.set_pin(tmp_path, A, True)
    sessionprefs.set_name(tmp_path, A, "  Lunch\tmoney  ")
    sessionprefs.set_pin(tmp_path, B, False)
    on_disk = json.loads((tmp_path / ".orch" / "run" / "dashboard" / "sessions.json").read_text())
    assert on_disk == {"pins": {A: True, B: False}, "names": {A: "Lunch money"}}
    assert sessionprefs.read(tmp_path) == on_disk


def test_an_empty_name_goes_back_to_the_title_and_long_names_are_cut(tmp_path):
    sessionprefs.set_name(tmp_path, A, "x" * 200)
    assert sessionprefs.read(tmp_path)["names"][A] == "x" * sessionprefs.NAME_MAX
    sessionprefs.set_name(tmp_path, A, "   ")
    assert A not in sessionprefs.read(tmp_path)["names"]
    sessionprefs.set_name(tmp_path, A, None)
    assert sessionprefs.read(tmp_path)["names"] == {}


@pytest.mark.parametrize(
    "call",
    [
        lambda r: sessionprefs.set_pin(r, "../x", True),
        lambda r: sessionprefs.set_pin(r, A, "yes"),
        lambda r: sessionprefs.set_name(r, "t_x", "a"),
        lambda r: sessionprefs.set_name(r, A, 5),
    ],
)
def test_bad_input_is_refused_and_nothing_is_written(tmp_path, call):
    with pytest.raises(sessionprefs.BadPref):
        call(tmp_path)
    assert not (tmp_path / ".orch" / "run" / "dashboard" / "sessions.json").exists()


def test_a_broken_file_reads_as_nothing_kept(tmp_path):
    p = tmp_path / ".orch" / "run" / "dashboard" / "sessions.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"pins": {"../x": True, A: "yes"}, "names": [1]}))
    assert sessionprefs.read(tmp_path) == {"pins": {}, "names": {}}
    p.write_text("not json")
    assert sessionprefs.read(tmp_path) == {"pins": {}, "names": {}}


def test_only_the_newest_choices_are_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(sessionprefs, "KEEP", 3)
    for i in range(5):
        sessionprefs.set_pin(tmp_path, f"t_keep{i:04d}", True)
    assert list(sessionprefs.read(tmp_path)["pins"]) == ["t_keep0002", "t_keep0003", "t_keep0004"]


def test_sessions_without_a_ticket_are_pinned_until_unpinned(tmp_path):
    rows = [
        {"id": A, "title": "Ticket", "kind": ""},
        {"id": B, "title": "Manager", "kind": "manager"},
        {"id": "t_pincccc3", "title": "Plain terminal", "kind": "terminal"},
    ]
    assert [s["pinned"] for s in sessionprefs.apply(tmp_path, [dict(r) for r in rows])] == [False, True, True]
    sessionprefs.set_pin(tmp_path, B, False)
    sessionprefs.set_pin(tmp_path, A, True)
    assert [s["pinned"] for s in sessionprefs.apply(tmp_path, [dict(r) for r in rows])] == [True, False, True]


def test_a_name_like_the_title_shows_as_no_own_name(tmp_path):
    sessionprefs.set_name(tmp_path, A, "Ticket")
    sessionprefs.set_name(tmp_path, B, "Own")
    got = sessionprefs.apply(tmp_path, [{"id": A, "title": "Ticket"}, {"id": B, "title": "Other"}])
    assert [s["name"] for s in got] == [None, "Own"]


def test_the_ops_need_the_person_and_keep_the_choice(tmp_path):
    with pytest.raises(actions.NeedsPerson):
        actions.run_op(tmp_path, "/x/orch", "session.pin", {"session": A, "pinned": True}, session=False)
    with pytest.raises(actions.BadRequest):
        actions.run_op(tmp_path, "/x/orch", "session.pin", {"session": "nope", "pinned": True}, session=True)
    code, _, extra = actions.run_op(
        tmp_path, "/x/orch", "session.pin", {"session": A, "pinned": True}, session=True
    )
    assert code == 200 and extra["prefs"]["pins"] == {A: True}
    code, _, extra = actions.run_op(
        tmp_path, "/x/orch", "session.name", {"session": A, "name": "Mine"}, session=True
    )
    assert code == 200 and extra["prefs"]["names"] == {A: "Mine"}


def test_every_page_and_reload_reads_the_kept_pins_and_names(tmp_path, monkeypatch):
    """Two requests without anything in common (two browsers): both see what was kept."""
    monkeypatch.setattr(sessions, "run_orch", lambda *a, **k: None)
    sessions._TAILS.clear()
    (tmp_path / ".orch" / "tickets").mkdir(parents=True)
    run = {
        "running": True,
        "state": "alive",
        "claim": {"agent": "generic", "mode": "live"},
        "helper": {"state": "working"},
    }
    state = {
        "tickets": [{"id": A, "key": "ORCH-1", "title": "Ticket 1", "status": "active"}],
        "runs": {A: run},
    }
    srv = make_server(tmp_path, 0, orch_bin="orch")
    srv.state_cache.get = lambda: (state, 0.0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def one():
        with urllib.request.urlopen(base + "/api/sessions") as r:
            return json.loads(r.read())["sessions"][0]

    try:
        assert (one()["pinned"], one()["name"]) == (False, None)
        sessionprefs.set_pin(tmp_path, A, True)
        sessionprefs.set_name(tmp_path, A, "Price list")
        assert (one()["pinned"], one()["name"]) == (True, "Price list")
    finally:
        srv.shutdown()
