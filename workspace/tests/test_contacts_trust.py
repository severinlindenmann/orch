# ruff: noqa: F811  (the fixtures of test_msgtrust are imported by name)
"""The Contacts page's fingerprints and states (ORCH-1203): the trust block of the relay view, the
person's own name at Accept, and Accept / Stop trusting from the dashboard's signed-in person grant
(never from a helper)."""

from __future__ import annotations

import pytest
from test_msgtrust import PEER, SEED_PEER, _pub, homes, person, signed_msg, ws  # noqa: F401  fixtures

from orch import msgsig, msgtrust, ownerpick, relay_view
from orch.errors import Refused

FP = msgsig.fingerprint(_pub(SEED_PEER))


def trust(root):
    import json

    import jsonschema
    from conftest import CONTRACTS

    v = relay_view.view(root)
    schema = json.loads((CONTRACTS / "addon-view.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(v)
    return next(b for b in v["blocks"] if b["type"] == "contacts")


def test_view_lists_every_contact_with_fingerprint_and_state(ws, run):
    b = trust(ws)
    rows = {r["id"]: r for r in b["items"]}
    assert rows[PEER] == {
        "id": PEER,
        "name": "Reports",
        "kind": "workspace",
        "state": "not_accepted",
        "fingerprint": FP,
        "held": 0,
    }
    assert len(FP.split(" ")) == 8 and all(len(g) == 4 for g in FP.split(" "))
    # this workspace's own fingerprint comes from its own key, never from the relay
    assert run("relay", "key")[0] == 0
    own = trust(ws)["own"]
    assert len(own["fingerprint"].split(" ")) == 8 and own["fingerprint"] != FP


def test_contacts_that_need_an_accept_come_first(ws, run, rel, person):
    msgtrust.accept(ws, "ws_contoso001", "human:tester", "cli")
    # A first contact is trusted now; a taken-back one waits.
    msgtrust.withdraw(ws, PEER, "human:tester", "cli")
    rel.inbox.append(signed_msg(SEED_PEER, body={"text": "Hello"}))
    run("relay", "inbox", "--json")
    rows = trust(ws)["items"]
    assert [r["state"] for r in rows] == ["withdrawn", "accepted"]
    assert rows[0]["held"] == 1 and rows[1]["accepted_at"]


def test_accept_keeps_the_persons_own_name_and_shows_the_relays(ws, person):
    msgtrust.accept(ws, PEER, "human:tester", "dashboard", FP, name="  Reports   team ")
    r = next(r for r in trust(ws)["items"] if r["id"] == PEER)
    assert r["state"] == "accepted" and r["name"] == "Reports team" and r["relay_name"] == "Reports"
    msgtrust.accept(ws, PEER, "human:tester", "dashboard", FP, name="")  # empty: the relay's name again
    r = next(r for r in trust(ws)["items"] if r["id"] == PEER)
    assert r["name"] == "Reports" and "relay_name" not in r


@pytest.mark.parametrize("bad", ["x" * 61, "Re‮ports", "two\nlines"])
def test_accept_refuses_a_name_that_is_not_one_plain_line(ws, person, bad):
    with pytest.raises(Refused):
        msgtrust.accept(ws, PEER, "human:tester", "cli", FP, name=bad)
    assert next(r for r in trust(ws)["items"] if r["id"] == PEER)["state"] == "not_accepted"


def test_new_key_shows_the_old_fingerprint(ws, rel, person):
    msgtrust.accept(ws, PEER, "human:tester", "cli", FP)
    from test_msgtrust import _dir_entry

    rel.snapshot["workspaces"]["workspaces"][0] = _dir_entry(PEER, bytes.fromhex("44" * 32), "Reports")
    from orch import relay

    relay.refresh(ws)
    r = next(r for r in trust(ws)["items"] if r["id"] == PEER)
    assert r["state"] == "new_key" and r["old_fingerprint"] == FP and r["fingerprint"] != FP


def test_dashboard_grant_lets_a_person_accept_without_a_terminal(ws, run, monkeypatch):
    """The dashboard hands the call a one-time grant from the signed-in page session: that is the proof."""
    monkeypatch.setattr(ownerpick, "person_granted", lambda root, by: not str(by).startswith("agent:"))
    code, txt, err = run(
        "relay",
        "contacts",
        "accept",
        "--fingerprint",
        FP,
        "--name",
        "Reports team",
        "--by",
        "human:ann",
        "--",
        PEER,
    )
    assert code == 0, err
    st = msgtrust._load(ws)["contacts"][PEER]
    assert (
        st["keys"][0]["via"] == "dashboard"
        and st["keys"][0]["by"] == "human:ann"
        and st["name"] == "Reports team"
    )
    assert run("relay", "contacts", "withdraw", "--by", "human:ann", "--", PEER)[0] == 0
    assert next(r for r in trust(ws)["items"] if r["id"] == PEER)["state"] == "withdrawn"


def test_without_the_grant_or_as_a_helper_nothing_is_accepted(ws, run, monkeypatch):
    monkeypatch.setattr(ownerpick, "person_granted", lambda root, by: False)
    code, _, err = run("relay", "contacts", "accept", "--fingerprint", FP, "--", PEER)  # pytest: no terminal
    assert code == 2 and "Only a person" in err
    monkeypatch.setattr(msgtrust, "_is_tty", lambda: True)
    code, _, err = run("relay", "contacts", "accept", "--fingerprint", FP, "--by", "agent:claude", "--", PEER)
    assert code == 2 and "Only a person" in err
    assert next(r for r in trust(ws)["items"] if r["id"] == PEER)["state"] == "not_accepted"


def test_relay_view_text_lists_contacts_too(ws, run):
    code, out, err = run("relay", "view")
    assert code == 0, err
    assert f"Reports  {FP}  Not accepted yet" in out


def test_a_swapped_key_shows_the_old_fingerprint_in_every_state(ws, rel, person):
    """Review: Withdrawn and Not valid come before New key; a key swap must still show (old fingerprint)."""
    from test_msgtrust import _dir_entry

    from orch import relay

    msgtrust.accept(ws, PEER, "human:tester", "cli", FP)
    msgtrust.withdraw(ws, PEER, "human:tester", "cli")
    rel.snapshot["workspaces"]["workspaces"][0] = _dir_entry(PEER, bytes.fromhex("44" * 32), "Reports")
    relay.refresh(ws)
    r = next(r for r in trust(ws)["items"] if r["id"] == PEER)
    assert r["state"] == "withdrawn" and r["old_fingerprint"] == FP and r["fingerprint"] != FP


def test_a_terminal_inside_a_helper_run_is_no_proof(ws, run, monkeypatch):
    monkeypatch.setattr(ownerpick, "person_granted", lambda root, by: False)
    monkeypatch.setattr(msgtrust, "_is_tty", lambda: True)
    from orch import tickets

    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    monkeypatch.setenv("ORCH_RUN", "r_123")
    code, _, err = run("relay", "contacts", "accept", "--fingerprint", FP, "--by", "human:x", "--", PEER)
    assert code == 2 and "Only a person" in err
    assert next(r for r in trust(ws)["items"] if r["id"] == PEER)["state"] == "not_accepted"


def test_a_terminal_in_a_helper_session_is_no_proof(ws, run, monkeypatch):
    """A helper's tool session (Claude Code, Codex ...) never counts as a person, even with a terminal."""
    monkeypatch.setattr(ownerpick, "person_granted", lambda root, by: False)
    monkeypatch.setattr(msgtrust, "_is_tty", lambda: True)
    from orch import tickets

    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude-code")
    for args in (("accept", "--fingerprint", FP, "--by", "human:x", "--", PEER), ("withdraw", PEER)):
        code, _, err = run("relay", "contacts", *args)
        assert code == 2 and "Only a person" in err
    assert next(r for r in trust(ws)["items"] if r["id"] == PEER)["state"] == "not_accepted"


def test_the_person_check_asks_the_one_terminal_check(monkeypatch):
    """No own isatty(): the central check (term.is_terminal) decides; the Windows NUL device is no person."""
    import os
    import sys

    from orch import term

    with open(os.devnull) as f:
        monkeypatch.setattr(sys, "stdin", f)
        assert msgtrust._is_tty() is False
    monkeypatch.setattr(sys, "stdin", None)
    assert msgtrust._is_tty() is False
    monkeypatch.setattr(term, "is_terminal", lambda s: True)
    assert msgtrust._is_tty() is True


def test_a_broken_key_file_hides_only_the_own_fingerprint(ws, run, monkeypatch):
    from orch import signkey

    def broken(root):
        raise ValueError("bad key file")

    monkeypatch.setattr(signkey, "public_key", broken)
    b = trust(ws)
    assert "own" not in b and any(r["id"] == PEER for r in b["items"])
    monkeypatch.setattr(msgtrust, "contacts", lambda root: [{"id": PEER}] + 1)  # a TypeError inside
    v = relay_view.view(ws)
    assert not any(x["type"] == "contacts" for x in v["blocks"]) and any(
        x["type"] == "list" for x in v["blocks"]
    )


def test_a_contact_the_relay_no_longer_lists_gets_a_plain_name(ws, rel, person):
    from orch import relay

    msgtrust.accept(ws, PEER, "human:tester", "cli", FP)
    rel.snapshot["workspaces"]["workspaces"] = rel.snapshot["workspaces"]["workspaces"][1:]
    relay.refresh(ws)
    r = next(r for r in trust(ws)["items"] if r["id"] == PEER)
    assert r["name"] == "Unlisted workspace" and "relay_name" not in r and r["fingerprint"] == FP
