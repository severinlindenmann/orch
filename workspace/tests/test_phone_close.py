"""Phone cards of questions settled in orch close by themselves (relay-api.md "Question taken back",
"Settled in orch"): an answer given in orch, a review round that ended in orch, a dropped or done ticket.
One taken-back text per question with a fixed reason, never the answer; cards that went stale before this
existed close too. A webhook subscriber sees the same text as a `closed` event (the relay makes it;
relay/tests/subs.rs)."""

import json

import pytest
from test_phone_proposal import PHONE, conn  # noqa: F401  (the fixture)
from test_relay_client import msg

from orch import phone_view, relay, tickets


def _new_ticket(run, title="Invoice export"):
    code, out, _ = run("ticket", "new", title, "--json", "--by", "agent:x")
    assert code == 0
    return json.loads(out)["id"]


def _ask(run, tid):
    code, out, err = run(
        "ask",
        tid,
        "Which format?",
        "--option",
        "CSV",
        "--option",
        "XLSX",
        "--phone",
        "--json",
        "--by",
        "agent:x",
    )
    assert code == 0, out + err
    return json.loads(out)


def _closed(rel):
    return [m for m in rel.sent if "taken_back" in m["body"]]


def _question_mid(rel, tid, qid="q1"):
    return next(
        m["id"]
        for m in rel.sent
        if m["type"] == "question" and m.get("ticket") == tid and m["body"].get("question_id") == qid
    )


def _status(run, tid, status, by="human:me"):
    code, out, err = run("ticket", "status", tid, status, "--by", by)
    assert code == 0, out + err


def _only_fields(sent):
    """Exactly what leaves the machine for one close: the envelope and the fixed reason, no ticket text."""
    assert set(sent) <= {
        "schema",
        "id",
        "from",
        "to",
        "type",
        "reply_to",
        "created_at",
        "body",
        "ticket",
        "key",
    }
    assert set(sent["body"]) == {"text", "taken_back"} and set(sent["body"]["taken_back"]) == {"reason"}
    assert sent["to"] == "phones" and sent["type"] == "text"


def test_an_answer_given_in_orch_closes_the_phone_card_once(proj, run, conn):  # noqa: F811
    tid = _new_ticket(run)
    _ask(run, tid)
    assert relay.sync_closed(proj) == []  # still open: nothing to close
    code, out, err = run("answer", tid, "q1", "XLSX", "--json", "--by", "human:me")
    assert code == 0, out + err
    assert len(relay.sync_closed(proj)) == 1
    got = _closed(conn)
    assert len(got) == 1
    _only_fields(got[0])
    assert got[0]["body"] == {
        "text": "Taken back: Answered in orch",
        "taken_back": {"reason": "Answered in orch"},
    }
    assert got[0]["reply_to"] == _question_mid(conn, tid) and got[0]["ticket"] == tid
    assert "XLSX" not in json.dumps(got[0])  # never the answer
    assert relay.sync_closed(proj) == []  # once only
    assert len(_closed(conn)) == 1


def test_the_inbox_pull_closes_it_without_a_direct_call(proj, run, conn):  # noqa: F811
    tid = _new_ticket(run)
    _ask(run, tid)
    assert run("answer", tid, "q1", "CSV", "--by", "human:me")[0] == 0
    assert run("relay", "inbox")[0] == 0  # every pull syncs the phone views, this sweep included
    assert [m["body"]["taken_back"]["reason"] for m in _closed(conn)] == ["Answered in orch"]


def test_a_phone_answer_sends_nothing_back(proj, run, conn):  # noqa: F811
    tid = _new_ticket(run)
    _ask(run, tid)
    conn.inbox.append(
        msg(
            "m_ans0000000000001",
            "answer",
            {"question_id": "q1", "answer": "CSV", "answered_by": "human:iPhone"},
            frm=PHONE,
            ticket=tid,
            reply_to=_question_mid(conn, tid),
        )
    )
    assert run("relay", "inbox")[0] == 0
    assert tickets.load(proj, tid)["questions"][0]["via"] == "phone"
    relay.sync_closed(proj)
    assert _closed(conn) == []


def test_an_undone_answer_keeps_the_card_open(proj, run, conn):  # noqa: F811
    """The dashboard's Undo stops the answer before it is saved: the question stays open, so does the card."""
    tid = _new_ticket(run)
    _ask(run, tid)
    relay.sync_closed(proj)
    assert tickets.load(proj, tid)["questions"][0]["answer"] is None
    assert _closed(conn) == []


