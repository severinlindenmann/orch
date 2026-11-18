"""Ticket kinds (ORCH-645, owner 18 Nov): the helper that tidies a new ticket says what kind of work it is,
and each workspace lists the kinds the Reviewer accepts by itself (workflow.reviewer_kinds, default bugs).
A draft, mockup or design is never accepted by an automation (ORCH-582)."""

import pytest

from orch import config, lookreview, reviewer, runs, tickets
from orch.errors import Refused

PR = "https://github.com/acme/app/pull/12"


@pytest.fixture(autouse=True)
def no_starts(monkeypatch):
    monkeypatch.setattr(runs, "start", lambda root, tid, by, **kw: {"run": "r_x"})


@pytest.fixture
def facts(monkeypatch):
    """GitHub: one merged, green, small fix."""
    box = {
        "url": PR,
        "number": 12,
        "state": "MERGED",
        "green": True,
        "checks": 17,
        "failed": 0,
        "merged_at": "2999-01-01T00:00:00Z",
        "files": [{"path": "workspace/src/orch/runs.py", "additions": 20, "deletions": 4}],
        "added": {"workspace/src/orch/runs.py": ["    if not rec:", "        return None"]},
    }
    monkeypatch.setattr(reviewer, "pr_facts", lambda url: box if url == PR else None)
    return box


@pytest.fixture
def on(proj, run):
    assert run("config", "set", "workflow.reviewer", "on", "--by", "human:tester")[0] == 0


def _finished(proj, run, new_ticket, kind=None):
    tid = new_ticket("Fix the stale run record")
    extra = ["--kind", kind] if kind else []
    assert run("ticket", "tidy", tid, "Fix the stale run record", "--done-when", "the stale record is fixed",
               *extra, "--by", "agent:claude")[0] == 0  # fmt: skip
    assert run("check", "add", tid, "Fix the stale record", "--covers", "the stale record is fixed",
               "--by", "human:tester")[0] == 0  # fmt: skip
    assert run("check", "done", tid, "c1", "--pr", PR, "--by", "human:tester")[0] == 0
    tickets.set_status(proj, tid, "review", "human:tester")
    return tid


def _verdict(proj):
    return [(a["verdict"], a["why"]) for a in reviewer.run(proj)["actions"]]


# ------------------------------------------------------------------ the kind on a ticket


def test_tidy_sets_the_kind_and_the_start_text_asks_for_it(proj, run, new_ticket):
    tid = new_ticket("fix login")
    assert "--kind <kind>" in runs.fresh_prompt(tickets.load(proj, tid), [], proj)
    t = tickets.tidy(proj, tid, "Fix login", "agent:claude", kind_name="small_bug")
    assert t["kind"] == {"name": "small_bug", "by": "agent:claude"}
    assert any(h["text"] == "Kind: Small bug" for h in t["history"])
    code, out = run("ticket", "show", tid)[:2]
    assert code == 0 and "Kind: Small bug" in out
    with pytest.raises(Refused):
        tickets.tidy(proj, new_ticket("x"), "X", "agent:claude", kind_name="huge")


def test_a_person_can_change_the_kind_and_a_helper_cannot_undo_it(proj, run, new_ticket):
    tid = new_ticket("fix login")
    assert run("ticket", "kind", tid, "bug", "--by", "agent:claude")[0] == 0
    assert run("ticket", "kind", tid, "draft", "--by", "human:tester")[0] == 0
    t = tickets.load(proj, tid)
    assert tickets.kind(t) == "draft" and tickets.kind_by_person(t)
    assert any(h["text"] == "Kind: Draft or design (was: Bug)" for h in t["history"])
    code, out, err = run("ticket", "kind", tid, "small_bug", "--by", "agent:claude")
    assert code == 2 and "only a person changes it" in out + err
    assert tickets.kind(tickets.load(proj, tid)) == "draft"
    assert run("ticket", "kind", tid, "draft", "--by", "human:tester")[0] == 2  # already is


def test_an_unknown_kind_reads_as_none():
    assert tickets.kind({"kind": {"name": "epic", "by": "x"}}) is None
    assert tickets.kind({"kind": "bug"}) is None
    assert tickets.kind({}) is None


# ------------------------------------------------------------------ the workspace setting


def test_the_list_defaults_to_bugs_and_only_a_person_changes_it(proj, run):
    assert config.reviewer_kinds(proj) == ["bug", "small_bug"]
    code, out, err = run("config", "set", "workflow.reviewer_kinds", "small_feature", "--by", "agent:claude")
    assert code == 2 and "Only a person" in out + err
    assert (
        run("config", "set", "workflow.reviewer_kinds", "small_bug small_feature", "--by", "human:t")[0] == 0
    )
    assert config.reviewer_kinds(proj) == ["small_bug", "small_feature"]
    assert run("config", "get", "workflow.reviewer_kinds")[1].strip().endswith("small_bug,small_feature")
    assert run("config", "set", "workflow.reviewer_kinds", "none", "--by", "human:t")[0] == 0
    assert config.reviewer_kinds(proj) == []


@pytest.mark.parametrize("value", ["draft", "bug,draft", "everything"])
def test_draft_or_an_unknown_kind_is_refused_in_the_list(proj, run, value):
    assert run("config", "set", "workflow.reviewer_kinds", value, "--by", "human:t")[0] == 2
    assert config.reviewer_kinds(proj) == ["bug", "small_bug"]


