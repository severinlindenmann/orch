"""The precheck: quick checks on a group's merged tree before the group is pushed (ORCH-545, owner 19 Nov)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest
from test_queue import FakeGit, FakeGitHub, make, states, url

from orch_pull_requests import precheck, store
from orch_pull_requests.group import Git
from orch_pull_requests.precheck import Result

TEN = [1, 2, 3, 4, 5, 6, 7, 8, 10, 11]  # the fake GitHub never shows #9


class TreeGit(FakeGit):
    """Each built commit names its members, so the fake precheck knows which pull requests a tree holds."""

    def __init__(self):
        super().__init__()
        self.trees = {}

    def fetch(self, base, nums):
        got = super().fetch(base, nums)
        self.trees[got["base"]] = ()
        return got

    def build(self, base_sha, heads):
        _, inc, con = super().build(base_sha, heads)
        sha = f"{len(self.trees):040x}"
        self.trees[sha] = tuple(inc)
        return sha, inc, con


def _setup(ws, members, cfg='precheck = "rules"\n'):
    (ws / ".orch").mkdir(exist_ok=True)
    (ws / ".orch" / "config.toml").write_text(f"[pull_requests]\nmax_group = 10\nmerge_alone = false\n{cfg}")
    for n in members:
        store.add(ws, url(n), None, "agent:t", login="bot")
    return {n: {"files": (f"workspace-addons/sync/src/orch_sync/m{n}.py",)} for n in members}


def _pre(git, bad=(), together=False, trouble=False, broken=False):
    seen = []

    def run(g, sha, cmd):
        members = git.trees[sha]
        seen.append((members, cmd))
        if trouble:
            return Result(None, "could not run")
        if broken:
            return Result(False, "ci_light.py: error: unrecognized arguments: --rules")
        red = any(m in bad for m in members) or (together and len(members) > 1)
        return Result(
            not red, "FAILED tests/test_adapters.py::test_no_tool_names_outside_the_adapter" if red else ""
        )

    return run, seen


def test_a_member_red_in_the_precheck_leaves_at_once_and_the_rest_runs_once(ws):
    """Owner 19 Nov: the offender is dropped before the 16 minute group run, the other 9 merge after one run."""
    gh, git = FakeGitHub(_setup(ws, TEN)), TreeGit()
    pre, seen = _pre(git, bad={7})
    lines = []
    r, calls = make(ws, gh, git, log=lines.append)
    r.pre = pre
    r.run()
    assert [gh.groups[c] for c in calls] == [[n for n in TEN if n != 7]]  # one group run, without #7
    assert states(ws) == {**{n: "merged" for n in TEN if n != 7}, 7: "out"}
    assert seen[0] == (tuple(TEN), "rules") and seen[1] == ((), "rules")  # the group, then the base alone
    assert len(seen) == 2 + len(TEN) + 1  # group, base, each alone, the group again
    row = store.find(store.read(ws), url(7))
    assert "precheck" in row["why"] and "test_no_tool_names_outside_the_adapter" in row["why"]
    assert any("#7 left the queue before the group run" in x for x in lines)


def test_red_only_together_leaves_the_decision_to_the_group_run(ws):
    gh, git = FakeGitHub(_setup(ws, [1, 2, 3])), TreeGit()
    pre, _ = _pre(git, together=True)
    r, calls = make(ws, gh, git)
    r.pre = pre
    r.run()
    assert [gh.groups[c] for c in calls] == [[1, 2, 3]] and states(ws) == {
        1: "merged",
        2: "merged",
        3: "merged",
    }


def test_a_precheck_that_could_not_run_is_not_red(ws):
    gh, git = FakeGitHub(_setup(ws, [1, 2])), TreeGit()
    pre, _ = _pre(git, trouble=True)
    lines = []
    r, calls = make(ws, gh, git, log=lines.append)
    r.pre = pre
    r.run()
    assert len(calls) == 1 and states(ws) == {1: "merged", 2: "merged"}
    assert any("precheck did not run" in x for x in lines)


def test_a_lone_pull_request_red_in_the_precheck_never_gets_a_group_run(ws):
    gh, git = FakeGitHub(_setup(ws, [5])), TreeGit()
    pre, seen = _pre(git, bad={5})
    r, calls = make(ws, gh, git)
    r.pre = pre
    r.run()
    assert calls == [] and git.pushed == [] and states(ws) == {5: "out"} and len(seen) == 2  # it, the base


def test_a_precheck_red_on_the_base_itself_blames_nobody(ws):
    """19 Nov try: a command develop does not know yet is red everywhere; it must never empty the queue."""
    gh, git = FakeGitHub(_setup(ws, [1, 2, 3])), TreeGit()
    pre, seen = _pre(git, broken=True)
    lines = []
    r, calls = make(ws, gh, git, log=lines.append)
    r.pre = pre
    r.run()
    assert [gh.groups[c] for c in calls] == [[1, 2, 3]] and states(ws) == {
        1: "merged",
        2: "merged",
        3: "merged",
    }
    assert [m for m, _ in seen] == [(1, 2, 3), ()]
    assert any("red on the base itself" in x for x in lines)


def test_no_setting_no_precheck(ws):
    gh, git = FakeGitHub(_setup(ws, [1, 2], cfg="")), TreeGit()
    pre, seen = _pre(git, bad={1})
    r, calls = make(ws, gh, git)
    r.pre = pre
    r.run()
    assert seen == [] and len(calls) == 1


def test_the_precheck_runs_in_a_throw_away_home_with_only_path_and_uv_kept(tmp_path):
    base = {
        "PATH": "/bin",
        "HOME": "/Users/me",
        "ORCH_HOME": "/Users/me/.orch-tool",
        "GH_TOKEN": "x",
        "LANG": "C",
    }
    got = precheck.env(tmp_path / "home", base)
    assert got["HOME"] == got["USERPROFILE"] == str(tmp_path / "home")
    assert got["ORCH_HOME"] == str(tmp_path / "home" / "orch") and got["ORCH_HOME_STRICT"] == "1"
    assert "GH_TOKEN" not in got and got["PATH"] == "/bin" and got["LANG"] == "C"
    assert got["UV_CACHE_DIR"] and got["UV_PYTHON_INSTALL_DIR"]


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_the_precheck_runs_the_command_in_a_copy_of_the_group_commit(tmp_path):
    """A real bare copy as the queue keeps it: the command sees the commit's files, red is red, and the copy is
    gone afterwards."""
    origin = tmp_path / "origin"
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}  # fmt: skip
    subprocess.run(["git", "init", "-q", "-b", "develop", str(origin)], check=True, env=env)
    (origin / "rule.txt").write_text("green\n")
    subprocess.run(["git", "-C", str(origin), "add", "."], check=True, env=env)
    subprocess.run(["git", "-C", str(origin), "commit", "-qm", "x"], check=True, env=env)
    git = Git(tmp_path / "queue", "o/r", url=origin.as_uri())
    git.prepare()
    subprocess.run(["git", "-C", str(origin), "config", "uploadpack.allowFilter", "true"], check=True)
    git.run(
        "fetch", "-q", "--filter=blob:none", "origin", "+refs/heads/develop:refs/queue/base"
    )  # as fetch() does
    sha = git.run("rev-parse", "refs/queue/base").stdout.strip()
    py = f'"{sys.executable}"'
    green = precheck.run(
        git, sha, f"{py} -c \"import os,sys; sys.exit(open('rule.txt').read() != 'green\\n')\""
    )
    assert green.ok is True
    red = precheck.run(
        git,
        sha,
        f"{py} -c \"import os; print('FAILED x', os.environ['ORCH_HOME_STRICT']); raise SystemExit(3)\"",
    )
    assert red.ok is False and "FAILED x 1" in red.tail
    assert git.run("worktree", "list").stdout.count("\n") == 1  # no copy linked to the queue's git folder
    probe = "import subprocess; print(subprocess.run(['git', 'rev-parse', '--git-dir', 'HEAD:rule.txt'], capture_output=True, text=True).stdout)"
    seen = precheck.run(git, sha, f'{py} -c "{probe}"')
    assert seen.ok is True and seen.tail.splitlines()[0] == ".git"  # its own repository, not the queue's copy
