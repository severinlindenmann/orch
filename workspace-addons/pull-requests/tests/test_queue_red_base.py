"""The merge queue on a red base branch (ORCH-391): no groups, fixes first, nobody blamed for the base's failures."""

from __future__ import annotations

import json

import pytest
from test_queue import FakeGit, FakeGitHub, make, states, url

from orch_pull_requests import runner, store
from orch_pull_requests.github import GitHub

RED = frozenset({"lint", "addons / page-smoke"})


class RedGitHub(FakeGitHub):
    """prs[n]['jobs']: the checks that fail when n is red (its own checks with 'failed', or a group with n)."""

    def __init__(self, prs, red=(RED,)):
        super().__init__(prs)
        self.answers = list(red)  # one per look at the base branch; the last one stays
        self.looks = 0

    def base_failed(self, repo, base):
        self.looks += 1
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]

    def failed_checks(self, u):
        members = self.groups.get(u) or [int(u.rsplit("/", 1)[1])]
        out = set()
        for m in members:
            p = self.prs[m]
            if p.get("failed") or p.get("ran_red") or u in self.groups:
                out |= set(p.get("jobs", {"own"}))
        return frozenset(out)


def add(ws, n, **kw):
    store.add(ws, url(n), kw.pop("ticket", None), "agent:t", login="bot", base="develop", **kw)


def row(ws, n):
    return next(r for r in reversed(store.read(ws)) if r["number"] == n)


def test_red_base_builds_no_groups_and_the_fix_goes_first(ws):
    for n in (1, 2, 3):
        add(ws, n)
    add(ws, 4, first=True)  # the fix of develop, added last
    gh = RedGitHub({n: {} for n in (1, 2, 3, 4)})
    r, calls = make(ws, gh, FakeGit())
    r.run()
    assert not gh.groups  # every one alone: no group run on top of red develop
    assert calls[0] == url(4) and states(ws) == {1: "merged", 2: "merged", 3: "merged", 4: "merged"}


def test_first_goes_ahead_of_the_line_but_behind_earlier_fixes(ws):
    add(ws, 1)
    add(ws, 2)
    add(ws, 3, first=True)
    add(ws, 4, first=True)
    assert [r["number"] for r in store.waiting(ws)] == [3, 4, 1, 2]
    _, new = store.add(ws, url(2), None, "agent:t", first=True)  # already waiting: moved up, not twice
    assert not new and [r["number"] for r in store.waiting(ws)] == [3, 4, 2, 1]


def test_own_checks_red_only_where_develop_is_red_wait_without_a_try(ws):
    add(ws, 1)
    add(ws, 2)
    gh = RedGitHub({1: {"failed": True, "jobs": {"lint"}}, 2: {"failed": True, "jobs": {"lint", "unit"}}})
    r, _ = make(ws, gh, FakeGit())
    assert r.next_batch() == []
    one, two = row(ws, 1), row(ws, 2)
    assert one["state"] == "waiting" and not one.get("tries") and "same checks" in one["why"]
    assert float(one["not_before"]) > 1000
    assert two["state"] == "out"  # 'unit' is green on develop: its own failure


def test_a_red_group_in_the_base_branchs_checks_is_not_split(ws, monkeypatch):
    monkeypatch.setattr(runner, "RED_LOOK_SECS", 0)
    for n in (1, 2, 3):
        add(ws, n)
    # develop looked green when the round began; the group then failed exactly where develop now fails
    gh = RedGitHub({n: {"jobs": {"addons / page-smoke"}} for n in (1, 2, 3)}, red=(frozenset(), RED))
    r, calls = make(ws, gh, FakeGit(), red_on_base={1, 2, 3})
    batch = r.next_batch()
    assert len(batch) == 3
    r.process(batch)
    assert len(calls) == 1 and len(gh.groups) == 1  # one run, no halves
    assert all(row(ws, n)["state"] == "waiting" and not row(ws, n).get("tries") for n in (1, 2, 3))


def test_a_red_group_with_other_failures_is_still_split(ws, monkeypatch):
    monkeypatch.setattr(runner, "RED_LOOK_SECS", 0)
    for n in (1, 2):
        add(ws, n)
    gh = RedGitHub({1: {"jobs": {"unit"}}, 2: {}}, red=(frozenset(), RED))
    r, _ = make(ws, gh, FakeGit(), bad={1})
    r.process(r.next_batch())
    assert states(ws) == {1: "out", 2: "merged"}


def test_a_fix_still_red_in_the_same_checks_uses_a_try(ws):
    add(ws, 1, first=True)
    gh = RedGitHub({1: {"jobs": {"lint"}}})
    r, calls = make(ws, gh, FakeGit(), bad={1})
    batch = r.next_batch()
    gh.prs[1]["ran_red"] = True  # its checks ran and failed where develop fails
    r.process(batch)
    assert calls == [url(1)] and row(ws, 1)["state"] == "waiting" and row(ws, 1)["tries"] == 1


def test_behind_waits_for_green_base_instead_of_a_doomed_check(ws):
    add(ws, 1)
    gh = RedGitHub({1: {}})
    r, _ = make(ws, gh, FakeGit(), behind={1})
    r.process(r.next_batch())
    assert not gh.groups and row(ws, 1)["state"] == "waiting" and "is red" in row(ws, 1)["why"]


