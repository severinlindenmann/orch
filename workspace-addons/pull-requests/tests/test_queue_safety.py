"""The merge queue's safety rules, with real git and the real core waiter (orch.prwait.run_one).

A stand-in for GitHub (World) keeps its pull requests in a real bare repository: a head is refs/pull/N/head, a
merge writes a real merge commit onto develop, and a pull request counts as merged once its head is on develop,
as GitHub marks it. So "it never landed" below is a real `git merge-base --is-ancestor` on develop.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from orch import prwait
from orch.errors import Refused as CoreRefused

from orch_pull_requests import cli, runner, settings, store
from orch_pull_requests.group import Git
from orch_pull_requests.store import Refused

REPO = "acme/app"
GREEN = {"name": "test", "state": "SUCCESS", "bucket": "pass"}
RED = {"name": "test", "state": "FAILURE", "bucket": "fail"}


def url(n: int) -> str:
    return f"https://github.com/{REPO}/pull/{n}"


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    pre = ["-c", "user.name=T", "-c", "user.email=t@example.invalid", "-c", "init.defaultBranch=develop"]
    return subprocess.run(["git", *pre, *args], cwd=cwd, check=check, capture_output=True, text=True)


def out(cwd: Path, *args: str) -> str:
    return git(cwd, *args).stdout.strip()


class World:
    """GitHub for the runner (pr, login, create_pr, close, delete_branch) and for the core waiter (Src)."""

    def __init__(self, bare: Path, numbers=(1, 2, 3, 4)):
        self.bare = bare
        self.prs = {n: {"state": "OPEN", "isDraft": False, "base": "develop", "review": ""} for n in numbers}
        self.groups: dict[str, dict] = {}
        self.me = "bot"
        self.bad: set[int] = set()
        self.on_wait = None  # called with the url when the core waiter first looks at checks
        self.hiccups: dict[str, int] = {}  # what -> how many times GitHub does not answer

    def hiccup(self, what: str) -> bool:
        if getattr(self, "down", 0) > 0:  # GitHub is down: every call fails until the outage ends
            self.down -= 1
            return True
        if self.hiccups.get(what, 0) > 0:
            self.hiccups[what] -= 1
            return True
        return False

    # -- git ------------------------------------------------------------------------------------------
    def head(self, n: int) -> str:
        return out(self.bare, "rev-parse", f"refs/pull/{n}/head")

    def landed(self, n: int) -> bool:
        return (
            git(self.bare, "merge-base", "--is-ancestor", self.head(n), "develop", check=False).returncode
            == 0
        )

    def queue_branches(self) -> list[str]:
        return out(self.bare, "for-each-ref", "--format=%(refname:short)", "refs/heads/orch-queue").split()

    def merge(self, u: str, head: str) -> bool:
        g = self.groups.get(u)
        state = g["state"] if g else self.prs[int(u.rsplit("/", 1)[1])]["state"]
        want = g["head"] if g else self.head(int(u.rsplit("/", 1)[1]))
        if state != "OPEN" or head != want:
            return False
        into = g["base"] if g else self.prs[int(u.rsplit("/", 1)[1])]["base"]  # GitHub merges into the base
        dev = git(self.bare, "rev-parse", "--verify", "-q", into, check=False).stdout.strip() or out(
            self.bare, "rev-parse", "develop"
        )
        tree = out(self.bare, "merge-tree", "--write-tree", dev, head).splitlines()[0]
        new = out(self.bare, "commit-tree", tree, "-p", dev, "-p", head, "-m", f"Merge {u}")
        out(self.bare, "update-ref", f"refs/heads/{into}", new)
        if g:
            g["state"] = "MERGED"
        for n, p in self.prs.items():  # GitHub marks every pull request whose head is now on develop
            if p["state"] == "OPEN" and self.landed(n):
                p["state"] = "MERGED"
        return True

    # -- the runner's GitHub ----------------------------------------------------------------------------
    def login(self):
        self.logins = getattr(self, "logins", 0) + 1
        return None if self.logins > 1 and self.hiccup("login") else self.me

    def pr(self, u):
        if self.hiccup(f"view {u}"):
            return None
        g = self.groups.get(u)
        if g:
            return {"state": g["state"], "isDraft": False, "baseRefName": g["base"], "headRefOid": g["head"]}
        n = int(u.rsplit("/", 1)[1])
        p = self.prs[n]
        return {"state": p["state"], "isDraft": p["isDraft"], "baseRefName": p["base"],
                "reviewDecision": p["review"], "reviews": p.get("reviews", []), "headRefOid": self.head(n), "number": n,
                "title": f"Change {n}", "isCrossRepository": False}  # fmt: skip

    def own_checks_failed(self, u):
        return False

    def create_pr(self, repo, base, branch, title, body):
        u = f"https://github.com/{repo}/pull/{500 + len(self.groups)}"
        members = [int(x) for x in title.split(":", 1)[1].replace("#", "").split(",")]
        head = out(self.bare, "rev-parse", f"refs/heads/{branch}")
        self.groups[u] = {"branch": branch, "base": base, "state": "OPEN", "head": head, "members": members}
        return u

    def close(self, u):
        if self.groups[u]["state"] != "OPEN":
            return False
        self.groups[u]["state"] = "CLOSED"
        return True

    def delete_branch(self, repo, branch):
        git(self.bare, "update-ref", "-d", f"refs/heads/{branch}", check=False)
        return True

    def open_groups(self) -> list[str]:
        return [u for u, g in self.groups.items() if g["state"] == "OPEN"]


class Src(prwait.Replay):
    """The core waiter's view of one pull request in the World: green unless a member is bad."""

    def __init__(self, world: World, u: str):
        super().__init__({"polls": [[GREEN]], "required": []})
        self.w, self.url, self.gh, self.looked = world, u, "/fake/gh", False

    def view(self):
        return self.w.pr(self.url)

    def is_draft(self):
        v = self.view()
        return None if v is None else v["isDraft"]

    def required(self):
        self.fallback = False
        if self.w.hiccup("rules"):
            raise CoreRefused("could not read the rules of the branch develop")
        return []

    def look(self):
        if not self.looked and self.w.on_wait:
            self.looked = True
            self.w.on_wait(self.url)
        g = self.w.groups.get(self.url)
        members = g["members"] if g else [int(self.url.rsplit("/", 1)[1])]
        return [RED if any(m in self.w.bad for m in members) else GREEN], ""

    def landed(self, head, base):
        return []

    def changed_files(self):
        return ["x.txt"]


