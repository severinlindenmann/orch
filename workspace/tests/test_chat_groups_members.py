"""Team chat 2.2: adding and removing workspaces in a ticket chat safely (contracts/chat-groups.md §6).

Only the ticket's workspace changes the member list; an added workspace gets the ticket card and the chat
so far, nothing else; forged, replayed and removed-member messages are refused; copies still waiting for a
removed member are dropped; a group with an older (version 1) member; adding and removing while the relay
is out of reach. The host / member fixtures come from test_chat_groups."""

# ruff: noqa: F811  (the fixtures imported below are used as test arguments)
import json

import pytest
from test_chat_groups import (  # noqa: F401  (fixtures are used by name)
    BANK,
    FIN,
    HOME,
    MEMBERS,
    PHONE,
    STRANGER,
    WS,
    _added,
    _joined,
    contract_errors,
    entry,
    from_host,
    gout,
    group_msg,
    grp,
    host,
    inbox,
    member,
    mid,
    sent,
)

from orch import chat_groups as cg
from orch import relay, tickets
from orch.errors import Refused

SECRET = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


def _state(proj):
    return json.loads((proj / ".orch/secrets/groups.json").read_text())


def _say(proj, tid, by, text, chat=True):
    tickets.apply_op(proj, tid, lambda t: tickets.add_history(t, by, text, "cli", chat=chat), by=by)


def _down(monkeypatch):
    real = relay._post_message

    def down(root, raw):
        raise Refused("Can't reach relay.example right now. Check your internet and try again.")

    monkeypatch.setattr(relay, "_post_message", down)
    return lambda: monkeypatch.setattr(relay, "_post_message", real)


def _outbox(proj):
    return [json.loads(p.read_text()) for p in sorted((proj / ".orch/outbox").glob("m_*.json"))]


def _kinds(msgs):
    """What each message is: the group event kind, card (card+chat with the chat so far), or text."""
    out = []
    for m in msgs:
        b = m["body"]
        if b.get("group_event"):
            out.append(b["group_event"]["kind"])
        elif "shared_ticket" in b:
            out.append("card+chat" if "shared_chat" in b else "card")
        else:
            out.append(m["type"])
    return out


# ---- only the ticket's workspace adds or removes --------------------------------------------------------


def test_the_person_adds_a_workspace_and_it_gets_the_ticket_and_the_whole_chat_only(proj, run, rel, host):
    _say(proj, host, "human:owner", "Can someone check the 2025 letter?")
    _say(proj, host, "agent:claude", "I found it, the amount is 412 CHF.")
    _say(proj, host, "agent:claude", "Internal note: looked in the tax folder", chat=False)
    _say(proj, host, "human:owner", f"The token is {SECRET}")
    cg.add_member(proj, host, HOME, "human:owner")
    to_home = sent(rel, to=HOME)
    assert _kinds(to_home) == ["member_added", "card+chat"]  # nothing else goes to the new member
    ev = to_home[0]["body"]["group_event"]
    assert ev["added_by"] == "you" and ev["ws"] == HOME
    home = next(x for x in to_home[0]["body"]["group"]["members"] if x["ws"] == HOME)
    assert home["added_by"] == "you" and "joined_at" in home
    me = next(x for x in to_home[0]["body"]["group"]["members"] if x["ws"] == WS)
    assert "added_by" not in me  # the host's own entry never has added_by
    chat = to_home[1]["body"]
    assert "seq" not in chat["group"] and chat["shared_ticket"]["title"] == "Pay car tax 2027"  # targeted
    lines = chat["shared_chat"]["lines"]
    assert [x["who"] for x in lines] == ["person", "helper", "person"]
    assert lines[1]["text"] == "I found it, the amount is 412 CHF."
    assert not any("Internal note" in x["text"] for x in lines)  # only chat lines, never other history
    assert SECRET not in json.dumps(to_home) and "[hidden]" in lines[2]["text"]
    for m in to_home:
        assert contract_errors(m) == [], (contract_errors(m), m)
    # a workspace added by the host's helper says so, and the record keeps who added whom
    cg.add_member(proj, host, BANK, "agent:claude")
    ev = [m for m in sent(rel, to=BANK) if m["body"].get("group_event")][0]["body"]["group_event"]
    assert ev["added_by"] == WS
    v = cg.view(proj)["hosted"][0]
    assert {m["ws"]: m["added_by"] for m in v["members"]} == {WS: None, HOME: "you", BANK: WS}
    rec = tickets.load(proj, host)["ext"]["relay"]["group"]["members"]
    assert {m["ws"]: m.get("added_by") for m in rec} == {WS: None, HOME: "you", BANK: WS}