@pytest.mark.parametrize(("status", "reason"), [("dropped", "Ticket dropped"), ("done", "Ticket done")])
def test_a_dropped_or_done_ticket_closes_its_open_card(proj, run, conn, status, reason):  # noqa: F811
    tid = _new_ticket(run)
    _ask(run, tid)
    _status(run, tid, status)
    relay.sync_closed(proj)
    got = _closed(conn)
    assert [m["body"]["taken_back"]["reason"] for m in got] == [reason]
    _only_fields(got[0])


def test_a_removed_ticket_closes_its_card(proj, run, conn):  # noqa: F811
    tid = _new_ticket(run)
    _ask(run, tid)
    tickets.ticket_path(proj, tid).unlink()
    relay.sync_closed(proj)
    assert [m["body"]["taken_back"]["reason"] for m in _closed(conn)] == ["Ticket removed"]


def test_a_ticket_leaving_review_closes_its_review_round(proj, run, conn):  # noqa: F811
    tid = _new_ticket(run)
    _status(run, tid, "review")
    assert phone_view.sync_reviews(proj) == [tid]
    round_mid = next(m["id"] for m in conn.sent if m["type"] == "question" and m["body"].get("review"))
    relay.sync_closed(proj)
    assert _closed(conn) == []  # in Review: the round is open
    _status(run, tid, "done")  # accepted in orch
    phone_view.sync_reviews(proj)
    relay.sync_closed(proj)
    got = _closed(conn)
    assert len(got) == 1
    _only_fields(got[0])
    assert got[0]["reply_to"] == round_mid
    assert got[0]["body"]["taken_back"]["reason"] == "Review finished in orch"


def test_a_new_review_round_closes_the_old_one_only(proj, run, conn):  # noqa: F811
    tid = _new_ticket(run)
    _status(run, tid, "review")
    phone_view.sync_reviews(proj)
    _status(run, tid, "active")  # Ask for changes
    phone_view.sync_reviews(proj)
    _status(run, tid, "review")  # round 2
    phone_view.sync_reviews(proj)
    rounds = [m["id"] for m in conn.sent if m["type"] == "question" and m["body"].get("review")]
    assert len(rounds) == 2
    relay.sync_closed(proj)
    assert [m["reply_to"] for m in _closed(conn)] == [rounds[0]]


def test_cards_stale_from_before_clear_over_a_few_pulls(proj, run, conn):  # noqa: F811
    """Questions answered in orch before this existed: the sweep finds them all, CLOSE_MAX a pull."""
    n = relay.CLOSE_MAX + 5
    for i in range(n):
        tid = _new_ticket(run, f"Old question {i}")
        _ask(run, tid)
        assert run("answer", tid, "q1", "CSV", "--by", "human:me")[0] == 0
    assert len(relay.sync_closed(proj)) == relay.CLOSE_MAX
    assert len(relay.sync_closed(proj)) == 5
    assert relay.sync_closed(proj) == []
    assert len({m["reply_to"] for m in _closed(conn)}) == n


def test_an_older_relay_that_refuses_a_review_round_is_tried_again_later(proj, run, conn, monkeypatch):  # noqa: F811
    tid = _new_ticket(run)
    _status(run, tid, "review")
    phone_view.sync_reviews(proj)
    _status(run, tid, "done")
    phone_view.sync_reviews(proj)
    real = relay._post_message
    tries = []

    def old_relay(root, raw):
        if "taken_back" in json.loads(raw)["body"]:
            tries.append(1)
            e = relay.Refused("Only an ordinary question can be taken back.")
            e.status = 403
            raise e
        return real(root, raw)

    monkeypatch.setattr(relay, "_post_message", old_relay)
    assert relay.sync_closed(proj, now=1000.0) == []
    assert relay.sync_closed(proj, now=1000.0 + 60) == []  # not every pull
    assert len(tries) == 1
    monkeypatch.setattr(relay, "_post_message", real)
    assert len(relay.sync_closed(proj, now=1000.0 + relay.CLOSE_RETRY + 1)) == 1
    assert [m["body"]["taken_back"]["reason"] for m in _closed(conn)] == ["Review finished in orch"]


def test_any_other_refusal_is_final(proj, run, conn, monkeypatch):  # noqa: F811
    tid = _new_ticket(run)
    _ask(run, tid)
    assert run("answer", tid, "q1", "CSV", "--by", "human:me")[0] == 0
    tries = []

    def answered_first(root, raw):
        tries.append(1)
        e = relay.Refused("This question was already answered.")
        e.status = 409
        raise e

    monkeypatch.setattr(relay, "_post_message", answered_first)
    relay.sync_closed(proj)
    relay.sync_closed(proj)
    assert len(tries) == 1


def test_relay_off_sends_nothing(proj, run):
    tid = _new_ticket(run)
    run("ask", tid, "Which format?", "--option", "CSV", "--option", "XLSX", "--by", "agent:x")
    assert relay.sync_closed(proj) == []