@pytest.fixture
def world(tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("no git")
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "-q")
    (work / "a.txt").write_text("a\n", encoding="utf-8")
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "base")
    base = out(work, "rev-parse", "HEAD")
    for n in (1, 2, 3, 4):
        git(work, "checkout", "-q", "-B", f"pr{n}", base)
        (work / f"f{n}.txt").write_text(f"{n}\n", encoding="utf-8")
        git(work, "add", f"f{n}.txt")
        git(work, "commit", "-q", "-m", f"pr {n}")
    git(work, "checkout", "-q", "develop")
    bare = tmp_path / "origin.git"
    git(tmp_path, "clone", "-q", "--bare", str(work), str(bare))
    for n in (1, 2, 3, 4):
        git(bare, "update-ref", f"refs/pull/{n}/head", out(bare, "rev-parse", f"refs/heads/pr{n}"))
    w = World(bare)

    def fake_run(argv, timeout=30):
        assert argv[1:3] == ["pr", "merge"], argv
        ok = w.merge(argv[3], argv[argv.index("--match-head-commit") + 1])
        return subprocess.CompletedProcess(argv, 0 if ok else 1, "", "" if ok else "not mergeable")

    monkeypatch.setattr(prwait, "_run", fake_run)
    return w


def make(ws: Path, w: World, take=None, waiter=None, logs=None):
    t = [1000.0]

    def sleep(secs):
        t[0] += secs

    def real_waiter(u, before_merge):
        return prwait.run_one(u, True, src=Src(w, u), before_merge=before_merge)

    return runner.Runner(
        ws, w, lambda repo: Git(store.folder(ws), REPO, url=str(w.bare)), waiter=waiter or real_waiter,
        take=take or (lambda kind, what: True), log=(logs.append if logs is not None else (lambda s: None)),
        clock=lambda: t[0], sleep=sleep,
    )  # fmt: skip


