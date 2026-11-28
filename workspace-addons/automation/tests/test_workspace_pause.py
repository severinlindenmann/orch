"""R8.6: `orch pause` stops every start of the automation loop, and nothing due is used up while paused, so
`orch resume` starts it on the next pass. One case per way the loop starts something."""

import json

import pytest
from conftest import T, add_ticket, calls, runs_started
from orch import brake
from test_inbox import _pickups, relay_on
from test_loop import new_reports, report_setting

from orch_automation import scripts
from orch_automation.loop import Scheduler


def _wake(ws):
    add_ticket(
        ws, "t_wake0001", status="waiting", waiting_on={"kind": "time", "until": "2026-11-04T07:00:00Z"}
    )
    return "t_wake0001"


def _repeat(ws):
    add_ticket(ws, "t_rep00001", ext={"automation": {"recurring": True, "cron": "0 7 * * *"}})
    return "t_rep00001"


def _script_repeat(ws):
    add_ticket(
        ws, "t_scr00001", ext={"automation": {"recurring": True, "cron": "0 7 * * *", "script": "watch"}}
    )
    return "t_scr00001"


def _group_repeat(ws):
    add_ticket(
        ws,
        "t_grp00001",
        ext={"automation": {"recurring": True, "cron": "0 7 * * *", "group": {"a": "0 7 * * *"}}},
    )
    return "t_grp00001"


def _phone_text(ws):
    add_ticket(ws, "t_phone001", created_at="2026-11-04T07:30:00Z", ext={"relay": {"origin": "phone"}})
    return "t_phone001"


def _queued_input(ws):
    add_ticket(ws, "t_queue001", status="ready")
    (ws / "ended-t_queue001").write_text("")
    (ws / "pending-t_queue001").write_text(json.dumps(["p_answer0001"]))
    return "t_queue001"


def _chat_text(ws):
    (ws / "chat-ticket").write_text("t_chat0001")
    (ws / "pending-t_chat0001").write_text(json.dumps(["p_phone00001"]))
    (ws / "ended-t_chat0001").write_text("")
    return "t_chat0001"


def _relay_start(ws):
    add_ticket(ws, "t_made0001")
    (ws / "done-tickets.json").write_text(json.dumps({"m_1": "t_made0001"}))
    msg = {
        "id": "m_1",
        "type": "start",
        "from": "ws_a",
        "allowed": True,
        "body": {"key": "k", "text": "Do it"},
    }
    relay_on(ws, [msg])
    return "t_made0001"


def _peer_pickup(ws):
    relay_on(ws, [])
    add_ticket(ws, "t_move0001")
    (ws / "ended-t_move0001").write_text("")
    _pickups(ws, [{"id": "m_2", "from": "ws_a", "ticket": "t_move0001", "general": False}])
    return "t_move0001"


def _problem_report(ws):
    report_setting(ws)
    new_reports(ws, ("t_rpt00001", True))
    return "t_rpt00001"


def _try_again(ws):
    q = {"id": "q1", "text": "x", "options": ["Try again", "Leave it"], "kind": "automation:failure"}
    add_ticket(ws, "t_again001", questions=[{**q, "answer": "Try again", "answered_by": "human:s"}])
    return "t_again001"


PATHS = [
    _wake, _repeat, _script_repeat, _group_repeat, _phone_text, _queued_input, _chat_text, _relay_start,
    _peer_pickup, _problem_report, _try_again,
]  # fmt: skip


@pytest.fixture
def launched(monkeypatch):
    """Script starts, recorded instead of spawned (the script itself is tested in test_scripts)."""
    out = []

    def launch(root, tid, name, member=False):
        out.append(tid)
        return "started", None

    monkeypatch.setattr(scripts, "launch", launch)
    return out


def _questions(ws):
    return [
        q for p in (ws / ".orch/tickets").glob("t_*.json") for q in json.loads(p.read_text())["questions"]
    ]


@pytest.mark.parametrize("setup", PATHS, ids=[p.__name__.strip("_") for p in PATHS])
def test_pause_holds_every_loop_start_and_resume_starts_it(ws, launched, setup):
    tid = setup(ws)
    questions = _questions(ws)
    brake.pause(ws, "human:t")
    s = Scheduler(ws)
    assert s.tick(T(8)) == [] and s.tick(T(8, 1)) == []
    assert runs_started(ws) == [] and launched == []
    assert not any(c["args"][0] in ("relay", "diag", "wait") for c in calls(ws)), "nothing due is used up"
    assert _questions(ws) == questions, "a pause is not a failure: no question"
    assert brake.resume(ws)
    assert Scheduler(ws).tick(T(8, 2)) == [tid]
    assert [*runs_started(ws), *launched] == [tid]


def test_a_pause_does_not_hold_the_health_checks(ws):
    """They are what lifts the system keeper's pause on a full disk (doctorpass)."""
    brake.pause(ws, "agent:system-keeper", "Disk almost full")
    Scheduler(ws).tick(T(8))
    assert any(c["args"][:2] == ["doctor", "soon"] for c in calls(ws))


# W-043 (owner, 28 Nov): "Cards that need no person, and questions whose cause is gone".
PAUSED_Q = "The helper could not start: Automation is paused in this workspace. Turn it back on with: orch resume."


def _failure(ws, tid, text, **kw):
    q = {"id": "q1", "text": text, "options": ["Try again", "Leave it"], "kind": "automation:failure"}
    return add_ticket(ws, tid, status="waiting", questions=[{**q, "answer": None}], **kw)


def test_w043_a_start_refused_by_the_pause_asks_nothing(ws):
    add_ticket(ws, "t_p0000001", status="ready")
    Scheduler(ws).fail("t_p0000001", "Automation is paused in this workspace. Turn it back on with: orch resume.")
    assert [c for c in calls(ws) if c["args"][:1] == ["ask"]] == []
    Scheduler(ws).fail("t_p0000001", "the agent stopped within 10 seconds without doing anything")
    assert [c["args"][2] for c in calls(ws) if c["args"][:1] == ["ask"]] == [
        "The helper could not start: the agent stopped within 10 seconds without doing anything."
    ]


def test_w043_a_question_whose_cause_was_the_pause_closes_when_automation_runs_again(ws):
    _failure(ws, "t_p0000002", PAUSED_Q)
    _failure(ws, "t_p0000003", "The helper could not start: No agent found.")
    brake.pause(ws, "human:s")
    assert Scheduler(ws).tick(T(8)) == []  # still paused: nothing is closed, nothing starts
    assert [c for c in calls(ws) if "--take-back" in c["args"]] == []
    brake.resume(ws)
    assert Scheduler(ws).tick(T(8, 1)) == ["t_p0000002"]
    back = [c["args"] for c in calls(ws) if "--take-back" in c["args"]]
    assert [(a[1], a[a.index("--take-back") + 1]) for a in back] == [("t_p0000002", "q1")]
    assert runs_started(ws) == ["t_p0000002"]  # the start the pause held back, once
    import json as _json

    read = lambda tid: _json.loads((ws / ".orch" / "tickets" / f"{tid}.json").read_text())  # noqa: E731
    assert read("t_p0000002")["questions"][0]["answer"].startswith("Taken back: Automation runs again")
    assert read("t_p0000003")["questions"][0]["answer"] is None  # another cause: it still waits for the person
    assert Scheduler(ws).tick(T(8, 2)) == [] and runs_started(ws) == ["t_p0000002"]  # never twice
