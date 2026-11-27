"""The gh wrapper (github.GitHub): what the queue makes of GitHub's answers, its errors and its odd replies.
No real gh call: GitHub._run is scripted per test."""

import json
import subprocess

import pytest

from orch_pull_requests import github
from orch_pull_requests.store import Refused

REPO = "acme/app"
URL = f"https://github.com/{REPO}/pull/7"


def gh(monkeypatch, answer):
    """A GitHub whose gh calls go to answer(args) -> (exit code, stdout[, stderr]); records every call."""
    monkeypatch.setattr(github.shutil, "which", lambda name: "/opt/gh tools/gh")
    g = github.GitHub()
    g.calls = []

    def run(*args, timeout=60):
        g.calls.append(args)
        rc, out, *err = answer(args)
        return subprocess.CompletedProcess([g.gh, *args], rc, out, err[0] if err else "")

    g._run = run
    return g


def test_no_gh_is_refused_with_what_to_do(monkeypatch):
    monkeypatch.setattr(github.shutil, "which", lambda name: None)
    with pytest.raises(Refused, match="needs the GitHub command line"):
        github.GitHub()


@pytest.mark.parametrize("rc, out, want", [(0, "octo\n", "octo"), (0, "\n", None), (1, "octo", None)])
def test_login_is_none_when_github_did_not_say(monkeypatch, rc, out, want):
    assert gh(monkeypatch, lambda a: (rc, out)).login() == want


@pytest.mark.parametrize("rc, out", [(1, ""), (0, "not json"), (0, "[]"), (0, json.dumps({"state": "OPEN"}))])
def test_a_pull_request_github_did_not_answer_is_none(monkeypatch, rc, out):
    g = gh(monkeypatch, lambda a: (rc, out))
    assert g.pr(URL) is None and g.checks(URL) is None


def test_own_checks_unreadable_is_none_and_counts_no_failure(monkeypatch):
    for out in ("", "not json", json.dumps({"a": 1})):
        g = gh(monkeypatch, lambda a, out=out: (1, out))
        assert g.own_checks(URL) is None
        assert g.failed_checks(URL) == frozenset() and g.own_checks_failed(URL) is False


def test_own_checks_read_while_some_still_run(monkeypatch):
    rows = [
        {"name": "lint", "bucket": "fail", "link": "https://github.com/acme/app/actions/runs/1/job/11",
         "workflow": "ci", "startedAt": "2026-11-25T10:00:00Z"},
        {"name": "tests", "bucket": "pending", "link": "https://github.com/acme/app/actions/runs/1/job/12",
         "workflow": "ci", "startedAt": "2026-11-25T10:00:00Z"},
        "junk",
    ]  # fmt: skip
    g = gh(monkeypatch, lambda a: (8, json.dumps(rows)))  # gh exits 8 while checks run
    got = g.own_checks(URL)
    assert got == {
        "failed": [
            {"name": "lint", "link": "https://github.com/acme/app/actions/runs/1/job/11", "state": ""}
        ],
        "pending": ["tests"],
        "cancelled": [],  # ORCH-2029: a check that was only cancelled is listed apart, never as failed
    }
    assert g.own_checks_failed(URL) is True


def test_first_failure_reads_the_failed_log_and_falls_back_to_the_whole_log(monkeypatch):
    def answer(a):
        if "--log-failed" in a:
            return 0, "   \n"  # gh could not tell the failed steps
        return 0, "job\tstep\t2026-11-25T10:00:00Z FAILED tests/test_x.py::test_a - boom\n"

    g = gh(monkeypatch, answer)
    assert "tests/test_x.py::test_a" in g.first_failure("https://github.com/acme/app/actions/runs/5/job/9")
    assert [c[:4] for c in g.calls] == [("run", "view", "--job", "9")] * 2
    assert g.first_failure("https://example.com/not/a/job") == "" and len(g.calls) == 2


def test_job_log_unreadable_is_empty(monkeypatch):
    assert gh(monkeypatch, lambda a: (1, "partial")).job_log(REPO, 3) == ""


