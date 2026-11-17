"""A pull request's checks, merge state and the word its ticket link shows (pure, no network)."""

import pytest
from prpage_util import gql_pr

from orch_pull_requests import prstate


def run_(name, status="COMPLETED", conclusion="SUCCESS"):
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion}


def test_parse_url():
    assert prstate.parse_url("https://github.com/acme/app/pull/12") == ("acme/app", 12)
    assert prstate.parse_url("https://github.com/acme/app/pull/12/") == ("acme/app", 12)
    assert prstate.parse_url("https://github.com/acme/app/issues/12") is None
    assert prstate.parse_url("https://evil.example/acme/app/pull/12") is None


@pytest.mark.parametrize(
    "nodes,word",
    [
        ([], "none"),
        ([run_("a"), run_("b", conclusion="SKIPPED")], "passed"),
        ([run_("a"), run_("b", status="IN_PROGRESS", conclusion=None)], "running"),
        ([run_("a", conclusion="FAILURE"), run_("b", status="QUEUED", conclusion=None)], "failed"),
        ([run_("a", conclusion="CANCELLED")], "failed"),
        ([run_("a", conclusion="TIMED_OUT")], "failed"),
        ([run_("a", conclusion="NEUTRAL")], "failed"),  # the core waiter never counts NEUTRAL as green
        ([{"__typename": "StatusContext", "context": "ci/x", "state": "PENDING"}], "running"),
        ([{"__typename": "StatusContext", "context": "ci/x", "state": "ERROR"}], "failed"),
        ([{"__typename": "StatusContext", "context": "ci/x", "state": "SUCCESS"}], "passed"),
    ],
)
def test_check_words(nodes, word):
    assert prstate.checks(nodes)["word"] == word


def test_unexpanded_matrix_job_is_left_out():
    c = prstate.checks([run_("test (${{ matrix.os }})", conclusion="SKIPPED")])
    assert c["word"] == "none" and c["passed"] == 0


def test_counts_and_failed_names():
    c = prstate.checks([run_("a"), run_("lint", conclusion="FAILURE"), run_("c", "QUEUED", None)])
    assert (c["passed"], c["failed"], c["running"], c["failed_names"]) == (1, 1, 1, ["lint"])


@pytest.mark.parametrize(
    "kw,merge,status",
    [
        ({}, "ready", "ready to merge"),
        ({"state": "MERGED"}, "merged", "merged"),
        ({"state": "CLOSED"}, "closed", "closed"),
        ({"draft": True}, "draft", "draft"),
        ({"mergeable": "CONFLICTING", "merge": "DIRTY"}, "conflict", "conflict"),
        ({"merge": "BEHIND"}, "behind", "behind"),
        ({"merge": "BLOCKED"}, "blocked", "blocked"),
        ({"merge": "UNKNOWN", "mergeable": "UNKNOWN"}, "unknown", "open"),
        ({"merge": "BLOCKED", "checks": [run_("a", conclusion="FAILURE")]}, "blocked", "checks failed"),
        ({"merge": "BLOCKED", "checks": [run_("a", "IN_PROGRESS", None)]}, "blocked", "checks running"),
    ],
)
def test_merge_and_status(kw, merge, status):
    r = prstate.row("acme/app", gql_pr(5, **kw))
    assert (r["merge"], r["status"]) == (merge, status)
    assert r["status"] in prstate.STATUS_WORDS and r["merge"] in prstate.MERGE_WORDS


def test_row_ignores_junk():
    assert prstate.row("acme/app", None) is None
    assert prstate.row("acme/app", {"number": "5"}) is None
    r = prstate.row("acme/app", {"number": 5})
    assert r["checks"]["word"] == "none" and r["status"] == "open"


def test_main_pr_is_the_newest_open_one():
    rows = [
        prstate.row("acme/app", gql_pr(3)),
        prstate.row("acme/app", gql_pr(9, state="MERGED")),
        prstate.row("acme/app", gql_pr(4, checks=[run_("a", conclusion="FAILURE")])),
    ]
    assert prstate.ext_of(rows) == {"pr": "#4", "checks": "failed", "merge": "ready"}
    assert prstate.ext_of([rows[1]]) == {"pr": "#9", "checks": "passed", "merge": "merged"}
    assert prstate.ext_of([]) is None
