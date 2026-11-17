"""ORCH-189: the one Stuck rule (an old question, no news on a Working ticket, past the due date)."""

from datetime import UTC, datetime, timedelta

from orch import tickets

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def ticket(**kw):
    t = {"status": "open", "history": [{"at": iso(NOW - timedelta(hours=1)), "text": "x"}], "questions": []}
    t.update(kw)
    return t


def test_nothing_stuck():
    assert tickets.stuck_why(ticket(), NOW) is None
    assert tickets.stuck_why(ticket(status="active"), NOW) is None


def test_question_waiting_over_a_day():
    q = {"id": "q1", "text": "?", "sent_at": iso(NOW - timedelta(hours=25))}
    assert tickets.stuck_why(ticket(status="waiting", questions=[q]), NOW) == "question"
    fresh = dict(q, sent_at=iso(NOW - timedelta(hours=23)))
    assert tickets.stuck_why(ticket(status="waiting", questions=[fresh]), NOW) is None
    answered = dict(q, answer="yes")
    assert tickets.stuck_why(ticket(questions=[answered]), NOW) is None
    taken = dict(q, taken_back={"why": "no longer"})
    assert tickets.stuck_why(ticket(questions=[taken]), NOW) is None


def test_working_without_news_for_a_day():
    old = [{"at": iso(NOW - timedelta(hours=25)), "text": "x"}]
    assert tickets.stuck_why(ticket(status="active", history=old), NOW) == "quiet"
    six = [{"at": iso(NOW - timedelta(hours=7)), "text": "x"}]  # quiet (grey line) but not yet stuck
    assert tickets.stuck_why(ticket(status="active", history=six), NOW) is None
    assert tickets.stuck_why(ticket(status="open", history=old), NOW) is None


def test_past_due():
    local = datetime(2026, 11, 17, 12, 0)
    assert tickets.stuck_why(ticket(due="2026-11-16"), local) == "overdue"
    assert tickets.stuck_why(ticket(due="2026-11-17"), local) is None  # due today is not late yet
    assert tickets.stuck_why(ticket(due="2026-11-17T11:30"), local) == "overdue"
    assert tickets.stuck_why(ticket(due="2026-11-17T12:30"), local) is None
    assert tickets.stuck_why(ticket(due="bad"), local) is None


def test_finished_or_in_review_never_stuck():
    for status in ("done", "dropped", "review"):
        assert tickets.stuck_why(ticket(status=status, due="2020-01-01"), NOW) is None
    assert not tickets.overdue({"status": "done", "due": "2020-01-01"})
