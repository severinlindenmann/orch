"""ORCH-450: every merge is checked in a queue group; a change to CI or to the queue itself runs alone, and one a
person merges is only checked (proof run), then marked for the person's Merge card."""

from __future__ import annotations

from test_queue import FakeGit, FakeGitHub, make, states, url

from orch_pull_requests import runner, settings, store
from orch_pull_requests.github import MARK, GitHub


def add(ws, *nums, ticket=None):
    for n in nums:
        store.add(ws, url(n), ticket, "agent:t", login="bot")


def members(gh, calls):
    return [gh.groups[c] for c in calls]


def test_a_ci_change_waits_for_a_group_of_its_own_and_the_others_go_on(ws):
    add(ws, 1, 2, 3)
    gh = FakeGitHub({1: {}, 2: {"files": [".github/actions/setup/action.yml"]}, 3: {}})
    r, calls = make(ws, gh, FakeGit())
    r.run()
    assert members(gh, calls) == [[1, 3], [2]] and set(states(ws).values()) == {"merged"}


def test_a_queue_change_first_in_line_runs_alone_before_the_others(ws):
    add(ws, 1, 2, 3)
    gh = FakeGitHub({1: {"files": ["workspace-addons/pull-requests/src/x.py"]}, 2: {}, 3: {}})
    r, calls = make(ws, gh, FakeGit())
    r.run()
    assert members(gh, calls) == [[1], [2, 3]] and set(states(ws).values()) == {"merged"}


def test_a_red_ci_change_alone_leaves_and_blames_nobody_else(ws):
    add(ws, 1, 2)
    gh = FakeGitHub({1: {"files": ["workspace/src/orch/prwait.py"]}, 2: {}})
    r, calls = make(ws, gh, FakeGit(), red_on_base={1})
    r.run()
    assert members(gh, calls) == [[1], [2]] and states(ws) == {1: "out", 2: "merged"}
    assert "queue group was red" in store.find(store.read(ws), url(1))["why"]


def test_too_many_files_to_see_all_runs_alone_and_a_person_merges_it(ws):
    add(ws, 1, 2)
    gh = FakeGitHub({1: {"files": [f"src/f{i}.py" for i in range(100)]}, 2: {}})
    r, calls = make(ws, gh, FakeGit())
    r.run()
    assert members(gh, calls) == [[1], [2]] and states(ws) == {1: "out", 2: "merged"}
    assert gh.prs[1].get("state", "OPEN") == "OPEN"  # a workflow could hide among the files GitHub left out


def test_the_alone_paths_can_be_set(ws):
    assert ".github/" in settings.alone_paths(ws)
    (ws / ".orch" / "config.toml").write_text(
        '[pull_requests]\nalone_paths = ["/infra/"]\n', encoding="utf-8"
    )
    assert settings.alone_paths(ws) == ["infra/"]


def test_a_workflow_change_is_proved_alone_never_merged_and_gets_the_owners_card(ws):
    add(ws, 1, 2, ticket="t_abc123")
    asked = []
    gh = FakeGitHub({1: {"files": [".github/workflows/ci.yml"]}, 2: {}})
    r, calls = make(ws, gh, FakeGit(), ask=lambda root, tid, u: asked.append((tid, u)) or "ORCH-9")
    r.run()
    assert members(gh, calls) == [[1], [2]] and states(ws) == {1: "out", 2: "merged"}
    assert gh.prs[1].get("state", "OPEN") == "OPEN"  # the queue never merges what the owner merges
    assert asked == [("t_abc123", url(1))]
    assert (f"{1:040d}", "Checked green in a queue group on top of develop") in gh.marks  # its head is marked
    row = store.find(store.read(ws), url(1))
    assert "checked green in its own queue group" in row["why"] and "Merge card on ORCH-9" in row["why"]
    assert gh.closed == [calls[0]]  # the proof group itself is closed, its branch deleted
    assert calls[0].rsplit("/", 1)[0] and gh.deleted


def test_a_red_proof_run_leaves_without_a_mark_or_a_card(ws):
    add(ws, 1, ticket="t_abc123")
    asked = []
    gh = FakeGitHub({1: {"files": [".github/CODEOWNERS"]}})
    r, _ = make(ws, gh, FakeGit(), red_on_base={1}, ask=lambda *a: asked.append(a) or "X")
    r.run()
    assert states(ws) == {1: "out"} and not asked
    assert all(sha == "c" * 40 for sha, _ in gh.marks)  # only the group commit, never the pull request head


def test_a_proved_pull_request_without_a_ticket_says_a_person_merges_it_on_github(ws):
    add(ws, 1)
    gh = FakeGitHub({1: {"files": [".github/workflows/ci.yml"]}})
    r, _ = make(ws, gh, FakeGit())
    r.run()
    assert "a person merges it on GitHub" in store.find(store.read(ws), url(1))["why"]


def test_no_mark_on_the_group_commit_means_no_group_run(ws):
    add(ws, 1, 2)
    gh = FakeGitHub({1: {}, 2: {}})
    gh.set_status = lambda *a, **k: False
    r, calls = make(ws, gh, FakeGit())
    r.run()
    assert calls == [] and states(ws) == {1: "out", 2: "out"}
    assert "mark was not set" in store.find(store.read(ws), url(1))["why"]


def test_owner_change_reads_workflows_and_code_owners():
    assert runner.owner_change({"files": [{"path": ".github/workflows/ci.yml"}]})
    assert runner.owner_change({"files": [{"path": ".github/CODEOWNERS"}]})
    assert runner.owner_change({"files": [{"path": "docs/CODEOWNERS"}]})
    assert runner.owner_change({"files": [{"path": ".github/workflows/README.md"}]})
    assert not runner.owner_change({"files": [{"path": ".github/actions/a.yml"}]})
    assert runner.owner_change({})  # GitHub listed no files: a person merges it (fails closed)


def test_github_sets_and_reads_the_mark(monkeypatch):
    gh = GitHub.__new__(GitHub)
    ran = []

    class Got:
        returncode = 0
        stdout = '{"statuses": [{"context": "orch/merge-queue", "state": "success"}]}'

    monkeypatch.setattr(gh, "_run", lambda *a, **k: ran.append(a) or Got())
    assert gh.set_status("acme/app", "a" * 40, "Built by the orch merge queue", "https://x/pull/5")
    args = ran[0]
    assert "repos/acme/app/statuses/" + "a" * 40 in args and f"context={MARK}" in args
    assert "state=success" in args and "target_url=https://x/pull/5" in args
    assert gh.has_mark("acme/app", "a" * 40) is True
