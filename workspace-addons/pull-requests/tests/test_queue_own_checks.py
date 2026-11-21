"""A pull request's own checks (ORCH-1377): still running = it waits in line and holds up nobody; red = its failed
jobs run again once; red again = it leaves with the failed check and its first failing test."""

from __future__ import annotations

from test_queue import FakeGit, FakeGitHub, make, states, url

from orch_pull_requests import blame, store

JOB = "https://github.com/acme/app/actions/runs/77/job/{}"


class OwnChecks(FakeGitHub):
    """checks: number -> {"failed": [names], "pending": [names]}; a rerun turns the failed ones to `after`."""

    def __init__(self, prs, checks, after=None):
        super().__init__(prs)
        self.checks, self.after = checks, after or {}
        self.reruns: list[tuple[str, int]] = []
        self.logs_read: list[str] = []

    def own_checks(self, u):
        n = int(u.rsplit("/", 1)[1])
        c = self.checks.get(n, {})
        return {
            "failed": [{"name": x, "link": JOB.format(n)} for x in c.get("failed", [])],
            "pending": list(c.get("pending", [])),
        }

    def rerun_failed(self, repo, run):
        self.reruns.append((repo, run))
        for n, c in list(self.checks.items()):
            if c.get("failed") and n in self.after:
                self.checks[n] = self.after[n]
        return True

    def first_failure(self, link):
        self.logs_read.append(link)
        return "FAILED tests/test_views.py::test_board - AssertionError"


def _row(ws, n):
    return store.find(store.read(ws), url(n))


def test_running_own_checks_keep_it_waiting_in_its_place_and_the_others_go_on(ws):
    for n in (1, 2, 3):
        store.add(ws, url(n), None, "agent:t", login="bot")
    gh = OwnChecks({1: {}, 2: {}, 3: {}}, {1: {"pending": ["workspace / test"]}})
    r, _ = make(ws, gh, FakeGit())
    batch = r.next_batch()
    assert [e["number"] for e in batch] == [2, 3]  # #1 holds up nobody
    row = _row(ws, 1)
    assert row["state"] == "waiting" and "still running" in row["why"] and row.get("tries", 0) == 0
    r.process(batch)
    assert states(ws) == {1: "waiting", 2: "merged", 3: "merged"}
    gh.checks[1] = {}  # its checks ended green: taken in the next round, not dropped
    r.run()
    assert states(ws)[1] == "merged"


def test_a_failed_check_while_others_still_run_is_not_dropped_yet(ws):
    store.add(ws, url(1), None, "agent:t", login="bot")
    gh = OwnChecks({1: {}}, {1: {"failed": ["addons / dashboard"], "pending": ["workspace / test"]}})
    r, _ = make(ws, gh, FakeGit())
    assert r.next_batch() == []
    row = _row(ws, 1)
    assert row["state"] == "waiting" and "addons / dashboard failed: run again once" in row["why"]
    assert gh.reruns == []  # a rerun waits until the run ended


def test_a_red_own_check_runs_again_once_and_a_green_rerun_merges(ws):
    store.add(ws, url(1), None, "agent:t", login="bot")
    gh = OwnChecks({1: {}}, {1: {"failed": ["addons / dashboard"]}}, after={1: {}})
    lines = []
    r, _ = make(ws, gh, FakeGit(), log=lines.append)
    assert r.next_batch() == []
    row = _row(ws, 1)
    assert gh.reruns == [("acme/app", 77)] and row["state"] == "waiting"
    assert row["rerun_head"] == f"{1:040d}" and "runs it again once" in row["why"]
    r.run()
    assert states(ws) == {1: "merged"} and len(gh.reruns) == 1


def test_red_again_after_its_rerun_it_leaves_naming_the_check_and_the_first_failing_test(ws, woke):
    store.add(ws, url(1), "t_abc123", "agent:t", login="bot")
    gh = OwnChecks({1: {}}, {1: {"failed": ["addons / dashboard"]}})  # the rerun stays red
    r, _ = make(ws, gh, FakeGit())
    r.run()
    row = _row(ws, 1)
    assert len(gh.reruns) == 1 and row["state"] == "out"
    assert "failed again after one rerun: addons / dashboard" in row["why"]
    assert "first failing test: FAILED tests/test_views.py::test_board" in row["why"]
    assert row["red_head"] == f"{1:040d}"


