"""Phones tied to people and the ticks checked (ORCH-1161, steps 4 and 5 of the first slice, owner 21 Nov:
"enforce the ticks before this goes in"). Every phone path: unknown, cut and removed phones and missing
rights are refused before anything is written; a phone's person is the actor; queued work is checked again
when it would start."""

import json

import pytest
from test_relay_client import connect, msg

from orch import people, relay, runs, tickets

LEA, MAX, NEW = "ph_lea00000001", "ph_max00000001", "ph_new00000001"


@pytest.fixture
def team(proj, run, rel):
    """Relay connected with three paired phones; people on: owner Sev, Lea (write), Max (write, decide);
    Lea's and Max's phones tied, the third phone not."""
    rel.snapshot["workspaces"]["phones"] = [
        {"id": LEA, "name": "Lea phone", "online": True, "last_seen": None},
        {"id": MAX, "name": "Max phone", "online": True, "last_seen": None},
        {"id": NEW, "name": "Pixel", "online": True, "last_seen": None},
    ]
    connect(run, rel)
    people.turn_on(proj, "Sev")
    lea = people.add(proj, "Lea")
    mx = people.add(proj, "Max", ["write", "decide"])
    people.tie(proj, LEA, "Lea")
    people.tie(proj, MAX, "Max")
    return {"lea": lea["id"], "max": mx["id"]}


def _text(rel, run, mid, frm, text="Please book the table"):
    rel.inbox.append(msg(mid, "text", {"text": text}, frm=frm))
    return run("relay", "inbox")[1]


def _made_by(proj, mid):
    return relay._ticket_by_message(proj, mid)


def test_list_off_changes_nothing(proj, run, rel):
    rel.snapshot["workspaces"]["phones"] = [{"id": NEW, "name": "Pixel", "online": True, "last_seen": None}]
    connect(run, rel)
    _text(rel, run, "m_off0000000000001", NEW)
    assert _made_by(proj, "m_off0000000000001") is not None
    assert people.who_sent(proj, NEW, "answer") is None


def test_text_from_untied_phone_is_refused(proj, run, rel, team):
    _text(rel, run, "m_new0000000000001", NEW)
    assert _made_by(proj, "m_new0000000000001") is None
    assert "not tied" in people.refused(proj)[-1]["why"]
    assert "Please book" not in json.dumps(people.refused(proj))  # no message content kept


def test_text_from_tied_phone_records_person_and_device(proj, run, rel, team):
    _text(rel, run, "m_lea0000000000001", LEA)
    tid = _made_by(proj, "m_lea0000000000001")
    assert tid is not None
    lines = [h for h in tickets.load(proj, tid)["history"] if h.get("via") == "phone"]
    assert lines and all(h["person"] == team["lea"] and h["device"] == LEA for h in lines)


def test_cut_phone_and_removed_person_are_refused(proj, run, rel, team):
    people.cut(proj, LEA)
    _text(rel, run, "m_cut0000000000001", LEA)
    assert _made_by(proj, "m_cut0000000000001") is None
    assert "cut off" in people.refused(proj)[-1]["why"]
    people.remove(proj, "Max")
    _text(rel, run, "m_rem0000000000001", MAX)
    assert _made_by(proj, "m_rem0000000000001") is None
    assert "removed" in people.refused(proj)[-1]["why"]


def test_phone_no_longer_paired_is_refused(proj, run, rel, team):
    rel.snapshot["workspaces"]["phones"] = [p for p in rel.snapshot["workspaces"]["phones"] if p["id"] != LEA]
    run("relay", "refresh")
    _text(rel, run, "m_unp0000000000001", LEA)
    assert _made_by(proj, "m_unp0000000000001") is None
    assert "not paired" in people.refused(proj)[-1]["why"]


def test_damaged_list_lets_no_phone_in(proj, run, rel, team):
    people.path(proj).write_text("{", encoding="utf-8")
    _text(rel, run, "m_brk0000000000001", MAX)
    assert _made_by(proj, "m_brk0000000000001") is None
    assert "damaged" in people.refused(proj)[-1]["why"]


def _ask_phone(run, new_ticket, rel):
    tid = new_ticket()
    run("ask", tid, "Which day?", "--option", "Tue", "--option", "Thu", "--phone")
    return tid, next(m["id"] for m in reversed(rel.sent) if m.get("type") == "question")


def _answer(rel, run, mid, frm, tid, qmid, word="Tue", by="human:pr_aaaaaaaaaa"):
    body = {"question_id": "q1", "answer": word, "answered_by": by}
    rel.inbox.append(msg(mid, "answer", body, frm=frm, ticket=tid, reply_to=qmid))
    return run("relay", "inbox")[1]


def test_answer_needs_decide_and_records_the_person(proj, run, rel, team, new_ticket):
    tid, qmid = _ask_phone(run, new_ticket, rel)
    _answer(rel, run, "m_ans0000000000001", LEA, tid, qmid)  # Lea may only write
    q = tickets.load(proj, tid)["questions"][0]
    assert q["answer"] is None  # refused before anything was written: the question stays open
    assert "Lea may not decide" in people.refused(proj)[-1]["why"]
    # Max may decide; the answer's own answered_by (someone else) is ignored: the phone's person counts
    _answer(rel, run, "m_ans0000000000002", MAX, tid, qmid, by="human:" + team["lea"])
    q = tickets.load(proj, tid)["questions"][0]
    assert (q["answer"], q["answered_by"], q["via"]) == ("Tue", "human:" + team["max"], "phone")


