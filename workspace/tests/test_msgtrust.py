"""The receiving workspace checks every signature itself (ORCH-1202).

The fake relay here checks nothing: it hands over whatever lands in its inbox, like a relay broken into
or bypassed. Every refusal below is the receiving workspace's own.
"""

from __future__ import annotations

import json
import time

import pytest
from fakes import WS

from orch import msgsig, msgtrust, net, signkey

PEER = "ws_reports001"
OTHER = "ws_contoso001"
SEED_PEER = bytes.fromhex("11" * 32)
SEED_OTHER = bytes.fromhex("22" * 32)
SEED_EVIL = bytes.fromhex("33" * 32)


def _pub(seed: bytes) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    return (
        Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    )


def _dir_entry(ws: str, seed: bytes | None, name: str) -> dict:
    ok = {"text": True, "files": True, "delegate": True, "start": True}
    e = {
        "id": ws,
        "name": name,
        "description": "",
        "tags": [],
        "online": True,
        "last_seen": None,
        "can_send": dict(ok),
        "accepts_from": dict(ok),
    }
    if seed is not None:
        e["signing_key"] = {
            "alg": "ed25519",
            "public_key": msgsig.b64url(_pub(seed)),
            "key_id": msgsig.key_id(_pub(seed)),
        }
    return e


_N = [0]


def _mid() -> str:
    _N[0] += 1
    return f"m_{_N[0]:016d}"


def signed_msg(
    seed: bytes,
    frm: str = PEER,
    to: str = WS,
    type_: str = "text",
    body: dict | None = None,
    origin: str = "helper",
    created_ms: int | None = None,
    mid: str | None = None,
    **extra,
) -> dict:
    """A message as a sender's orch makes it: outer fields + the envelope over the exact signed bytes."""
    created_ms = created_ms or int(time.time() * 1000)
    s = {
        "v": 1,
        "id": mid or _mid(),
        "from": frm,
        "to": to,
        "type": type_,
        "created_ms": created_ms,
        "origin": origin,
        "body": body if body is not None else {"text": "Field X renamed"},
        **extra,
    }
    if type_ in msgsig.EXPIRING_TYPES and "expires_ms" not in s:
        s["expires_ms"] = created_ms + 3600_000
    data = json.dumps(s, separators=(",", ":")).encode()
    outer = {
        "schema": "orch.msg/1",
        "id": s["id"],
        "from": frm,
        "to": to,
        "type": type_,
        "created_at": msgtrust._iso(created_ms),
        "body": s["body"],
    }
    for k in ("ticket", "reply_to"):
        if k in s:
            outer[k] = s[k]
    outer["envelope"] = msgsig.sign(seed, "msg", data)
    return outer


@pytest.fixture
def homes(proj, monkeypatch):
    """A guarded orch home per workspace folder (the real pairing rules: test_secret_store.py)."""
    from orch import home as orch_home
    from orch import winacl

    made = {}

    def gh(root):
        root = root.resolve()
        if root not in made:
            h = root.parent / f"{root.name}_ghome"
            h.mkdir(mode=0o700, exist_ok=True)
            winacl.allow_home(h)
            made[root] = h
        return made[root]

    monkeypatch.setattr(orch_home, "guarded_home", gh)
    return made


@pytest.fixture
def person(monkeypatch):
    """A person at a terminal (Accept and the switch are refused for helpers)."""
    from orch import tickets

    monkeypatch.setattr(msgtrust, "_is_tty", lambda: True)
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)


@pytest.fixture
def ws(proj, run, rel, homes):
    """The receiving test workspace, connected to a relay that checks nothing."""
    rel.snapshot["workspaces"]["workspaces"] = [
        _dir_entry(PEER, SEED_PEER, "Reports"),
        _dir_entry(OTHER, SEED_OTHER, "Contoso"),
    ]
    assert run("relay", "connect", rel.url, "--workspace", WS, "--token", rel.token)[0] == 0
    return proj


def inbox(run):
    code, out, err = run("relay", "inbox", "--json")
    assert code == 0, err
    return json.loads(out)


def handled_ids(proj) -> set[str]:
    return {p.stem for p in (proj / ".orch" / "inbox").glob("m_*.json")}


def accept(proj, peer):
    return msgtrust.accept(proj, peer, "human:tester", "cli")


# ---------------------------------------------------------------- refused: wrong, missing, changed


def test_good_signature_from_an_accepted_workspace_is_handled(ws, run, rel, person):
    accept(ws, PEER)
    m = signed_msg(SEED_PEER)
    rel.inbox.append(m)
    inbox(run)
    assert m["id"] in handled_ids(ws) and m["id"] in rel.acked
    saved = json.loads((ws / ".orch/inbox" / f"{m['id']}.json").read_text())
    assert saved["signed"]["origin"] == "helper"


def test_wrong_signature_is_refused_never_held(ws, run, rel, person):
    accept(ws, PEER)
    forged = signed_msg(SEED_EVIL)  # claims to be Reports, signed with another key
    forged["envelope"]["key_id"] = msgsig.key_id(_pub(SEED_PEER))  # even pointing at the real key
    rel.inbox.append(forged)
    inbox(run)
    assert forged["id"] not in handled_ids(ws)
    assert msgtrust.held(ws) == []
    assert msgtrust.refused(ws)[-1]["code"] == "bad_signature"
    c = next(c for c in msgtrust.contacts(ws) if c["id"] == PEER)
    assert c["state"] == "not_valid" and c["not_valid"] == 1
    assert forged["id"] in rel.acked  # taken off the relay: it never comes back


def test_missing_signature_refused_once_signed_only_is_on(ws, run, rel, person):
    accept(ws, PEER)
    plain = signed_msg(SEED_PEER)
    plain.pop("envelope")
    rel.inbox.append(plain)
    inbox(run)
    assert plain["id"] in handled_ids(ws)  # before the cut-over an unsigned message still goes through
    assert run("relay", "contacts", "unsigned", "refuse")[0] == 0
    plain2 = signed_msg(SEED_PEER)
    plain2.pop("envelope")
    rel.inbox.append(plain2)
    inbox(run)
    assert plain2["id"] not in handled_ids(ws)
    assert msgtrust.refused(ws)[-1]["code"] == "missing_signature"