def add(ws: Path, *numbers: int, login: str = "bot") -> None:
    for n in numbers:
        store.add(ws, url(n), None, "agent:t", base="develop", login=login)


def states(ws: Path) -> dict[int, str]:
    return {r["number"]: r["state"] for r in store.read(ws)}


def why(ws: Path, n: int) -> str:
    return store.find(store.read(ws), url(n))["why"]


def nothing_left_behind(ws: Path, w: World) -> None:
    assert w.open_groups() == [] and w.queue_branches() == [] and store.groups(ws) == []


def _review(who: str, state: str) -> dict:
    return {"author": {"login": who}, "state": state}


# -- H1 / M4 / M5: a member that changed while its group ran ------------------------------------------------
CHANGES = {
    "closed": lambda w, ws, cards: w.prs[1].update(state="CLOSED"),
    "draft": lambda w, ws, cards: w.prs[1].update(isDraft=True),
    "retargeted": lambda w, ws, cards: w.prs[1].update(base="release"),
    # develop's rules require no reviews: GitHub leaves reviewDecision empty, only the review itself says it
    # and a later reply in a thread (a COMMENTED review of the same person) does not take it back
    "changes requested": lambda w, ws, cards: w.prs[1].update(
        reviews=[_review("x", "CHANGES_REQUESTED"), _review("x", "COMMENTED"), _review("y", "APPROVED")]
    ),
    "review required": lambda w, ws, cards: w.prs[1].update(review="CHANGES_REQUESTED"),
    "merge card": lambda w, ws, cards: cards.update({runner.pr_key(url(1)): "ORCH-7"}),
}


@pytest.mark.parametrize("change", sorted(CHANGES))
def test_a_member_changed_while_its_group_ran_is_never_merged(ws, world, monkeypatch, change):
    cards: dict = {}
    monkeypatch.setattr(runner, "merge_cards", lambda root: dict(cards))
    add(ws, 1, 2, 3)

    def on_wait(u):
        if u in world.groups and not cards.get("done"):
            cards["done"] = True
            CHANGES[change](world, ws, cards)

    world.on_wait = on_wait
    make(ws, world).run()
    assert not world.landed(1), f"#1 landed on develop after it was {change}"
    assert world.landed(2) and world.landed(3)
    assert states(ws) == {1: "out", 2: "merged", 3: "merged"}
    assert len(world.groups) == 2  # [1,2,3] held before its merge, then [2,3]
    nothing_left_behind(ws, world)


def test_the_reviewers_probe_a_member_closed_during_a_red_group_never_lands(ws, world):
    add(ws, 1, 2, 3, 4)
    world.bad = {3}
    world.on_wait = lambda u: world.prs[1].update(state="CLOSED") if u in world.groups else None
    make(ws, world).run()
    assert not world.landed(1) and not world.landed(3)
    assert world.landed(2) and world.landed(4)
    assert states(ws) == {1: "out", 2: "merged", 3: "out", 4: "merged"}
    assert "closed" in why(ws, 1)
    assert len(world.groups) == 2  # [1,2,3,4] and [3,4]: #1 is looked at again before [1,2] is built
    nothing_left_behind(ws, world)


def test_a_member_closed_after_the_build_is_left_out_before_the_group_opens(ws, world, monkeypatch):
    add(ws, 1, 2, 3)
    real = Git.push

    def push(self, sha, branch):
        real(self, sha, branch)
        world.prs[2]["state"] = "CLOSED"  # between the push and the group pull request

    monkeypatch.setattr(Git, "push", push)
    make(ws, world).run()
    assert not world.landed(2) and world.landed(1) and world.landed(3)
    assert [g["members"] for g in world.groups.values()] == [
        [1, 3]
    ]  # the first branch never got a pull request
    nothing_left_behind(ws, world)


def test_a_single_pull_request_is_looked_at_right_before_its_merge(ws, world, monkeypatch):
    cards: dict = {}
    monkeypatch.setattr(runner, "merge_cards", lambda root: dict(cards))
    add(ws, 1)
    world.on_wait = lambda u: cards.update({runner.pr_key(url(1)): "ORCH-7"})
    make(ws, world).run()
    assert not world.landed(1) and states(ws) == {1: "out"} and "Merge card on ORCH-7" in why(ws, 1)


