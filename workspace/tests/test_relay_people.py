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


def test_phone_ticket_run_waits_for_start_work(proj, run, rel, team, monkeypatch):
    monkeypatch.setattr(tickets, "now", lambda: "2099-01-01T00:00:00Z")  # made after the phone was tied
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


# ---- outside review (Codex) of the enforcement: each gap it found, closed


def test_every_start_checks_the_tick_at_the_moment_of_starting(proj, run, rel, team, new_ticket):
    """runs.start is the one place every start goes through: the helper resuming after Max's answer, a start
    that waited for a slot (by orch itself) for a ticket a phone text made."""
    tid = new_ticket()
    with pytest.raises(people.Refused, match="Max may not start work"):
        runs.start(proj, tid, "human:" + team["max"])
    _text(rel, run, "m_slt0000000000001", LEA)
    phone_tid = _made_by(proj, "m_slt0000000000001")
    assert people.start_allowed(proj, phone_tid, "agent:automation")[0] is False
    assert people.start_allowed(proj, phone_tid, "human:lume") == (True, None)  # the person at this computer
    with pytest.raises(people.Refused, match="may not start work"):
        runs.start(proj, phone_tid, "agent:automation")


def test_a_persons_queued_answer_starts_nothing_without_start_work(proj, team, new_ticket):
    tid = new_ticket()
    runs.pending_add(proj, tid, "human:" + team["max"], "answer", "Tue", "phone")
    assert runs.human_waiting(proj, tid) == []
    people.set_rights(proj, "Max", ["write", "decide", "start"])
    assert len(runs.human_waiting(proj, tid)) == 1


def test_queued_work_of_a_phone_no_longer_paired_never_starts(proj, run, rel, team, new_ticket, monkeypatch):
    people.set_rights(proj, "Lea", ["write", "start"])
    tid = new_ticket()
    monkeypatch.setattr(tickets, "now", lambda: "2099-01-01T00:00:00Z")
    runs.pending_add(proj, tid, "agent:relay from " + LEA, "message", "hello", "phone", phone=LEA)
    assert len(runs.human_waiting(proj, tid)) == 1
    rel.snapshot["workspaces"]["phones"] = [p for p in rel.snapshot["workspaces"]["phones"] if p["id"] != LEA]
    run("relay", "refresh")
    assert runs.human_waiting(proj, tid) == []


def test_tying_a_phone_again_never_revives_tickets_it_made_before(proj, run, rel, team):
    _text(rel, run, "m_old0000000000001", LEA)
    tid = _made_by(proj, "m_old0000000000001")
    people.cut(proj, LEA)
    people.set_rights(proj, "Max", ["write", "decide", "start"])
    people.tie(proj, LEA, "Max")  # the phone now belongs to someone who may start work
    ok, why = people.ticket_may_start(proj, tid)
    assert not ok and "before it was tied again" in why


def test_an_allow_answered_by_a_phone_is_void_once_that_phone_is_cut(proj, team):
    people.set_rights(proj, "Max", ["write", "decide", "start"])
    by = "human:" + team["max"]
    people.remember_answer(proj, "t_aaaaaa", "q1", MAX)
    assert people.answer_still_ok(proj, "t_aaaaaa", "q1", by, "decide", "start")
    people.cut(proj, MAX)
    assert not people.answer_still_ok(proj, "t_aaaaaa", "q1", by, "decide", "start")


def test_a_refused_answer_sends_the_question_to_the_phones_again(proj, run, rel, team, new_ticket):
    """The real relay keeps only the first answer to a question message: after a refused one, the open
    question goes out again so a phone that may decide can still answer."""
    tid, qmid = _ask_phone(run, new_ticket, rel)
    before = sum(1 for m in rel.sent if m.get("type") == "question")
    _answer(rel, run, "m_ans0000000000009", LEA, tid, qmid)
    assert sum(1 for m in rel.sent if m.get("type") == "question") == before + 1
    new_qmid = next(m["id"] for m in reversed(rel.sent) if m.get("type") == "question")
    _answer(rel, run, "m_ans0000000000010", MAX, tid, new_qmid)
    assert tickets.load(proj, tid)["questions"][0]["answered_by"] == "human:" + team["max"]


# ---- second outside look (Codex) at the fixes


