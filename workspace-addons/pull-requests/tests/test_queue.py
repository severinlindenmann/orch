"""The merge queue: store, group commit (real git), runner (fake GitHub and fake core waiter), commands."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from orch_pull_requests import cli, runner, store
from orch_pull_requests.group import Git
from orch_pull_requests.store import Refused

REPO = "acme/app"


def url(n: int) -> str:
    return f"https://github.com/{REPO}/pull/{n}"


# -- store -----------------------------------------------------------------------------------------------
def test_add_keeps_order_and_never_twice(ws):
    _, new_a = store.add(ws, url(1), None, "agent:t")
    store.add(ws, url(2) + " ", None, "agent:t")
    again, new = store.add(ws, url(1), "t_abc123", "agent:t")
    assert new_a and not new and again["ticket"] == "t_abc123"
    assert [r["number"] for r in store.read(ws)] == [1, 2]
    assert all(r["state"] == "waiting" for r in store.read(ws))


def test_refuses_what_is_no_pull_request(ws):
    with pytest.raises(Refused):
        store.add(ws, "https://github.com/acme/app/issues/3", None, "agent:t")


def test_remove_and_back_to_front(ws):
    for n in (1, 2, 3):
        store.add(ws, url(n), None, "agent:t")
    assert store.remove(ws, url(1), "human:p")
    assert not store.remove(ws, url(1), "human:p")
    store.set_state(ws, url(3), store.RUNNING, "in a group")
    with pytest.raises(Refused):
        store.remove(ws, url(3), "human:p")
    store.back_to_front(ws, [url(3)], "again")
    assert [r["number"] for r in store.waiting(ws)] == [3, 2]
    # a finished entry can be queued again as a new one
    store.add(ws, url(1), None, "agent:t")
    assert [r["state"] for r in store.read(ws) if r["number"] == 1] == ["out", "waiting"]


def test_lock_held_by_a_dead_process_is_taken_over(ws):
    lock = store.folder(ws) / "queue.lock"
    lock.mkdir(parents=True)
    (lock / "owner").write_text("999999 2001-01-01T00:00:00Z", encoding="utf-8")
    store.add(ws, url(1), None, "agent:t")
    assert not lock.exists()


# -- group commit with real git ----------------------------------------------------------------------------
def _git(cwd: Path, *args: str) -> str:
    env_args = ["-c", "user.name=T", "-c", "user.email=t@example.invalid", "-c", "init.defaultBranch=develop"]
    return subprocess.run(
        ["git", *env_args, *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _make_prs(work: Path) -> Path:
    bare = work.parent / "origin.git"
    _git(work.parent, "clone", "-q", "--bare", str(work), str(bare))
    for n in (1, 2, 3, 4):
        sha = _git(bare, "rev-parse", f"refs/heads/pr{n}")
        _git(bare, "update-ref", f"refs/pull/{n}/head", sha)
    return bare


@pytest.fixture
def bare(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("no git")
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q")
    (work / "a.txt").write_text("a\n", encoding="utf-8")
    (work / "shared.txt").write_text("one\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "base")
    base = _git(work, "rev-parse", "HEAD")
    for n, (name, text) in {1: ("b.txt", "b\n"), 2: ("c.txt", "c\n"), 3: ("shared.txt", "three\n"),
                            4: ("shared.txt", "four\n")}.items():  # fmt: skip
        _git(work, "checkout", "-q", "-B", f"pr{n}", base)
        (work / name).write_text(text, encoding="utf-8")
        _git(work, "add", name)
        _git(work, "commit", "-q", "-m", f"pr {n}")
    _git(work, "checkout", "-q", "develop")
    return _make_prs(work)


def test_group_commit_takes_in_clean_heads_and_leaves_conflicts_out(ws, bare):
    git = Git(store.folder(ws), REPO, url=str(bare))
    heads = git.fetch("develop", [1, 2, 3, 4])
    sha, included, conflicted = git.build(heads["base"], [(n, heads[str(n)]) for n in (1, 2, 3, 4)])
    assert included == [1, 2, 3] and conflicted == [4]
    git.push(sha, "orch-queue/develop-1")
    files = _git(bare, "ls-tree", "--name-only", "orch-queue/develop-1").split()
    assert sorted(files) == ["a.txt", "b.txt", "c.txt", "shared.txt"]
    assert _git(bare, "show", "orch-queue/develop-1:shared.txt") == "three"
    # every pull request head is in the group, so GitHub marks it merged once the group is merged
    for n in (1, 2, 3):
        _git(bare, "merge-base", "--is-ancestor", heads[str(n)], "orch-queue/develop-1")


# -- runner with fakes ---------------------------------------------------------------------------------------
@dataclass
class Outcome:
    url: str
    ok: bool
    status: str
    line: str


class FakeGitHub:
    def __init__(self, prs: dict[int, dict]):
        self.prs = prs  # number -> {state, isDraft, failed}
        self.groups: dict[str, list[int]] = {}
        self.closed, self.deleted = [], []

    def pr(self, u):
        if "/pull/9" in u:
            return None
        n = int(u.rsplit("/", 1)[1])
        p = self.prs[n]
        return {"state": p.get("state", "OPEN"), "isDraft": p.get("isDraft", False), "baseRefName": "develop",
                "isCrossRepository": p.get("fork", False),
                "headRefOid": f"{n:040d}", "number": n, "title": f"Change {n}",
                "closingIssuesReferences": [{"number": 100 + n, "repository": {"name": "app", "owner": {"login": "acme"}}}]}  # fmt: skip

    def own_checks_failed(self, u):
        return self.prs[int(u.rsplit("/", 1)[1])].get("failed", False)

    def create_pr(self, repo, base, branch, title, body):
        g = f"https://github.com/{repo}/pull/{500 + len(self.groups)}"
        self.groups[g] = [int(x) for x in title.split(":", 1)[1].replace("#", "").split(",")]
        self.bodies = getattr(self, "bodies", []) + [body]
        return g

    def close(self, u):
        self.closed.append(u)
        return True

    def delete_branch(self, repo, branch):
        self.deleted.append(branch)
        return True


class FakeGit:
    def __init__(self, conflicts=(), push_fails=False):
        self.conflicts, self.push_fails, self.pushed = set(conflicts), push_fails, []

    def fetch(self, base, nums):
        return {"base": "b" * 40, **{str(n): f"{n:040d}" for n in nums}}

    def build(self, base_sha, heads):
        inc = [n for n, _ in heads if n not in self.conflicts]
        return "c" * 40, inc, [n for n, _ in heads if n in self.conflicts]

    def push(self, sha, branch):
        if self.push_fails:
            raise Refused("push refused")
        self.pushed.append(branch)


def make(ws, gh, git, bad=(), log=None):
    calls = []
    t = [1000.0]

    def sleep(secs):
        t[0] += secs

    def waiter(u):
        calls.append(u)
        members = gh.groups.get(u) or [int(u.rsplit("/", 1)[1])]
        if any(m in bad for m in members):
            return Outcome(u, False, "checks failed", f"Checks of {u}: NOT green")
        for m in members:
            gh.prs[m]["state"] = "MERGED"
        return Outcome(u, True, "merged", f"Merged {u} on green checks.")

    r = runner.Runner(ws, gh, lambda repo: git, waiter=waiter, take=lambda k, w: True,
                      log=(log if log is not None else (lambda s: None)), clock=lambda: t[0], sleep=sleep)  # fmt: skip
    return r, calls


def states(ws):
    return {r["number"]: r["state"] for r in store.read(ws)}


def test_one_pull_request_goes_to_the_core_waiter(ws):
    store.add(ws, url(1), None, "agent:t")
    gh = FakeGitHub({1: {}})
    r, calls = make(ws, gh, FakeGit())
    r.run()
    assert calls == [url(1)] and states(ws) == {1: "merged"} and not gh.groups


def test_a_green_group_merges_all_with_one_check_run(ws):
    for n in (1, 2, 3):
        store.add(ws, url(n), None, "agent:t")
    gh, git = FakeGitHub({1: {}, 2: {}, 3: {}}), FakeGit()
    r, calls = make(ws, gh, git)
    r.run()
    assert len(calls) == 1 and gh.groups[calls[0]] == [1, 2, 3]
    assert states(ws) == {1: "merged", 2: "merged", 3: "merged"}
    assert git.pushed == ["orch-queue/develop-1000"] and gh.deleted == ["orch-queue/develop-1000"]
    assert "Closes #101" in gh.bodies[0] and "#3 `Change 3`" in gh.bodies[0]
    assert all("with the group" in x["why"] for x in store.read(ws))


def test_a_red_group_is_split_and_the_good_ones_still_merge(ws):
    for n in (1, 2, 3, 4):
        store.add(ws, url(n), None, "agent:t")
    gh = FakeGitHub({n: {} for n in (1, 2, 3, 4)})
    r, calls = make(ws, gh, FakeGit(), bad={3})
    r.run()
    assert states(ws) == {1: "merged", 2: "merged", 3: "out", 4: "merged"}
    assert len(gh.closed) == 2  # [1,2,3,4] and [3,4] were red
    assert calls[-2:] == [url(3), url(4)]  # the last half of two ran one by one


def test_entries_that_cannot_be_merged_leave_with_a_reason(ws):
    for n in (1, 2, 3, 4, 9):
        store.add(ws, url(n), None, "agent:t")
    gh = FakeGitHub(
        {1: {"state": "MERGED"}, 2: {"state": "CLOSED"}, 3: {"isDraft": True}, 4: {"failed": True}}
    )
    r, calls = make(ws, gh, FakeGit())
    r.run()
    rows = {x["number"]: x for x in store.read(ws)}
    assert states(ws) == {1: "merged", 2: "out", 3: "out", 4: "out", 9: "out"} and not calls
    assert "draft" in rows[3]["why"] and "Checks" in rows[4]["why"] and "did not show" in rows[9]["why"]


def test_a_conflicting_pull_request_runs_alone_after_the_group(ws):
    for n in (1, 2, 3):
        store.add(ws, url(n), None, "agent:t")
    gh = FakeGitHub({1: {}, 2: {}, 3: {}})
    r, calls = make(ws, gh, FakeGit(conflicts={2}))
    r.run()
    assert gh.groups[calls[0]] == [1, 3] and calls[1] == url(2)
    assert states(ws) == {1: "merged", 2: "merged", 3: "merged"}
    assert "conflicted" in {x["number"]: x for x in store.read(ws)}[2]["why"]


def test_a_group_that_cannot_be_pushed_is_retried_then_leaves(ws):
    for n in (1, 2):
        store.add(ws, url(n), None, "agent:t")
    gh = FakeGitHub({1: {}, 2: {}})
    r, calls = make(ws, gh, FakeGit(push_fails=True))
    r.run()
    rows = store.read(ws)
    assert states(ws) == {1: "out", 2: "out"} and not calls
    assert all(f"after {runner.MAX_TRIES} tries" in x["why"] for x in rows)


def test_a_pull_request_with_a_new_commit_waits_again(ws):
    for n in (1, 2):
        store.add(ws, url(n), None, "agent:t")
    gh = FakeGitHub({1: {}, 2: {}})
    r, _ = make(ws, gh, FakeGit())
    real = r.waiter

    def waiter(u):
        o = real(u)
        if u in gh.groups:
            gh.prs[2]["state"] = "OPEN"  # its new head is not in the group
        return o

    r.waiter = waiter
    batch = r.next_batch()
    assert r.group(batch) == []  # nothing red
    assert states(ws) == {1: "merged", 2: "waiting"}


def test_the_verdict_goes_on_the_ticket(ws, monkeypatch):
    from orch import tickets

    seen = []
    monkeypatch.setattr(tickets, "note_history", lambda root, tid, by, text: seen.append(("h", tid, text)))
    monkeypatch.setattr(tickets, "ref_set", lambda root, tid, u, status, by: seen.append(("r", tid, status)))
    store.add(ws, url(1), "t_abc123", "agent:t")
    r, _ = make(ws, FakeGitHub({1: {}}), FakeGit())
    r.run()
    assert ("r", "t_abc123", "merged") in seen and any(k == "h" for k, *_ in seen)


# -- commands --------------------------------------------------------------------------------------------
def test_add_list_remove_commands(ws, monkeypatch, capsys):
    started = []
    monkeypatch.setattr(cli, "start_runner", lambda root: started.append(root))
    assert cli.main(["queue", "add", url(1)]) == 0
    assert "Added to the merge queue" in capsys.readouterr().out and started
    assert cli.main(["queue", "add", url(2), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ahead"] == 1
    assert cli.main(["queue", "list", "--json"]) == 0
    assert [r["number"] for r in json.loads(capsys.readouterr().out)["entries"]] == [1, 2]
    assert cli.main(["queue", "remove", url(1)]) == 0
    assert cli.main(["queue", "add", "not a url"]) == 2


def test_wait_reports_the_end(ws, monkeypatch, capsys):
    monkeypatch.setattr(cli, "start_runner", lambda root: None)
    store.add(ws, url(1), None, "agent:t")
    store.set_state(ws, url(1), store.MERGED, "Merged it with the group.")
    assert cli._wait(ws, url(1), 1, False) == 0
    assert "Merged it" in capsys.readouterr().out


def test_only_one_runner_holds_the_lock(ws):
    assert cli._hold_runner(ws) and cli.runner_alive(ws)
    assert not cli._hold_runner(ws)
    store._drop_lock(cli._runner_lock(ws))
    assert not cli.runner_alive(ws)


def test_a_pull_request_with_a_merge_card_on_any_ticket_is_never_merged_here(ws, monkeypatch):
    monkeypatch.setattr(runner, "merge_cards", lambda root: {url(2): "DM1-7"})
    for n in (1, 2):
        store.add(ws, url(n), None, "agent:t")
    r, calls = make(ws, FakeGitHub({1: {}, 2: {}}), FakeGit())
    r.run()
    assert calls == [url(1)] and states(ws) == {1: "merged", 2: "out"}
    assert "Merge card on DM1-7" in store.find(store.read(ws), url(2))["why"]


def test_a_head_that_moved_before_the_fetch_is_left_out_of_the_group(ws):
    for n in (1, 2, 3):
        store.add(ws, url(n), None, "agent:t")
    gh, git = FakeGitHub({1: {}, 2: {}, 3: {}}), FakeGit()
    real = git.fetch
    pushed = {"done": False}

    def fetch(base, nums):
        out = real(base, nums)
        if not pushed["done"] and "2" in out:
            pushed["done"] = True
            out["2"] = "f" * 40  # someone pushed to #2 between the look and the fetch
        return out

    git.fetch = fetch
    r, calls = make(ws, gh, git)
    r.run()
    assert gh.groups[calls[0]] == [1, 3] and calls[1] == url(2)
    assert states(ws) == {1: "merged", 2: "merged", 3: "merged"}


def test_a_title_cannot_close_issues():
    _, body = runner._group_text([{"number": 1, "title": "Fixes #5, `closes` acme/x#9"}, {"number": 2}])
    assert "- #1 `Fixes #5, 'closes' acme/x#9`" in body and "Closes" not in body


def test_a_fork_pull_request_runs_alone(ws):
    for n in (1, 2, 3):
        store.add(ws, url(n), None, "agent:t")
    gh = FakeGitHub({1: {}, 2: {"fork": True}, 3: {}})
    r, calls = make(ws, gh, FakeGit())
    r.run()
    assert url(2) in calls and all(2 not in g for g in gh.groups.values())
    assert states(ws) == {1: "merged", 2: "merged", 3: "merged"}


def test_entries_a_dead_runner_left_running_go_back_in_line(ws):
    for n in (1, 2):
        store.add(ws, url(n), None, "agent:t")
    store.set_state(ws, url(1), store.RUNNING, "in the group", group="https://github.com/acme/app/pull/77")
    gh = FakeGitHub({1: {}, 2: {}})
    r, _ = make(ws, gh, FakeGit())
    r.run()
    assert gh.closed == ["https://github.com/acme/app/pull/77"]
    assert states(ws) == {1: "merged", 2: "merged"}


def test_no_room_in_the_write_limit_pauses_without_using_up_tries(ws):
    for n in (1, 2):
        store.add(ws, url(n), None, "agent:t")
    gh = FakeGitHub({1: {}, 2: {}})
    r, calls = make(ws, gh, FakeGit())
    refused = {"n": 0}

    def take(kind, what):
        if kind == "other" and "push" in what and refused["n"] < 5:
            refused["n"] += 1
            return False
        return True

    r.take = take
    r.run()
    assert refused["n"] == 5 and states(ws) == {1: "merged", 2: "merged"} and len(calls) == 1


def test_a_removed_entry_is_not_claimed(ws):
    for n in (1, 2):
        store.add(ws, url(n), None, "agent:t")
    rows = store.waiting(ws)
    store.remove(ws, url(2), "human:p")
    assert [b["number"] for b in store.claim(ws, rows)] == [1]


def test_a_crash_puts_the_batch_back_in_line(ws):
    for n in (1, 2):
        store.add(ws, url(n), None, "agent:t")
    gh = FakeGitHub({1: {}, 2: {}})
    git = FakeGit()
    boom = {"n": 0}
    real = git.build

    def build(*a):
        boom["n"] += 1
        if boom["n"] == 1:
            raise KeyError("x")
        return real(*a)

    git.build = build
    r, _ = make(ws, gh, git)
    r.run()
    assert states(ws) == {1: "merged", 2: "merged"}


def test_a_stale_lock_without_owner_is_taken_over(ws):
    import os
    import time

    lock = store.folder(ws) / "queue.lock"
    lock.mkdir(parents=True)
    old = time.time() - 100
    os.utime(lock, (old, old))
    store.add(ws, url(1), None, "agent:t")
    assert not lock.exists() and len(store.read(ws)) == 1


def test_a_damaged_queue_file_is_never_overwritten(ws):
    store.add(ws, url(1), None, "agent:t")
    f = store.folder(ws) / "queue.json"
    f.write_text("{not json", encoding="utf-8")
    with pytest.raises(Refused):
        store.add(ws, url(2), None, "agent:t")
    assert f.read_text(encoding="utf-8") == "{not json"
