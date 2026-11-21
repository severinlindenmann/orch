"""A queue group red only in known flaky checks runs its failed jobs again once before it is split (ORCH-1340).

21 Nov: 3 of 4 red groups failed only in the factory-dashboard clock run and the dashboard checks; the members
blamed for it merged green later, and each such red cost 2-3 extra full runs."""

from __future__ import annotations

from test_queue import REPO, FakeGit, FakeGitHub, Outcome, make, states, url

from orch_pull_requests import settings, store

FLAKY = ["addons / dashboard", "clock / *"]
CLOCK = "clock / at 22:30:00 UTC (factory-dashboard)"


def _config(ws, flaky=FLAKY, extra=""):
    lines = ["[pull_requests]", "max_group = 10"]
    if flaky is not None:
        lines.append("flaky_checks = [" + ", ".join(f'"{x}"' for x in flaky) + "]")
    (ws / ".orch" / "config.toml").write_text("\n".join(lines) + "\n" + extra, encoding="utf-8")


class GroupChecks(FakeGitHub):
    """runs: the check results of each run of the FIRST group, in order: [{"failed": [...], "pending": [...]}, ...]
    (runs[i] after i reruns); later groups (the parts of a split) are green; a member's own checks are green."""

    def __init__(self, prs, runs):
        super().__init__(prs)
        self.runs, self.reruns, self.looks = runs, [], 0
        self.ended_after = 0  # looks before pending checks of a run end (and become `then` of that run)

    def _run(self, u):
        if not self.groups or u != next(iter(self.groups)):
            return {}
        return self.runs[min(len(self.reruns), len(self.runs) - 1)]

    def own_checks(self, u):
        self.looks += 1
        c = self._run(u)
        pending = list(c.get("pending", []))
        failed = list(c.get("failed", []))
        if pending and self.looks > self.ended_after:  # the running checks ended
            failed += list(c.get("then", []))
            c["failed"], c["pending"] = failed, []
            pending = []
        job = f"https://github.com/{REPO}/actions/runs/{77 + len(self.reruns)}/job/1"
        return {"failed": [{"name": x, "link": job} for x in failed], "pending": pending}

    def failed_checks(self, u):
        return frozenset(self._run(u).get("failed", []))

    def rerun_failed(self, repo, run):
        self.reruns.append((repo, run))
        return True


def _go(ws, runs, n=(1, 2, 3), ended_after=0):
    for x in n:
        store.add(ws, url(x), None, "agent:t", login="bot")
    gh = GroupChecks({x: {} for x in n}, runs)
    gh.ended_after = ended_after
    r, calls = make(ws, gh, FakeGit())

    def waiter(u, before_merge=None, merge=True, stop=None):
        if u in gh.groups:
            calls.append(u)
            if gh._run(u).get("failed") or gh._run(u).get("pending"):
                return Outcome(u, False, "checks failed", f"Checks of {u}: NOT green")
        held = before_merge and before_merge(gh.pr(u)["headRefOid"])
        if held:
            return Outcome(u, False, "held", f"not merged: {held}")
        for m in gh.groups.get(u) or [int(u.rsplit("/", 1)[1])]:
            gh.prs[m]["state"] = "MERGED"
        gh.gstate[u] = "MERGED"
        return Outcome(u, True, "merged", f"Merged {u} on green checks.")

    r.waiter = waiter
    return r, gh, calls


def test_a_group_red_only_in_flaky_checks_runs_them_again_once_and_merges_without_a_split(ws):
    _config(ws)
    r, gh, calls = _go(ws, [{"failed": ["addons / dashboard", CLOCK, "gate"]}, {}])
    r.run()
    assert gh.reruns == [(REPO, 77)]
    assert len(set(calls)) == 1 and len(calls) == 2  # one group, its checks waited for twice, no split
    assert states(ws) == {1: "merged", 2: "merged", 3: "merged"}
    assert gh.closed == []  # the group pull request stayed open for the rerun


def test_red_again_after_the_rerun_is_split_as_before_and_never_run_again_a_second_time(ws):
    _config(ws)
    red = {"failed": ["addons / dashboard", "gate"]}
    r, gh, calls = _go(ws, [red, red])  # the rerun is red too; the parts after the split are green
    r.run()
    assert gh.reruns == [(REPO, 77)]  # once for the first group only
    assert [gh.groups[c] for c in dict.fromkeys(calls)][:1] == [[1, 2, 3]]
    assert len(set(calls)) > 1  # it was split
    assert states(ws) == {1: "merged", 2: "merged", 3: "merged"}


def test_a_group_also_red_in_a_check_that_is_not_flaky_is_split_without_a_rerun(ws):
    _config(ws)
    r, gh, calls = _go(
        ws, [{"failed": ["addons / dashboard", "workspace / test (ubuntu-latest, 1/2)", "gate"]}]
    )
    r.process(r.next_batch())
    assert gh.reruns == [] and calls.count(calls[0]) == 1 and len(set(calls)) > 1  # split at once