def test_a_slot_start_after_a_phone_answer_keeps_that_phone(proj, team, new_ticket, monkeypatch):
    from orch import runs_live

    people.set_rights(proj, "Max", ["write", "decide", "start"])
    tid = new_ticket()
    monkeypatch.setattr(tickets, "now", lambda: "2099-01-01T00:00:00Z")
    with people.acting((team["max"], MAX)):
        runs_live._queue_for_slot(proj, tid, "human:" + team["max"], "start please")
    slot = next(i for i in runs.undelivered(proj, tid) if i.get("via") == "slots")
    assert slot["phone"] == MAX
    assert people.phone_may_start(proj, MAX, slot["at"])
    people.cut(proj, MAX)
    assert not people.phone_may_start(proj, MAX, slot["at"])  # start_waiting skips it


def test_answer_records_are_never_dropped_and_an_unknown_phone_answer_is_refused(proj, team):
    people.set_rights(proj, "Max", ["write", "decide", "start"])
    by = "human:" + team["max"]
    people.remember_answer(proj, "t_first", "q1", MAX)
    people.cut(proj, MAX)
    for i in range(210):
        people.remember_answer(proj, f"t_{i}", "q1", LEA)
    assert not people.answer_still_ok(proj, "t_first", "q1", by, "decide", "start", via="phone")
    assert not people.answer_still_ok(proj, "t_none", "q1", by, "decide", "start", via="phone")
    assert people.answer_still_ok(proj, "t_none", "q1", by, "decide", "start", via="dashboard")


def test_with_the_list_off_person_ids_are_not_checked(proj, team, new_ticket):
    tid = new_ticket()
    runs.pending_add(proj, tid, "human:" + team["max"], "answer", "Tue", "phone")
    people.path(proj).rename(people.path(proj).with_name("people.json.away"))
    assert len(runs.human_waiting(proj, tid)) == 1  # as before the list existed


def test_a_phone_answer_queued_for_a_helper_keeps_its_phone(proj, team, new_ticket, monkeypatch):
    people.set_rights(proj, "Max", ["write", "decide", "start"])
    tid = new_ticket()
    monkeypatch.setattr(tickets, "now", lambda: "2099-01-01T00:00:00Z")
    with people.acting((team["max"], MAX)):
        runs.pending_add(proj, tid, "human:" + team["max"], "answer", "Tue", "phone")
    assert [i["phone"] for i in runs.human_waiting(proj, tid)] == [MAX]
    people.cut(proj, MAX)
    assert runs.human_waiting(proj, tid) == []  # the cut phone's answer starts nothing


# ------------------------------------------------------------------ browsers (ORCH-1197)
# A browser signs in on the relay's own page with an invitation the admin made on the relay admin page.
# The relay gives it a device id like a phone's and says `kind: browser`; on the workspace it is tied, cut,
# checked and shown exactly like a phone, only named a browser.

BRO = "ph_bro00000001"


@pytest.fixture
def browser(proj, run, rel, team):
    """Max (write, decide) also has a browser, tied to him like his phone."""
    rel.snapshot["workspaces"]["phones"].append(
        {"id": BRO, "name": "Max laptop", "kind": "browser", "online": True, "last_seen": None}
    )
    run("relay", "refresh")
    people.tie(proj, BRO, "Max")
    return BRO


def test_a_browser_is_tied_and_named_a_browser(proj, run, team, browser):
    view = {p["id"]: p for p in people.view(proj)["phones"]}
    assert view[BRO]["kind"] == "browser" and view[BRO]["person"] == team["max"]
    assert view[MAX]["kind"] == "phone" and view[LEA]["kind"] == "phone"  # no kind (older relay): phone
    doc = people.load(proj)
    assert next(d for d in doc["devices"] if d["id"] == BRO)["kind"] == "browser"
    assert doc["log"][-1]["what"] == f"Tied browser {BRO} to Max"
    out = run("people", "list")[1]
    assert f"browser Max laptop  [{BRO}]  Max" in out and f"phone Max phone  [{MAX}]  Max" in out


def test_a_browser_text_and_answer_show_its_person(proj, run, rel, team, browser, new_ticket):
    _text(rel, run, "m_bro0000000000001", BRO)
    tid = _made_by(proj, "m_bro0000000000001")
    assert tid is not None
    lines = [h for h in tickets.load(proj, tid)["history"] if h.get("via") == "phone"]
    assert lines and all(h["person"] == team["max"] and h["device"] == BRO for h in lines)
    assert people.names(proj)[team["max"]] == "Max"  # the history view shows the line's person by this name
    qtid, qmid = _ask_phone(run, new_ticket, rel)
    _answer(rel, run, "m_bro0000000000002", BRO, qtid, qmid, by="human:" + team["lea"])
    q = tickets.load(proj, qtid)["questions"][0]
    assert (q["answer"], q["answered_by"]) == ("Tue", "human:" + team["max"])


