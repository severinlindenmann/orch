"""Releases merge by themselves when the owner allowed it (ORCH-79): `orch ask ... --merge --release` marks a
release Merge card; `orch review tend-releases` merges it for the owner once every check is green, only while
Settings say so (`workflow.release_merge`, off by default, only a person turns it on). Off, red, changed or
paused: nothing merges and the owner's Merge click stays."""

import json

import pytest
from test_merge_card import HEAD, PR, FakeGh, _q
from test_merge_card import gh as gh  # noqa: F401  (the fixture)

from orch import brake, ghmerge, review, tickets
from orch.releasekeeper import ROLLUP_JOBS

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

    def __init__(self, head_ref="release/part30-1117", base="main", default="main", files="0", fork=False):
        self.head_ref, self.base, self.default, self.files, self.fork = head_ref, base, default, files, fork
        self.compared = []

    def __call__(self, argv, **kw):
        import subprocess

        args = argv[1:]
        if args[:2] == ["pr", "view"]:
            out = json.dumps({"baseRefName": self.base, "headRefName": self.head_ref,
                              "isCrossRepository": self.fork})  # fmt: skip
        elif args[:2] == ["api", "repos/acme/app"]:
            out = self.default + "\n"
        elif args[:2] == ["api", "repos/acme/app/branches/develop"]:
            out = "b" * 40 + "\n"
        elif args[0] == "api" and "/compare/" in args[1]:
            self.compared.append(args[1])
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
        ({"fork": True}, "another repository"),
    ],
)
def test_release_problem(monkeypatch, gh_kw, want):
    monkeypatch.undo()  # the real check, not the autouse stand-in
    monkeypatch.setattr(ghmerge.shutil, "which", lambda name: "/fake/bin/gh")
    fake = ReleaseGh(**gh_kw)
    monkeypatch.setattr(ghmerge.subprocess, "run", fake)
    got = ghmerge.release_problem(PR, HEAD)
    assert got is None if want is None else want in got
    if want is None:  # compared with develop's own commit, never the name (a tag could carry it)
        assert fake.compared == [f"repos/acme/app/compare/{'b' * 40}...{HEAD}"]


ROLL = next(iter(ROLLUP_JOBS))  # the CI roll-up job
WIN = "workspace / test (windows-latest, 12/16)"
KNOWN = {"workspace / test (windows-latest)": "ORCH-32, until 2026-11-30"}


def _red(*failed, roll="FAILURE"):
    return {"state": "OPEN", "head": HEAD, "green": False,
            "failed": [(n, roll if n == ROLL else "FAILURE") for n in failed]}  # fmt: skip


def _rollup(gh, *failed):
    gh.rollup = [
        {"name": "workspace / lint", "workflowName": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}
    ]
    gh.rollup += [
        {"name": n, "workflowName": "ci", "status": "COMPLETED", "conclusion": "FAILURE"} for n in failed
    ]


def test_red_only_in_named_exceptions_merges_by_itself(tk, run, gh):  # noqa: F811
    """ORCH-178 (from ORCH-431): the owner's click on such a card would merge it; with the switch on it goes
    by itself, and the card's answer names the exception. The roll-up job is judged by its jobs."""
    root, tid = tk
    _ask(run, tid, "--release")
    _on(run)
    _rollup(gh, ROLL, WIN)  # what the merge reads again at GitHub right before it merges
    res = review.tend_releases(root, checks_of=lambda u: _red(ROLL, WIN), known_red=KNOWN)
    row = res["actions"][0]
    assert row["verdict"] == "merge" and row["done"] is True and gh.merges
    assert f"{WIN} (ORCH-32, until 2026-11-30)" in row["why"]
    q = _q(root, tid)
    assert q["answer"] == "Merge" and "named exceptions" in q["decision"]["summary"]


