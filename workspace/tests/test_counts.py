"""ORCH-476: the one source for every count and step (orch/counts.py, `orch counts`)."""

import json

from orch import counts, history, review, tickets


def _t(tid, status="active", checklist=(), questions=(), **kw):
    return {"id": tid, "status": status, "checklist": list(checklist), "questions": list(questions), **kw}


def test_step_counts_every_task_a_wont_do_one_too():
    # the report's DEM-1: Home "Step 4 of 4", Focus "Step 3 of 3", layer "3 of 4 tasks finished"
    t = _t(
        "t_dem1aa",
        checklist=[
            {"id": "c1", "done": True},
            {"id": "c2", "wont_do": True},
            {"id": "c3", "done": True},
            {"id": "c4", "state": "doing"},
        ],
    )
    assert counts.step(t) == {"n": 4, "of": 4}
    p = counts.progress(t)
    assert (p["finished"], p["total"], p["done"], p["wont_do"], p["doing"], p["todo"]) == (3, 4, 2, 1, 1, 0)


def test_step_is_the_task_being_done_else_the_first_open_one():
    t = _t("t_aaaaaa", checklist=[{"id": "c1"}, {"id": "c2", "state": "doing"}, {"id": "c3"}])
    assert counts.step(t) == {"n": 2, "of": 3}
    t["checklist"][1]["state"] = None
    assert counts.step(t) == {"n": 1, "of": 3}
    assert counts.step(_t("t_bbbbbb", checklist=[{"id": "c1", "done": True}])) is None
    assert counts.step(_t("t_cccccc", status="done", checklist=[{"id": "c1"}])) is None


def test_the_word_for_a_task_not_done_is_wont_do_never_skipped():
    assert counts.task_word({"wont_do": True}) == "won't do"
    assert counts.task_word({"wont_do": True, "done": True}) == "won't do"
    assert {counts.task_word(c) for c in ({"done": True}, {"state": "doing"}, {})} == {
        "Done",
        "Working",
        "To do",
    }


def test_needs_you_is_one_per_open_question_plus_one_per_result():
    ts = [
        _t("t_q2aaaa", questions=[{"id": "q1", "answer": None}, {"id": "q2", "answer": None}]),
        _t("t_revaaa", status="review"),
        _t("t_answer", questions=[{"id": "q1", "answer": "A"}]),
        _t("t_doneaa", status="done", questions=[{"id": "q1", "answer": None}]),
        _t("t_genera", general=True, questions=[{"id": "q1", "answer": None}]),
    ]
    n = counts.needs_you(ts)
    assert (n["count"], n["questions"], n["results"], n["tickets"]) == (3, 2, 1, ["t_q2aaaa", "t_revaaa"])
    assert n["items"] == [
        {"ticket": "t_q2aaaa", "question": "q1"},
        {"ticket": "t_q2aaaa", "question": "q2"},
        {"ticket": "t_revaaa", "question": None},
    ]


def test_working_needs_a_live_process():
    # the report's DEM-3: "Working · 3 days" with no process behind it
    ts = [_t("t_dem3aa"), _t("t_liveaa"), _t("t_idleaa"), _t("t_stucka")]
    runs = {
        "t_dem3aa": {"running": False},
        "t_liveaa": {"running": True, "helper": {"state": "working"}},
        "t_idleaa": {"running": True, "helper": {"state": "idle"}},
        "t_stucka": {"running": True, "helper": {"state": "stuck"}},
    }
    s = counts.summary(ts, runs)
    assert s["working"] == 1 and s["running"] == 3
    assert s["tickets"]["t_dem3aa"]["helper"] is None
    assert s["helpers"]["stuck"] == 1 and s["tickets"]["t_stucka"]["stuck"] == "helper"
    assert "t_stucka" in s["stuck_tickets"]


def test_stuck_joins_the_ticket_rule_and_a_stuck_helper():
    old = _t("t_oldqqq", questions=[{"id": "q1", "answer": None, "asked_at": "2020-01-01T00:00:00Z"}])
    s = counts.summary([old, _t("t_review", status="review")])
    assert s["stuck"] == 1 and s["tickets"]["t_oldqqq"]["stuck"] == "question"


