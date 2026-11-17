"""Releases merge by themselves when the owner allowed it (ORCH-79): `orch ask ... --merge --release` marks a
release Merge card; `orch review tend-releases` merges it for the owner once every check is green, only while
Settings say so (`workflow.release_merge`, off by default, only a person turns it on). Off, red, changed or
paused: nothing merges and the owner's Merge click stays."""

import json

import pytest
from test_merge_card import HEAD, PR, FakeGh, _q
from test_merge_card import gh as gh  # noqa: F401  (the fixture)

from orch import brake, ghmerge, review, tickets

GREEN = {"state": "OPEN", "head": HEAD, "green": True}


@pytest.fixture(autouse=True)
def a_real_release(monkeypatch):
    """GitHub says: a release/... branch into the default branch with nothing that is not on develop."""
    monkeypatch.setattr(ghmerge, "release_problem", lambda url, head: None)
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)


@pytest.fixture
def tk(proj, run, gh):  # noqa: F811
    code, out, _ = run("ticket", "new", "Release 30", "--json", "--by", "agent:x")
    assert code == 0
    return proj, json.loads(out)["id"]


def _ask(run, tid, *extra):
    got = run(
        "ask", tid, "Merge release 30 into main?", "--link", "Release 30", "--open", PR, "--merge",
        "--then", "Release 30 goes to main.", *extra, "--json", "--by", "agent:x",
    )  # fmt: skip
    FakeGh.current.calls.clear()
    FakeGh.current.envs.clear()  # reading the pull request when the card is made is not the merge
    return got


def _on(run):
    assert run("config", "set", "workflow.release_merge", "on", "--by", "human:pat")[0] == 0


def test_the_setting_is_off_by_default_and_only_a_person_turns_it_on(proj, run, monkeypatch):
    code, out, _ = run("config", "get", "workflow.release_merge", "--json")
    assert code == 0 and json.loads(out)["workflow.release_merge"] is False
    code, out, err = run("config", "set", "workflow.release_merge", "on", "--by", "agent:x")
    assert code == 2 and "Only the owner" in out + err
    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")  # an agent in the environment, whatever --by
    assert run("config", "set", "workflow.release_merge", "on", "--by", "human:pat")[0] == 2
    assert run("config", "set", "workflow.release_merge", "off")[0] == 0  # anyone may turn it off
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    _on(run)
    code, out, _ = run("config", "get", "workflow.release_merge", "--json")
    assert json.loads(out)["workflow.release_merge"] is True


def test_release_marks_the_merge_card(tk, run, validate):
    root, tid = tk
    code, out, err = _ask(run, tid, "--release")
    assert code == 0, out + err
    q = _q(root, tid)
    assert q["action"] == {"merge": PR, "head": HEAD, "release": True} and review.merge_url(q) == PR
    assert "merges by itself once every check is green" in q["card"]["why"]
    validate(tickets.load(root, tid))
    code, out, _ = run("ask", tid, "Plain?", "--release", "--by", "agent:x")
    assert code == 2


def test_off_nothing_merges(tk, run):
    root, tid = tk
    _ask(run, tid, "--release")
    res = review.tend_releases(root, checks_of=lambda u: GREEN)
    assert res["off"] is True and not FakeGh.current.merges
    assert _q(root, tid)["answer"] is None


def test_on_and_green_merges_for_the_owner_with_the_own_login(tk, run, gh):  # noqa: F811
    root, tid = tk
    _ask(run, tid, "--release")
    _on(run)
    dry = review.tend_releases(root, dry_run=True, checks_of=lambda u: GREEN)
    assert [a["verdict"] for a in dry["actions"]] == ["merge"] and not gh.merges
    res = review.tend_releases(root, checks_of=lambda u: GREEN)
    assert res["actions"][0]["done"] is True
    assert gh.merges and all(not e for e in gh.envs)  # helper tokens dropped: gh's own sign-in merges
    q = _q(root, tid)
    assert q["answer"] == "Merge" and q["answered_by"] == tickets.RELEASE_KEEPER
    assert q["decision"]["action"] == "approve"
    lines = [h["text"] for h in tickets.load(root, tid)["history"]]
    assert any(x.startswith(tickets.RELEASE_MERGED_LINE) and "pat-gh" in x for x in lines)
    again = review.tend_releases(root, checks_of=lambda u: GREEN)
    assert again["actions"] == []  # answered: never twice


