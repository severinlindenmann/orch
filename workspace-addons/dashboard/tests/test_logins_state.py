"""What helpers need (ORCH-45): the live page gets the last check of every tool login, connection and key, never a
secret, and Check again runs `orch logins --json`."""

from __future__ import annotations

from pathlib import Path

import pytest
from orch import health  # imported first, so the isolation fixture fakes its real home

from orch_dashboard.actions import BadRequest, build_argv
from orch_dashboard.data import load_logins, load_state


@pytest.fixture
def ws(ws, tmp_path, monkeypatch):
    """The shared workspace, moved where a guarded orch home pairs with it: the check is kept there
    (ORCH-46 security review), never in .orch/run."""
    import shutil

    from orch import addons

    acct = tmp_path / "acct"
    (acct / ".orch-test" / "home").mkdir(parents=True)
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-test" / "home"))
    return Path(shutil.copytree(ws, acct / ".orch-test" / ws.name))


ROW = {
    "name": "claude",
    "label": "Claude Code",
    "kind": "login",
    "state": "soon",
    "ends_at": "2026-11-17T21:24:57Z",
    "helper": "claude",
    "chosen": True,
    "stops": [{"id": "t_abc123", "key": "ORCH-12", "title": "Fix login page", "extra": "dropped"}],
}


def test_never_checked_shows_nothing(ws):
    assert load_logins(ws) is None


def test_the_last_check_reaches_the_page_with_only_its_few_facts(ws):
    secret = "sk-ant-oat01-NEVER"
    health.save(
        ws,
        [
            {**ROW, "token": secret},
            {**ROW, "name": "x", "state": "bogus"},
            {**ROW, "name": "old", "kind": None},
        ],
    )
    doc = load_logins(ws)
    assert [r["name"] for r in doc["items"]] == ["claude", "old"]  # an unknown state is left out
    first = doc["items"][0]
    assert set(first) == {"name", "label", "kind", "state", "ends_at", "helper", "chosen", "stops"}
    assert first["stops"] == [{"id": "t_abc123", "key": "ORCH-12", "title": "Fix login page"}]
    assert doc["items"][1]["kind"] == "login"  # an older result without a kind: a login
    assert secret not in str(doc) and doc["checked_at"]


def test_the_live_page_carries_it_and_a_snapshot_does_not(ws, act_orch):
    health.save(ws, [ROW])
    assert load_state(ws, orch_bin=str(act_orch), with_settings=True)["logins"]["items"][0]["state"] == "soon"
    assert load_state(ws, orch_bin=str(act_orch), with_addons=False)["logins"] is None


def test_check_again_runs_orch_logins_and_takes_nothing_else():
    assert build_argv("logins.check", {}) == ["logins", "--json"]
    with pytest.raises(BadRequest):
        build_argv("logins.check", {"command": "rm"})


def test_the_renew_step_fields_pass_only_when_they_are_plain(ws):
    health.save(
        ws,
        [
            {**ROW, "renew": True, "key": "PAYMENTS_KEY"},
            {**ROW, "name": "b", "renew": "yes", "key": "$(rm -rf x)"},
        ],
    )
    first, second = load_logins(ws)["items"]
    assert first["renew"] is True and first["key"] == "PAYMENTS_KEY"
    assert "renew" not in second and "key" not in second


def test_a_check_a_helper_wrote_into_the_project_is_never_shown(ws):
    """ORCH-46 security review: a helper can write .orch/run; a false 'needs renewing' with its own text there
    never reaches Home or Settings (the page reads only the guarded orch home)."""
    import json

    forged = {
        "schema": "orch.health/1",
        "checked_at": "2026-11-17T08:00:00Z",
        "items": [
            {"name": "bank", "label": "Your bank login", "kind": "login", "state": "renew", "key": "X"}
        ],
    }
    (ws / ".orch" / "run").mkdir(parents=True, exist_ok=True)
    (ws / ".orch" / "run" / "health.json").write_text(json.dumps(forged), encoding="utf-8")
    assert load_logins(ws) is None
    health.save(ws, [ROW])
    assert [r["name"] for r in load_logins(ws)["items"]] == ["claude"]
    assert not (ws / ".orch" / "run" / "health.json").exists()  # the old place is cleared on the next check


def test_the_sign_in_command_passes_only_when_it_is_plain(ws):
    """ORCH-218: the terminal command a tool signs in with reaches the page; anything else is dropped."""
    health.save(
        ws,
        [
            {**ROW, "sign_in": "az login"},
            {**ROW, "name": "b", "sign_in": "az login; curl x | sh"},
            {**ROW, "name": "c", "sign_in": "<b>x</b>"},
        ],
    )
    first, second, third = load_logins(ws)["items"]
    assert first["sign_in"] == "az login"
    assert "sign_in" not in second and "sign_in" not in third


# ORCH-1693: the phone link is connected by pasting its one line into Settings, never in a terminal.
def test_the_pasted_phone_link_line_runs_relay_connect_and_nothing_else():
    token = "orn_" + "Ab-_9" * 9
    want = ["relay", "connect", "https://relay.example.org", "--workspace", "ws_abcde12345", "--token", token]
    for line in (
        f"orch relay connect https://relay.example.org --workspace ws_abcde12345 --token {token}",
        f"  `orch relay connect https://relay.example.org --workspace ws_abcde12345 --token {token}`\n",
        f"https://relay.example.org --workspace ws_abcde12345 --token {token}",
    ):
        assert build_argv("relay.connect", {"line": line}, None)[:7] == want
    for bad in (
        f"orch relay connect https://relay.example.org --workspace ws_abcde12345 --token {token}; rm -rf ~",
        f"orch publish connect https://relay.example.org --workspace ws_abcde12345 --token {token}",
        "orch relay connect https://relay.example.org --workspace ws_abcde12345 --token secret",
        "",
        None,
    ):
        with pytest.raises(BadRequest, match="Copy it again"):
            build_argv("relay.connect", {"line": bad}, None)
    with pytest.raises(BadRequest):
        build_argv("relay.connect", {"line": "x", "command": "rm"}, None)