@pytest.mark.parametrize(
    ("facts", "known"),
    [
        (_red(ROLL, WIN, "workspace / lint"), KNOWN),  # one red check without an exception
        (_red(ROLL, WIN), None),  # `orch review tend-releases` alone: no exceptions passed
        (_red(ROLL, WIN), {}),
        (_red(ROLL), KNOWN),  # only the roll-up: nothing names why
        (_red(ROLL, WIN, roll="CANCELLED"), KNOWN),  # the roll-up itself was cut: not explained by WIN
        (_red(ROLL, "workspace / test (windows-latest, arm64)"), KNOWN),  # another matrix axis, not a part
        ({"state": "OPEN", "head": HEAD, "green": False, "failed": None}, KNOWN),  # a check still runs
        ({"state": "OPEN", "head": HEAD, "green": False}, KNOWN),
    ],
)
def test_red_outside_the_exceptions_still_waits(tk, run, facts, known):
    root, tid = tk
    _ask(run, tid, "--release")
    _on(run)
    res = review.tend_releases(root, checks_of=lambda u: facts, known_red=known)
    assert [a["verdict"] for a in res["actions"]] == ["wait"]
    assert not FakeGh.current.merges and _q(root, tid)["answer"] is None


def test_named_exceptions_never_pass_the_release_check(tk, run, monkeypatch):
    root, tid = tk
    _ask(run, tid, "--release")
    _on(run)
    monkeypatch.setattr(ghmerge, "release_problem", lambda url, head: "not from a release/ branch")
    res = review.tend_releases(root, checks_of=lambda u: _red(ROLL, WIN), known_red=KNOWN)
    assert [a["verdict"] for a in res["actions"]] == ["wait"] and not FakeGh.current.merges


def test_failed_names_reads_the_newest_run_and_waits_while_one_runs():
    done = {"status": "COMPLETED"}
    roll = [
        {**done, "name": "a", "workflowName": "ci", "conclusion": "FAILURE", "startedAt": "1"},
        {**done, "name": "a", "workflowName": "ci", "conclusion": "SUCCESS", "startedAt": "2"},
        {**done, "name": WIN, "workflowName": "ci", "conclusion": "FAILURE", "startedAt": "1"},
        {"context": "legacy", "state": "SUCCESS"},
    ]
    assert ghmerge.failed_names(roll) == [(WIN, "FAILURE")]
    assert ghmerge.failed_names([*roll, {"name": "b", "status": "IN_PROGRESS"}]) is None
    assert ghmerge.failed_names([*roll, {"context": "c", "state": "PENDING"}]) is None
    assert ghmerge.failed_names([]) is None


def test_the_keeper_hands_its_named_exceptions_to_the_merge(monkeypatch, tmp_path):
    from orch import releasekeeper

    got = {}
    monkeypatch.setattr(review, "tend_releases", lambda root, **kw: got.update(root=root, **kw) or {})

    class W:
        root = tmp_path

        def known_red(self):
            return dict(KNOWN)

    releasekeeper.tend_releases(W())
    assert got == {"root": tmp_path, "known_red": KNOWN}


def test_the_merge_reads_github_again_and_refuses_a_red_check_outside_the_exceptions(tk, run, gh):  # noqa: F811
    """Between the judgement and the merge a check can change: the merge itself allows only the named red
    checks, and the owner's click (no exceptions) still needs every check green."""
    root, tid = tk
    _ask(run, tid, "--release")
    _on(run)
    _rollup(gh, ROLL, WIN, "workspace / lint (2)")
    res = review.tend_releases(root, checks_of=lambda u: _red(ROLL, WIN), known_red=KNOWN)
    assert res["actions"][0]["verdict"] == "wait" and "checks have not all passed" in res["actions"][0]["why"]
    assert not gh.merges and _q(root, tid)["answer"] is None
    _rollup(gh, ROLL, WIN)
    with pytest.raises(tickets.Refused):
        ghmerge.merge(PR, HEAD)  # no exceptions: a red check stops the merge as before
    ok = frozenset({(ROLL, "FAILURE"), (WIN, "FAILURE")})
    gh.rollup[1]["conclusion"] = "CANCELLED"  # the roll-up ran again and was cut: no longer what was excused
    with pytest.raises(tickets.Refused):
        ghmerge.merge(PR, HEAD, excused=ok)
    gh.rollup = [None]  # a list nobody can judge
    with pytest.raises(tickets.Refused, match="could not be read"):
        ghmerge.merge(PR, HEAD, excused=ok)
    gh.rollup = []  # GitHub answers nothing: with exceptions nothing merges
    with pytest.raises(tickets.Refused, match="could not be read"):
        ghmerge.merge(PR, HEAD, excused=ok)
    _rollup(gh, ROLL, WIN)
    assert ghmerge.merge(PR, HEAD, excused=ok)["already"] is False and gh.merges