def test_failed_tests_reads_failed_runs_first_and_at_most_four(monkeypatch):
    runs = [{"id": i, "conclusion": c} for i, c in
            enumerate(["cancelled", "success", "failure", "failure", "failure", "failure", "failure"])]  # fmt: skip

    def answer(a):
        if a[:2] == ("pr", "view"):
            return 0, json.dumps({"headRefOid": "abc"})
        if a[0] == "api":
            assert "head_sha=abc" in a[1]
            return 0, json.dumps({"workflow_runs": runs})
        rid = a[2]
        return (
            (0, f"FAILED tests/test_{rid}.py::t - x\nFAILED tests/test_2.py::t - x\n")
            if rid != "3"
            else (1, "")
        )

    g = gh(monkeypatch, answer)
    assert g.failed_tests(URL) == ["test_2.py", "test_4.py", "test_5.py"]  # 3's log unreadable, no doubles
    assert [c[2] for c in g.calls if c[0] == "run"] == ["2", "3", "4", "5"]  # failures before the cancelled


def test_failed_tests_without_an_answer_is_empty(monkeypatch):
    assert gh(monkeypatch, lambda a: (1, "")).failed_tests(URL) == []
    g = gh(monkeypatch, lambda a: (0, json.dumps({"headRefOid": "abc"})))
    assert g.failed_tests("https://github.com/no-repo/pull/7") == []


def _base_runs(runs, jobs):
    def answer(a):
        if a[:2] == ("run", "list"):
            return 0, json.dumps(runs)
        return jobs.get(a[2], (1, ""))

    return answer


def test_base_failed_takes_the_newest_finished_run_of_each_workflow(monkeypatch):
    runs = [
        {"databaseId": 9, "workflowName": "ci", "status": "in_progress", "conclusion": ""},
        {"databaseId": 8, "workflowName": "ci", "status": "completed", "conclusion": "cancelled"},
        {"databaseId": 7, "workflowName": "ci", "status": "completed", "conclusion": "failure"},
        {"databaseId": 6, "workflowName": "ci", "status": "completed", "conclusion": "success"},  # older
        {"databaseId": 5, "workflowName": "docs", "status": "completed", "conclusion": "success"},
        "junk",
    ]
    jobs = {"7": (0, json.dumps({"jobs": [{"name": "lint", "conclusion": "failure"},
                                          {"name": "unit", "conclusion": "timed_out"},
                                          {"name": "e2e", "conclusion": "success"}]}))}  # fmt: skip
    g = gh(monkeypatch, _base_runs(runs, jobs))
    assert g.base_failed(REPO, "develop") == frozenset({"lint", "unit"})


def test_base_failed_unknown_is_never_green(monkeypatch):
    assert gh(monkeypatch, lambda a: (1, "")).base_failed(REPO, "develop") is None
    going = [{"databaseId": i, "workflowName": "ci", "status": "in_progress"} for i in range(20)]
    assert gh(monkeypatch, _base_runs(going, {})).base_failed(REPO, "develop") is None
    red = [{"databaseId": 1, "workflowName": "ci", "status": "completed", "conclusion": "failure"}]
    assert gh(monkeypatch, _base_runs(red, {"1": (0, "{}")})).base_failed(REPO, "develop") is None


def test_check_state_counts_only_the_newest_run_tied_to_this_pull_request_alone(monkeypatch):
    def state(runs):
        return gh(monkeypatch, lambda a: (0, json.dumps({"check_runs": runs}))).check_state(
            REPO, "s", "ci / x", 7
        )

    def run(i, prs, status="completed", conclusion="success"):
        return {
            "id": i,
            "status": status,
            "conclusion": conclusion,
            "pull_requests": [{"number": n} for n in prs],
        }

    assert state([run(1, [7], conclusion="failure"), run(2, [7])]) == "success"
    assert state([run(1, [7]), run(2, [7], status="in_progress")]) == "pending"
    assert state([run(1, [8])]) is None  # another pull request's run
    assert state([run(1, [7]), run(2, [7, 8])]) is None  # the newest is shared with another: never trusted
    assert state([]) is None
    g = gh(monkeypatch, lambda a: (0, "{}"))
    g.check_state(REPO, "s", "ci / x & y", 7)
    assert "check_name=ci%20/%20x%20%26%20y" in g.calls[0][1]


def test_create_pr_and_issue_return_the_last_address_or_none(monkeypatch):
    out = "Warning: x\nhttps://github.com/acme/app/pull/9\n"
    g = gh(monkeypatch, lambda a: (0, out))
    assert g.create_pr(REPO, "develop", "q/1", "T", "B", labels=("owner-approved",)).endswith("/pull/9")
    assert g.calls[0][-2:] == ("--label", "owner-approved")
    assert gh(monkeypatch, lambda a: (1, out)).create_pr(REPO, "develop", "q/1", "T", "B") is None
    assert gh(monkeypatch, lambda a: (0, "made it\n")).create_issue(REPO, "T", "B") is None
    assert gh(monkeypatch, lambda a: (0, "https://github.com/acme/app/issues/3")).create_issue(REPO, "T", "B")


