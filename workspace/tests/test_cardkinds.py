"""Review overhaul (owner's picks 25 Nov 2026): twelve card kinds in four families picked by orch from what a
card carries (R3 B), the list's order (R2 A: what holds up work first), the refusals of `orch ask` (R5 A)
and the Reviewer mode "propose" (R1 A plus the owner's addition: nothing closes by itself is a mode, not the
default)."""

import json

import pytest

from orch import cardkinds, config, review, reviewer, runs, tickets
from orch.errors import Refused

PR = "https://github.com/acme/app/pull/12"


# ---------------------------------------------------------------- kinds


@pytest.mark.parametrize(
    ("card", "extra", "kind"),
    [
        (
            {"kind": "choice", "preview": {"type": "options", "options": [{"id": "Yes", "title": "Yes"}]}},
            {},
            "question",
        ),
        (
            {
                "kind": "choice",
                "preview": {"type": "options", "options": [{"id": "A", "preview": {"type": "img"}}]},
            },
            {},
            "choice",
        ),
        ({"kind": "draft", "preview": {"type": "compare", "before": {"type": "img"}}}, {}, "before_after"),
        # ORCH-2316: old and new wording side by side is Changed words, not Before and after
        (
            {"kind": "draft", "preview": {"type": "compare", "before": {"type": "doc"}, "after": {}}},
            {},
            "changed_words",
        ),
        ({"kind": "draft", "preview": {"type": "img"}}, {}, "pictures"),
        ({"kind": "draft", "preview": {"type": "doc", "paras": ["x"]}}, {}, "document"),
        ({"kind": "draft", "preview": {"type": "doc", "diff": [["-", "a"]]}}, {}, "changed_words"),
        ({"kind": "plan", "preview": {"type": "doc", "chart": {"bars": [1]}}}, {}, "numbers"),
        ({"kind": "draft", "preview": {"type": "table"}}, {}, "numbers"),
        ({"kind": "draft", "preview": {"type": "doc", "status": {"tone": "done"}}}, {}, "test_results"),
        ({"kind": "link"}, {}, "put_live"),
        ({"kind": "draft"}, {"merge": True}, "put_live"),
        ({"kind": "run", "run": {"class": "orch"}}, {}, "run_it"),
        ({"kind": "run", "run": {"class": "login"}}, {}, "try_yourself"),
        ({"kind": "stuck"}, {}, "stuck"),
        ({"kind": "choice"}, {"question_kind": "automation:failure"}, "stuck"),
        ({"kind": "draft", "preview": None}, {}, "question"),  # a plain question without options
        ({"kind": "check", "files": [{"type": "img"}]}, {}, "pictures"),
        ({"kind": "check", "files": [{"type": "pdf"}]}, {}, "document"),
        (
            {"kind": "check", "preview": {"type": "doc", "chips": [{"text": "All checks passed"}]}},
            {},
            "test_results",
        ),
        ({"kind": "check", "preview": {"type": "doc"}}, {}, "document"),
    ],
)
def test_orch_picks_the_kind_from_what_the_card_carries(card, extra, kind):
    assert cardkinds.kind_of(card, **extra) == kind


def test_twelve_kinds_in_four_families_with_plain_names():
    assert len(cardkinds.KINDS) == 12
    assert {f for f, _ in cardkinds.KINDS.values()} == set(cardkinds.FAMILIES)
    # orch is for any work (owner, 25 Nov): no developer words on a card
    # ("Test results" is the owner-picked name for the result card, 26 Nov, ORCH-2178)
    words = " ".join(
        [*cardkinds.FAMILIES.values(), *(n for _, n in cardkinds.KINDS.values()), *cardkinds.LANES.values()]
    )
    for dev in ("merge", "pull request", "deploy", "CI", "code", "commit", "diff"):
        assert dev.lower() not in words.lower().split()