def test_a_long_chat_keeps_the_newest_lines_within_the_limits(proj, run, rel, host):
    for i in range(cg.CHAT_LINES_MAX + 5):
        _say(proj, host, "human:owner", f"line {i} " + "x" * 150)
    cg.add_member(proj, host, HOME, "human:owner")
    chat = [m for m in sent(rel, to=HOME) if "shared_chat" in m["body"]][0]
    sc = chat["body"]["shared_chat"]
    assert sc["lines"][-1]["text"].startswith(f"line {cg.CHAT_LINES_MAX + 4} ")
    assert len(json.dumps(sc, separators=(",", ":")).encode()) <= cg.CHAT_BYTES_MAX
    assert sc["more"] == cg.CHAT_LINES_MAX + 5 - len(sc["lines"]) and contract_errors(chat) == []


def test_no_chat_on_the_card_when_the_ticket_has_no_chat_yet(proj, run, rel, host):
    cg.add_member(proj, host, HOME, "human:owner")
    assert _kinds(sent(rel, to=HOME)) == ["member_added", "card"]


def test_a_member_cannot_add_or_remove_anyone(proj, run, rel, grp):
    host, gid, _ = grp
    before = _state(proj)["hosted"][gid]["members"]
    claims = [
        {"kind": "member_added", "ws": STRANGER, "name": "X", "added_by": "you", "from_seq": 9},
        {"kind": "member_left", "ws": BANK, "reason": "removed", "removed_by": "you"},
    ]
    for i, ev in enumerate(claims):
        m = group_msg(
            HOME, gid, host, MEMBERS, {"text": "x", "group_event": {**ev, "at": "2026-11-08T10:00:00Z"}}
        )
        m["id"] = mid(f"claim{i}")
        assert "dropped" in inbox(run, rel, m)[0]["note"]
    assert _state(proj)["hosted"][gid]["members"] == before and gout(rel) == []


def test_a_task_from_another_workspaces_chat_cannot_add_there(proj, run, rel, member):
    t = tickets.create(proj, "Find the 2025 letter", "human:test")
    link = {"group_task": {"host": FIN, "group": "grp_t_fin14a", "delegate": mid("dlg")}}
    tickets.ext_set(proj, t["id"], "relay", json.dumps(link), "human:test")
    code, out, err = run("relay", "group", "add", t["id"], "Finance")
    assert code == 2 and "Only" in (out + err) and "adds or removes workspaces" in (out + err)
    assert gout(rel) == []


# ---- forged, replayed and removed-member messages -------------------------------------------------------


def test_forged_replayed_and_removed_member_messages_are_refused_at_the_host(
    proj, run, rel, grp, monkeypatch
):
    host, gid, _ = grp
    talk = group_msg(HOME, gid, host, MEMBERS, {"text": "the PDF is attached"}, id=mid("talk1"))
    inbox(run, rel, talk)
    copies = len(gout(rel))
    assert copies >= 2
    # the same message again (a replay): no second copy, no second chat line
    rel.acked.clear()
    inbox(run, rel, talk)
    assert len(gout(rel)) == copies
    lines = [h for h in tickets.load(proj, host)["history"] if h.get("chat_message")]
    assert sum("the PDF is attached" in h["text"] for h in lines) == 1
    # a stranger claiming to be the host of our group
    forged = group_msg(STRANGER, gid, host, MEMBERS, {"text": "x"}, id=mid("forged1"))
    forged["body"]["group"]["host"] = STRANGER
    assert "dropped" in inbox(run, rel, forged)[0]["note"]
    # removed: nothing it sends is taken any more, its version report included
    monkeypatch.setattr(tickets, "require_human", lambda *a, **k: None)
    cg.remove_member(proj, host, HOME, "human:owner")
    rel.sent.clear()
    for i, body in enumerate(
        [
            {"text": "still here"},
            {"text": "Seen", "seen": {"seq": 3}, "update": {"kind": "note"}},
            {"text": "Seen", "member_version": {"orch_version": "9.9.9", "chat_groups": 2}},
        ]
    ):
        assert (
            "dropped"
            in inbox(run, rel, group_msg(HOME, gid, host, MEMBERS, body, id=mid(f"rm{i}")))[0]["note"]
        )
    assert gout(rel) == []
    assert "orch_version" not in _state(proj)["hosted"][gid]["members"][HOME]