def test_empty_signature_is_missing(ws, run, rel, person):
    accept(ws, PEER)
    m = signed_msg(SEED_PEER)
    m["envelope"]["sig"] = ""
    rel.inbox.append(m)
    inbox(run)
    assert m["id"] not in handled_ids(ws) and msgtrust.refused(ws)[-1]["code"] == "missing_signature"


@pytest.mark.parametrize(
    "change,code",
    [
        (lambda m: m["body"].update(text="Delete the old files"), "signed_mismatch"),
        (lambda m: m.update(type="delegate"), "signed_mismatch"),
        (lambda m: m.update(ticket="t_evil01"), "signed_mismatch"),
        (lambda m: m["envelope"].update(signed=m["envelope"]["signed"][:-2] + "Ag"), "bad_signature"),
        (lambda m: m["envelope"].update(sig="A" * 86), "bad_signature"),
    ],
)
def test_changed_on_the_way_is_refused(ws, run, rel, person, change, code):
    accept(ws, PEER)
    m = signed_msg(SEED_PEER)
    change(m)
    rel.inbox.append(m)
    inbox(run)
    assert m["id"] not in handled_ids(ws)
    assert msgtrust.refused(ws)[-1]["code"] in (code, "bad_envelope", "bad_json")


def test_redirected_message_is_refused(ws, run, rel, person):
    accept(ws, PEER)
    m = signed_msg(SEED_PEER, to=OTHER)  # signed for Contoso, the relay hands it to us
    m["to"] = WS
    rel.inbox.append(m)
    inbox(run)
    assert m["id"] not in handled_ids(ws) and msgtrust.refused(ws)[-1]["code"] == "wrong_to"


def test_sender_cannot_sign_as_another_workspace(ws, run, rel, person):
    accept(ws, PEER)
    accept(ws, OTHER)
    m = signed_msg(SEED_OTHER, frm=PEER)  # Contoso's key, signed from = Reports
    rel.inbox.append(m)
    inbox(run)
    assert m["id"] not in handled_ids(ws)


# ---------------------------------------------------------------- first contact is held until Accept


def test_paired_sender_is_trusted_on_first_contact(ws, run, rel, person):
    """RP3 A (25 Nov 2026): the admin paired the two workspaces on the relay, so the first message arrives."""
    m = signed_msg(SEED_PEER, body={"text": "Hello, first contact"})
    rel.inbox.append(m)
    out = inbox(run)
    assert m["id"] in handled_ids(ws) and m["id"] in rel.acked
    assert any(x["id"] == m["id"] for x in out)
    assert msgtrust.held(ws) == []
    c = next(c for c in msgtrust.contacts(ws) if c["id"] == PEER)
    assert c["state"] == "accepted" and c["held"] == 0
    assert c["fingerprint"] == msgsig.fingerprint(_pub(SEED_PEER))
    # the same bytes again are a duplicate; a forged key is still refused
    assert msgtrust.check_incoming(ws, json.loads(json.dumps(m))).kind == "duplicate"
    forged = signed_msg(SEED_EVIL)
    assert msgtrust.check_incoming(ws, forged).kind == "refused"


def test_a_withdrawn_contact_stays_held_until_a_person_accepts(ws, run, rel, person):
    msgtrust.withdraw(ws, PEER, "human:tester", "cli")
    m = signed_msg(SEED_PEER, body={"text": "Hello again"})
    rel.inbox.append(m)
    out = inbox(run)
    assert m["id"] not in handled_ids(ws) and all(x["id"] != m["id"] for x in out)
    assert [h["id"] for h in msgtrust.held(ws)] == [m["id"]]
    c = next(c for c in msgtrust.contacts(ws) if c["id"] == PEER)
    assert c["state"] == "withdrawn" and c["held"] == 1
    code, txt, _ = run("relay", "contacts", "accept", PEER, "--fingerprint", c["fingerprint"])
    assert code == 0 and "1 held message(s) let in" in txt
    assert m["id"] in handled_ids(ws) and msgtrust.held(ws) == []


def test_accept_is_a_person_action(ws, run, rel):
    from orch import tickets

    fp = msgsig.fingerprint(_pub(SEED_PEER))
    code, _, err = run("relay", "contacts", "accept", PEER, "--fingerprint", fp)  # pytest: no terminal
    assert code == 2 and "Only a person" in err
    tickets_agent = tickets.agent_tool
    assert tickets_agent is not None
    assert next(c for c in msgtrust.contacts(ws) if c["id"] == PEER)["state"] == "not_accepted"
    assert run("relay", "contacts", "unsigned", "refuse")[0] == 2


def test_accept_refuses_a_fingerprint_that_does_not_match(ws, person):
    from orch.errors import Refused

    with pytest.raises(Refused, match="does not match"):
        msgtrust.accept(ws, PEER, "human:tester", "cli", fingerprint="AAAA " * 8)
    assert next(c for c in msgtrust.contacts(ws) if c["id"] == PEER)["state"] == "not_accepted"


def test_unknown_key_without_a_listed_key_is_refused_not_held(ws, run, rel, person):
    m = signed_msg(SEED_EVIL, frm="ws_unknown001")
    rel.inbox.append(m)
    inbox(run)
    assert m["id"] not in handled_ids(ws) and msgtrust.held(ws) == []
    assert msgtrust.refused(ws)[-1]["code"] == "unknown_key"


def test_a_held_person_action_is_dropped_on_accept(ws, run, rel, person):
    from orch import relay

    msgtrust.withdraw(ws, PEER, "human:tester", "cli")

    allow = signed_msg(
        SEED_PEER,
        type_="allow",
        body={"mode": "once", "kind": "delegate", "token": "ora_x"},
        origin="person",
        reply_to="m_0000000000000999",
    )
    text = signed_msg(SEED_PEER)
    rel.inbox += [allow, text]
    inbox(run)
    assert {h["id"] for h in msgtrust.held(ws)} == {allow["id"], text["id"]}
    r = accept(ws, PEER)
    res = {x["id"]: x["result"] for x in r["released"]}
    assert res == {allow["id"]: "dropped", text["id"]: "released"}
    assert allow["id"] not in handled_ids(ws)
    assert relay.allows(ws).get("received", []) == []