def test_answers_and_stuck_hold_up_work_and_sort_first():
    q = cardkinds.look({"kind": "choice", "preview": {"type": "options", "options": []}})
    stuck = cardkinds.look({"kind": "stuck"})
    live = cardkinds.look({"kind": "link"})
    pics = cardkinds.look({"kind": "check", "files": [{"type": "img"}]})
    proposed = cardkinds.look({"kind": "check"}, proposed=True)
    assert [x["lane"] for x in (q, stuck, live, pics, proposed)] == [
        "holds_up",
        "holds_up",
        "click",
        "look",
        "proposed",
    ]
    assert q["name"] == "Question" and q["family"] == "answer"
    rows = [{"card_kind": x} for x in (proposed, pics, live, stuck, q)]
    assert [r["card_kind"]["lane"] for r in sorted(rows, key=cardkinds.lane_rank)] == [
        "holds_up", "holds_up", "click", "look", "proposed"]  # fmt: skip


def test_the_stack_carries_the_look_and_puts_a_question_before_a_result(proj, run, new_ticket):
    done = new_ticket("Write the spring newsletter")
    tickets.set_status(proj, done, "review", "human:tester")
    ask = new_ticket("Book the team lunch")
    assert (
        run(
            "ask",
            ask,
            "Which day?",
            "--option",
            "Tuesday",
            "--option",
            "Thursday",
            "--recommend",
            "Tuesday",
            "--by",
            "agent:x",
        )[0]
        == 0  # fmt: skip
    )
    items = review.stack(proj)
    assert [i["ticket"] for i in items] == [ask, done]
    assert items[0]["card_kind"] == {
        "family": "answer",
        "kind": "question",
        "name": "Question",
        "lane": "holds_up",
    }
    assert items[1]["card_kind"]["family"] == "look"
    assert "proposal" not in items[1]


# ---------------------------------------------------------------- orch ask refuses three bad questions


def test_a_long_question_is_refused_with_the_next_step(proj, run, new_ticket):
    tid = new_ticket("Release walk")
    long = "Please " + " ".join(["open the app and check the menu"] * 7) + "?"
    code, _, err = run(
        "ask", tid, long, "--option", "It worked", "--option", "Something did not work", "--by", "agent:x"
    )
    assert code != 0
    assert "one short sentence" in err and "ticket summary" in err
    assert tickets.load(proj, tid)["questions"] == []


def test_a_state_report_is_not_a_question(proj, run, new_ticket):
    tid = new_ticket("Weekly report")
    code, _, err = run("ask", tid, "Automation is paused, so the helper could not start.", "--by", "agent:x")
    assert code != 0 and "orch ticket summary" in err
    # a real question about the same thing is fine
    assert run("ask", tid, "Automation is paused. Turn it on again?", "--option", "Yes", "--option", "No",
               "--recommend", "Yes", "--by", "agent:x")[0] == 0  # fmt: skip


def test_a_question_without_a_suggested_answer_gets_the_next_step(proj, run, new_ticket):
    tid = new_ticket("Trip to Rome")
    code, out, _ = run(
        "ask", tid, "Which hotel?", "--option", "Near the station", "--option", "Old town", "--by", "agent:x"
    )
    assert code == 0 and cardkinds.ASK_HINT in out  # answers but none suggested: a hint, not a refusal
    flight = ["Which flight?", "--option", "Morning", "--option", "Evening", "--recommend", "Morning"]
    code, out, _ = run("ask", tid, *flight, "--by", "agent:x")
    assert code == 0 and cardkinds.ASK_HINT not in out


