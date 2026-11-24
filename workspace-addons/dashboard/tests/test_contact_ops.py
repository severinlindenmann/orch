"""Contacts (ORCH-1203): Accept and Stop trusting from the dashboard. One fixed argv each, only checked ids, the
fingerprint the person was shown and their own name; a signed-in person's click only, with a one-time grant."""

import json

import pytest

from orch_dashboard import actions

FP = "D4WP 8N2K XQ7H 3RTA 9C5M B6YE 0GJS V1ZF"


@pytest.fixture
def ws(ws, tmp_path, monkeypatch):
    """The workspace where a guarded orch home pairs with it (the person grant is kept there)."""
    import shutil
    from pathlib import Path

    from orch import addons

    acct = tmp_path / "acct"
    (acct / ".orch-test" / "home").mkdir(parents=True)
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-test" / "home"))
    return Path(shutil.copytree(ws, acct / ".orch-test" / ws.name))


def test_accept_and_withdraw_build_one_fixed_argv():
    argv = actions.build_argv(
        "contact.accept", {"peer": "ws_abcdefghij", "fingerprint": FP, "name": " Home Mac "}
    )
    assert argv[:3] == ["relay", "contacts", "accept"]
    assert f"--fingerprint={FP}" in argv and "--name=Home Mac" in argv
    assert argv[-2:] == ["--", "ws_abcdefghij"]
    argv = actions.build_argv("contact.withdraw", {"peer": "ph_abcdefghij"})
    assert argv[:3] == ["relay", "contacts", "withdraw"] and argv[-2:] == ["--", "ph_abcdefghij"]


@pytest.mark.parametrize(
    "args",
    [
        {"peer": "--fingerprint", "fingerprint": FP},
        {"peer": "ws_abc", "fingerprint": FP},
        {"peer": "ws_abcdefghij", "fingerprint": "abcd " * 8},
        {"peer": "ws_abcdefghij"},
        {"peer": "ws_abcdefghij", "fingerprint": FP, "name": "x" * 61},
        {"peer": "ws_abcdefghij", "fingerprint": FP, "name": "a\u202eb"},
        {"peer": "ws_abcdefghij", "fingerprint": FP, "by": "agent:claude"},
    ],
)
def test_accept_refuses_anything_else(args):
    with pytest.raises(actions.BadRequest):
        actions.build_argv("contact.accept", args)


class _R:
    returncode, stdout, stderr = 0, json.dumps({"peer": "ws_abcdefghij", "state": "accepted"}), ""


@pytest.mark.parametrize("op", ["contact.accept", "contact.withdraw"])
def test_only_a_signed_in_person_and_with_a_one_time_grant(ws, monkeypatch, op):
    from orch import renew
    from orch.pagesession import SELF

    seen = {}
    monkeypatch.setattr(actions, "_run", lambda argv, **kw: seen.update(argv=argv, kw=kw) or _R())
    args = {"peer": "ws_abcdefghij", **({"fingerprint": FP} if op == "contact.accept" else {})}
    with pytest.raises(actions.NeedsPerson):  # watch-only: nothing runs
        actions.run_op(ws, SELF, op, args)
    assert seen == {}
    code, _, out = actions.run_op(ws, SELF, op, args, session=True)
    assert code == 200 and out["peer"] == "ws_abcdefghij"
    assert seen["kw"]["env"].get(renew.GRANT_ENV + "_FD") and seen["kw"]["pass_fds"]
    assert renew.GRANT_ENV not in seen["kw"]["env"]


def _view(block):
    return {"schema": "orch.addon-view/1", "generated_at": "2026-11-21T18:00:00Z", "blocks": [block]}


def test_view_check_keeps_a_good_contacts_block_and_drops_a_bad_one():
    from orch_dashboard import views

    row = {
        "id": "ws_abcdefghij",
        "name": "Home",
        "kind": "workspace",
        "state": "accepted",
        "fingerprint": FP,
        "held": 0,
    }
    good = {"type": "contacts", "own": {"name": "Me", "fingerprint": FP}, "items": [row]}
    assert views.check_view(_view(good))["blocks"] == [good]
    for bad in (
        {**row, "fingerprint": "<b>"},
        {**row, "state": "trusted"},
        {**row, "id": "ws_x"},
        {**row, "name": "<img>"},
        {**row, "extra": 1},
    ):
        v = views.check_view(_view({"type": "contacts", "items": [bad]}))
        assert v is None or v["blocks"] == []
