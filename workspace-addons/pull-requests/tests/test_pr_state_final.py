"""One family of state bugs: a merged pull request is final on its ticket and in the queue; GitHub's "not known yet"
never replaces a known merge state; a check of a replaced run never counts as failed. Fake gh data only."""

from __future__ import annotations

import json
import subprocess

from prpage_util import FakeGitHub, add_ticket, gql_pr

from orch_pull_requests import cli, poll, prread, prstate, store
from orch_pull_requests.github import GitHub

PR = "https://github.com/acme/app/pull/{}"


# -- merged is final (#1639, #2083, #2662) ------------------------------------------------------------------
def test_a_merged_link_stays_merged_while_github_still_lists_it_open_and_blocked(prws):
    # the queue merged it with its group and set the link to merged; GitHub has not marked it merged yet
    t = add_ticket(prws, "t_aaaaa1", [{"url": PR.format(1822), "status": "merged", "title": "Mine"}])
    data = poll.load(prws)
    poll.read(prws, {"acme/app": []}, data, FakeGitHub({"acme/app": [gql_pr(1822, merge="BLOCKED")]}))
    assert data["prs"][PR.format(1822)]["status"] == "blocked"
    res = poll.answer(t, data)
    assert res["refs"] == [{"url": PR.format(1822), "status": "merged"}]
    assert res["ext"]["pull-requests"]["merge"] == "Merged"
    assert not poll.differs({**t, "ext": {"pull-requests": res["ext"]["pull-requests"]}}, res)


def test_a_kept_open_row_github_no_longer_answers_about_is_dropped(prws):
    # 2638 was open and blocked; it merged, and the answer left it out (LINKED_MAX): its old row is no truth
    t = add_ticket(
        prws, "t_aaaaa1", [{"url": PR.format(2638), "status": "blocked"}, {"url": PR.format(2660)}]
    )
    data = poll.load(prws)
    poll.read(
        prws, {"acme/app": [2638, 2660]}, data, FakeGitHub({"acme/app": [gql_pr(2638, merge="BLOCKED")]})
    )
    assert PR.format(2638) in data["prs"]
    poll.read(
        prws, {"acme/app": [2638, 2660]}, data, FakeGitHub({"acme/app": [gql_pr(2660, merge="BLOCKED")]})
    )
    assert PR.format(2638) not in data["prs"]
    assert [r["url"] for r in poll.answer(t, data)["refs"]] == [PR.format(2660)]


def test_the_newest_linked_pull_requests_are_the_ones_asked_about():
    seen = []

    def run(args):
        seen.append(args)
        body = {"data": {"repository": {"open": {"nodes": []}}}}
        return subprocess.CompletedProcess(args, 0, json.dumps(body), "")

    prread.fetch("acme/app", list(range(1, prread.LINKED_MAX + 21)), run=run)
    q = next(a for a in seen[0] if a.startswith("query="))
    assert f"p{prread.LINKED_MAX + 20}:" in q and "p21:" in q and "p20:" not in q


# -- "not known yet" never replaces a known state (#2118) -----------------------------------------------------
def test_not_known_yet_on_the_same_head_keeps_the_known_merge_state(prws):
    t = add_ticket(prws, "t_aaaaa1", [{"url": PR.format(2042)}])
    data = poll.load(prws)
    poll.read(prws, {"acme/app": [2042]}, data, FakeGitHub({"acme/app": [gql_pr(2042, merge="BLOCKED")]}))
    first = poll.answer(t, data)
    shown = add_ticket(prws, "t_aaaaa1", [{"url": PR.format(2042), "status": first["refs"][0]["status"],
                                          "title": "Change 2042"}], ext=first["ext"])  # fmt: skip
    unknown = gql_pr(2042, merge="UNKNOWN", mergeable="UNKNOWN")
    poll.read(prws, {"acme/app": [2042]}, data, FakeGitHub({"acme/app": [unknown]}))
    r = data["prs"][PR.format(2042)]
    assert (r["merge"], r["status"]) == ("blocked", "blocked")
    assert not poll.differs(shown, poll.answer(shown, data))  # no refresh line, nothing wakes the ticket
    # a new head is a new question: there "not known yet" is the truth
    poll.read(prws, {"acme/app": [2042]}, data,
              FakeGitHub({"acme/app": [gql_pr(2042, merge="UNKNOWN", mergeable="UNKNOWN", sha="f" * 40)]}))  # fmt: skip
    assert data["prs"][PR.format(2042)]["merge"] == "unknown"