def test_base_looked_at_once_a_minute(ws):
    add(ws, 1)
    gh = RedGitHub({1: {"failed": True, "jobs": {"lint"}}})
    r, _ = make(ws, gh, FakeGit())
    r.red_base("acme/app", "develop")
    r.red_base("acme/app", "develop")
    assert gh.looks == 1


def test_release_keeper_red_ticket_counts_as_the_fix(ws):
    from orch import config, tickets

    role = tickets.create(ws, "Role: Release keeper", "human:p")
    red = tickets.create(
        ws, "Fix red CI on develop", "agent:release-keeper", parent=role["id"],
        fields={"done_when": "The next ci run on develop is green"},
    )  # fmt: skip
    deploy = tickets.create(
        ws, "Deploy release 3", "agent:release-keeper", parent=role["id"],
        fields={"done_when": "The production health checks answer"},
    )  # fmt: skip
    other = tickets.create(ws, "Something", "agent:claude", fields={"done_when": "it is green"})
    config.path(ws).parent.mkdir(parents=True, exist_ok=True)
    config.path(ws).write_text(f'[github]\nrelease_keeper = "{role["id"]}"\n', encoding="utf-8")
    assert runner._release_fix(ws, red["id"])
    assert not runner._release_fix(ws, deploy["id"])
    assert not runner._release_fix(ws, other["id"])
    assert not runner._release_fix(ws, None)


def test_github_reads_the_failed_jobs_of_the_last_finished_push_run(monkeypatch):
    gh = GitHub.__new__(GitHub)
    runs = [
        {"databaseId": 5, "workflowName": "ci", "status": "in_progress", "conclusion": ""},
        {"databaseId": 4, "workflowName": "ci", "status": "completed", "conclusion": "cancelled"},
        {"databaseId": 3, "workflowName": "ci", "status": "completed", "conclusion": "failure"},
        {"databaseId": 2, "workflowName": "ci", "status": "completed", "conclusion": "success"},
        {"databaseId": 1, "workflowName": "docs", "status": "completed", "conclusion": "success"},
    ]
    jobs = {"jobs": [{"name": "lint", "conclusion": "failure"}, {"name": "unit", "conclusion": "success"},
                     {"name": "slow", "conclusion": "timed_out"}]}  # fmt: skip
    asked = []

    def fake(*args):
        asked.append(args)
        return runs if args[:2] == ("run", "list") else jobs

    monkeypatch.setattr(gh, "_json", fake)
    assert gh.base_failed("acme/app", "develop") == {"lint", "slow"}
    assert [a[2] for a in asked if a[:2] == ("run", "view")] == ["3"]
    runs[2]["conclusion"] = "success"
    assert gh.base_failed("acme/app", "develop") == frozenset()
    monkeypatch.setattr(gh, "_json", lambda *a: None)
    assert gh.base_failed("acme/app", "develop") is None


def test_github_never_reads_twenty_unfinished_runs_as_green(monkeypatch):
    gh = GitHub.__new__(GitHub)
    going = [{"databaseId": n, "workflowName": "ci", "status": "in_progress"} for n in range(20)]
    monkeypatch.setattr(gh, "_json", lambda *a: going)
    assert gh.base_failed("acme/app", "develop") is None
    monkeypatch.setattr(gh, "_json", lambda *a: going[:3])  # only three runs at all, none finished: green
    assert gh.base_failed("acme/app", "develop") == frozenset()


def test_a_finished_entry_added_again_first_is_the_one_found(ws):
    add(ws, 1)
    add(ws, 2)
    store.set_state(ws, url(2), store.OUT, "checks failed")
    again, new = store.add(ws, url(2), None, "agent:t", first=True, login="bot", base="develop")
    assert new and store.find(store.read(ws), url(2))["state"] == "waiting"
    assert [r["number"] for r in store.claim(ws, [again])] == [2]


def test_a_pull_request_moved_to_a_red_base_is_checked_there(ws, monkeypatch):
    monkeypatch.setattr(runner.settings, "bases", lambda root: ["develop", "next"])
    for n in (1, 2):
        add(ws, n)
    gh = RedGitHub({1: {"base": "next"}, 2: {"base": "next"}})
    gh.base_failed = lambda repo, base: RED if base == "next" else frozenset()
    r, _ = make(ws, gh, FakeGit())
    assert [e["number"] for e in r.next_batch()] == [1]  # one at a time: no group on top of red 'next'


def test_github_failed_check_names(monkeypatch):
    gh = GitHub.__new__(GitHub)

    class Got:
        returncode = 8
        stdout = json.dumps([{"name": "lint", "bucket": "fail"}, {"name": "unit", "bucket": "pass"}])

    monkeypatch.setattr(gh, "_run", lambda *a, **k: Got())
    assert gh.failed_checks("u") == {"lint"} and gh.own_checks_failed("u")


@pytest.fixture(autouse=True)
def _no_release_keeper(monkeypatch, request):
    if request.node.name != "test_release_keeper_red_ticket_counts_as_the_fix":
        monkeypatch.setattr(runner, "_release_fix", lambda root, tid: False)