def test_a_status_description_is_cut_to_what_github_takes(monkeypatch):
    g = gh(monkeypatch, lambda a: (0, ""))
    assert g.set_status(REPO, "s", "x" * 300, target="https://ci") is True
    assert "description=" + "x" * 140 in g.calls[0] and "target_url=https://ci" in g.calls[0]
    assert g.post_status(REPO, "s", "ci", "success", "y" * 300) is True
    assert "description=" + "y" * 140 in g.calls[1]


@pytest.mark.parametrize(
    "rc, out, want",
    [
        (1, "", None),
        (0, json.dumps({"statuses": [{"context": github.MARK, "state": "failure"}]}), False),
        (0, json.dumps({"statuses": [{"context": github.MARK, "state": "success"}]}), True),
        (0, json.dumps({"statuses": None}), False),
    ],
)
def test_has_mark(monkeypatch, rc, out, want):
    assert gh(monkeypatch, lambda a: (rc, out)).has_mark(REPO, "s") is want


def test_merged_prs_and_runs_skip_what_they_cannot_read(monkeypatch):
    g = gh(monkeypatch, lambda a: (0, json.dumps([{"number": 1}, "junk"])))
    assert g.merged_prs(REPO, "develop", "2026-11-24") == [{"number": 1}]
    assert gh(monkeypatch, lambda a: (0, "{}")).merged_prs(REPO, "develop", "x") is None
    lines = '{"head_sha": "a"}\nnot json\n[1]\n{"head_sha": "b"}\n'
    assert gh(monkeypatch, lambda a: (0, lines)).runs(REPO, "a", "b") == [
        {"head_sha": "a"},
        {"head_sha": "b"},
    ]
    assert gh(monkeypatch, lambda a: (1, lines)).runs(REPO, "a", "b") is None


def test_find_issue_trusts_only_this_logins_own_issue(monkeypatch):
    issues = [
        {"url": "https://github.com/acme/app/issues/1", "body": "MARK-1", "author": {"login": "mallory"}},
        {"url": "https://github.com/acme/app/issues/2", "body": "other", "author": {"login": "Octo"}},
        {"url": "javascript:alert(1)", "body": "MARK-1", "author": {"login": "octo"}},
        {"url": "https://github.com/acme/app/issues/4", "body": "see MARK-1", "author": {"login": "OCTO"}},
    ]

    def answer(a):
        return (0, "octo\n") if a[:2] == ("api", "user") else (0, json.dumps(issues))

    g = gh(monkeypatch, answer)
    assert g.find_issue(REPO, "MARK-1") == "https://github.com/acme/app/issues/4"
    assert ("--author", "octo") == g.calls[1][g.calls[1].index("--author") :][:2]
    assert gh(monkeypatch, lambda a: (1, "")).find_issue(REPO, "MARK-1") is None  # no login: no search


def test_issue_state(monkeypatch):
    assert gh(monkeypatch, lambda a: (0, '{"state": "CLOSED"}')).issue_state("u") == "CLOSED"
    assert gh(monkeypatch, lambda a: (0, '{"state": 1}')).issue_state("u") is None


@pytest.mark.parametrize(
    "rc, err, want",
    [(0, "", True), (1, "gh: Reference does not exist (HTTP 422)", True), (1, "HTTP 404: Not Found", True),
     (1, "HTTP 403: forbidden", False)],
)  # fmt: skip
def test_delete_branch_counts_a_branch_already_gone_as_deleted(monkeypatch, rc, err, want):
    g = gh(monkeypatch, lambda a: (rc, "", err))
    assert g.delete_branch(REPO, "orch-queue/grüne gruppe#1") is want
    assert g.calls[0][-1] == "repos/acme/app/git/refs/heads/orch-queue/gr%C3%BCne%20gruppe%231"


def test_the_writes_say_whether_github_took_them(monkeypatch):
    ok, bad = gh(monkeypatch, lambda a: (0, "")), gh(monkeypatch, lambda a: (1, ""))
    for g, want in ((ok, True), (bad, False)):
        assert g.rerun_job(REPO, 1) is want and g.rerun_failed(REPO, 2) is want
        assert g.set_variable(REPO, "V", "1") is want and g.close(URL) is want