# -- a check of a replaced run never counts as failed (#2411) ------------------------------------------------
JOB = "https://github.com/acme/app/actions/runs/{}/job/{}"


def gh_checks(rows):
    """A GitHub whose `gh pr checks --json` answers rows."""
    g = GitHub.__new__(GitHub)
    g.gh = "gh"
    g._run = lambda *a, **k: subprocess.CompletedProcess(a, 8, json.dumps(rows), "")
    return g


def test_the_queue_waits_for_the_ready_run_instead_of_taking_the_draft_time_failure():
    draft_verdict = {"name": "verdict", "bucket": "fail", "workflow": "ci", "link": JOB.format(100, 1),
                  "startedAt": "2026-11-22T06:03:10Z"}  # fmt: skip
    ready_test = {"name": "test", "bucket": "pending", "workflow": "ci", "link": JOB.format(200, 5),
                  "startedAt": "2026-11-22T06:07:00Z"}  # fmt: skip
    got = gh_checks([draft_verdict, ready_test]).own_checks(PR.format(2407))
    assert got == {"failed": [], "pending": ["verdict", "test"], "cancelled": []}
    assert gh_checks([draft_verdict, ready_test]).failed_checks(PR.format(2407)) == frozenset()
    # the newer run ended without making it again: the failure counts (GitHub sees it too)
    ended = {**ready_test, "bucket": "pass"}
    assert gh_checks([draft_verdict, ended]).own_checks(PR.format(2407))["failed"][0]["name"] == "verdict"


def test_the_page_shows_the_draft_time_failure_as_running_while_the_ready_run_goes():
    def node(name, run, concl):
        return {"__typename": "CheckRun", "name": name, "status": "COMPLETED" if concl else "IN_PROGRESS",
                "conclusion": concl, "startedAt": f"2026-11-22T06:0{run // 100}:00Z",
                "checkSuite": {"workflowRun": {"databaseId": run, "workflow": {"name": "ci"}}}}  # fmt: skip

    c = prstate.checks([node("verdict", 100, "FAILURE"), node("test", 200, None)])
    assert (c["word"], c["failed"]) == ("running", 0)
    # gh pr view's shape (workflowName, detailsUrl) follows the same rule
    gh_view = [{"__typename": "CheckRun", "name": "verdict", "conclusion": "FAILURE", "workflowName": "ci",
                "detailsUrl": JOB.format(100, 1)},
               {"__typename": "CheckRun", "name": "test", "conclusion": "", "status": "IN_PROGRESS",
                "workflowName": "ci", "detailsUrl": JOB.format(200, 5)}]  # fmt: skip
    assert prstate.checks(gh_view)["word"] == "running"


# -- a waiting entry GitHub shows merged ends (#1458) --------------------------------------------------------
class MergedGitHub:
    def pr(self, url):
        return {"state": "MERGED", "headRefOid": "a" * 40}


def test_wait_returns_merged_for_a_waiting_pull_request_merged_past_the_queue(ws, monkeypatch, capsys):
    monkeypatch.setattr(cli, "start_runner", lambda root: None)
    monkeypatch.setattr(cli, "runner_alive", lambda root: True)
    monkeypatch.setattr(cli, "POLL_SECS", 0)
    monkeypatch.setattr(cli, "_github", MergedGitHub)
    store.add(ws, PR.format(1429), None, "agent:t", login="bot")
    assert cli._wait(ws, PR.format(1429), 60, False) == 0
    assert store.find(store.read(ws), PR.format(1429))["state"] == store.MERGED
    assert "merged already" in capsys.readouterr().out


def test_the_refresh_ends_a_waiting_entry_github_shows_merged(prws):
    add_ticket(prws, "t_aaaaa1", [{"url": PR.format(1429)}])
    store.add(prws, PR.format(1429), None, "agent:t", login="bot")
    store.add(prws, PR.format(1430), None, "agent:t", login="bot")
    fake = FakeGitHub({"acme/app": [gql_pr(1429, "MERGED"), gql_pr(1430)]})
    poll.once(prws, fetch=fake)
    rows = store.read(prws)
    assert store.find(rows, PR.format(1429))["state"] == store.MERGED
    assert store.find(rows, PR.format(1430))["state"] == store.WAITING