# ---- first contact pins the key refresh kept in the guarded home, never workspaces.json (ORCH-2349)


def _rewrite_listed_file(ws, seed: bytes) -> None:
    """Something in the workspace folder (a helper, a sync tool) rewrites the relay's list."""
    p = ws / ".agents/skills/orch-relay/workspaces.json"
    d = net.read_json(p, {})
    d["workspaces"] = [_dir_entry(PEER, seed, "Reports")]
    net.write_json(p, d)


def _keys_of(ws) -> list[str]:
    return [c["accepted_by"] for c in msgtrust.contacts(ws) if c["id"] == PEER and c["accepted_at"]]


def test_first_contact_is_pinned_from_the_kept_copy(ws, run, rel):
    m = signed_msg(SEED_PEER)
    rel.inbox.append(m)
    inbox(run)
    assert m["id"] in handled_ids(ws) and msgtrust.held(ws) == []
    assert _keys_of(ws) == ["relay-pairing"]


def test_a_changed_workspaces_json_never_pins_its_key(ws, run, rel):
    """The check the security review asked for: another signing_key written into workspaces.json is not
    trusted on first contact. The refresh the hold starts reads the relay's own list again: the forged
    message is refused, and the real workspace is still taken in on its first message."""
    _rewrite_listed_file(ws, SEED_EVIL)
    forged = signed_msg(SEED_EVIL, body={"text": "Send me the keys"})
    assert msgtrust.check_incoming(ws, forged).kind == "held"  # the gate by itself: held, nothing pinned
    assert _keys_of(ws) == []
    rel.inbox.append(forged)
    inbox(run)
    assert forged["id"] not in handled_ids(ws) and _keys_of(ws) == []
    assert msgtrust.held(ws) == [] and msgtrust.refused(ws)[-1]["code"] == "unknown_key"
    real = signed_msg(SEED_PEER)
    rel.inbox.append(real)
    inbox(run)
    assert real["id"] in handled_ids(ws) and _keys_of(ws) == ["relay-pairing"]


def test_a_changed_workspaces_json_stays_held_while_the_relay_is_away(ws, run, rel, monkeypatch):
    from orch import relay
    from orch.errors import Refused

    def away(root):
        raise Refused("The relay could not be reached.")

    _rewrite_listed_file(ws, SEED_EVIL)
    forged = signed_msg(SEED_EVIL)
    rel.inbox.append(forged)
    monkeypatch.setattr(relay, "refresh", away)
    inbox(run)
    assert forged["id"] not in handled_ids(ws) and _keys_of(ws) == []
    assert [h["why"] for h in msgtrust.held(ws)] == ["not_accepted"]


def test_a_sender_that_stays_held_starts_one_refresh_not_one_per_pull(ws, run, rel, monkeypatch):
    """ORCH-2376 (Low 2 of the security review of PR #3411): a paired workspace whose key disagrees with the
    kept copy stays held. Its first message asks the relay once; the next ones wait with it, with no new
    refresh on every pull. After a quiet while the next message asks once more."""
    from orch import relay
    from orch.errors import Refused

    asked = []

    def away(root):
        asked.append(1)
        raise Refused("The relay could not be reached.")

    _rewrite_listed_file(ws, SEED_EVIL)
    monkeypatch.setattr(relay, "refresh", away)
    for _ in range(3):  # three pulls, each with a new message of the same sender
        rel.inbox.append(signed_msg(SEED_EVIL))
        inbox(run)
    assert len(asked) == 1, asked
    assert [h["why"] for h in msgtrust.held(ws)] == ["not_accepted"] * 3
    rel.inbox.extend([signed_msg(SEED_EVIL), signed_msg(SEED_EVIL)])  # two in one pull: still none
    inbox(run)
    assert len(asked) == 1, asked
    monkeypatch.setattr(relay, "SETTLE_AGAIN", 0)  # as if the newest held one were minutes old
    rel.inbox.append(signed_msg(SEED_EVIL))
    inbox(run)
    assert len(asked) == 2, asked
    assert relay._settle_due(ws, None) is True and relay._settle_due(ws, "ws_nobody0001") is True


def test_an_install_without_a_kept_copy_settles_first_contact_by_a_refresh(ws, run, rel):
    """An install from before ORCH-2349 has workspaces.json but no kept keys: the first message is held,
    the pull asks the relay, and the message is handed on in the same run (a task too, never dropped)."""
    (msgtrust._dir(ws) / msgtrust.LISTED).unlink()
    text = signed_msg(SEED_PEER, body={"text": "Hello"})
    task = signed_msg(SEED_PEER, type_="delegate", body={"title": "Check the report"}, origin="person")
    rel.inbox += [text, task]
    out = inbox(run)
    assert {text["id"], task["id"]} <= handled_ids(ws) and msgtrust.held(ws) == []
    assert {text["id"], task["id"]} <= {x["id"] for x in out}
    assert _keys_of(ws) == ["relay-pairing"]


def test_the_kept_copy_is_read_only_from_the_guarded_home(ws):
    p = msgtrust._dir(ws) / msgtrust.LISTED
    assert ws not in p.parents
    assert json.loads(p.read_text())["keys"][PEER] == _pub(SEED_PEER).hex()
    p.write_text("not json")
    assert msgtrust._listed_key(ws, PEER) is None  # damaged: nothing is pinned


def test_a_swapped_key_is_held_again(ws, run, rel, person):
    accept(ws, PEER)
    # the relay now lists another key for Reports (a reinstall, or a swap by a broken relay)
    d = net.read_json(ws / ".agents/skills/orch-relay/workspaces.json", {})
    d["workspaces"] = [_dir_entry(PEER, SEED_EVIL, "Reports")]
    net.write_json(ws / ".agents/skills/orch-relay/workspaces.json", d)
    m = signed_msg(SEED_EVIL)
    rel.inbox.append(m)
    inbox(run)
    assert m["id"] not in handled_ids(ws)
    assert [h["why"] for h in msgtrust.held(ws)] == ["changed"]
    assert next(c for c in msgtrust.contacts(ws) if c["id"] == PEER)["state"] == "changed"


