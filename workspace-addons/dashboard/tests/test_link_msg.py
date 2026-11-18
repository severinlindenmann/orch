"""ORCH-387: a page server started in a helper tool's terminal never opens a page session. Its refusal must
say so, not 'This link was already used' (which sent a tester after the wrong cause)."""

from types import SimpleNamespace

from orch.pagesession import WATCH_ONLY_MSG

from orch_dashboard import server


def test_a_watch_only_server_says_why_it_cannot_open_a_session():
    msg = server._link_msg(SimpleNamespace(active=False, revoked=False), "dashboard").decode()
    assert msg == WATCH_ONLY_MSG and "already used" not in msg


def test_a_live_server_still_says_the_link_was_used():
    assert b"already used" in server._link_msg(SimpleNamespace(active=True, revoked=False), "dashboard")