@pytest.mark.parametrize(
    ("facts", "verdict"),
    [
        ({"state": "OPEN", "head": HEAD, "green": False}, "wait"),
        ({"state": "OPEN", "head": "b" * 40, "green": True}, "stale"),
        ({"state": "CLOSED", "head": HEAD, "green": False}, "stale"),
        (None, "wait"),
    ],
)
def test_red_changed_or_unreadable_waits_for_the_click(tk, run, facts, verdict):
    root, tid = tk
    _ask(run, tid, "--release")
    _on(run)
    res = review.tend_releases(root, checks_of=lambda u: facts)
    assert [a["verdict"] for a in res["actions"]] == [verdict]
    assert not FakeGh.current.merges and _q(root, tid)["answer"] is None


def test_a_merge_card_without_release_is_never_merged_by_itself(tk, run):
    root, tid = tk
    _ask(run, tid)
    _on(run)
    assert review.tend_releases(root, checks_of=lambda u: GREEN)["actions"] == []
    assert not FakeGh.current.merges


def test_paused_automation_merges_nothing(tk, run, monkeypatch):
    root, tid = tk
    _ask(run, tid, "--release")
    _on(run)
    monkeypatch.setattr(brake, "paused", lambda root: {"by": "human:pat"})
    assert review.tend_releases(root, checks_of=lambda u: GREEN)["paused"] is True
    assert not FakeGh.current.merges


def test_github_refusal_saves_no_answer(tk, run, gh):  # noqa: F811
    root, tid = tk
    _ask(run, tid, "--release")
    _on(run)
    gh.merge_rc, gh.merge_err = 1, "X Pull request is not mergeable"
    res = review.tend_releases(root, checks_of=lambda u: GREEN)
    assert res["actions"][0]["done"] is False and res["actions"][0]["verdict"] == "wait"
    assert _q(root, tid)["answer"] is None


def test_the_record_refuses_another_card_or_the_setting_off(tk, run):
    root, tid = tk
    _ask(run, tid, "--release")
    d = {"action": "approve"}
    with pytest.raises(tickets.Refused):
        tickets.merged_for_owner(root, tid, "q1", PR, HEAD, "x", d)  # off
    _on(run)
    with pytest.raises(tickets.Refused):
        tickets.merged_for_owner(root, tid, "q1", PR, "c" * 40, "x", d)  # another commit


def test_cli_tend_releases(tk, run):
    root, tid = tk
    code, out, _ = run("review", "tend-releases")
    assert code == 0 and "only on your click" in out
    _on(run)
    code, out, _ = run("review", "tend-releases", "--dry-run", "--json")
    assert code == 0 and json.loads(out)["off"] is False


def test_other_work_marked_release_never_merges_by_itself(tk, run, monkeypatch):
    root, tid = tk
    _ask(run, tid, "--release")
    _on(run)
    monkeypatch.setattr(
        ghmerge, "release_problem", lambda url, head: "it does not come from a release/... branch"
    )
    res = review.tend_releases(root, checks_of=lambda u: GREEN)
    assert res["actions"][0]["verdict"] == "wait" and "release/" in res["actions"][0]["why"]
    assert not FakeGh.current.merges and _q(root, tid)["answer"] is None


def test_refused_inside_a_helper(tk, run, monkeypatch):
    root, tid = tk
    _ask(run, tid, "--release")
    _on(run)
    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    with pytest.raises(tickets.Refused):
        review.tend_releases(root, checks_of=lambda u: GREEN)
    assert not FakeGh.current.merges


class ReleaseGh:
    """gh for ghmerge.release_problem: the pull request's branches, the default branch, the compare count."""

    def __init__(self, head_ref="release/part30-1117", base="main", default="main", files="0"):
        self.head_ref, self.base, self.default, self.files = head_ref, base, default, files

    def __call__(self, argv, **kw):
        import subprocess

        args = argv[1:]
        if args[:2] == ["pr", "view"]:
            out = json.dumps({"baseRefName": self.base, "headRefName": self.head_ref})
        elif args[:2] == ["api", "repos/acme/app"]:
            out = self.default + "\n"
        elif args[0] == "api" and "/compare/develop..." in args[1]:
            out = self.files + "\n"
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(argv, 0, out, "")


@pytest.mark.parametrize(
    ("gh_kw", "want"),
    [
        ({}, None),
        ({"head_ref": "feat/sneaky"}, "release/"),
        ({"base": "develop"}, "default branch"),
        ({"files": "3"}, "not on develop"),
    ],
)
def test_release_problem(monkeypatch, gh_kw, want):
    monkeypatch.undo()  # the real check, not the autouse stand-in
    monkeypatch.setattr(ghmerge.shutil, "which", lambda name: "/fake/bin/gh")
    monkeypatch.setattr(ghmerge.subprocess, "run", ReleaseGh(**gh_kw))
    got = ghmerge.release_problem(PR, HEAD)
    assert got is None if want is None else want in got
