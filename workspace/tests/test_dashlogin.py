"""ORCH-1035: dashboard login tokens (made on the command line, 30 days) and the browser sessions made
from them. Only hashes are on disk; a revoked or expired token ends its sessions; agents cannot make one."""

import json
import sys
import time

import pytest

from orch import addons, dashlogin, pagelaunch
from orch import home as home_mod
from orch.errors import Refused


@pytest.fixture
def tws(tmp_path, monkeypatch):
    acct = tmp_path / "acct"
    ws = acct / ".orch-test" / "ws"
    (ws / ".orch").mkdir(parents=True)
    (acct / ".orch-test" / "home").mkdir()
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-test" / "home"))
    monkeypatch.setattr(home_mod, "install_kind", lambda: "test")
    for k in ("ORCH_AGENT", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        monkeypatch.delenv(k, raising=False)
    from orch import tickets

    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    return ws


def _files(ws):
    d = home_mod.key_dir(ws)
    return d / "dashboard-tokens.json", d / "dashboard-sessions.json"


def test_new_token_is_shown_once_and_only_its_hash_is_kept(tws):
    token, entry = dashlogin.new_token(tws, "Anna's laptop")
    assert token.startswith(f"odt_{entry['id']}_") and len(token) == 4 + 8 + 1 + 43
    assert entry["state"] == "active" and entry["label"] == "Annas laptop"
    assert entry["expires"] - entry["created"] == 30 * 86400
    tokens_file, _ = _files(tws)
    raw = tokens_file.read_text()
    assert token not in raw and token.split("_", 2)[2] not in raw
    if sys.platform != "win32":
        assert tokens_file.stat().st_mode & 0o777 == 0o600
    assert [t["id"] for t in dashlogin.list_tokens(tws)] == [entry["id"]]
    assert "sha256" not in dashlogin.list_tokens(tws)[0]


def test_login_makes_a_browser_session_with_only_hashes_on_disk(tws):
    token, _ = dashlogin.new_token(tws)
    s = dashlogin.login(tws, token)
    assert s and s["cookie"].startswith(s["sid"] + ".")
    _, sessions_file = _files(tws)
    raw = sessions_file.read_text()
    assert s["cookie"] not in raw and s["page"] not in raw and token not in raw
    got = dashlogin.session(tws, s["cookie"], s["page"])
    assert got and got["sid"] == s["sid"] and got["person"] is None
    # the cookie alone reads, but never acts; a wrong page key or cookie is no session
    assert dashlogin.session(tws, s["cookie"], need_page=False)
    assert dashlogin.session(tws, s["cookie"]) is None
    assert dashlogin.session(tws, s["cookie"], s["page"] + "x") is None
    assert dashlogin.session(tws, s["cookie"] + "x", s["page"]) is None
    # two browsers: two sessions
    s2 = dashlogin.login(tws, token)
    assert s2["sid"] != s["sid"] and dashlogin.session(tws, s2["cookie"], s2["page"])


@pytest.mark.parametrize("bad", ["", "odt_", "odt_abcdefgh_" + "A" * 43, "x" * 300, None, 5])
def test_a_wrong_token_logs_nobody_in(tws, bad):
    dashlogin.new_token(tws)
    assert dashlogin.login(tws, bad) is None


def test_revoke_ends_every_session_of_that_token_only(tws):
    t1, e1 = dashlogin.new_token(tws)
    t2, _ = dashlogin.new_token(tws)
    a, b = dashlogin.login(tws, t1), dashlogin.login(tws, t2)
    assert dashlogin.revoke_token(tws, e1["id"])
    assert dashlogin.session(tws, a["cookie"], a["page"]) is None
    assert dashlogin.session(tws, b["cookie"], b["page"])
    assert dashlogin.login(tws, t1) is None
    assert {t["id"]: t["state"] for t in dashlogin.list_tokens(tws)}[e1["id"]] == "revoked"
    assert not dashlogin.revoke_token(tws, "nothere1")
    assert not dashlogin.revoke_token(tws, "../x")


def test_an_expired_token_is_no_session(tws, monkeypatch):
    token, _ = dashlogin.new_token(tws)
    s = dashlogin.login(tws, token)
    later = time.time() + 31 * 86400
    monkeypatch.setattr(dashlogin.time, "time", lambda: later)
    assert dashlogin.session(tws, s["cookie"], s["page"]) is None
    assert dashlogin.login(tws, token) is None
    assert dashlogin.list_tokens(tws)[0]["state"] == "expired"


def test_a_session_never_outlives_its_token(tws):
    token, entry = dashlogin.new_token(tws)
    assert dashlogin.login(tws, token)["expires"] == entry["expires"]


def test_person_and_logout(tws):
    token, _ = dashlogin.new_token(tws)
    s = dashlogin.login(tws, token)
    assert dashlogin.set_person(tws, s["sid"], "Anna")
    assert dashlogin.session(tws, s["cookie"], s["page"])["person"] == "Anna"
    assert dashlogin.logout(tws, s["sid"])
    assert dashlogin.session(tws, s["cookie"], s["page"]) is None
    assert not dashlogin.set_person(tws, s["sid"], "Anna")


def test_a_broken_sessions_file_logs_nobody_in(tws):
    token, _ = dashlogin.new_token(tws)
    s = dashlogin.login(tws, token)
    _, sessions_file = _files(tws)
    sessions_file.write_text("{not json")
    assert dashlogin.session(tws, s["cookie"], s["page"]) is None


def test_sessions_are_pruned(tws):
    token, _ = dashlogin.new_token(tws)
    for _ in range(dashlogin.MAX_SESSIONS + 5):
        dashlogin.login(tws, token)
    _, sessions_file = _files(tws)
    assert len(json.loads(sessions_file.read_text())["sessions"]) == dashlogin.MAX_SESSIONS


def test_an_agent_cannot_make_a_token(tws, monkeypatch):
    from orch import tickets

    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    monkeypatch.setattr(pagelaunch, "is_test_workspace", lambda root: False)
    with pytest.raises(Refused):
        dashlogin.new_token(tws)
    # listing and revoking stay open (no secret in a list; revoking only takes access away)
    assert dashlogin.list_tokens(tws) == []


def test_cookie_name_is_per_workspace_not_per_port(tws):
    name = dashlogin.cookie_name(tws)
    home_mod.key_dir(tws)
    name = dashlogin.cookie_name(tws)
    assert name.startswith("orch_dash_") and name.replace("_", "").isalnum()


def test_the_secret_scan_finds_a_login_token(tws):
    from orch import secretscan

    token, _ = dashlogin.new_token(tws)
    assert secretscan.find(f"here is the token {token} for you", strict=False)
