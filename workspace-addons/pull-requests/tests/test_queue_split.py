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


def test_a_red_group_of_ten_runs_the_suspect_alone_first_then_the_nine(ws):
    """Done-when of ORCH-558: the member touching the failing area alone, the other 9 merge, 2 more full runs.
    ORCH-1377: the suspect is checked alone first."""
    for n in TEN:
        store.add(ws, url(n), None, "agent:t", login="bot")
    gh = NamedChecks(_ten(), frozenset({"addons / dashboard-clickthroughs"}))
    lines = []
    r, calls = make(ws, gh, FakeGit(), red_on_base={7}, log=lines.append)
    (ws / ".orch").mkdir(exist_ok=True)
    (ws / ".orch" / "config.toml").write_text("[pull_requests]\nmax_group = 10\nmerge_alone = false\n")
    r.run()
    assert [gh.groups[c] for c in calls] == [TEN, [7], [n for n in TEN if n != 7]]
    assert states(ws) == {**{n: "merged" for n in TEN if n != 7}, 7: "out"}
    assert any("#7 touch that and run alone first; the other 9 after" in x for x in lines)


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


CT_LOG = """addons / dashboard-clickthroughs\tRun\t2026-11-20T20:44:32Z FAILED  Relay: message a workspace (m-relay-chat.cjs, 34.9s)
addons / dashboard-clickthroughs\tRun\t2026-11-20T20:44:32Z         no Share with group button (at m-relay-chat.cjs:63: await x)
workspace / test\tRun\t2026-11-20T20:44:33Z FAILED tests/test_sessions.py::test_one - assert 1 == 2
workspace / test\tRun\t2026-11-20T20:44:33Z ERROR workspace-addons/sync/tests/test_card.py::test_x
workspace / test\tRun\t2026-11-20T20:44:33Z some line naming other.py that is not a failure
"""


def test_failed_tests_are_read_from_the_failure_lines_of_a_log():
    """As `gh run view --log-failed` prints them (job, step, time in front) and as plain lines."""
    want = ["m-relay-chat.cjs", "test_sessions.py", "test_card.py"]
    assert blame.failed_tests(CT_LOG) == want  # other.py is on no failure line
    assert blame.failed_tests("\n".join(x.split("Z ", 1)[1] for x in CT_LOG.splitlines())) == want
    assert blame.failed_tests("") == []


def test_the_failed_test_file_picks_the_suspect_where_the_check_name_matches_everyone():
    """ORCH-1118: 'dashboard-clickthroughs' shares 'dashboard' with every dashboard member; the failed
    click-through m-relay-chat.cjs names the one that changed the relay chat."""
    failed = ["addons / dashboard-clickthroughs"]
    members = [
        ("a", ["workspace-addons/dashboard/src/orch_dashboard/static/home.js"]),
        ("b", ["workspace-addons/dashboard/src/orch_dashboard/static/relay_chat.js"]),
        ("c", ["workspace-addons/dashboard/src/orch_dashboard/static/sync.js"]),
    ]
    assert blame.suspects(failed, members) == []  # the check name alone tells nobody apart
    assert blame.suspects(failed, members, ["m-relay-chat.cjs"]) == ["b"]
    # a test file nobody touches: the check names decide as before
    assert blame.suspects(["addons / sync"], [("a", ["workspace-addons/sync/x.py"]), ("b", ["docs/y.md"])],
                          ["test_zzz.py"]) == ["a"]  # fmt: skip


class FailedTests(NamedChecks):
    def failed_tests(self, u):
        return ["m-relay-chat.cjs"] if u in self.groups else []


def test_a_red_group_splits_off_the_member_its_failed_test_names(ws):
    prs = {
        n: {"files": (f"workspace-addons/dashboard/src/orch_dashboard/static/p{n}.js",)} for n in range(1, 5)
    }
    prs[3] = {"files": ("workspace-addons/dashboard/src/orch_dashboard/static/relay_chat.js",)}
    for n in range(1, 5):
        store.add(ws, url(n), None, "agent:t", login="bot")
    gh = FailedTests(prs, frozenset({"addons / dashboard-clickthroughs"}))
    lines = []
    r, calls = make(ws, gh, FakeGit(), red_on_base={3}, log=lines.append)
    r.run()
    assert [gh.groups[c] for c in calls][:3] == [[1, 2, 3, 4], [3], [1, 2, 4]]
    assert any("(m-relay-chat.cjs)" in x and "#3 touch that" in x for x in lines)


def test_a_member_of_a_red_group_is_never_merged_alone_on_its_light_checks(ws):
    """ORCH-909: merge_alone on (default): the one that broke the group is checked again in a group of its own."""
    for n in (2, 3):
        store.add(ws, url(n), None, "agent:t", login="bot")
    gh = NamedChecks({n: {"fresh": True} for n in (2, 3)}, frozenset({"clock / suites"}))
    r, calls = make(ws, gh, FakeGit(), red_on_base={3})
    r.run()
    assert gh.direct == []  # neither merged on its own light checks
    assert [gh.groups[c] for c in calls][:3] == [[2, 3], [2], [3]]
    assert states(ws) == {2: "merged", 3: "out"}