# -- H2: base branches and the login ---------------------------------------------------------------------------
def _config(ws: Path, text: str) -> None:
    (ws / ".orch" / "config.toml").write_text(text, encoding="utf-8")


def test_only_allowed_base_branches_and_never_main(ws, world):
    assert settings.bases(ws) == ["develop"]
    _config(ws, '[pull_requests]\nbases = ["develop", "main", "Master", "release"]\n')
    assert settings.bases(ws) == ["develop", "release"]
    _config(ws, "")
    world.prs[1]["base"] = "main"
    with pytest.raises(Refused, match="merges only into develop"):
        runner.admit(ws, world, url(1))
    # retargeted to main while it waited: it leaves the queue, nothing lands
    add(ws, 1, 2, 3)
    make(ws, world).run()
    assert states(ws) == {1: "out", 2: "merged", 3: "merged"} and not world.landed(1)
    assert "goes into main" in why(ws, 1)


def test_the_queue_add_command_refuses_main_and_requested_changes(ws, world, monkeypatch, capsys):
    monkeypatch.setattr(cli, "start_runner", lambda root: None)
    monkeypatch.setattr(cli, "_github", lambda: world)
    world.prs[1]["base"] = "main"
    world.prs[2]["review"] = "CHANGES_REQUESTED"
    world.prs[3]["review"] = "REVIEW_REQUIRED"
    world.prs[4]["reviews"] = [_review("x", "CHANGES_REQUESTED"), _review("x", "COMMENTED")]
    assert cli.main(["queue", "add", url(4)]) == 2
    world.prs[4]["reviews"] = [_review("x", "CHANGES_REQUESTED"), _review("x", "APPROVED")]
    assert cli.main(["queue", "add", url(1)]) == 2
    assert cli.main(["queue", "add", url(2)]) == 2
    assert cli.main(["queue", "add", url(3)]) == 2
    assert cli.main(["queue", "add", url(4)]) == 0
    assert [(r["number"], r["base"], r["login"]) for r in store.read(ws)] == [(4, "develop", "bot")]
    err = capsys.readouterr().err
    assert "merges only into develop" in err and "changes were requested" in err and "needs a review" in err


def test_the_runner_checks_its_login_at_start(ws, world):
    add(ws, 1, 2)
    _config(ws, '[pull_requests]\nlogin = "bot"\n')
    world.me = "owner"
    logs: list[str] = []
    r = make(ws, world, logs=logs)
    assert r.run() == 0 and not r.has_work()
    assert states(ws) == {1: "waiting", 2: "waiting"} and not world.groups
    assert any("merges only as bot" in x for x in logs)
    with pytest.raises(Refused, match="merges only as bot"):
        runner.admit(ws, world, url(3))
    world.me = None
    assert make(ws, world).run() == 0 and states(ws) == {1: "waiting", 2: "waiting"}


def test_a_runner_never_merges_what_another_login_added(ws, world):
    add(ws, 1, 2, login="bot")
    world.me = "owner"  # someone else's shell started the runner
    r = make(ws, world)
    r.run()
    assert states(ws) == {1: "waiting", 2: "waiting"} and not world.groups and not r.has_work()
    world.me = "BOT"  # logins do not care about case
    make(ws, world).run()
    assert states(ws) == {1: "merged", 2: "merged"}


# -- M1 / M2: nothing left behind ------------------------------------------------------------------------------
def test_an_error_while_the_group_runs_leaves_no_group_behind(ws, world):
    add(ws, 1, 2, 3)
    first = {"done": False}

    def waiter(u, before_merge):
        if u in world.groups and not first["done"]:
            first["done"] = True
            raise RuntimeError("boom")
        return prwait.run_one(u, True, src=Src(world, u), before_merge=before_merge)

    make(ws, world, waiter=waiter).run()
    assert states(ws) == {1: "merged", 2: "merged", 3: "merged"}
    assert [g["state"] for g in world.groups.values()] == ["CLOSED", "MERGED"]
    nothing_left_behind(ws, world)


