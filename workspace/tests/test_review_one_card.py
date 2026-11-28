"""ORCH-1741 (owner 23 Nov: "39 things wait on you"): only what needs the person waits on them.

- A ticket in Review whose pull request is open and in the merge queue (or being repaired by a helper the
  queue woke) is not counted and has no Check card; it comes back once the queue gives up on it.
- One card per ticket: an open question or the "passed its checks but was not merged" row takes the place of
  the Check card; the Check card also says why the Reviewer was not sure.
"""

import json
import time

import pytest

from orch import counts, needs, review, reviewer, stuck, tickets

PR = "https://github.com/acme/app/pull/12"
pytestmark = pytest.mark.usefixtures("queue_on")


@pytest.fixture(autouse=True)
def _no_github(monkeypatch):
    monkeypatch.setenv("ORCH_NO_PULL_LOOK", "1")


def _in_review(proj, run, new_ticket, title="Fix the export", pr=PR, status="ready to merge"):
    tid = new_ticket(title)
    if pr:
        tickets.ref_add(proj, tid, pr, "agent:x")
        t = tickets.load(proj, tid)
        for r in t["refs"]:
            r.update(kind="github-pr", status=status)
        tickets.save(proj, t)
    assert run("ticket", "status", tid, "done", "--by", "agent:claude")[0] == 0
    assert tickets.load(proj, tid)["status"] == "review"
    return tid


def _queue(proj, state, url=PR):
    p = proj / ".orch" / "addons" / "pull-requests" / "queue.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"entries": [{"url": url, "state": state, "ticket": None}]}), encoding="utf-8")


def _green(proj, url=PR):
    now = time.time()
    stuck._write(proj, {"pulls": {url: {"state": "OPEN", "green": True, "head": "abc1234", "at": now}}})


def _cards(proj, tid):
    return [c for c in review.stack(proj) if c["ticket"] == tid]


def _needs(proj):
    return counts.now(proj)["needs_you"]


def test_queued_ticket_does_not_wait_on_the_person(proj, run, new_ticket):
    tid = _in_review(proj, run, new_ticket)
    assert tid in _needs(proj)["tickets"]  # not queued yet: the Check card
    _queue(proj, "waiting")
    n = _needs(proj)
    assert tid not in n["tickets"] and n["queue"] == [tid]
    assert _cards(proj, tid) == []
    _queue(proj, "running")
    assert _cards(proj, tid) == [] and _needs(proj)["queue"] == [tid]


def test_it_comes_back_when_the_queue_gives_up(proj, run, new_ticket):
    tid = _in_review(proj, run, new_ticket)
    _queue(proj, "out")
    n = _needs(proj)
    assert tid in n["tickets"] and n["queue"] == []
    assert [c["kind"] for c in _cards(proj, tid)] == ["check"]


def test_a_merged_pull_request_is_not_held(proj, run, new_ticket):
    tid = _in_review(proj, run, new_ticket, status="merged")
    _queue(proj, "waiting")  # an old line of the file: the link says merged
    assert tid in _needs(proj)["tickets"] and _needs(proj)["queue"] == []


def test_a_broken_queue_file_shows_the_card(proj, run, new_ticket):
    tid = _in_review(proj, run, new_ticket)
    p = proj / ".orch" / "addons" / "pull-requests" / "queue.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert [c["kind"] for c in _cards(proj, tid)] == ["check"]


def test_a_helper_repairing_the_pull_request_holds_it(proj, run, new_ticket, monkeypatch):
    tid = _in_review(proj, run, new_ticket)
    monkeypatch.setattr(stuck, "helper_busy", lambda root, t: t["id"] == tid)
    assert _needs(proj)["queue"] == [tid] and _cards(proj, tid) == []


def test_a_question_on_a_held_ticket_still_shows(proj, run, new_ticket):
    tid = _in_review(proj, run, new_ticket)
    _queue(proj, "waiting")
    tickets.ask(proj, tid, "Start the run?", ["Start", "Not now"], None, "agent:x", kind="factory:start")
    assert [c["kind"] for c in _cards(proj, tid)] != []
    assert all(c["kind"] != "check" for c in _cards(proj, tid))


def test_unmerged_row_takes_the_place_of_the_check_card(proj, run, new_ticket):
    tid = _in_review(proj, run, new_ticket)
    _green(proj)
    rows = [r for r in needs.core_rows(proj) if r["ticket"] == tid]
    assert [r["kind"] for r in rows] == ["helper:unmerged"]
    assert _cards(proj, tid) == []
    # #2385: the needs-you number counts the row itself, once, in place of the Check card
    items = [i for i in _needs(proj)["items"] if i["ticket"] == tid]
    assert [i.get("stopped") for i in items] == ["helper:unmerged"]


def test_no_unmerged_row_while_the_queue_holds_it(proj, run, new_ticket):
    tid = _in_review(proj, run, new_ticket)
    _green(proj)
    _queue(proj, "waiting")
    assert [r for r in needs.core_rows(proj) if r["ticket"] == tid] == []
    assert _cards(proj, tid) == []


def test_an_open_question_takes_the_place_of_the_check_card(proj, run, new_ticket):
    tid = _in_review(proj, run, new_ticket, pr=None)
    tickets.ask(proj, tid, "Start the run?", ["Start", "Not now"], None, "agent:x", kind="factory:start")
    assert [c["kind"] for c in _cards(proj, tid)] != ["check"]
    assert len(_cards(proj, tid)) == 1
    assert [i["question"] for i in _needs(proj)["items"] if i["ticket"] == tid] == ["q1"]


