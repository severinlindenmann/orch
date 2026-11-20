"""A red group is split by what failed, not blindly in halves; merge_alone off checks a lone one in a group (ORCH-545)."""

from __future__ import annotations

from test_queue import FakeGit, FakeGitHub, make, states, url

from orch_pull_requests import blame, store


class NamedChecks(FakeGitHub):
    """A group's failed checks have names: the check of the area the bad member touches."""

    def __init__(self, prs, failed_names):
        super().__init__(prs)
        self.failed_names = failed_names

    def failed_checks(self, u):
        members = self.groups.get(u)
        if members is None:  # a member's own checks
            return frozenset({"light"}) if self.prs[int(u.rsplit("/", 1)[1])].get("failed") else frozenset()
        return self.failed_names


TEN = [1, 2, 3, 4, 5, 6, 7, 8, 10, 11]  # the fake GitHub never shows #9


def _ten(bad_files=("workspace-addons/dashboard/clickthrough/features/g-github.cjs",)):
    prs = {n: {"files": (f"workspace-addons/sync/src/orch_sync/m{n}.py",)} for n in TEN}
    prs[7] = {"files": bad_files}
    return prs


def test_suspects_are_the_members_sharing_most_words_with_the_failed_checks():
    failed = ["addons / dashboard-clickthroughs"]
    members = [
        ("a", ["workspace-addons/sync/src/x.py"]),  # addons: 1
        ("b", ["workspace-addons/dashboard/clickthrough/run.cjs"]),  # addons, dashboard: 2
        ("c", ["docs/x.md"]),
    ]
    assert blame.suspects(failed, members) == ["b"]


def test_no_suspects_when_nothing_tells_them_apart():
    assert blame.suspects([], [("a", ["x"]), ("b", ["y"])]) == []
    assert (
        blame.suspects(["clock / suites"], [("a", ["src/a.py"]), ("b", ["src/b.py"])]) == []
    )  # no shared word
    ws_fail = ["workspace / test (ubuntu-latest, 1/2)"]
    assert (
        blame.suspects(ws_fail, [("a", ["workspace/src/a.py"]), ("b", ["workspace/src/b.py"])]) == []
    )  # all
    assert blame.suspects(["addons / sync"], [("a", ["workspace-addons/sync/x.py"])]) == []  # one member


def test_a_red_group_of_ten_runs_the_nine_first_and_the_suspect_alone(ws):
    """Done-when of ORCH-558: the member touching the failing area alone, the other 9 merge, 2 more full runs."""
    for n in TEN:
        store.add(ws, url(n), None, "agent:t", login="bot")
    gh = NamedChecks(_ten(), frozenset({"addons / dashboard-clickthroughs"}))
    lines = []
    r, calls = make(ws, gh, FakeGit(), red_on_base={7}, log=lines.append)
    (ws / ".orch").mkdir(exist_ok=True)
    (ws / ".orch" / "config.toml").write_text("[pull_requests]\nmax_group = 10\nmerge_alone = false\n")
    r.run()
    assert [gh.groups[c] for c in calls] == [TEN, [n for n in TEN if n != 7], [7]]
    assert states(ws) == {**{n: "merged" for n in TEN if n != 7}, 7: "out"}
    assert any("#7 touch that; the other 9 run again first" in x for x in lines)


def test_a_green_group_of_ten_merges_all_ten_after_one_run(ws):
    """Done-when of ORCH-557: 10 waiting, one group of 10 on top of develop, one full run, all 10 merged."""
    (ws / ".orch").mkdir(exist_ok=True)
    (ws / ".orch" / "config.toml").write_text("[pull_requests]\nmax_group = 10\nmerge_alone = false\n")
    for n in TEN:
        store.add(ws, url(n), None, "agent:t", login="bot")
    gh, git = FakeGitHub(_ten()), FakeGit()
    r, calls = make(ws, gh, git)
    r.run()
    assert len(calls) == 1 and gh.groups[calls[0]] == TEN  # one group, one run of the checks
    assert gh.direct == [] and len(git.pushed) == 1  # no member merged on its own light checks
    assert git.pushed[0].startswith("orch-queue/develop-")  # built on top of develop
    assert states(ws) == {n: "merged" for n in TEN}


def test_without_a_telling_check_name_a_red_group_is_split_in_halves(ws):
    for n in range(1, 5):
        store.add(ws, url(n), None, "agent:t", login="bot")
    gh = NamedChecks({n: {} for n in range(1, 5)}, frozenset({"clock / suites"}))
    r, calls = make(ws, gh, FakeGit(), red_on_base={3})
    r.run()
    assert [gh.groups[c] for c in calls][:3] == [[1, 2, 3, 4], [1, 2], [3, 4]]


def test_merge_alone_off_checks_a_lone_green_pull_request_in_a_group_of_its_own(ws):
    """Its own checks are only the light set: no direct merge, a group run on top of the base counts."""
    (ws / ".orch").mkdir(exist_ok=True)
    (ws / ".orch" / "config.toml").write_text("[pull_requests]\nmerge_alone = false\n")
    store.add(ws, url(1), None, "agent:t", login="bot")
    gh, git = FakeGitHub({1: {"fresh": True}}), FakeGit()
    r, calls = make(ws, gh, git)
    r.run()
    assert gh.direct == [] and len(calls) == 1 and gh.groups[calls[0]] == [1]
    assert states(ws) == {1: "merged"} and len(git.pushed) == 1


def test_merge_alone_is_on_by_default_and_reads_only_true_or_false(ws):
    from orch_pull_requests import settings

    assert settings.merge_alone(ws) is True
    (ws / ".orch").mkdir(exist_ok=True)
    (ws / ".orch" / "config.toml").write_text('[pull_requests]\nmerge_alone = "no"\n')
    assert settings.merge_alone(ws) is True


def test_the_checks_clock_restarts_when_a_smaller_group_is_opened(ws, monkeypatch):
    """ORCH-914: after a red split the member's 'checks running' time counts from its new group, not the first."""
    for n in range(1, 5):
        store.add(ws, url(n), None, "agent:t", login="bot")
    ticks = iter(f"2026-11-19T10:{m:02d}:00Z" for m in range(60))
    monkeypatch.setattr(store, "now", lambda: next(ticks))
    seen = {}
    real = store.set_state

    def spy(root, u, state, why, **extra):
        if "group" in extra and extra["group"]:
            seen.setdefault(u, []).append(extra.get("taken"))
        return real(root, u, state, why, **extra)

    monkeypatch.setattr(store, "set_state", spy)
    gh = NamedChecks({n: {} for n in range(1, 5)}, frozenset({"clock / suites"}))
    r, _calls = make(ws, gh, FakeGit(), red_on_base={3})
    r.run()
    assert len(seen[url(1)]) >= 2 and None not in seen[url(1)]
    assert len(set(seen[url(1)])) == len(seen[url(1)])  # a new start time for every group it was in
