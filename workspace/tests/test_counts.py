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
    assert {counts.task_word(c) for c in ({"done": True}, {"state": "doing"}, {})} == {"Done", "Working", "To do"}


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