def test_withdraw_holds_again(ws, run, rel, person):
    accept(ws, PEER)
    assert run("relay", "contacts", "withdraw", PEER)[0] == 0
    m = signed_msg(SEED_PEER)
    rel.inbox.append(m)
    inbox(run)
    assert m["id"] not in handled_ids(ws) and [h["why"] for h in msgtrust.held(ws)] == ["withdrawn"]


# ---------------------------------------------------------------- replay and freshness (kept locally)


def test_replayed_message_is_refused_and_a_resend_is_quiet(ws, run, rel, person):
    accept(ws, PEER)
    m = signed_msg(SEED_PEER)
    rel.inbox.append(m)
    inbox(run)
    assert m["id"] in handled_ids(ws)
    run("relay", "done", m["id"])
    # the relay hands the very same message again (a lost ack): quietly ignored
    rel.acked.clear()
    inbox(run)
    assert msgtrust.refused(ws) == []
    # the same id with other signed bytes: refused
    rel.inbox[:] = [signed_msg(SEED_PEER, mid=m["id"], body={"text": "other"})]
    rel.acked.clear()
    inbox(run)
    assert msgtrust.refused(ws)[-1]["code"] == "replayed"


def test_a_signed_message_whose_save_failed_is_saved_on_the_next_pull(ws, run, rel, person, monkeypatch):
    """R3.1: the replay list marks the id before the inbox file is written. When that write fails (disk full,
    a synced folder holding the file), the relay's next delivery of the very same bytes is a 'duplicate' - it
    must still be saved and handled once, never acked away and lost."""
    accept(ws, PEER)
    m = signed_msg(SEED_PEER)
    rel.inbox.append(m)
    real = net.write_json

    def fail_inbox(path, data, *a, **k):
        if path.name == f"{m['id']}.json":
            raise OSError("No space left on device")
        return real(path, data, *a, **k)

    monkeypatch.setattr(net, "write_json", fail_inbox)
    with pytest.raises(OSError):
        run("relay", "inbox", "--json")
    assert m["id"] not in handled_ids(ws) and m["id"] not in rel.acked  # left on the relay
    monkeypatch.setattr(net, "write_json", real)
    items = inbox(run)
    assert m["id"] in handled_ids(ws) and m["id"] in rel.acked
    assert [i["id"] for i in items].count(m["id"]) == 1 and msgtrust.refused(ws) == []
    rel.acked.clear()  # and the same bytes once more after it was handled: still only once
    assert [i for i in inbox(run) if i["id"] == m["id"]] == []


def test_a_message_saved_before_a_later_save_failed_still_reaches_the_arrival_journal(
    ws, run, rel, person, monkeypatch
):
    """R3.1: A is saved, B's save fails, the pull stops before its journal. On the next pull A is a duplicate
    already on disk: it is not saved twice, but it still gets its arrival entry (watchers wait on it)."""
    from orch import relay

    accept(ws, PEER)
    a, b = signed_msg(SEED_PEER), signed_msg(SEED_PEER)
    rel.inbox.extend([a, b])
    real = net.write_json

    def fail_b(path, data, *args, **k):
        if path.name == f"{b['id']}.json":
            raise OSError("No space left on device")
        return real(path, data, *args, **k)

    monkeypatch.setattr(net, "write_json", fail_b)
    with pytest.raises(OSError):
        run("relay", "inbox", "--json")
    assert a["id"] not in {e["id"] for e in relay._read_arrivals(ws)}
    monkeypatch.setattr(net, "write_json", real)
    items = inbox(run)
    journal = [e["id"] for e in relay._read_arrivals(ws)]
    assert journal.count(a["id"]) == 1 and journal.count(b["id"]) == 1
    assert sorted(i["id"] for i in items if i["id"] in (a["id"], b["id"])) == sorted([a["id"], b["id"]])


def test_replay_list_lives_in_the_guarded_home(ws, run, rel, person, homes):
    accept(ws, PEER)
    m = signed_msg(SEED_PEER)
    rel.inbox.append(m)
    inbox(run)
    trust = homes[ws.resolve()] / "keys"
    files = list(trust.rglob("trust.json"))
    assert len(files) == 1 and f"{PEER}/{m['id']}" in json.loads(files[0].read_text())["seen"]
    assert not list(ws.rglob("trust.json"))  # never in the workspace folder


def test_expired_and_future_messages_are_refused(ws, run, rel, person):
    accept(ws, PEER)
    now = int(time.time() * 1000)
    old_start = signed_msg(
        SEED_PEER, type_="start", body={"key": "k", "text": "go"}, created_ms=now - 2 * 3600_000
    )
    future = signed_msg(SEED_PEER, created_ms=now + 10 * 60_000)
    ancient = signed_msg(SEED_PEER, created_ms=now - 31 * 24 * 3600_000)
    rel.inbox += [old_start, future, ancient]
    inbox(run)
    assert not handled_ids(ws) & {old_start["id"], future["id"], ancient["id"]}
    assert [r["code"] for r in msgtrust.refused(ws)] == ["expired", "future", "too_old"]


def test_an_allow_signed_as_a_helper_is_refused(ws, run, rel, person):
    accept(ws, PEER)
    m = signed_msg(
        SEED_PEER,
        type_="allow",
        body={"mode": "once", "kind": "delegate", "token": "ora_x"},
        origin="helper",
        reply_to="m_0000000000000998",
    )
    rel.inbox.append(m)
    inbox(run)
    assert m["id"] not in handled_ids(ws) and msgtrust.refused(ws)[-1]["code"] == "not_person"