def test_a_hand_edited_bad_list_accepts_nothing(proj):
    config.set_key(proj, "workflow", "reviewer_kinds", "bug,draft")
    assert config.reviewer_kinds(proj) == []
    config.set_key(proj, "workflow", "reviewer_kinds", 3)
    assert config.reviewer_kinds(proj) == []


# ------------------------------------------------------------------ the Reviewer


def test_a_small_bug_is_accepted_by_default(proj, run, new_ticket, facts, on):
    tid = _finished(proj, run, new_ticket, "small_bug")
    assert _verdict(proj)[0][0] == "accept"
    assert tickets.load(proj, tid)["status"] == "done"


def test_a_kind_not_listed_is_left_for_the_owner(proj, run, new_ticket, facts, on):
    tid = _finished(proj, run, new_ticket, "small_feature")
    assert _verdict(proj) == [("leave", "small feature work is not accepted by itself here (Settings).")]
    t = tickets.load(proj, tid)
    assert t["status"] == "review"
    assert t["history"][-1]["text"].startswith("Left for you by the Reviewer: small feature work")


def test_a_listed_feature_is_accepted_when_small_but_a_new_setting_still_waits(
    proj, run, new_ticket, facts, on
):
    assert (
        run("config", "set", "workflow.reviewer_kinds", "small_bug,small_feature", "--by", "human:t")[0] == 0
    )
    _finished(proj, run, new_ticket, "small_feature")
    assert _verdict(proj)[0][0] == "accept"
    facts["added"] = {"workspace/src/orch/runs.py": ['    x.add_argument("--fast")']}
    _finished(proj, run, new_ticket, "small_feature")
    (verdict, why), = _verdict(proj)  # fmt: skip
    assert verdict == "leave" and "adds a command or a setting" in why


def test_a_draft_is_never_accepted_even_when_everything_else_is_fine(proj, run, new_ticket, facts, on):
    _finished(proj, run, new_ticket, "draft")
    assert _verdict(proj) == [("leave", "drafts, mockups and designs are only accepted by you.")]


def test_an_empty_list_accepts_nothing_also_without_a_kind(proj, run, new_ticket, facts, on):
    assert run("config", "set", "workflow.reviewer_kinds", "none", "--by", "human:t")[0] == 0
    _finished(proj, run, new_ticket)
    assert _verdict(proj) == [("leave", "this workspace lets the Reviewer accept no kind of work by itself.")]


def test_a_ticket_without_a_kind_keeps_todays_rule(proj, run, new_ticket, facts, on):
    _finished(proj, run, new_ticket)
    assert _verdict(proj)[0][0] == "accept"


def test_the_list_does_nothing_while_the_reviewer_is_off(proj, run, new_ticket, facts):
    tid = _finished(proj, run, new_ticket, "small_bug")
    assert reviewer.run(proj)["actions"] == []
    assert tickets.load(proj, tid)["status"] == "review"


def test_the_second_look_leaves_a_kind_the_workspace_does_not_accept(proj, run, new_ticket, facts):
    tid = _finished(proj, run, new_ticket, "feature")
    t = tickets.load(proj, tid)
    res = reviewer.decide(proj, t, [facts])
    assert res["verdict"] == "leave" and res["kind_block"]
    assert lookreview.triage(t, [facts], res, 0) is None


def test_a_helper_cannot_pose_as_a_person_or_turn_a_draft_into_a_bug(proj, run, new_ticket, monkeypatch):
    tid = new_ticket("new look")
    assert run("ticket", "kind", tid, "draft", "--by", "agent:claude")[0] == 0
    code, out, err = run("ticket", "kind", tid, "small_bug", "--by", "agent:claude")
    assert code == 2 and "Only a person moves a ticket out of Draft or design" in out + err
    other = new_ticket("fix login")
    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")  # a helper that says --by human:...
    t = tickets.set_kind(proj, other, "bug", "human:tester")
    assert t["kind"]["by"] == "agent:claude" and not tickets.kind_by_person(t)


def test_a_helper_cannot_change_the_kind_of_finished_work(proj, run, new_ticket):
    tid = new_ticket("fix login")
    assert run("ticket", "kind", tid, "feature", "--by", "agent:claude")[0] == 0
    tickets.set_status(proj, tid, "review", "human:tester")
    code, out, err = run("ticket", "kind", tid, "small_bug", "--by", "agent:claude")
    assert code == 2 and "only a person changes its kind now" in out + err
    assert run("ticket", "kind", tid, "small_bug", "--by", "human:tester")[0] == 0


def test_a_ticket_without_a_kind_counts_as_a_small_bug(proj, run, new_ticket, facts, on):
    assert run("config", "set", "workflow.reviewer_kinds", "bug,small_feature", "--by", "human:t")[0] == 0
    _finished(proj, run, new_ticket)
    assert _verdict(proj) == [("leave", "small bug work is not accepted by itself here (Settings).")]


def test_a_helper_cannot_give_finished_work_its_first_kind(proj, run, new_ticket):
    tid = new_ticket("fix login")
    tickets.set_status(proj, tid, "review", "human:tester")
    assert run("ticket", "kind", tid, "feature", "--by", "agent:claude")[0] == 2
    assert tickets.kind(tickets.load(proj, tid)) is None