def test_a_helpers_question_without_answers_is_refused(proj, run, new_ticket, monkeypatch):
    """ORCH-2177 (AGENTS R2.4): one sentence and the next step; nothing is written."""
    tid = new_ticket("Trip to Rome")
    monkeypatch.setattr(tickets, "attended", lambda: False)
    for who in (["--by", "agent:x"], []):  # nobody named and no terminal is a helper too
        code, out, err = run("ask", tid, "Which hotel?", *who)
        assert code != 0 and cardkinds.ASK_NEEDS_ANSWERS in err, out + err
        assert "--option" in err and "--recommend" in err
    assert tickets.load(proj, tid)["questions"] == []
    # the more telling refusals come first
    code, _, err = run("ask", tid, "Paste your API key", "--by", "agent:x")
    assert code != 0 and "credential" in err and cardkinds.ASK_NEEDS_ANSWERS not in err
    # ideas to sort, a card, and an add-on's own question bring their answers or word themselves
    ideas = ["--idea", "A reel", "--idea", "A post"]
    assert run("ask", tid, "Which ideas should I work out?", *ideas, "--by", "agent:x")[0] == 0
    assert run("ask", tid, "Check the disk?", "--run", "df -h", "--by", "agent:x")[0] == 0
    assert run("ask", tid, "Restart the shop page?", "--kind", "services:failing", "--by", "agent:x")[0] == 0


def test_a_persons_own_question_without_answers_keeps_the_hint(proj, run, new_ticket, monkeypatch):
    """ORCH-2177: the one caller that cannot give options yet asks as the person (an add-on's question to
    another workspace, by a click, answered in free words). From inside a helper's run it is a helper."""
    tid = new_ticket("Trip to Rome")
    code, out, err = run("ask", tid, "What would you change before this ships?", "--by", "human:tester")
    assert code == 0 and cardkinds.ASK_HINT in out, out + err
    monkeypatch.setenv("ORCH_AGENT", "claude")
    code, _, err = run("ask", tid, "And what else?", "--by", "human:tester")
    assert code != 0 and cardkinds.ASK_NEEDS_ANSWERS in err


def test_refusals_apply_to_cards_only_by_length():
    cardkinds.refuse_bad_question("Everything is done.", [], card=True)  # a card brings its own answers
    with pytest.raises(Refused):
        cardkinds.refuse_bad_question(" ".join(["word"] * 41), [], card=True)


# ---------------------------------------------------------------- Reviewer mode


def test_reviewer_mode_defaults_to_accept_and_only_a_person_turns_accept_back_on(proj, run):
    assert config.reviewer_mode(proj) == "accept"
    assert run("config", "set", "workflow.reviewer_mode", "propose", "--by", "agent:x")[0] == 0
    assert config.reviewer_mode(proj) == "propose"
    code, _, err = run("config", "set", "workflow.reviewer_mode", "accept", "--by", "agent:x")
    assert code != 0 and "Only a person" in err
    assert run("config", "set", "workflow.reviewer_mode", "accept", "--by", "human:tester")[0] == 0
    code, out, _ = run("config", "get", "workflow.reviewer_mode")
    assert code == 0 and "accept" in out
    assert run("config", "set", "workflow.reviewer_mode", "sometimes", "--by", "human:tester")[0] != 0


@pytest.fixture
def merged(monkeypatch):
    facts = {"url": PR, "number": 12, "state": "MERGED", "green": True, "checks": 3, "failed": 0,
             "merged_at": "2999-01-01T00:00:00Z",
             "files": [{"path": "workspace/src/orch/runs.py", "additions": 5, "deletions": 1}],
             "added": {"workspace/src/orch/runs.py": ["    return None"]}}  # fmt: skip
    monkeypatch.setattr(reviewer, "pr_facts", lambda url: facts if url == PR else None)
    monkeypatch.setattr(runs, "start", lambda *a, **k: {"run": "r_x"})


def _finished(proj, run, new_ticket):
    tid = new_ticket("Fix the stale run record")
    assert run("ticket", "tidy", tid, "Fix the stale run record", "--description", "d", "--done-when",
               "the stale record is fixed", "--by", "human:tester")[0] == 0  # fmt: skip
    assert (
        run("check", "add", tid, "Fix it", "--covers", "the stale record is fixed", "--by", "human:tester")[0]
        == 0
    )
    assert run("check", "done", tid, "c1", "--pr", PR, "--by", "human:tester")[0] == 0
    tickets.set_status(proj, tid, "review", "human:tester")
    return tid