def test_relay_made_types_pass_unsigned_and_never_act(ws, run, rel, person):
    run("relay", "contacts", "unsigned", "refuse")
    hint = {
        "schema": "orch.msg/1",
        "id": _mid(),
        "from": "admin",
        "to": WS,
        "type": "refresh-hint",
        "created_at": "2026-11-21T10:00:00Z",
        "body": {"version": 1},
    }
    rel.inbox.append(hint)
    assert msgtrust.check_incoming(ws, hint).kind == "plain"
    # a relay-made type is never one of the types that act on a person's behalf
    assert not set(msgtrust.RELAY_MADE_TYPES) & {"allow", "answer", "start", "delegate"}
    # an unsigned answer, delegate or text is not on the list: refused with signed_only on
    for t in ("answer", "delegate", "allow", "text"):
        m = dict(hint, id=_mid(), type=t, **{"from": PEER})
        assert msgtrust.check_incoming(ws, m).code == "missing_signature"


# ---------------------------------------------------------------- sending


def test_every_sent_message_carries_its_signature(ws, run, rel):
    pub, _ = signkey.ensure(ws)
    code, out, err = run("relay", "send", PEER, "Field X renamed", "--ticket", "t_7k3f9q", "--json")
    assert code == 0, err
    sent = rel.sent[-1]
    owner, s = msgsig.verify(sent["envelope"], "msg", [(WS, pub)])
    assert owner == WS and s["body"] == sent["body"] and s["to"] == PEER and s["ticket"] == "t_7k3f9q"
    assert s["origin"] == "helper"  # no terminal here: never a person's action


def test_sent_by_a_person_is_marked_person(ws, rel):
    from orch import relay

    signkey.ensure(ws)
    with msgtrust.as_person():
        relay.send_text(ws, PEER, "From me")
    s = msgsig.read_strict_json(msgsig.read_envelope(rel.sent[-1]["envelope"]).signed)
    assert s["origin"] == "person"


def _delegate_waiting(ws, run, rel) -> str:
    """An unsigned delegate (before the cut-over it still goes through) waiting for the person's allow."""
    mid = "m_deleg00000000001"
    rel.inbox.append(
        {
            "id": mid,
            "from": PEER,
            "to": WS,
            "type": "delegate",
            "created_at": "2026-11-23T10:00:00Z",
            "body": {"title": "Do it", "text": "x", "checklist": []},
        }
    )
    assert run("relay", "inbox")[0] == 0
    return mid


def test_an_allow_given_at_a_terminal_is_signed_as_the_persons(ws, run, rel, person):
    # ORCH-1822: the CLI did not pass who allowed, so every allow was signed as a helper's and refused
    pub, _ = signkey.ensure(ws)
    mid = _delegate_waiting(ws, run, rel)
    code, out, err = run("relay", "allow", mid, "--once")
    assert code == 0, err
    sent = rel.sent[-1]
    _, s = msgsig.verify(sent["envelope"], "msg", [(WS, pub)])
    assert sent["type"] == "allow" and s["origin"] == "person"


def test_an_allow_without_a_terminal_is_signed_as_a_helpers(ws, run, rel):
    pub, _ = signkey.ensure(ws)
    mid = _delegate_waiting(ws, run, rel)
    assert run("relay", "allow", mid, "--once", "--by", "human:tester")[0] == 0  # --by alone proves nothing
    _, s = msgsig.verify(rel.sent[-1]["envelope"], "msg", [(WS, pub)])
    assert s["origin"] == "helper"


def test_without_a_key_messages_still_go_out_unsigned(ws, run, rel, monkeypatch):
    monkeypatch.setattr(signkey, "public_key", lambda root: None)  # a workspace with no key yet
    assert run("relay", "send", PEER, "hello")[0] == 0
    assert "envelope" not in rel.sent[-1]


# ---------------------------------------------------------------- two workspaces, the relay bypassed


def _second_workspace(tmp_path, ws_id: str, peers: list[dict]):
    b = tmp_path.parent / f"{tmp_path.name}_b"
    (b / ".orch/secrets").mkdir(parents=True)
    net.write_json(
        b / ".orch/secrets/relay.json", {"url": "http://127.0.0.1:9", "workspace": ws_id, "token": "x"}
    )
    (b / ".agents/skills/orch-relay").mkdir(parents=True)
    net.write_json(
        b / ".agents/skills/orch-relay/workspaces.json",
        {
            "schema": "orch.workspaces/1",
            "self": ws_id,
            "updated_at": "2026-11-21T10:00:00Z",
            "workspaces": peers,
        },
    )
    return b


def test_two_workspaces_relay_bypassed(ws, run, rel, person, tmp_path, homes):
    """A's real send path signs; its exact bytes go straight into B's check, with no relay in between."""
    pub_a, _ = signkey.ensure(ws)
    entry_a = {
        "id": WS,
        "name": "Pilatus",
        "description": "",
        "tags": [],
        "online": True,
        "last_seen": None,
        "signing_key": {"alg": "ed25519", "public_key": msgsig.b64url(pub_a), "key_id": msgsig.key_id(pub_a)},
    }
    b = _second_workspace(tmp_path, PEER, [entry_a])
    from orch import addons

    addons.put_local_id(b, "b" * 32)
    msgtrust.keep_listed(b, {"workspaces": [entry_a]})  # what B's refresh keeps of the relay's answer
    assert run("relay", "send", PEER, "Please check the report", "--json")[0] == 0
    wire = json.loads(json.dumps(rel.sent[-1]))  # what the relay would hand over, byte for byte
    # B has not heard from A before, but the relay lists A (paired by the admin): trusted on first contact
    v = msgtrust.check_incoming(b, wire)
    assert v.kind == "ok" and msgtrust.held(b) == []
    # the same bytes again: a duplicate, never handled twice
    assert msgtrust.check_incoming(b, wire).kind == "duplicate"
    # changed on the way: refused
    assert run("relay", "send", PEER, "Second", "--json")[0] == 0
    bad = json.loads(json.dumps(rel.sent[-1]))
    bad["body"]["text"] = "Delete everything"
    assert msgtrust.check_incoming(b, bad).code == "signed_mismatch"
    # signature taken off: refused once B is signed-only
    msgtrust.set_refuse_unsigned(b, True, "human:tester")
    bare = json.loads(json.dumps(rel.sent[-1]))
    bare.pop("envelope")
    assert msgtrust.check_incoming(b, bare).code == "missing_signature"
    good = json.loads(json.dumps(rel.sent[-1]))
    assert msgtrust.check_incoming(b, good).kind == "ok"