def test_a_new_commit_gets_its_own_rerun(ws):
    store.add(ws, url(1), None, "agent:t", login="bot")
    store.set_state(ws, url(1), store.WAITING, "x", rerun_head="0" * 40)  # the rerun was for an older head
    gh = OwnChecks({1: {}}, {1: {"failed": ["lint"]}})
    r, _ = make(ws, gh, FakeGit())
    assert r.next_batch() == [] and len(gh.reruns) == 1 and _row(ws, 1)["state"] == "waiting"


def test_no_rerun_possible_leaves_at_once_with_the_check_named(ws):
    store.add(ws, url(1), None, "agent:t", login="bot")
    gh = OwnChecks({1: {}}, {1: {"failed": ["lint"]}})
    gh.rerun_failed = lambda repo, run: False  # GitHub refused it
    r, _ = make(ws, gh, FakeGit())
    r.next_batch()
    row = _row(ws, 1)
    assert row["state"] == "out" and "Checks of" in row["why"] and ": lint; first failing test" in row["why"]


def test_no_room_for_the_rerun_waits_without_a_try(ws):
    store.add(ws, url(1), None, "agent:t", login="bot")
    gh = OwnChecks({1: {}}, {1: {"failed": ["lint"]}})
    r, _ = make(ws, gh, FakeGit())
    r._take = lambda kind, what: False
    r.next_batch()
    row = _row(ws, 1)
    assert gh.reruns == [] and row["state"] == "waiting" and "room in the write limit" in row["why"]
    assert not row.get("rerun_head")


def test_first_failure_reads_the_first_failure_line_without_the_gh_prefix():
    log = (
        "test\tRun pytest\t2026-11-21T10:00:00Z collected 30 items\n"
        "test\tRun pytest\t2026-11-21T10:01:00Z FAILED tests/test_a.py::test_one - assert 1 == 2\n"
        "test\tRun pytest\t2026-11-21T10:01:00Z FAILED tests/test_b.py::test_two\n"
    )
    assert blame.first_failure(log) == "FAILED tests/test_a.py::test_one - assert 1 == 2"
    assert blame.first_failure("all good") == ""


class TwoRuns(OwnChecks):
    """Failed checks in two workflow runs (77 and 88)."""

    def own_checks(self, u):
        c = self.checks.get(1, {})
        rows = [
            {"name": x, "link": f"https://github.com/acme/app/actions/runs/{run}/job/1"}
            for x, run in c.get("failed", [])
        ]
        return {"failed": rows, "pending": list(c.get("pending", []))}


def test_a_rerun_that_fails_fast_while_others_still_run_waits_for_them(ws):
    """Outside review: red again in one job while the rerun's other jobs run: it waits for all of them."""
    store.add(ws, url(1), None, "agent:t", login="bot")
    store.set_state(ws, url(1), store.WAITING, "x", rerun_head=f"{1:040d}", rerun_runs=["77"])
    gh = OwnChecks({1: {}}, {1: {"failed": ["lint"], "pending": ["workspace / test"]}})
    r, _ = make(ws, gh, FakeGit())
    assert r.next_batch() == [] and _row(ws, 1)["state"] == "waiting"


def test_each_workflow_run_gets_its_own_rerun_when_another_was_refused(ws):
    """Outside review: run 77's rerun refused, 88's started; 88 still red later is 'again', 77 never retried."""
    store.add(ws, url(1), None, "agent:t", login="bot")
    gh = TwoRuns({1: {}}, {1: {"failed": [("lint", 77), ("tests", 88)]}})
    gh.rerun_failed = lambda repo, run: (gh.reruns.append(run), run == 88)[1]
    r, _ = make(ws, gh, FakeGit())
    assert r.next_batch() == [] and gh.reruns == [77, 88]
    assert _row(ws, 1)["rerun_runs"] == ["77", "88"]
    r.clock = lambda: 10**9
    r.next_batch()
    row = _row(ws, 1)
    assert gh.reruns == [77, 88] and row["state"] == "out" and "again after one rerun" in row["why"]


def test_no_room_for_a_second_run_keeps_its_rerun_for_later(ws):
    store.add(ws, url(1), None, "agent:t", login="bot")
    gh = TwoRuns({1: {}}, {1: {"failed": [("lint", 77), ("tests", 88)]}})
    gh.rerun_failed = lambda repo, run: (gh.reruns.append(run), True)[1]
    r, _ = make(ws, gh, FakeGit())
    slots = iter([True, False])
    r._take = lambda kind, what: next(slots, False)
    r.next_batch()
    assert gh.reruns == [77] and _row(ws, 1)["rerun_runs"] == ["77"]
    r._take = lambda kind, what: True
    r.clock = lambda: 10**9
    r.next_batch()
    assert gh.reruns == [77, 88] and _row(ws, 1)["state"] == "waiting"
