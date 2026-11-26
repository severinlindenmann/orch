"""The ideas card (ORCH-2186, Focused review E): `orch ask --idea` asks the person to sort a short list one
by one (Keep, Later or No) on Review. Saving part of it is fine: what is left for later (or not sorted) comes
back as a smaller card on the same ticket that never holds up the ticket. The helper reads one plain line."""

import json

import pytest

from orch import attention, autoreview, review, reviewer, tickets
from orch.errors import Refused

ME = "human:owner"
IDEAS = ["Customer story, 3 posts", "Advent calendar", "Video with an installer", "Podcast guest spot"]


def _ask(run, tid, *extra, ideas=IDEAS):
    args = ["ask", tid, "Which content ideas should the helper work out?"]
    for i in ideas:
        args += ["--idea", i]
    return run(*args, *extra, "--by", "agent:helper")


def _q(proj, tid, qid="q1"):
    return next(q for q in tickets.load(proj, tid)["questions"] if q["id"] == qid)


def test_ask_keeps_the_ideas_in_the_digest_and_says_the_next_step(proj, run, new_ticket):
    tid = new_ticket("December ideas")
    code, out, err = _ask(run, tid, "--fact", "Three ideas need no budget.")
    assert code == 0, out + err
    assert "Keep, Later or No" in out and "--option" not in out
    q = _q(proj, tid)
    assert q["ideas"] == IDEAS and q["options"] == []
    plain = {k: v for k, v in q.items() if k != "ideas"}
    assert tickets.question_digest(q) != tickets.question_digest(plain)
    assert tickets.load(proj, tid)["status"] == "waiting"


@pytest.mark.parametrize(
    "extra, ideas, says",
    [
        (["--option", "A", "--option", "B"], IDEAS, "plain question only"),
        ([], ["Only one"], "2 to 12"),
        ([], [f"idea {i}" for i in range(13)], "2 to 12"),
        ([], ["Same idea", "same  IDEA"], "Each --idea once"),
        ([], ["x" * 201, "short"], "at most 200"),
    ],
)
def test_ask_refuses_a_bad_list(proj, run, new_ticket, extra, ideas, says):
    tid = new_ticket("Ideas")
    code, out, err = _ask(run, tid, *extra, ideas=ideas)
    assert code == 2 and says in out + err
    assert tickets.load(proj, tid)["questions"] == []


def test_ideas_are_secret_scanned(proj, run, new_ticket):
    tid = new_ticket("Ideas")
    code, out, err = _ask(run, tid, ideas=["Post the key ghp_" + "a" * 36, "Advent calendar"])
    assert code == 2
    assert tickets.load(proj, tid)["questions"] == []


def test_review_list_carries_them_in_take_your_time(proj, run, new_ticket):
    tid = new_ticket("Ideas")
    assert _ask(run, tid)[0] == 0
    item = next(c for c in review.stack(proj) if c["ticket"] == tid)
    assert item["ideas"] == IDEAS
    assert item["card_kind"]["kind"] == "document"  # a page that cannot sort them shows the list
    assert item["card"]["preview"] == {"type": "doc", "steps": IDEAS}
    assert attention.group_of(item)["group"] == "time"


