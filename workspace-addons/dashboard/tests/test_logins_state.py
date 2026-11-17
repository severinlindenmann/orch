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