def test_a_member_refuses_a_forged_host_and_a_replayed_add_after_its_removal(proj, run, rel, member):
    inbox(run, rel, _added(1))
    # a workspace that is not the host sends a member change for the group
    forged = from_host(
        "text",
        {
            "text": "x",
            "group_event": {
                "kind": "member_left",
                "at": "2026-11-08T10:00:00Z",
                "ws": WS,
                "reason": "removed",
            },
        },
        seq=2,
        id=mid("fake-rm"),
    )
    forged["from"] = STRANGER
    assert "dropped" in inbox(run, rel, forged)[0]["note"] and _joined(proj)["left"] is False
    removed = from_host(
        "text",
        {
            "text": "You removed Pilatus Workspace from this group",
            "group_event": {
                "kind": "member_left",
                "at": "2026-11-08T10:01:00Z",
                "ws": WS,
                "reason": "removed",
                "removed_by": "you",
            },
        },
        seq=2,
        id=mid("real-rm"),
    )
    inbox(run, rel, removed)
    assert _joined(proj)["left"] is True
    # the old member_added again (same id, or a new id with the old seq): never adds us back
    rel.acked.clear()
    inbox(run, rel, _added(1))
    again = _added(1)
    again["id"] = mid("replayed-add")
    assert "dropped" in inbox(run, rel, again)[0]["note"]
    assert _joined(proj)["left"] is True


def _card(rev, lines=None, i="c"):
    card = {
        "ticket": "t_fin14a",
        "key": "FIN-14",
        "title": "Pay car tax 2027",
        "status": "active",
        "summary": "",
        "question": None,
        "checklist": [],
        "done": 0,
        "total": 0,
        "rev": rev,
    }
    body = {"text": "From Finance · FIN-14", "shared_ticket": card}
    if lines is not None:
        body["shared_chat"] = {"lines": lines, "more": 2}
    return from_host("text", body, id=mid(f"card{i}{rev}"))


def test_the_chat_so_far_comes_on_the_card_and_is_kept_once(proj, run, rel, member):
    inbox(run, rel, _added(1))
    first = [{"who": "person", "text": "Can someone check the letter?"}]
    out = inbox(run, rel, _card(1, first))
    assert out[0].get("note", "").startswith("ticket card")
    j = _joined(proj)
    assert j["chat_before"] == {"lines": first, "more": 2} and j["card"]["rev"] == 1
    assert not any(x.get("text") == "From Finance · FIN-14" for x in j["log"])  # not a new chat line
    # a later card (the ticket changed) updates the card but never replaces the chat we joined with
    inbox(run, rel, _card(2, [{"who": "person", "text": "other"}]))
    j = _joined(proj)
    assert j["card"]["rev"] == 2 and j["chat_before"]["lines"] == first
    assert cg.view(proj)["joined"][0]["chat_before"]["more"] == 2
    # the chat without the card is refused (it only rides on the card)
    bare = from_host("text", {"text": "x", "shared_chat": {"lines": first}}, seq=2, id=mid("bare"))
    assert "dropped" in inbox(run, rel, bare)[0]["note"]
    # untrusted text from the host is cleaned and cut; an unknown speaker is skipped
    odd = [{"who": "admin", "text": "x"}, {"who": "member", "name": "Home\nX", "text": "y" * 3000}]
    kept = cg._clean_chat({"lines": odd})
    assert [x["who"] for x in kept["lines"]] == ["member"] and len(kept["lines"][0]["text"]) <= 2000
    assert "\n" not in kept["lines"][0]["name"]