# ---------------------------------------------------------------- groups carry the author's signature


def _host_copy(author_env: dict | None, text: str, author: str = OTHER, members=(WS, OTHER, PEER)) -> dict:
    """What a group host (Reports) sends us for a member's (Contoso's) message, signed by the host."""
    gid = "grp_t_abc123"
    body = {
        "text": text,
        "group": {
            "id": gid,
            "host": PEER,
            "title": "Launch",
            "seq": 3,
            "members": [{"ws": w, "name": w} for w in members],
        },
        "by": author,
        "via": "helper",
        "origin": {"id": "m_00000000000000aa", "from": author, "at": "2026-11-21T10:00:00Z"},
    }
    if author_env is not None:
        body["author"] = author_env
    return signed_msg(SEED_PEER, body=body, ticket="t_abc123")


def _author_env(text: str, seed: bytes = SEED_OTHER) -> dict:
    m = signed_msg(
        seed,
        frm=OTHER,
        to=PEER,
        mid="m_00000000000000aa",
        body={"text": text, "group": {"id": "grp_t_abc123", "host": PEER}, "by": OTHER},
    )
    return m["envelope"]


def test_group_copy_carries_and_checks_the_authors_signature(ws, person):
    accept(ws, PEER)
    accept(ws, OTHER)
    assert (
        msgtrust.check_incoming(ws, _host_copy(_author_env("Draft is ready"), "Draft is ready")).kind == "ok"
    )
    # the host changed the member's words: refused
    v = msgtrust.check_incoming(ws, _host_copy(_author_env("Draft is ready"), "Draft is NOT ready"))
    assert v.kind == "refused" and v.code == "author_mismatch"
    # the host dropped the author's signature
    assert msgtrust.check_incoming(ws, _host_copy(None, "Draft is ready")).code == "missing_signature"
    # the host forged the member's signature
    assert msgtrust.check_incoming(ws, _host_copy(_author_env("Hi", SEED_EVIL), "Hi")).kind == "refused"
    # the author is not in the member list the host signed
    v = msgtrust.check_incoming(ws, _host_copy(_author_env("Hi"), "Hi", members=(WS, PEER)))
    assert v.code == "author_mismatch"


def test_group_copy_from_an_author_not_accepted_is_held(ws, person):
    accept(ws, PEER)  # the host, not the author
    v = msgtrust.check_incoming(ws, _host_copy(_author_env("Hello group"), "Hello group"))
    assert v.kind == "held" and v.peer == OTHER
    msgtrust.hold(ws, v)
    r = accept(ws, OTHER)
    assert [x["result"] for x in r["released"]] == ["released"]


def test_host_passes_the_members_signature_on_and_every_member_checks_it(
    proj, run, rel, homes, person, tmp_path
):
    """The real host path: a member's signed group text reaches the host, the host's copy for the other member
    carries the member's own envelope unchanged, and that member checks the author's signature itself."""
    from orch import chat_groups, tickets

    home_seed, bank_seed = SEED_PEER, SEED_OTHER
    rel.snapshot["workspaces"]["workspaces"] = [
        _dir_entry(PEER, home_seed, "Home"),
        _dir_entry(OTHER, bank_seed, "Bank"),
    ]
    assert run("relay", "connect", rel.url, "--workspace", WS, "--token", rel.token)[0] == 0
    pub_host, _ = signkey.ensure(proj)
    tid = tickets.create(proj, "Pay car tax 2027", "human:test")["id"]
    run("relay", "delegate", "Home", "Find the letter", "--text", "x", "--ticket", tid, "--group")
    run("relay", "group", "add", tid, OTHER)
    gid = "grp_" + tid
    accept(proj, PEER)
    members = [{"ws": w, "name": n} for w, n in ((WS, "Pilatus"), (PEER, "Home"), (OTHER, "Bank"))]
    body = {
        "group": {"id": gid, "host": WS, "title": "Pay car tax 2027", "members": members},
        "by": PEER,
        "via": "helper",
        "text": "Found it: CHF 412.",
    }
    m = signed_msg(home_seed, frm=PEER, to=WS, body=body, ticket=tid)
    rel.sent.clear()
    inbox(run)
    rel.inbox.append(m)
    assert inbox(run)[0]["note"].startswith("group")
    (copy,) = [x for x in rel.sent if x["to"] == OTHER]
    assert copy["body"]["author"] == m["envelope"]  # unchanged, byte for byte
    assert chat_groups.message_errors(copy) == []
    # Bank, a second workspace, checks the copy with the relay bypassed
    entry_host = {
        "id": WS,
        "name": "Pilatus",
        "description": "",
        "tags": [],
        "online": True,
        "last_seen": None,
        "signing_key": {
            "alg": "ed25519",
            "public_key": msgsig.b64url(pub_host),
            "key_id": msgsig.key_id(pub_host),
        },
    }
    bank = _second_workspace(tmp_path, OTHER, [entry_host, _dir_entry(PEER, home_seed, "Home")])
    from orch import addons

    addons.put_local_id(bank, "c" * 32)
    msgtrust.accept(bank, WS, "human:tester", "dashboard")
    wire = json.loads(json.dumps(copy))
    v = msgtrust.check_incoming(bank, wire)
    assert v.kind == "held" and v.peer == PEER  # the host is accepted, the author not yet
    msgtrust.accept(bank, PEER, "human:tester", "dashboard")
    assert msgtrust.check_incoming(bank, json.loads(json.dumps(copy))).kind == "ok"
    changed = json.loads(json.dumps(copy))
    changed["id"] = "m_" + "e" * 16
    changed["body"]["text"] = "Found it: CHF 9412."
    # the host re-signs its changed copy, but cannot forge Home's words
    data = msgsig.read_strict_json(msgsig.read_envelope(copy["envelope"]).signed)
    data["id"], data["body"] = changed["id"], changed["body"]
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    changed["envelope"] = {
        "sig_v": 1,
        "key_id": msgsig.key_id(pub_host),
        "signed": msgsig.b64url(raw),
        "sig": msgsig.b64url(signkey.sign_bytes(proj, msgsig.signature_input("msg", raw))),
    }
    assert msgtrust.check_incoming(bank, changed).code == "author_mismatch"