def test_needs_you_equals_the_review_cards(proj, run):
    """The Review page's cards (review.stack) and the needs number are the same items."""
    assert run("init")[0] == 0
    a = json.loads(run("ticket", "new", "Two questions", "--json")[1])["id"]
    b = json.loads(run("ticket", "new", "A result", "--json")[1])["id"]
    assert run("ask", a, "Which colour?", "--option", "red", "--option", "blue")[0] == 0
    assert run("ask", a, "Which size?", "--option", "S", "--option", "M")[0] == 0
    tickets.set_status(proj, b, "review", "agent:claude")
    shown = history.shown_json(proj, tickets.list_all(proj))
    n = counts.needs_you(shown)
    assert n["count"] == len(review.stack(proj)) == 3
    code, out, err = run("counts", "--json")
    assert code == 0, err
    c = json.loads(out)
    assert c["needs_you"] == n and c["working"] == 0
    code, out, _ = run("counts")
    assert "Needs you: 3 (2 questions, 1 result to check)" in out


def test_a_left_over_session_of_a_ticket_in_review_is_no_helper():
    # ORCH-407: its "Test results" row stands for it; Home lists no helper row, so the core counts none
    t = _t("t_revidl", status="review")
    s = counts.summary([t], {"t_revidl": {"running": True, "helper": {"state": "stuck"}}})
    assert s["running"] == 0 and s["stuck"] == 0 and s["tickets"]["t_revidl"]["helper"] is None
    w = counts.summary([t], {"t_revidl": {"running": True, "helper": {"state": "working"}}})
    assert w["working"] == 1


def test_a_failed_start_needs_you_once_and_is_no_result():
    """ORCH-1687: Home listed three "could not start" rows the number left out."""
    start = {"kind": "external", "ref": "Not logged in", "start": True}
    ts = [
        {"id": "t_a", "status": "waiting", "waiting_on": start},
        {"id": "t_b", "status": "review"},
        {"id": "t_c", "status": "waiting", "waiting_on": start, "questions": [{"id": "q1", "text": "?"}]},
        {"id": "t_d", "status": "waiting", "waiting_on": {"kind": "ticket", "ref": "t_b"}},
    ]
    n = counts.needs_you(ts)
    assert (n["count"], n["questions"], n["results"], n["failed"]) == (3, 1, 1, 1)
    assert {"ticket": "t_a", "question": None, "start": True} in n["items"]


def test_work_that_stopped_is_in_the_number_once():
    """#2385: Home counted stuck tickets and idle helpers; the core number (Focus, Insights, orch counts)
    did not."""
    ts = [
        _t("t_idle"),
        _t("t_unsure", status="review"),
        _t("t_check", status="review"),
        _t("t_done", status="done"),
    ]
    row = lambda kind, tid: {"id": f"core:{kind}:{tid}", "source": "core", "kind": kind, "ticket": tid}  # noqa: E731
    rows = [
        row("helper:idle", "t_idle"),
        row("helper:idle", "t_idle"),  # the same row twice counts once
        row("reviewer:unsure", "t_unsure"),
        row("helper:failing", "t_done"),  # a finished ticket never counts
        {"id": "core:wait:t_idle", "source": "core", "kind": "overdue-wait", "ticket": "t_idle"},
    ]
    n = counts.needs_you(ts, stopped=rows)
    assert (n["count"], n["stopped"], n["results"], n["questions"]) == (3, 2, 1, 0)
    assert {"ticket": "t_unsure", "question": None} not in n["items"]  # its unsure row is its Check card
    assert counts.summary(ts, stopped=rows)["needs_you"] == n
    assert counts.needs_you(ts)["count"] == 2  # without the rows: the two results


def test_orch_counts_counts_a_stuck_ticket(proj, run):
    """#2385: `orch counts` reads the same stopped rows as `orch needs` (stuck.rows)."""
    assert run("init")[0] == 0
    a = json.loads(run("ticket", "new", "Keeps failing", "--json")[1])["id"]
    assert run("check", "add", a, "Build it")[0] == 0
    for _ in range(2):
        assert run("check", "record", a, "c1", "--cmd", "make", "--exit", "1")[0] == 0
    c = json.loads(run("counts", "--json")[1])
    assert c["needs_you"]["count"] == 1 and c["needs_you"]["stopped"] == 1
    assert "1 stopped short" in run("counts")[1]