# ---- copies still waiting for a removed member ----------------------------------------------------------


def test_removing_drops_the_copies_still_waiting_for_that_workspace(proj, run, rel, grp, monkeypatch):
    host, gid, _ = grp
    monkeypatch.setattr(tickets, "require_human", lambda *a, **k: None)
    up = _down(monkeypatch)
    cg.say(proj, host, "Please send the PDF")
    waiting = _outbox(proj)
    assert {m["to"] for m in waiting} == {HOME, BANK, "phones"}
    r = cg.remove_member(proj, host, HOME, "human:owner")
    assert r["dropped"] == 1
    left = _outbox(proj)
    assert [m["to"] for m in left if m["to"] == HOME] == [HOME]  # only the news of its own removal
    assert _kinds([m for m in left if m["to"] == HOME]) == ["member_left"]
    news = next(m for m in left if m["to"] == HOME)["body"]["group_event"]
    assert news["removed_by"] == "you" and news["reason"] == "removed"
    up()
    res = relay.resend_outbox(proj)
    assert res["waiting"] == [] and res["dropped"] == []
    assert _kinds(sent(rel, to=HOME)) == ["member_left"]
    assert _kinds(sent(rel, to=BANK)) == ["text", "member_left"]
    # the removed member's own copy still lists it, so it accepts the news; the others' copies do not
    assert HOME in [x["ws"] for x in sent(rel, to=HOME)[0]["body"]["group"]["members"]]
    assert HOME not in [x["ws"] for x in sent(rel, to=BANK)[1]["body"]["group"]["members"]]
    for m in sent(rel, to=HOME) + sent(rel, to=BANK):
        assert contract_errors(m) == [], (contract_errors(m), m)


def test_a_copy_written_before_a_crash_is_dropped_when_the_outbox_is_sent(proj, run, rel, grp, monkeypatch):
    host, gid, _ = grp
    up = _down(monkeypatch)
    cg.say(proj, host, "Please send the PDF")
    # the removal was saved but the sweep never ran (a crash in between)
    st = _state(proj)
    st["hosted"][gid]["members"][HOME]["left_at"] = "2026-11-08T10:05:00Z"
    st["hosted"][gid]["members"][HOME]["reason"] = "removed"
    (proj / ".orch/secrets/groups.json").write_text(json.dumps(st))
    up()
    res = relay.resend_outbox(proj)
    assert [d["reason"] for d in res["dropped"]] == ["no longer a member of the group"]
    assert sent(rel, to=HOME) == [] and len(sent(rel, to=BANK)) == 1


def test_a_pending_send_intent_skips_a_member_removed_before_the_replay(proj, run, rel, grp, monkeypatch):
    host, gid, _ = grp
    monkeypatch.setattr(tickets, "require_human", lambda *a, **k: None)
    calls = {"n": 0}
    real = cg._send

    def crash_after_first(*a, **k):  # the seq is saved, then the process dies after the first copy
        calls["n"] += 1
        if calls["n"] > 1:
            raise SystemExit("crash")
        return real(*a, **k)

    monkeypatch.setattr(cg, "_send", crash_after_first)
    with pytest.raises(SystemExit):
        cg.say(proj, host, "Please send the PDF")
    monkeypatch.setattr(cg, "_send", real)
    first = rel.sent[-1]["to"]
    other = BANK if first == HOME else HOME
    cg.remove_member(proj, host, other, "human:owner")
    rel.sent.clear()
    run("relay", "inbox")  # sync replays the pending intent
    texts = [m for m in gout(rel) if not m["body"].get("group_event") and "shared_ticket" not in m["body"]]
    assert other not in {m["to"] for m in texts} and "phones" in {m["to"] for m in texts}


# ---- mixed versions, offline add and remove -------------------------------------------------------------