def test_after_a_lost_list_old_actions_are_refused(ws, person, homes):
    """A workspace that handled messages before and lost its list (reinstall, restore): an allow or start made
    before the new list cannot be played again. A brand-new workspace has no such floor."""
    (ws / ".orch").mkdir(exist_ok=True)
    (ws / ".orch/inbox-seen.json").write_text("{}")
    st = msgtrust._load(ws)
    assert st["floor_ms"] > 0
    msgtrust.accept(ws, PEER, "human:tester", "cli")
    m = signed_msg(
        SEED_PEER,
        type_="start",
        body={"key": "k", "text": "go"},
        created_ms=msgtrust._load(ws)["floor_ms"] - 60_000,
    )
    assert msgtrust.check_incoming(ws, m).code == "before_floor"


def test_a_dropped_held_allow_sent_again_is_never_run(ws, run, rel, person):
    allow = signed_msg(
        SEED_PEER,
        type_="allow",
        body={"mode": "once", "kind": "delegate", "token": "ora_x"},
        origin="person",
        reply_to="m_0000000000000997",
    )
    msgtrust.withdraw(ws, PEER, "human:tester", "cli")
    rel.inbox.append(allow)
    inbox(run)
    accept(ws, PEER)
    rel.inbox[:] = [json.loads(json.dumps(allow))]  # the relay plays it again after Accept
    rel.acked.clear()
    inbox(run)
    assert allow["id"] not in handled_ids(ws)


def test_unsigned_messages_never_look_verified(ws, run, rel):
    m = signed_msg(SEED_PEER, body={"text": "hi", "author": {"sig_v": 1}})
    m.pop("envelope")
    m["signed"] = {"origin": "person"}
    v = msgtrust.check_incoming(ws, m)
    assert v.kind == "plain" and "signed" not in v.message and "author" not in v.message["body"]


def test_another_senders_id_never_replaces_a_saved_message(ws, run, rel, person):
    accept(ws, PEER)
    accept(ws, OTHER)
    first = signed_msg(SEED_PEER, mid="m_00000000000000cc", body={"text": "real"})
    rel.inbox.append(first)
    inbox(run)
    clash = signed_msg(SEED_OTHER, frm=OTHER, mid="m_00000000000000cc", body={"text": "overwrite"})
    rel.inbox.append(clash)
    inbox(run)
    saved = json.loads((ws / ".orch/inbox/m_00000000000000cc.json").read_text())
    assert saved["body"]["text"] == "real"


def test_the_host_cannot_hand_a_members_words_over_twice(ws, person):
    accept(ws, PEER)
    accept(ws, OTHER)
    env = _author_env("Draft is ready")
    assert msgtrust.check_incoming(ws, _host_copy(env, "Draft is ready")).kind == "ok"
    v = msgtrust.check_incoming(
        ws, _host_copy(env, "Draft is ready")
    )  # a new copy id, the same member message
    assert v.kind == "refused" and v.code == "replayed"


def test_a_stale_author_signature_is_refused_not_held(ws, person):
    accept(ws, PEER)
    old = int(time.time() * 1000) - 31 * 24 * 3600_000
    m = signed_msg(
        SEED_OTHER,
        frm=OTHER,
        to=PEER,
        mid="m_00000000000000aa",
        created_ms=old,
        body={"text": "Hi", "group": {"id": "grp_t_abc123", "host": PEER}, "by": OTHER},
    )
    v = msgtrust.check_incoming(ws, _host_copy(m["envelope"], "Hi"))
    assert v.kind == "refused" and v.code == "too_old"


def test_a_host_cannot_drop_or_bend_the_members_fields(ws, person):
    accept(ws, PEER)
    accept(ws, OTHER)
    env = _author_env("Draft is ready")
    # `origin` dropped while `by` still names the member
    m = _host_copy(env, "Draft is ready")
    body = {k: v for k, v in m["body"].items() if k != "origin"}
    assert (
        msgtrust.check_incoming(ws, signed_msg(SEED_PEER, body=body, ticket="t_abc123")).code
        == "author_mismatch"
    )
    # `by` names someone else than the signed author
    body = dict(_host_copy(env, "Draft is ready")["body"], by=PEER)
    assert (
        msgtrust.check_incoming(ws, signed_msg(SEED_PEER, body=body, ticket="t_abc123")).code
        == "author_mismatch"
    )
    # "written by the person" added by the host to a helper's words
    body = dict(_host_copy(_author_env("Draft is ready"), "Draft is ready")["body"], via="dashboard")
    assert (
        msgtrust.check_incoming(ws, signed_msg(SEED_PEER, body=body, ticket="t_abc123")).code
        == "author_mismatch"
    )
    # a task status the member never sent
    body = dict(
        _host_copy(_author_env("Draft is ready"), "Draft is ready")["body"],
        task={"delegate": "m_0000000000000abc", "ws": OTHER, "status": "done", "title": "x"},
    )
    assert (
        msgtrust.check_incoming(ws, signed_msg(SEED_PEER, body=body, ticket="t_abc123")).code
        == "author_mismatch"
    )


# ---------------------------------------------------------------- a phone's signed answer (ORCH-1204 c9)

PHONE = "ph_iphone0001"
SEED_PHONE = bytes.fromhex("44" * 32)


