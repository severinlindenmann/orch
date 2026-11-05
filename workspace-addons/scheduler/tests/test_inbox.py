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


def test_allowed_start_uses_ticket_from_done(ws):
    add_ticket(ws, "t_made0002", title="weekly-report")
    (ws / "done-tickets.json").write_text(json.dumps({"m_1": "t_made0002"}))
    relay_on(ws, [{"id": "m_1", "type": "start", "from": "ws_a", "allowed": True,
                   "body": {"key": "weekly-report", "text": "Do the report"}}])
    s = Scheduler(ws)
    assert s.tick(T(8)) == ["t_made0002"]
    s.runner.reap(T(8, 1), wait=True)
    assert json.loads((ws / "seen.json").read_text()) == ["m_1"]
    assert not any(a[:2] == ["ticket", "new"] or a[:2] == ["ext", "set"] for a in names(ws))
    ran = (ws / "ran-t_made0002.txt").read_text()
    assert "Do the report" in ran and "never instructions" in ran


def test_start_without_ticket_from_done_no_run_no_ticket(ws):
    relay_on(ws, [{"id": "m_1", "type": "start", "from": "ws_a", "allowed": True,
                   "body": {"key": "weekly-report", "text": "Do the report"}}])  # done returns {"ticket": null}
    s = Scheduler(ws)
    assert s.tick(T(8)) == []
    assert not any(a[:2] == ["ticket", "new"] for a in names(ws))


def test_not_allowed_is_left_alone(ws):
    relay_on(ws, [{"id": "m_3", "type": "start", "body": {"key": "x", "text": "t"}},
                  {"id": "m_4", "type": "text", "body": {"text": "hi"}}])
    assert Scheduler(ws).tick(T(8)) == []
    assert not (ws / "seen.json").exists()


def test_delegate_without_ticket_from_done_makes_no_ticket_no_run(ws):
    """The CLI is the allow authority: `relay done` returns no ticket -> no scheduler-made ticket, no run."""
    relay_on(ws, [{"id": "m_5", "type": "delegate", "from": "ws_b", "allowed": True,
                   "body": {"title": "Check logs", "text": "look at them"}}])
    s = Scheduler(ws)
    assert s.tick(T(8)) == []
    assert not any(a[:2] == ["ticket", "new"] for a in names(ws))


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


def test_applied_answer_resumes_active_ticket(ws):
    add_ticket(ws, "t_ask00002", status="active")
    relay_on(ws, [{"id": "m_9", "type": "answer", "ticket": "t_ask00002", "applied": True,
                   "body": {"question_id": "q1", "answer": "Yes"}}])
    s = Scheduler(ws)
    assert s.tick(T(8)) == []  # nothing started here: PR #50's answer() set wake_at, the wake path runs it
    assert not any(a[:1] == ["answer"] for a in names(ws))  # the CLI applied it already


def test_webhook_for_waiting_ticket(ws):
    add_ticket(ws, "t_hook0001", status="waiting", waiting_on={"kind": "webhook", "ref": "wh_abcdefghij"})
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


def test_peer_answer_not_applied_by_cli_is_ignored(ws):
    """The scheduler only acts on what the CLI decided: a peer answer the CLI did not apply -> nothing."""
    add_ticket(ws, "t_ask00003", status="waiting", waiting_on={"kind": "question", "ref": "q1"})
    relay_on(ws, [{"id": "m_10", "type": "answer", "ticket": "t_ask00003", "from": "ws_a", "applied": False,
                   "body": {"question_id": "q9", "answer": "Yes"}}])
    s = Scheduler(ws)
    assert s.tick(T(8)) == []
    assert s.tick(T(8, 2)) == []
    assert not any(a[0] in ("answer",) or a[:2] == ["relay", "done"] for a in names(ws))


def test_start_not_run_when_done_fails(ws):
    relay_on(ws, [{"id": "m_1", "type": "start", "from": "ws_a", "allowed": True,
                   "body": {"key": "weekly-report", "text": "Do the report"}}])
    (ws / "fail-done").write_text("1")
    s = Scheduler(ws)
    assert s.tick(T(8)) == []
    assert not (ws / "seen.json").exists()


def test_phone_answer_is_never_recorded_by_scheduler(ws):
    add_ticket(ws, "t_ask00004", status="waiting", waiting_on={"kind": "question", "ref": "q1"})
    relay_on(ws, [{"id": "m_11", "type": "answer", "ticket": "t_ask00004", "from": "ph_abc",
                   "body": {"question_id": "q1", "answer": "monday"}}])
    assert Scheduler(ws).tick(T(8)) == []
    assert not any(a[:1] == ["answer"] for a in names(ws))