def test_propose_mode_closes_nothing_and_puts_the_verdict_on_the_card(proj, run, new_ticket, merged):
    assert run("config", "set", "workflow.reviewer", "on", "--by", "human:tester")[0] == 0
    assert run("config", "set", "workflow.reviewer_mode", "propose", "--by", "human:tester")[0] == 0
    tid = _finished(proj, run, new_ticket)
    res = reviewer.run(proj)
    assert [(a["verdict"], a.get("proposed")) for a in res["actions"]] == [("accept", True)]
    t = tickets.load(proj, tid)
    assert t["status"] == "review"  # nothing closed by itself
    assert t["history"][-1]["text"].startswith(reviewer.PROPOSE_LINES["accept"])
    item = next(i for i in review.stack(proj) if i["ticket"] == tid)
    assert item["proposal"]["verdict"] == "accept" and item["recommended"] == "ok"
    assert item["card_kind"]["lane"] == "proposed"
    assert reviewer.run(proj)["actions"] == []  # once per change, no second line
    # the ticket moves on: the proposal is gone
    tickets.log(proj, tid, "The helper added a picture.", "agent:helper")
    item = next(i for i in review.stack(proj) if i["ticket"] == tid)
    assert "proposal" not in item and item["recommended"] is None


def test_accept_mode_still_accepts(proj, run, new_ticket, merged):
    assert run("config", "set", "workflow.reviewer", "on", "--by", "human:tester")[0] == 0
    tid = _finished(proj, run, new_ticket)
    reviewer.run(proj)
    assert tickets.load(proj, tid)["status"] == "done"


def test_proposal_reads_only_the_newest_line():
    by = tickets.REVIEWER
    line = {"by": by, "text": reviewer.PROPOSE_LINES["back"] + "a part is open", "at": "x"}
    assert reviewer.proposal([line]) == {"verdict": "back", "why": "a part is open"}
    assert (
        reviewer.proposal([line, {"by": by, "text": "Left for you by the Reviewer: big", "at": "y"}]) is None
    )
    assert reviewer.proposal([]) is None
    assert json.dumps(reviewer.proposal([line]))


def test_review_list_in_the_terminal_shows_the_same_groups(proj, run, new_ticket):
    done = new_ticket("Write the spring newsletter")
    tickets.set_status(proj, done, "review", "human:tester")
    ask = new_ticket("Book the team lunch")
    assert (
        run(
            "ask",
            ask,
            "Which day?",
            "--option",
            "Tuesday",
            "--option",
            "Thursday",
            "--recommend",
            "Tuesday",
            "--by",
            "agent:x",
        )[0]
        == 0  # fmt: skip
    )
    code, out, _ = run("review", "list")
    assert code == 0
    lines = out.splitlines()
    assert lines[1] == "Holds up work now" and "[Question]" in lines[2]
    assert lines[3] == "Look at the result" and "Write the spring newsletter" in lines[4]


def test_propose_mode_skips_the_second_look(proj, run, monkeypatch):
    from orch import lookreview

    assert run("config", "set", "workflow.reviewer", "on", "--by", "human:tester")[0] == 0
    assert run("config", "set", "workflow.reviewer_mode", "propose", "--by", "human:tester")[0] == 0
    monkeypatch.setattr(lookreview, "on", lambda root: True)
    monkeypatch.setattr(
        lookreview, "tend", lambda *a, **k: pytest.fail("the second look accepts: off in propose")
    )
    assert reviewer.run(proj)["second_look"] == []


def test_list_groups_use_the_approved_draft_words_and_run_it_sits_with_try_it_yourself():
    """ORCH-2316 (R2 A, draft r2-a): Holds up work now, Put it live, Try it yourself, Look at the result."""
    assert list(cardkinds.LANES.values())[:4] == [
        "Holds up work now", "Put it live", "Try it yourself", "Look at the result"]  # fmt: skip
    assert cardkinds.look({"kind": "run", "run": {"class": "orch"}})["lane"] == "help"
    assert cardkinds.look({"kind": "run", "run": {"class": "login"}})["lane"] == "help"
    assert cardkinds.look({"kind": "run", "run": {"class": "orch"}})["name"] == "Run it"
