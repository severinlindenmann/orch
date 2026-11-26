"""R8.6: core refuses an automatic start over the daily cap per ticket. The loop must take that refusal as a failed
start: one plain question, no retry on every pass, and no second helper."""

import json

from conftest import T, add_ticket, runs_started

from orch_automation import orchcli
from orch_automation.loop import Scheduler

CAP_WORDS = "already ran 20 times on its own today"


def tk(ws, tid):
    return json.loads((ws / f".orch/tickets/{tid}.json").read_text())


def failure_questions(ws, tid):
    return [q for q in tk(ws, tid)["questions"] if q.get("kind") == "automation:failure"]


def test_run_start_returns_the_cap_words_as_a_failure(ws):
    add_ticket(ws, "t_cap00001")
    (ws / "capped-t_cap00001").write_text("")
    res = orchcli.run_start(ws, "t_cap00001")
    assert res["result"] == "failed"
    assert CAP_WORDS in res["reason"] and "start it yourself" in res["reason"]


def test_capped_wake_asks_once_and_keeps_the_wait(ws):
    add_ticket(
        ws, "t_cap00002", status="waiting", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"}
    )
    (ws / "capped-t_cap00002").write_text("")
    s = Scheduler(ws)
    assert s.tick(T(8)) == []
    assert s.tick(T(8, 1)) == []
    qs = failure_questions(ws, "t_cap00002")
    assert len(qs) == 1 and CAP_WORDS in qs[0]["text"]
    assert tk(ws, "t_cap00002")["waiting_on"] is not None
    assert runs_started(ws).count("t_cap00002") == 1


def test_capped_repeat_is_not_retried_every_pass(ws):
    add_ticket(ws, "t_cap00003", ext={"automation": {"recurring": True, "cron": "* * * * *"}})
    (ws / "capped-t_cap00003").write_text("")
    s = Scheduler(ws)
    assert s.tick(T(8)) == []
    s.tick(T(8, 0).replace(second=50))
    assert runs_started(ws).count("t_cap00003") == 1
    assert len(failure_questions(ws, "t_cap00003")) == 1


def test_try_again_starts_once_the_cap_is_gone(ws):
    add_ticket(
        ws, "t_cap00004", status="waiting", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"}
    )
    (ws / "capped-t_cap00004").write_text("")
    s = Scheduler(ws)
    s.tick(T(8))
    t = tk(ws, "t_cap00004")
    t["questions"][0]["answer"] = "Try again"
    t["questions"][0]["answered_by"] = "human:s"
    (ws / ".orch/tickets/t_cap00004.json").write_text(json.dumps(t))
    (ws / "capped-t_cap00004").unlink()
    assert s.tick(T(8, 1)) == ["t_cap00004"]