def test_a_group_with_an_older_member_marks_it_and_sends_both_what_they_can_read(proj, run, rel, grp):
    host, gid, _ = grp
    v2 = group_msg(
        HOME,
        gid,
        host,
        MEMBERS,
        {"text": "Seen", "seen": {"seq": 2}, "member_version": {"orch_version": "0.9.4", "chat_groups": 2}},
        id=mid("ver-home"),
    )
    inbox(run, rel, v2)
    ms = {m["ws"]: m for m in cg.view(proj)["hosted"][0]["members"]}
    assert ms[HOME]["chat_groups"] == 2 and ms[HOME]["orch_version"] == "0.9.4"
    assert ms[BANK]["chat_groups"] == 1 and ms[BANK]["orch_version"] is None  # never reported: "older orch"
    cg.say(proj, host, "Thanks, both of you")
    for m in gout(rel):
        assert contract_errors(m) == [], (contract_errors(m), m)
        wire = {x["ws"]: x for x in m["body"]["group"]["members"]}
        assert wire[HOME].get("chat_groups") == 2 and "chat_groups" not in wire[BANK]
    # what a version 1 member keeps of the header: ws, name, look only (it ignores the rest)
    to_bank = [m for m in gout(rel) if m["to"] == BANK][0]
    clean = cg._clean_wire(to_bank["body"]["group"])
    assert all(set(x) <= {"ws", "name", "look"} for x in clean["members"])


def test_a_member_reports_its_version_once_with_its_first_seen(proj, run, rel, member, monkeypatch):
    monkeypatch.setattr(cg, "SEEN_EVERY", 0)
    inbox(run, rel, _added(1))
    run("relay", "inbox")
    seen = [m for m in sent(rel, to=FIN) if "seen" in m["body"]]
    assert seen and seen[0]["body"]["member_version"]["chat_groups"] == cg.CHAT_GROUPS_VERSION
    assert contract_errors(seen[0]) == []
    rel.sent.clear()
    inbox(run, rel, from_host("text", {"text": "hello"}, seq=2, id=mid("hello2")))
    run("relay", "inbox")
    seen = [m for m in sent(rel, to=FIN) if "seen" in m["body"]]
    assert seen and "member_version" not in seen[0]["body"]


def test_adding_and_removing_while_the_relay_is_out_of_reach(proj, run, rel, grp, monkeypatch):
    host, gid, _ = grp
    monkeypatch.setattr(tickets, "require_human", lambda *a, **k: None)
    rel.snapshot["workspaces"]["workspaces"].append(entry(STRANGER, "Garage", "car", "green"))
    run("relay", "refresh")  # the directory now knows Garage
    _say(proj, host, "human:owner", "Who has the 2025 letter?")
    up = _down(monkeypatch)
    cg.add_member(proj, host, STRANGER, "human:owner")
    assert _kinds([m for m in _outbox(proj) if m["to"] == STRANGER]) == ["member_added", "card+chat"]
    cg.remove_member(proj, host, BANK, "human:owner")
    up()
    res = relay.resend_outbox(proj)
    assert res["waiting"] == [] and res["failed"] == []
    # delivered later, in the order they were saved: the new member gets its add, the card with the chat so
    # far, then the news that Bank was removed; Bank, removed before anything went out, gets only its removal
    assert _kinds(sent(rel, to=STRANGER)) == ["member_added", "card+chat", "member_left"]
    assert _kinds(sent(rel, to=BANK)) == ["member_left"]
    # removed while still offline: the queued add, card and chat for the new member are dropped
    up = _down(monkeypatch)
    rel.sent.clear()
    cg.remove_member(proj, host, STRANGER, "human:owner")
    cg.add_member(proj, host, BANK, "human:owner")
    cg.remove_member(proj, host, BANK, "human:owner")
    up()
    relay.resend_outbox(proj)
    assert _kinds(sent(rel, to=BANK)) == ["member_left"]
    assert _kinds(sent(rel, to=STRANGER)) == ["member_left"]
    for m in rel.sent:
        if m["body"].get("group") and m["to"] != WS:
            assert contract_errors(m) == [], (contract_errors(m), m)
