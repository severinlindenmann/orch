"""The background job's pass: linked repositories read once each, tickets refreshed only on a change."""

import json
import subprocess

from prpage_util import FakeGitHub, add_ticket, calls, gql_pr

from orch_pull_requests import poll
from orch_pull_requests import prread as gh

PR = "https://github.com/acme/app/pull/{}"


def refreshes(root):
    return [c for c in calls(root) if c["args"][:3] == ["pull-requests", "act", "refresh"]]


def test_plan_reads_each_linked_repo_once(prws):
    ts = [
        add_ticket(prws, "t_aaaaa1", [{"url": PR.format(1)}, {"url": PR.format(2), "status": "merged"}]),
        add_ticket(prws, "t_aaaaa2", [{"url": "https://github.com/acme/app/issues/7"}]),
        add_ticket(prws, "t_aaaaa3", [{"url": "https://github.com/acme/lib/pull/3"}], status="done"),
        add_ticket(prws, "t_aaaaa4", [{"url": "https://github.com/old/repo/issues/1"}], status="done"),
        add_ticket(prws, "t_aaaaa5", [{"url": "https://example.com/acme/app/pull/1"}]),
    ]
    # merged links are not asked about again; a finished ticket's repo only for its links still open
    assert poll.plan(ts) == {"acme/app": [1], "acme/lib": [3]}


def test_once_writes_state_and_refreshes_changed_tickets(prws):
    add_ticket(prws, "t_aaaaa1", [{"url": PR.format(1)}])
    add_ticket(prws, "t_aaaaa2", [{"url": "https://github.com/acme/app/issues/7"}])
    fake = FakeGitHub({"acme/app": [gql_pr(1), gql_pr(2, draft=True)]})
    res = poll.once(prws, fetch=fake)
    assert fake.calls == [("acme/app", [1])]
    assert res["refreshed"] == ["t_aaaaa1"] and res["errors"] == {}
    data = poll.load(prws)
    assert sorted(data["prs"]) == [PR.format(1), PR.format(2)]
    assert data["repos"]["acme/app"]["open"] == [1, 2]
    (r,) = refreshes(prws)
    assert r["args"][-1] == "t_aaaaa1" and r["cached"] == "1" and "--by" in r["args"]


def test_nothing_changed_means_no_refresh(prws):
    add_ticket(
        prws,
        "t_aaaaa1",
        [{"url": PR.format(1), "status": "ready to merge", "title": "Change 1"}],
        ext={"pull-requests": {"pr": "#1", "checks": "passed", "merge": "ready"}},
    )
    poll.once(prws, fetch=FakeGitHub({"acme/app": [gql_pr(1)]}))
    assert refreshes(prws) == []


def test_answer_is_the_refresh_contract(prws):
    t = add_ticket(prws, "t_aaaaa1", [{"url": PR.format(1) + "/", "title": "Mine"}, {"url": PR.format(4)}])
    data = poll.load(prws)
    poll.read(prws, {"acme/app": [1, 4]}, data, FakeGitHub({"acme/app": [gql_pr(1), gql_pr(4, "MERGED")]}))
    res = poll.answer(t, data)
    assert res["ticket"] == "t_aaaaa1"
    # the link is matched by the address the ticket holds; a title only where the ticket has none
    assert res["refs"] == [
        {"url": PR.format(1) + "/", "status": "ready to merge"},
        {"url": PR.format(4), "status": "merged", "title": "Change 4"},
    ]
    assert res["ext"] == {"pull-requests": {"pr": "#1", "checks": "passed", "merge": "ready"}}
    for item in res["refs"]:
        assert len(item["status"]) <= 24


def test_github_trouble_is_kept_per_repo(prws):
    add_ticket(prws, "t_aaaaa1", [{"url": PR.format(1)}])
    res = poll.once(prws, fetch=FakeGitHub({}, fail={"acme/app": gh.NOT_SIGNED_IN}))
    assert res["errors"] == {"acme/app": gh.NOT_SIGNED_IN}
    assert refreshes(prws) == []


def test_closed_unlinked_pull_requests_are_forgotten(prws):
    add_ticket(prws, "t_aaaaa1", [{"url": PR.format(1)}])
    poll.once(prws, fetch=FakeGitHub({"acme/app": [gql_pr(1), gql_pr(2)]}))
    poll.once(
        prws, fetch=FakeGitHub({"acme/app": [gql_pr(1)]})
    )  # 2 was merged by someone, no ticket links it
    assert sorted(poll.load(prws)["prs"]) == [PR.format(1)]


def test_refresh_one_live_and_cached(prws):
    t = add_ticket(prws, "t_aaaaa1", [{"url": PR.format(1)}])
    fake = FakeGitHub({"acme/app": [gql_pr(1, merge="BEHIND")]})
    assert poll.refresh_one(prws, t, cached=True, fetch=fake)["refs"] == []  # nothing read yet
    assert fake.calls == []
    res = poll.refresh_one(prws, t, cached=False, fetch=fake)
    assert fake.calls == [("acme/app", [1])] and res["refs"][0]["status"] == "behind"
    assert poll.refresh_one(prws, t, cached=True, fetch=fake)["refs"][0]["status"] == "behind"


def test_refresh_one_says_why_when_github_fails(prws):
    t = add_ticket(prws, "t_aaaaa1", [{"url": PR.format(1)}])
    res = poll.refresh_one(prws, t, cached=False, fetch=FakeGitHub({}, fail={"acme/app": gh.NO_GH}))
    assert res["refs"] == [] and res["say"] == gh.NO_GH


def test_a_broken_state_file_starts_fresh(prws):
    p = poll.state_file(prws)
    p.parent.mkdir(parents=True)
    p.write_text("{not json")
    assert poll.load(prws)["prs"] == {}
    p.write_text(json.dumps({"schema": "other/9", "prs": {"x": 1}}))
    assert poll.load(prws)["prs"] == {}


def test_gh_fetch_reads_one_query(monkeypatch):
    seen = []

    def run(args):
        seen.append(args)
        body = {
            "data": {
                "repository": {
                    "open": {"nodes": [gql_pr(5)]},
                    "p3": gql_pr(3, state="MERGED"),
                }
            }
        }
        return subprocess.CompletedProcess(args, 0, json.dumps(body), "")

    got = gh.fetch("acme/app", [3], run=run)
    assert [r["number"] for r in got["open"]] == [5] and got["linked"][3]["merge"] == "merged"
    (args,) = seen
    assert args[:2] == ["api", "graphql"] and "p3: pullRequest(number: 3)" in args[3]
    assert "mutation" not in " ".join(args)  # read-only


def test_gh_fetch_errors_are_plain():
    def fail(stderr):
        return lambda args: subprocess.CompletedProcess(args, 1, "", stderr)

    import pytest

    with pytest.raises(gh.GhError, match="gh auth login"):
        gh.fetch("acme/app", run=fail("To get started with GitHub CLI, please run:  gh auth login"))
    with pytest.raises(gh.GhError, match="does not exist"):
        gh.fetch("acme/app", run=fail("GraphQL: Could not resolve to a Repository"))
    with pytest.raises(gh.GhError, match="repository name"):
        gh.fetch("acme/app; rm -rf /")