def test_queue_remove_takes_out_a_member_waiting_for_its_part_of_a_split_but_not_one_being_checked(ws):
    """ORCH-1377 (#2170 on 21 Nov had to be made a draft): a member of a red group that waits for its part may
    leave with `queue remove`; one in the part being checked now may not."""
    import pytest

    from orch_pull_requests.store import Refused

    for n in (1, 2, 3, 4):
        store.add(ws, url(n), None, "agent:t", login="bot")
    gh = FakeGitHub({n: {} for n in (1, 2, 3, 4)})
    r, calls = make(ws, gh, FakeGit(), bad={1})
    seen = {}
    inner = r.waiter

    def waiter(u, before_merge=None, merge=True):
        if u in gh.groups and gh.groups[u] == [1, 2]:  # the first part runs; [3, 4] waits for its turn
            with pytest.raises(Refused):
                store.remove(ws, url(1), "human:p")
            seen["out"] = store.remove(ws, url(4), "human:p")
        return inner(u, before_merge, merge)

    r.waiter = waiter
    r.run()
    assert seen == {"out": True}
    assert [gh.groups[c] for c in calls][:2] == [[1, 2, 3, 4], [1, 2]]
    assert all(4 not in gh.groups[c] for c in calls[1:])  # never checked or merged after it was taken out
    got = states(ws)
    assert got[4] == "out" and got[3] == "merged" and got[1] == "out"
    assert "taken out by human:p" in store.find(store.read(ws), url(4))["why"]


def test_a_member_left_by_a_stopped_runner_loses_its_split_mark(ws):
    store.add(ws, url(1), None, "agent:t", login="bot")
    store.set_state(ws, url(1), store.RUNNING, "its group was red", split=True)
    store.back_to_front(ws, [url(1)], "the last runner stopped")
    assert "split" not in store.find(store.read(ws), url(1))


def test_imports_reads_python_and_javascript_imports():
    src = (
        "from orch import reads, needs as n\nfrom orch.tickets import load\nimport orch_dashboard.views\n"
        "from . import helpers\nconst x = require('../src/board.js')\nimport y from './util.mjs'\n"
    )
    got = blame.imports(src)
    for want in ("orch/reads", "orch/needs", "orch/tickets", "orch/tickets/load", "orch_dashboard/views",
                 "helpers", "board", "util"):  # fmt: skip
        assert want in got, want


def test_the_suite_imports_name_the_core_member_not_the_one_sharing_words():
    """ORCH-1377 (21 Nov, twice): a core change in reads.py broke a dashboard add-on test; the word guess blamed
    the dashboard member. The failing suite imports orch.reads: the core member is the suspect."""
    members = [
        ("core", ["workspace/src/orch/reads.py", "workspace/src/orch/needs.py"]),
        ("dash", ["workspace-addons/dashboard/src/orch_dashboard/static/board.js"]),
        ("docs", ["docs/x.md"]),
    ]
    tests = ["test_dashboard_board.py"]
    assert blame.suspects([], members, tests) == ["dash"]  # the words alone: wrong
    src = {
        "workspace-addons/dashboard/tests/test_dashboard_board.py": "from orch import reads\nimport json\n"
    }
    assert blame.suspects([], members, tests, src) == ["core"]
    # a member that changes the failing test file itself is a suspect too
    members.append(("test", ["workspace-addons/dashboard/tests/test_dashboard_board.py"]))
    assert blame.suspects([], members, tests, src) == ["core", "test"]


class ImportGit(FakeGit):
    def sources(self, sha, names):
        self.asked = (sha, list(names))
        return {"workspace-addons/dashboard/tests/test_board.py": "from orch import reads\n"}


class BoardTests(NamedChecks):
    def failed_tests(self, u):
        return ["test_board.py"] if u in self.groups else []


def test_a_red_group_checks_the_member_the_failing_suite_imports_alone_first(ws):
    prs = {
        n: {"files": (f"workspace-addons/dashboard/src/orch_dashboard/static/p{n}.js",)} for n in (1, 2, 3)
    }
    prs[2] = {"files": ("workspace/src/orch/reads.py",)}
    for n in (1, 2, 3):
        store.add(ws, url(n), None, "agent:t", login="bot")
    gh, git = BoardTests(prs, frozenset({"addons / dashboard"})), ImportGit()
    lines = []
    r, calls = make(ws, gh, git, red_on_base={2}, log=lines.append)
    r.run()
    assert [gh.groups[c] for c in calls][:3] == [[1, 2, 3], [2], [1, 3]]
    assert git.asked == ("c" * 40, ["test_board.py"])
    assert states(ws) == {1: "merged", 2: "out", 3: "merged"}
    assert any("#2 touch that and run alone first" in x for x in lines)


def test_the_clock_restarts_when_a_red_group_is_split(ws):
    for n in (1, 2):
        store.add(ws, url(n), None, "agent:t", login="bot")
    store.claim(ws, store.waiting(ws))
    rows = store.read(ws)
    for r in rows:
        r["taken"] = "2000-01-01T00:00:00Z"
        r["split"] = True
    store.change(ws, lambda cur: cur.__setitem__(slice(None), rows))
    store.start_part(ws, [url(2)])
    assert store.find(store.read(ws), url(2))["taken"] != "2000-01-01T00:00:00Z"
    assert store.find(store.read(ws), url(1))["taken"] == "2000-01-01T00:00:00Z"
