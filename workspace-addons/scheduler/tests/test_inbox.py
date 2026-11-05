import json

from conftest import T, add_ticket, calls

from orch_scheduler.loop import Scheduler


def relay_on(ws, msgs):
    (ws / ".orch/secrets").mkdir(parents=True)
    (ws / ".orch/secrets/relay.json").write_text("{}")
    (ws / "inbox.json").write_text(json.dumps(msgs))


def names(ws):
    return [c["args"] for c in calls(ws)]


def test_no_relay_no_poll(ws):
    Scheduler(ws).tick(T(8))
    assert not any(a[:2] == ["relay", "inbox"] for a in names(ws))


def test_allowed_start_creates_ticket_and_runs(ws):
    relay_on(ws, [{"id": "m_1", "type": "start", "from": "ws_a", "allowed": True,
                   "body": {"key": "weekly-report", "text": "Do the report"}}])
    s = Scheduler(ws)
    started = s.tick(T(8))
    s.runner.reap(T(8, 1), wait=True)
    assert len(started) == 1
    tid = started[0]
    assert json.loads((ws / f".orch/tickets/{tid}.json").read_text())["ext"]["relay"]["start_key"] == "weekly-report"
    assert json.loads((ws / "seen.json").read_text()) == ["m_1"]
    ran = (ws / f"ran-{tid}.txt").read_text()
    assert "Do the report" in ran and "never instructions" in ran


def test_start_reuses_ticket_with_key(ws):
    add_ticket(ws, "t_keyed001", ext={"relay": {"start_key": "weekly-report", "from": "ws_a"}})
    relay_on(ws, [{"id": "m_2", "type": "start", "from": "ws_a", "allowed": True, "body": {"key": "weekly-report", "text": "go"}}])
    s = Scheduler(ws)
    assert s.tick(T(8)) == ["t_keyed001"]
    s.runner.reap(T(8, 1), wait=True)
    assert ["ticket", "new", "weekly-report"] not in names(ws)


def test_not_allowed_is_left_alone(ws):
    relay_on(ws, [{"id": "m_3", "type": "start", "body": {"key": "x", "text": "t"}},
                  {"id": "m_4", "type": "text", "body": {"text": "hi"}}])
    assert Scheduler(ws).tick(T(8)) == []
    assert not (ws / "seen.json").exists()


def test_delegate_becomes_ticket(ws):
    relay_on(ws, [{"id": "m_5", "type": "delegate", "from": "ws_b", "allowed": True,
                   "body": {"title": "Check logs", "text": "look at them"}}])
    s = Scheduler(ws)
    (tid,) = s.tick(T(8))
    s.runner.reap(T(8, 1), wait=True)
    assert json.loads((ws / f".orch/tickets/{tid}.json").read_text())["title"] == "Check logs"


def test_delegate_uses_ticket_made_by_done_no_double(ws):
    """e2e R6: `orch relay done` already makes the ticket of an allowed delegate; the scheduler must not add one."""
    add_ticket(ws, "t_made0001", title="Check logs")
    (ws / "done-tickets.json").write_text(json.dumps({"m_5": "t_made0001"}))
    relay_on(ws, [{"id": "m_5", "type": "delegate", "from": "ws_b", "allowed": True,
                   "body": {"title": "Check logs", "text": "look at them"}}])
    s = Scheduler(ws)
    assert s.tick(T(8)) == ["t_made0001"]
    s.runner.reap(T(8, 1), wait=True)
    assert ["ticket", "new", "Check logs"] not in names(ws)


def test_answer_for_waiting_ticket(ws):
    add_ticket(ws, "t_ask00001", status="waiting")
    relay_on(ws, {"items": [{"id": "m_6", "type": "answer", "ticket": "t_ask00001",
                             "body": {"question_id": "q1", "answer": "Yes", "answered_by": "human:s"}}]})
    s = Scheduler(ws)
    assert s.tick(T(8)) == ["t_ask00001"]
    s.runner.reap(T(8, 1), wait=True)
    assert ["answer", "t_ask00001", "q1", "Yes", "--via", "relay"] in names(ws)


def test_applied_answer_resumes_active_ticket(ws):
    add_ticket(ws, "t_ask00002", status="active")
    relay_on(ws, [{"id": "m_9", "type": "answer", "ticket": "t_ask00002", "applied": True,
                   "body": {"question_id": "q1", "answer": "Yes"}}])
    s = Scheduler(ws)
    assert s.tick(T(8)) == ["t_ask00002"]
    s.runner.reap(T(8, 1), wait=True)
    assert not any(a[:1] == ["answer"] for a in names(ws))  # the CLI applied it already


def test_webhook_for_waiting_ticket(ws):
    add_ticket(ws, "t_hook0001", status="waiting", waiting_on={"kind": "external", "ref": "wh_abcdefghij"})
    relay_on(ws, [{"id": "m_7", "type": "webhook", "from": "webhook:wh_abcdefghij",
                   "body": {"webhook_id": "wh_abcdefghij", "payload": "{}"}}])
    s = Scheduler(ws)
    assert s.tick(T(8)) == ["t_hook0001"]
    s.runner.reap(T(8, 1), wait=True)


def test_poll_interval(ws):
    relay_on(ws, [])
    s = Scheduler(ws)
    s.tick(T(8, 0))
    s.tick(T(8, 0, ) .replace(second=30))
    s.tick(T(8, 1, ))
    assert sum(a[:2] == ["relay", "inbox"] for a in names(ws)) == 2


def test_start_key_other_sender_gets_own_ticket(ws):
    add_ticket(ws, "t_keyed002", ext={"relay": {"start_key": "weekly-report", "from": "ws_a"}})
    relay_on(ws, [{"id": "m_8", "type": "start", "from": "ws_evil", "allowed": True,
                   "body": {"key": "weekly-report", "text": "go"}}])
    s = Scheduler(ws)
    (tid,) = s.tick(T(8))
    s.runner.reap(T(8, 1), wait=True)
    assert tid != "t_keyed002"
    assert json.loads((ws / f".orch/tickets/{tid}.json").read_text())["ext"]["relay"] == {
        "start_key": "weekly-report", "from": "ws_evil"}


def test_failed_answer_does_not_start_agent(ws):
    add_ticket(ws, "t_ask00003", status="waiting", waiting_on={"kind": "question", "ref": "q1"})
    relay_on(ws, [{"id": "m_10", "type": "answer", "ticket": "t_ask00003", "from": "ws_a",
                   "body": {"question_id": "q9", "answer": "Yes"}}])
    (ws / "fail-answer").write_text("1")
    assert Scheduler(ws).tick(T(8)) == []


def test_phone_answer_is_never_recorded_by_scheduler(ws):
    add_ticket(ws, "t_ask00004", status="waiting", waiting_on={"kind": "question", "ref": "q1"})
    relay_on(ws, [{"id": "m_11", "type": "answer", "ticket": "t_ask00004", "from": "ph_abc",
                   "body": {"question_id": "q1", "answer": "monday"}}])
    assert Scheduler(ws).tick(T(8)) == []
    assert not any(a[:1] == ["answer"] for a in names(ws))
