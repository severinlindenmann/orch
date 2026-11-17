"""GET /api/t/<id>/sessions: earlier chat sessions of a ticket, read-only, through `orch run history`."""

from .conftest import TID, calls
from .test_server import req


def test_sessions_route_asks_orch_run_history(server, fake_orch):
    st, _, _ = req(server, "GET", f"/api/t/{TID}/sessions")
    assert st == 200
    assert ["run", "history", TID, "--json"] in calls(fake_orch)


def test_one_session_passes_its_id_after_a_flag(server, fake_orch):
    st, _, _ = req(server, "GET", f"/api/t/{TID}/sessions?session=abc-123")
    assert st == 200
    assert ["run", "history", TID, "--json", "--session", "abc-123"] in calls(fake_orch)


def test_bad_ticket_id_is_not_a_route(server):
    st, _, _ = req(server, "GET", "/api/t/x;rm/sessions")
    assert st == 404


def test_continue_builds_one_fixed_argv():
    from orch_focus import actions

    argv = actions.build_argv("session.continue", {"ticket": TID, "session": "abc-1"})
    assert argv[:6] == ["run", "history", TID, "--session", "abc-1", "--continue"]
    import pytest

    for bad in ("../x", "a b", "", None):
        with pytest.raises(actions.BadRequest):
            actions.build_argv("session.continue", {"ticket": TID, "session": bad})