def test_a_browser_is_cut_alone_and_with_its_person(proj, run, rel, team, browser):
    people.cut(proj, BRO)
    assert people.load(proj)["log"][-1]["what"] == f"Cut browser {BRO}"
    _text(rel, run, "m_bro0000000000003", BRO)
    assert _made_by(proj, "m_bro0000000000003") is None
    assert "cut off" in people.refused(proj)[-1]["why"]
    _text(rel, run, "m_bro0000000000004", MAX)  # Max's phone still works
    assert _made_by(proj, "m_bro0000000000004") is not None
    people.tie(proj, BRO, "Max")  # tied again, then Max is removed: phone and browser are both cut
    people.remove(proj, "Max")
    cut = {d["id"]: d["cut_at"] for d in people.load(proj)["devices"]}
    assert cut[BRO] and cut[MAX]
    for mid, frm in (("m_bro0000000000005", BRO), ("m_bro0000000000006", MAX)):
        _text(rel, run, mid, frm)
        assert _made_by(proj, mid) is None


# ---- ORCH-1164: the terminal names the people too (the dashboard already did)


def test_ticket_show_names_the_phone_writer_and_the_answering_person(proj, run, rel, team, new_ticket):
    _text(rel, run, "m_shw0000000000001", LEA)
    tid = _made_by(proj, "m_shw0000000000001")
    run("ask", tid, "Book it?", "--option", "yes", "--option", "no", "--phone")
    qmid = next(m["id"] for m in reversed(rel.sent) if m.get("type") == "question")
    _answer(rel, run, "m_shw0000000000002", MAX, tid, qmid, word="yes")
    out = run("ticket", "show", tid)[1]
    assert "Answered q1: Book it? - yes (Max)" in out
    assert "human:pr_" not in out
    people.rename(proj, "Lea", "Lea B")
    lea_line = next(h for h in tickets.load(proj, tid)["history"] if h.get("person") == team["lea"])
    assert people.line_who(people.names(proj), lea_line["by"], lea_line["person"]) == "Lea B"
    people.remove(proj, "Max")
    assert "(Max (removed))" in run("ticket", "show", tid)[1]


def test_line_who_keeps_old_actors_and_works_with_the_list_off():
    names = {"pr_aaaaaaaaaa": "Lea"}
    assert people.line_who(names, "human:lume") == "human:lume"
    assert people.line_who(names, "agent:claude") == "agent:claude"
    assert people.line_who(names, "agent:relay from ph_x", "pr_aaaaaaaaaa") == "Lea"
    assert people.line_who(names, "human:pr_bbbbbbbbbb") == "Someone removed"
    assert people.line_who({}, "human:pr_bbbbbbbbbb") == "human:pr_bbbbbbbbbb"  # list off: as written


def test_the_ticket_a_phone_text_made_names_its_person_from_the_first_line(proj, run, rel, team):
    _text(rel, run, "m_fst0000000000001", LEA)
    tid = _made_by(proj, "m_fst0000000000001")
    relay_lines = [h for h in tickets.load(proj, tid)["history"] if h["by"] == "agent:relay from " + LEA]
    assert relay_lines and all(h.get("person") == team["lea"] and h.get("device") == LEA for h in relay_lines)
    # the line names Lea for showing only: whether the ticket may start is still the phone's own check
    people.cut(proj, LEA)
    assert people.ticket_may_start(proj, tid)[0] is False


def test_a_cut_phone_removed_on_the_relay_keeps_its_name_in_settings(proj, run, rel, team):
    people.cut(proj, LEA)
    rel.snapshot["workspaces"]["phones"] = [p for p in rel.snapshot["workspaces"]["phones"] if p["id"] != LEA]
    run("relay", "refresh")
    rows = {r["id"]: r for r in people.phones_view(proj, people.load(proj))}
    assert rows[LEA]["name"] == "Lea phone" and rows[LEA]["paired"] is False and rows[LEA]["cut"] is True
    assert rows[MAX]["name"] == "Max phone"