def test_a_runner_that_died_mid_group_is_cleaned_up_by_the_next(ws, world):
    add(ws, 1, 2)
    # what a killed runner leaves: a pushed branch with no pull request yet, and an open group pull request
    dev = out(world.bare, "rev-parse", "develop")
    for b in ("orch-queue/develop-1", "orch-queue/develop-2", "orch-queue/develop-3"):
        out(world.bare, "update-ref", f"refs/heads/{b}", dev)
    store.change_group(ws, REPO, "orch-queue/develop-1")
    world.groups[url(90)] = {"branch": "orch-queue/develop-2", "base": "develop", "state": "OPEN",
                             "head": dev, "members": [1, 2]}  # fmt: skip
    store.change_group(ws, REPO, "orch-queue/develop-2", url=url(90))
    world.groups[url(91)] = {"branch": "orch-queue/develop-3", "base": "develop", "state": "MERGED",
                             "head": dev, "members": []}  # fmt: skip
    store.change_group(ws, REPO, "orch-queue/develop-3", url=url(91))
    for n in (1, 2):
        store.set_state(ws, url(n), store.RUNNING, "in the group", group=url(90))
    make(ws, world).run()
    assert world.groups[url(90)]["state"] == "CLOSED"
    assert states(ws) == {1: "merged", 2: "merged"}
    nothing_left_behind(ws, world)


def test_the_group_branch_is_written_down_before_its_push(ws, world, monkeypatch):
    add(ws, 1, 2)
    seen = []
    real = Git.push

    def push(self, sha, branch):
        seen.append([g["branch"] for g in store.groups(ws)])
        real(self, sha, branch)

    monkeypatch.setattr(Git, "push", push)
    make(ws, world).run()
    assert len(seen) == 1 and len(seen[0]) == 1 and seen[0][0].startswith("orch-queue/develop-1000-")
    nothing_left_behind(ws, world)


def test_no_room_to_close_keeps_the_note_and_the_next_runner_closes(ws, world):
    add(ws, 1, 2)
    world.bad = {1, 2}
    full = lambda kind, what: not (" close" in what or " delete " in what)
    make(ws, world, take=full).run()
    assert states(ws) == {1: "out", 2: "out"}
    assert world.open_groups() and world.queue_branches() and store.groups(ws)
    make(ws, world).run()  # room again: the next runner closes and deletes what was left
    nothing_left_behind(ws, world)


# -- M3: a GitHub hiccup is retried, not red ------------------------------------------------------------------
def test_unreadable_rules_are_retried_not_counted_as_red(ws, world):
    add(ws, 1, 2, 3)
    world.hiccups["rules"] = 1
    logs: list[str] = []
    make(ws, world, logs=logs).run()
    assert states(ws) == {1: "merged", 2: "merged", 3: "merged"}
    assert not any("splitting" in x for x in logs)
    assert len(world.groups) == 2  # the first group got no verdict, the second merged
    nothing_left_behind(ws, world)


def test_a_single_pull_request_with_a_hiccup_is_retried(ws, world):
    add(ws, 1)
    world.hiccups["rules"] = 1
    make(ws, world).run()
    assert states(ws) == {1: "merged"} and world.landed(1)


def test_github_not_showing_a_pull_request_once_is_retried(ws, world):
    add(ws, 1, 2)
    world.hiccups[f"view {url(1)}"] = 1
    make(ws, world).run()
    assert states(ws) == {1: "merged", 2: "merged"}


def test_github_never_showing_it_ends_after_the_tries(ws, world):
    add(ws, 1)
    world.hiccups[f"view {url(1)}"] = 99
    make(ws, world).run()
    assert states(ws) == {1: "out"} and f"after {runner.MAX_TRIES} tries" in why(ws, 1)


def test_a_github_outage_uses_up_no_tries(ws, world):
    add(ws, 1, 2)
    for what in (f"view {url(1)}", f"view {url(2)}", "login"):
        world.hiccups[what] = 5  # nothing answers for five rounds, more than MAX_TRIES
    make(ws, world).run()
    assert states(ws) == {1: "merged", 2: "merged"}