def test_reviewer_unsure_is_said_on_the_one_check_card(proj, run, new_ticket):
    tid = _in_review(proj, run, new_ticket, pr=None)
    mine = {}
    reviewer.remember_left(mine, "leave", "no pull request to check, so you look at it yourself.")
    reviewer._write_state(proj, {tid: mine})
    (card,) = _cards(proj, tid)
    assert card["card"]["why"] == (
        "Check this: the Reviewer was not sure: no pull request to check, so you look at it yourself."
    )
    # the row stays for Home (its one Check row, ORCH-1717) and the phone; never beside the card
    assert [r["kind"] for r in needs.core_rows(proj) if r["ticket"] == tid] == ["reviewer:unsure"]


def test_never_two_cards_for_one_ticket(proj, run, new_ticket):
    """Every mix of the reasons above: the Review page's cards plus the needs rows hold one per ticket
    (several open questions of one ticket stay separate decisions and are not mixed in here)."""
    a = _in_review(proj, run, new_ticket, "Queued")
    b = _in_review(proj, run, new_ticket, "Green", pr="https://github.com/acme/app/pull/13")
    c = _in_review(proj, run, new_ticket, "Unsure", pr=None)
    d = _in_review(proj, run, new_ticket, "Asked", pr=None)
    _queue(proj, "waiting")
    _green(proj, "https://github.com/acme/app/pull/13")
    mine = {}
    reviewer.remember_left(mine, "leave", "too big for a small fix.")
    reviewer._write_state(proj, {c: mine})
    tickets.ask(proj, d, "Start the run?", ["Start", "Not now"], None, "agent:x", kind="factory:start")
    # the "not sure" row is the Check card's own row on the pages (Home and Review fold it): left out here
    extra = [r for r in needs.core_rows(proj) if str(r["kind"]).startswith("helper:")]
    shown = [x["ticket"] for x in review.stack(proj)] + [r["ticket"] for r in extra]
    for tid in (b, c, d):
        assert shown.count(tid) == 1, (tid, shown)
    assert a not in shown


def test_a_question_and_a_green_pull_request_are_one_card(proj, run, new_ticket):
    tid = _in_review(proj, run, new_ticket)
    _green(proj)
    tickets.ask(proj, tid, "Start the run?", ["Start", "Not now"], None, "agent:x", kind="factory:start")
    extra = [r for r in needs.core_rows(proj) if r["ticket"] == tid and str(r["kind"]).startswith("helper:")]
    assert extra == []
    assert len(_cards(proj, tid)) == 1


def test_one_queued_pull_request_does_not_hide_another(proj, run, new_ticket):
    other = "https://github.com/acme/app/pull/13"
    tid = _in_review(proj, run, new_ticket)
    tickets.ref_add(proj, tid, other, "agent:x")
    t = tickets.load(proj, tid)
    for r in t["refs"]:
        r.update(kind="github-pr", status="ready to merge")
    tickets.save(proj, t)
    _queue(proj, "waiting")  # #12 in the queue, #13 not
    assert _needs(proj)["queue"] == []
    _green(proj, other)
    rows = [r for r in needs.core_rows(proj) if r["ticket"] == tid]
    assert [(r["kind"], r["pull"]["url"]) for r in rows] == [("helper:unmerged", other)]
    assert _cards(proj, tid) == []


# FX-04 (owner, 28 Nov): "Stuck" cards for pull requests that are simply waiting to be merged.
def _green_since(proj, minutes, url=PR):
    now = time.time()
    seen = {"state": "OPEN", "green": True, "head": "abc1234", "at": now, "green_since": now - minutes * 60}
    stuck._write(proj, {"pulls": {url: seen}})


def test_fx04_checks_that_only_just_passed_make_no_card_and_no_count(proj, run, new_ticket):
    tid = _in_review(proj, run, new_ticket)
    _green_since(proj, 5)
    assert [r for r in needs.core_rows(proj) if r["ticket"] == tid] == []
    assert _cards(proj, tid) == []
    n = _needs(proj)
    assert tid not in n["tickets"] and n["queue"] == [tid]  # it waits to be merged: one quiet line


def test_fx04_the_card_comes_once_the_usual_wait_is_over(proj, run, new_ticket):
    tid = _in_review(proj, run, new_ticket)
    _green_since(proj, stuck.UNMERGED_WAIT / 60 + 1)
    assert [r["kind"] for r in needs.core_rows(proj) if r["ticket"] == tid] == ["helper:unmerged"]
    n = _needs(proj)
    assert n["queue"] == [] and [i.get("stopped") for i in n["items"] if i["ticket"] == tid] == ["helper:unmerged"]


def test_fx04_an_older_open_pull_request_beside_a_new_one_still_makes_the_card(proj, run, new_ticket):
    tid = _in_review(proj, run, new_ticket)
    other = "https://github.com/acme/app/pull/13"
    tickets.ref_add(proj, tid, other, "agent:x")
    now = time.time()
    young = {"state": "OPEN", "green": True, "head": "abc1234", "at": now, "green_since": now - 60}
    old = {**young, "head": "def5678", "green_since": now - 2 * stuck.UNMERGED_WAIT}
    stuck._write(proj, {"pulls": {PR: young, other: old}})
    rows = [r for r in needs.core_rows(proj) if r["ticket"] == tid]
    assert [(r["kind"], r["pull"]["url"]) for r in rows] == [("helper:unmerged", other)]
    assert _needs(proj)["queue"] == []