def test_save_part_keeps_some_and_leaves_the_rest_as_a_smaller_card(proj, run, new_ticket):
    tid = new_ticket("Ideas")
    assert _ask(run, tid, "--fact", "Three ideas need no budget.")[0] == 0
    digest = tickets.question_digest(_q(proj, tid))
    note = {"ideas": {"keep": [1, 2], "no": [4]}}  # 3 is not sorted: it stays for later
    out = review.decide(proj, tid, "q1", "ok", None, json.dumps(note), by=ME, via="cli", digest=digest)
    assert out["answer"] == (
        "Keep: Customer story, 3 posts; Advent calendar. No: Podcast guest spot. "
        "Later: Video with an installer."
    )
    assert out["decision"]["ideas"] == {
        "keep": IDEAS[:2],
        "no": [IDEAS[3]],
        "later": [IDEAS[2]],
    }
    t = tickets.load(proj, tid)
    left = _q(proj, tid, "q2")
    assert left["ideas"] == [IDEAS[2]] and left["left_from"] == "q1"
    assert left["text"] == _q(proj, tid)["text"] and left["facts"] == ["Three ideas need no budget."]
    assert left["asked_by"] == "agent:helper" and left["answer"] is None
    # the helper works on what was kept: the ticket no longer waits, and the leftover never holds it up
    assert t["status"] != "waiting" and t["waiting_on"] is None
    assert tickets._open_questions(t) == []
    assert any("1 idea left for later: q2" in h.get("text", "") for h in t["history"])
    assert [c["key"] for c in review.stack(proj) if c["ticket"] == tid] == ["q2"]


def test_everything_sorted_leaves_no_card(proj, run, new_ticket):
    tid = new_ticket("Ideas")
    assert _ask(run, tid, ideas=IDEAS[:2])[0] == 0
    review.decide(proj, tid, "q1", "ok", None, {"ideas": {"keep": [2], "no": [1]}}, by=ME, via="cli")
    assert len(tickets.load(proj, tid)["questions"]) == 1


def test_looks_good_without_sorting_keeps_every_idea(proj, run, new_ticket):
    tid = new_ticket("Ideas")
    assert _ask(run, tid, ideas=IDEAS[:2])[0] == 0
    out = review.decide(proj, tid, "q1", "ok", by=ME, via="cli")
    assert out["answer"] == f"Keep: {IDEAS[0]}; {IDEAS[1]}."
    assert len(tickets.load(proj, tid)["questions"]) == 1


@pytest.mark.parametrize(
    "ideas, says",
    [
        ({}, "Sort at least one idea"),
        ({"keep": [5]}, "from 1 to 4"),
        ({"keep": [1], "no": [1]}, "sorted twice"),
        ({"maybe": [1]}, "Sort ideas as"),
        ({"keep": "1"}, "list of idea numbers"),
        ({"keep": [True]}, "from 1 to 4"),
    ],
)
def test_bad_sorting_is_refused_and_saves_nothing(proj, run, new_ticket, ideas, says):
    tid = new_ticket("Ideas")
    assert _ask(run, tid)[0] == 0
    with pytest.raises(Refused, match=says):
        review.decide(proj, tid, "q1", "ok", None, {"ideas": ideas}, by=ME, via="cli")
    assert _q(proj, tid)["answer"] is None


def test_dont_do_and_send_back_work_as_on_any_question(proj, run, new_ticket):
    tid = new_ticket("Ideas")
    assert _ask(run, tid)[0] == 0
    out = review.decide(proj, tid, "q1", "no", by=ME, via="cli")
    assert out["answer"] == "Don't do" and len(tickets.load(proj, tid)["questions"]) == 1


def test_review_answer_cli_takes_the_sorting_in_the_note(proj, run, new_ticket):
    tid = new_ticket("Ideas")
    assert _ask(run, tid)[0] == 0
    note = json.dumps({"ideas": {"keep": [3], "later": [1]}, "words": {"text": ""}})
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--note", note, "--by", ME)
    assert code == 0, out + err
    assert _q(proj, tid)["answer"].startswith("Keep: Video with an installer. Later: ")
    assert _q(proj, tid, "q2")["ideas"] == [IDEAS[0], IDEAS[1], IDEAS[3]]


def test_never_answered_by_the_reviewer_or_away_mode(proj, run, new_ticket):
    tid = new_ticket("Ideas")
    assert _ask(run, tid)[0] == 0
    t, q = tickets.load(proj, tid), _q(proj, tid)
    assert reviewer.routine(proj, t, q, now=9e12)[0] is False
    assert autoreview.away_answerable(t, q)[0] is False
