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
    rel.inbox.append(signed_msg(SEED_PEER, body={"text": "Hello"}))
    run("relay", "inbox", "--json")
    rows = trust(ws)["items"]
    assert [r["state"] for r in rows] == ["not_accepted", "accepted"]
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