def test_without_the_setting_every_red_group_is_split_as_before(ws):
    _config(ws, flaky=None)
    r, gh, calls = _go(ws, [{"failed": ["addons / dashboard", "gate"]}])
    r.process(r.next_batch())
    assert gh.reruns == [] and calls.count(calls[0]) == 1 and len(set(calls)) > 1


def test_a_group_red_only_in_the_summary_check_is_not_called_flaky(ws):
    _config(ws)
    r, gh, _ = _go(ws, [{"failed": ["gate"]}])
    r.process(r.next_batch())
    assert gh.reruns == []


def test_a_fast_flaky_failure_waits_for_the_other_checks_and_a_later_real_failure_splits(ws):
    """The waiter can say red at the first failure; the rerun is decided only once every check ended."""
    _config(ws)
    runs = [{"failed": [CLOCK], "pending": ["workspace / test"], "then": ["workspace / test"]}]
    r, gh, calls = _go(ws, runs, ended_after=3)
    r.process(r.next_batch())
    assert gh.reruns == []  # workspace / test failed too once it ended: not only flaky
    assert calls.count(calls[0]) == 1 and len(set(calls)) > 1


def test_a_fast_flaky_failure_whose_other_checks_end_green_is_run_again(ws):
    _config(ws)
    runs = [{"failed": [CLOCK], "pending": ["workspace / test"]}, {}]
    r, gh, calls = _go(ws, runs, ended_after=3)
    r.run()
    assert gh.reruns == [(REPO, 77)] and len(calls) == 2
    assert states(ws) == {1: "merged", 2: "merged", 3: "merged"}


def test_a_refused_rerun_splits_the_group(ws):
    _config(ws)
    r, gh, calls = _go(ws, [{"failed": ["addons / dashboard"]}])
    gh.rerun_failed = lambda repo, run: (gh.reruns.append((repo, run)), False)[1]
    log: list[str] = []
    r.log = log.append
    r.process(r.next_batch())
    assert gh.reruns == [(REPO, 77)] and calls.count(calls[0]) == 1 and len(set(calls)) > 1
    assert any("not all run again" in x for x in log)


def test_only_flaky_matches_names_with_a_star_and_ignores_case_and_summary_checks(ws):
    _config(ws, extra="")
    assert settings.flaky_checks(ws) == FLAKY and settings.summary_checks(ws) == ["gate"]
    assert settings.only_flaky(ws, {"Addons / Dashboard", "clock / at 23:59:40 UTC (workspace)", "gate"})
    assert not settings.only_flaky(ws, {"addons / dashboard-clickthroughs"})  # no star: the exact name only
    assert not settings.only_flaky(ws, set())
    assert not settings.only_flaky(ws, {"gate"})
    _config(ws, flaky=["e2e-smoke / *"], extra='summary_checks = ["gate", "all green"]\n')
    assert settings.only_flaky(ws, {"e2e-smoke / smoke", "all green"})


def test_a_failure_that_is_not_flaky_splits_at_once_without_waiting_for_the_running_checks(ws):
    """Outside review: a real failure next to a slow check must not hold the split for up to an hour."""
    _config(ws)
    runs = [{"failed": ["workspace / test (ubuntu-latest, 1/2)"], "pending": ["clock / suites"]}]
    r, gh, _ = _go(ws, runs, ended_after=10**6)  # the running check never ends
    slept: list[float] = []
    r.sleep = slept.append
    gh.groups["https://github.com/acme/app/pull/500"] = [1, 2, 3]
    o = Outcome("https://github.com/acme/app/pull/500", False, "checks failed", "NOT green")
    assert r.flaky_rerun(REPO, "https://github.com/acme/app/pull/500", o, []) is False
    assert slept == [] and gh.reruns == []


def test_a_partly_refused_rerun_splits_the_group(ws):
    """Outside review: one workflow run rerun, another refused: the refused one stays red, so it is split."""
    _config(ws)
    g = "https://github.com/acme/app/pull/500"
    r, gh, _ = _go(ws, [{"failed": ["addons / dashboard", CLOCK]}])
    gh.groups[g] = [1, 2, 3]
    job = "https://github.com/acme/app/actions/runs/{}/job/1"
    gh.own_checks = lambda u: {"failed": [{"name": "addons / dashboard", "link": job.format(77)},
                                          {"name": CLOCK, "link": job.format(88)}], "pending": []}  # fmt: skip
    gh.rerun_failed = lambda repo, run: (gh.reruns.append(run), run == 77)[1]
    o = Outcome(g, False, "checks failed", "NOT green")
    assert r.flaky_rerun(REPO, g, o, []) is False
    assert gh.reruns == [77, 88]


def test_a_follower_whose_lead_failed_is_not_run_again(ws):
    _config(ws)
    g = "https://github.com/acme/app/pull/500"
    r, gh, _ = _go(ws, [{"failed": ["addons / dashboard"]}])
    gh.groups[g] = [1, 2, 3]
    o = Outcome(g, False, "checks failed", "NOT green")
    assert r.flaky_rerun(REPO, g, o, [], stop=lambda: "the group before it was not merged") is False
    assert gh.reruns == []