def test_a_group_moved_to_another_base_is_never_merged_there(ws, world):
    add(ws, 1, 2)

    def on_wait(u):
        if u in world.groups and world.groups[u]["base"] == "develop" and len(world.groups) == 1:
            world.groups[u]["base"] = "main"  # someone retargets the group pull request itself

    world.on_wait = on_wait
    make(ws, world).run()
    first = next(iter(world.groups.values()))
    assert first["state"] == "CLOSED"
    assert states(ws) == {1: "merged", 2: "merged"}  # merged into develop by the next group
    assert out(world.bare, "for-each-ref", "refs/heads/main") == ""
    nothing_left_behind(ws, world)


def test_an_outage_after_the_first_round_keeps_the_runner_and_the_tries(ws, world):
    add(ws, 1)
    world.on_wait = lambda u: add(ws, 2) if u == url(1) else None  # queued while #1 runs
    real = world.merge

    def merge(u, head):
        done = real(u, head)
        if done and u == url(1):  # then GitHub goes away for a while: nothing answers
            world.down = 12  # the next 12 calls to GitHub (views and logins) get no answer
        return done

    world.merge = merge
    make(ws, world).run()
    assert states(ws) == {1: "merged", 2: "merged"}, why(ws, 2)


def test_a_login_switch_during_the_wait_stops_the_merge(ws, world):
    add(ws, 1, 2)
    world.on_wait = lambda u: setattr(world, "me", "owner") if u in world.groups else None
    make(ws, world).run()
    assert not world.landed(1) and not world.landed(2)
    assert states(ws) == {1: "waiting", 2: "waiting"}
    nothing_left_behind(ws, world)


def test_an_entry_without_a_login_leaves_with_the_reason(ws, world):
    store.add(ws, url(1), None, "agent:t")
    add(ws, 2)
    make(ws, world).run()
    assert states(ws) == {1: "out", 2: "merged"} and "without a login" in why(ws, 1)


def test_a_login_that_never_answers_again_stops_the_runner_with_a_line(ws, world):
    add(ws, 1)
    world.on_wait = lambda u: add(ws, 2) if u == url(1) else None
    real = world.merge

    def merge(u, head):
        done = real(u, head)
        if done and u == url(1):
            world.down = 10**6  # gh is signed out for good
        return done

    world.merge = merge
    logs: list[str] = []
    make(ws, world, logs=logs).run()
    assert states(ws) == {1: "merged", 2: "waiting"}
    assert any("for 30 minutes" in x for x in logs)


def test_a_hold_that_never_clears_uses_up_the_tries(ws, world, monkeypatch):
    add(ws, 1, 2)
    real = runner.Runner.why_not_group
    monkeypatch.setattr(runner.Runner, "why_not_group", lambda self, u, b, h: "the group looks wrong")
    make(ws, world).run()
    monkeypatch.setattr(runner.Runner, "why_not_group", real)
    assert states(ws) == {1: "out", 2: "out"} and f"after {runner.MAX_TRIES} tries" in why(ws, 1)
    assert not world.landed(1) and not world.landed(2)
    nothing_left_behind(ws, world)


def test_two_workspaces_never_share_a_group_branch(tmp_path, world):
    for name in ("ws-a", "ws-b"):  # both build their group in the same second (the fake clock)
        root = tmp_path / name
        (root / ".orch" / "tickets").mkdir(parents=True)
        for n in (1, 2):
            world.prs[n]["state"] = "OPEN"
            store.add(root, url(n), None, "agent:t", base="develop", login="bot")
        make(root, world).run()
    branches = [g["branch"] for g in world.groups.values()]
    assert len(branches) == 2 and len(set(branches)) == 2


def test_a_real_red_member_still_leaves(ws, world):
    add(ws, 1, 2)
    world.bad = {2}
    make(ws, world).run()
    assert states(ws) == {1: "merged", 2: "out"} and not world.landed(2)
    nothing_left_behind(ws, world)


# -- L2: one spelling per pull request ------------------------------------------------------------------------
def test_one_entry_whatever_the_case_of_the_address(ws):
    store.add(ws, "https://github.com/Acme/App/pull/5", None, "agent:t")
    _, new = store.add(ws, "https://github.com/acme/app/pull/5", None, "agent:t")
    assert not new and [r["url"] for r in store.read(ws)] == [url(5)]