def _phone_question(ws, rel) -> tuple[str, str, str]:
    """A paired phone with a key the person accepted, and a signed question sent to the phones.
    Returns (ticket id, question message id, sha256 of the question's signed bytes)."""
    import hashlib

    from orch import relay, tickets

    signkey.ensure(ws)
    p = ws / ".agents/skills/orch-relay/workspaces.json"
    d = json.loads(p.read_text())
    d["phones"] = [{**_dir_entry(PHONE, SEED_PHONE, "Severin's iPhone"), "id": PHONE}]
    p.write_text(json.dumps(d))
    accept(ws, PHONE)
    tid = tickets.create(ws, "Backups", "human:tester")["id"]
    tickets.ask(ws, tid, "Delete the old backups?", ["yes", "no"], "no", "agent:claude")
    t = tickets.load(ws, tid)
    qmid = relay.send_question(ws, t, t["questions"][0])["id"]
    sent = next(m for m in rel.sent if m["id"] == qmid)
    sha = hashlib.sha256(msgsig.read_envelope(sent["envelope"]).signed).hexdigest()
    return tid, qmid, sha


def _phone_answer(tid: str, qmid: str, sha: str, answer: str = "yes", qid: str = "q1") -> dict:
    body = {"question_id": "q1", "answer": answer, "answered_by": f"human:{PHONE}"}
    return signed_msg(
        SEED_PHONE,
        frm=PHONE,
        type_="answer",
        body=body,
        origin="person",
        ticket=tid,
        reply_to=qmid,
        question_id=qid,
        question_sha256=sha,
    )


def test_the_workspace_keeps_the_hash_of_each_signed_question(ws, run, rel, person):
    from orch import relay

    _tid, qmid, sha = _phone_question(ws, rel)
    assert json.loads(relay._asked_path(ws).read_text())[qmid]["question_sha256"] == sha


def test_a_signed_phone_answer_naming_the_question_is_applied_with_the_phones_name(ws, run, rel, person):
    from orch import tickets

    tid, qmid, sha = _phone_question(ws, rel)
    rel.inbox.append(_phone_answer(tid, qmid, sha))
    inbox(run)
    q = tickets.load(ws, tid)["questions"][0]
    assert q["answer"] == "yes"
    assert q["answered_by"] == "human:Severin's iPhone"  # the phone's id in the signed answer, shown by name


@pytest.mark.parametrize("bad", ["hash", "question"])
def test_a_signed_phone_answer_naming_another_question_is_never_applied(ws, run, rel, person, bad):
    from orch import tickets

    tid, qmid, sha = _phone_question(ws, rel)
    wrong = (
        _phone_answer(tid, qmid, "0" * 64)
        if bad == "hash"  # signed for other question bytes (the relay changed the question on the way)
        else _phone_answer(tid, qmid, sha, qid="q2")
    )
    rel.inbox.append(wrong)
    inbox(run)
    assert tickets.load(ws, tid)["questions"][0]["answer"] is None
    # the question stays open: the right signed answer is still applied
    rel.inbox.append(_phone_answer(tid, qmid, sha, answer="no"))
    inbox(run)
    assert tickets.load(ws, tid)["questions"][0]["answer"] == "no"


# ---------------------------------------------------------------- outside review (ORCH-1206)


@pytest.mark.parametrize("outer", [{"done": True}, {"done": 1.0}])
def test_a_body_equal_only_to_python_is_a_mismatch(ws, run, rel, person, outer):
    """True == 1 and 1.0 == 1 in Python: a body signed as {"done": 1} is not the same JSON."""
    accept(ws, PEER)
    m = signed_msg(SEED_PEER, body={"done": 1})
    m["body"] = outer
    rel.inbox.append(m)
    inbox(run)
    assert m["id"] not in handled_ids(ws) and msgtrust.refused(ws)[-1]["code"] == "signed_mismatch"


def test_what_is_delivered_is_what_was_signed(ws, person):
    """Outer fields the relay added or changed outside the compared ones never reach the handling."""
    accept(ws, PEER)
    m = signed_msg(SEED_PEER, origin="helper")
    m["origin"] = "person"
    m["question_sha256"] = "ab" * 32
    m["files"] = [{"blob_id": "b_evil", "size": 1, "sha256": "cd" * 32}]
    m["created_ms"] = 1
    v = msgtrust.check_incoming(ws, m)
    assert v.kind == "ok"
    assert v.message["origin"] == "helper" and v.message["created_ms"] > 1
    assert "question_sha256" not in v.message and "files" not in v.message


@pytest.mark.parametrize("typ", ["start", "delegate"])
def test_a_held_start_or_delegate_is_dropped_on_accept(ws, run, rel, person, typ):
    msgtrust.withdraw(ws, PEER, "human:tester", "cli")  # RP3 A: a paired first contact is not held
    m = signed_msg(SEED_PEER, type_=typ, body={"text": "Run it"}, origin="person")
    rel.inbox.append(m)
    inbox(run)
    assert [h["id"] for h in msgtrust.held(ws)] == [m["id"]]
    r = accept(ws, PEER)
    assert {x["id"]: x["result"] for x in r["released"]} == {m["id"]: "dropped"}
    assert m["id"] not in handled_ids(ws)


def test_a_held_message_of_any_body_shape_never_breaks_accept(ws, run, rel, person):
    msgtrust.withdraw(ws, PEER, "human:tester", "cli")  # RP3 A: a paired first contact is not held
    odd = signed_msg(SEED_OTHER, frm=OTHER, body={"origin": "x", "text": "hi"})
    mine = signed_msg(SEED_PEER)
    rel.inbox += [odd, mine]
    inbox(run)
    r = accept(ws, PEER)
    assert {x["id"]: x["result"] for x in r["released"]} == {mine["id"]: "released"}


@pytest.mark.parametrize("field,value", [("signed", "A" * 400_000), ("sig", "A" * 10_000)])
def test_an_oversized_envelope_field_is_refused_before_decoding(field, value, monkeypatch):
    def boom(_):
        raise AssertionError("decoded")

    m = signed_msg(SEED_PEER)
    env = {**m["envelope"], field: value}
    monkeypatch.setattr(msgsig, "b64url_decode_strict", boom)
    with pytest.raises(msgsig.SigError) as e:
        msgsig.read_envelope(env)
    assert e.value.code == "bad_envelope"
