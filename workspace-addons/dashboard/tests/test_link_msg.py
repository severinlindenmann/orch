from types import SimpleNamespace

import pytest

pytest.importorskip("orch")
from orch.pagesession import REVOKED_MSG, WATCH_ONLY_MSG

from orch_dashboard.server import _link_msg


def test_watch_only_page_says_why_not_already_used():
    body = _link_msg(SimpleNamespace(active=False, revoked=False), "dashboard").decode()
    assert body == WATCH_ONLY_MSG
    assert "already used" not in body


def test_spent_link_still_says_already_used():
    assert b"already used" in _link_msg(SimpleNamespace(active=True, revoked=False), "dashboard")


def test_revoked_session_keeps_its_message():
    assert _link_msg(SimpleNamespace(active=True, revoked=True), "dashboard").decode() == REVOKED_MSG


def test_agent_restart_of_remote_dashboard_warns(monkeypatch, tmp_path, capsys):
    from orch_dashboard import cli

    monkeypatch.setattr(cli, "_remote_on", lambda root: True)
    monkeypatch.setattr(cli, "_by_agent", lambda: True)
    monkeypatch.setattr(cli.service, "stop", lambda root: "stopped")
    (tmp_path / ".orch").mkdir()
    cli.main(["--dir", str(tmp_path), "stop", "--json"])
    assert "locked out" in capsys.readouterr().out