def test_allow_and_merge_answers_also_need_start_work(proj, team, monkeypatch):
    asked = {"ticket": "t_x", "question_id": "q1"}
    allow_q = {"questions": [{"id": "q1", "kind": "relay:allow"}]}
    monkeypatch.setattr(tickets, "load", lambda root, tid: allow_q)
    assert relay._phone_action(proj, asked) == "allow"
    monkeypatch.setattr(tickets, "load", lambda root, tid: {"questions": [{"id": "q1", "kind": "card"}]})
    monkeypatch.setattr(relay.review, "merge_url", lambda q: "https://github.com/acme/app/pull/1")
    assert relay._phone_action(proj, asked) == "merge"
    with pytest.raises(people.PhoneRefused, match="Max may not decide and start work"):
        people.who_sent(proj, MAX, "merge")
    people.set_rights(proj, "Max", ["write", "decide", "start"])
    assert people.who_sent(proj, MAX, "allow") == (team["max"], MAX)


def test_mobile_off_needs_decide(proj, team, monkeypatch):
    calls = []
    monkeypatch.setattr(relay, "_mobile_off_ok", lambda root, m: True)
    from orch import mobile_mode

    monkeypatch.setattr(mobile_mode, "turn_off", lambda *a, **k: calls.append(k))
    note = relay._handle_mobile_off(proj, {"id": "m_mob0000000000001", "from": LEA})
    assert not calls and "ignored" in note
    relay._handle_mobile_off(proj, {"id": "m_mob0000000000002", "from": MAX})
    assert len(calls) == 1


def test_queued_phone_text_starts_a_helper_only_with_start_work(proj, team, new_ticket, monkeypatch):
    tid = new_ticket()
    monkeypatch.setattr(tickets, "now", lambda: "2099-01-01T00:00:00Z")  # queued after the phone was tied
    runs.pending_add(proj, tid, "agent:relay from " + LEA, "message", "hello", "phone", phone=LEA)
    assert runs.human_waiting(proj, tid) == []  # Lea may not start work: kept, but nothing starts it
    people.set_rights(proj, "Lea", ["write", "start"])
    assert [i["phone"] for i in runs.human_waiting(proj, tid)] == [LEA]  # checked when it would start
    people.cut(proj, LEA)
    assert runs.human_waiting(proj, tid) == []  # a cut phone's queued work never starts


def test_phone_ticket_run_waits_for_start_work(proj, run, rel, team):
    _text(rel, run, "m_tik0000000000001", LEA)
    tid = _made_by(proj, "m_tik0000000000001")
    ok, why = people.ticket_may_start(proj, tid)
    assert not ok and "may not start work" in why
    code, out, _ = run("people", "may-start", tid, "--json")
    assert code == 0 and json.loads(out)["ok"] is False
    people.set_rights(proj, "Lea", ["write", "start"])
    assert people.ticket_may_start(proj, tid) == (True, None)


def test_allow_answer_is_checked_again_when_applied(proj, team):
    assert people.person_may(proj, "human:" + team["max"], "decide")
    assert not people.person_may(proj, "human:" + team["max"], "decide", "start")
    people.remove(proj, "Max")
    assert not people.person_may(proj, "human:" + team["max"], "decide")
    assert people.person_may(proj, "human:lume", "decide", "start")  # not a person id: as before


def test_tie_and_cut_from_cli_and_helpers_refused(proj, run, team, monkeypatch):
    assert run("people", "tie", NEW, "Max")[0] == 0
    assert people.who_sent(proj, NEW, "text") == (team["max"], NEW)
    assert run("people", "cut", NEW)[0] == 0
    with pytest.raises(people.PhoneRefused):
        people.who_sent(proj, NEW, "text")
    code, out, err = run("people", "cut", NEW)
    assert code == 2 and "already" in out + err
    monkeypatch.setenv("ORCH_AGENT", "claude")
    with pytest.raises(people.Refused, match="owner at this computer"):
        people.tie(proj, NEW, "Lea")


def test_tying_again_does_not_revive_queued_work_of_a_cut_phone(proj, team, new_ticket, monkeypatch):
    people.set_rights(proj, "Lea", ["write", "start"])
    tid = new_ticket()
    runs.pending_add(proj, tid, "agent:relay from " + LEA, "message", "hello", "phone", phone=LEA)
    people.cut(proj, LEA)
    assert runs.human_waiting(proj, tid) == []
    people.tie(proj, LEA, "Lea")  # tied again (the phone was found)
    assert runs.human_waiting(proj, tid) == []  # what it queued before the new tie never starts
    monkeypatch.setattr(tickets, "now", lambda: "2099-01-01T00:00:00Z")  # a later message
    runs.pending_add(proj, tid, "agent:relay from " + LEA, "message", "again", "phone", phone=LEA)
    assert [i["text"] for i in runs.human_waiting(proj, tid)] == ["again"]
