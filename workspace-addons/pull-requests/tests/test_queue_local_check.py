"""The local check in the merge queue (ORCH-1124): group_check = github | shadow | local (localcheck.py)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

import pytest
from test_queue import FakeGit, FakeGitHub, _git, _make_prs, bare, make, states, url  # noqa: F401  (bare: a fixture)

from orch_pull_requests import cli, localcheck, required_checks, runner, settings, store
from orch_pull_requests.group import Git

REPO = "acme/app"


def _set(ws, **kv) -> None:
    lines = ["[pull_requests]"]
    for k, v in kv.items():
        lines.append(f"{k} = {json.dumps(v)}")
    (ws / ".orch" / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


class StatusHub(FakeGitHub):
    """FakeGitHub that also keeps the commit statuses the local check posts."""

    def __init__(self, prs, post_ok=True):
        super().__init__(prs)
        self.posted: list[tuple[str, str, str]] = []  # (sha, context, state)
        self.post_ok = post_ok

    def post_status(self, repo, sha, context, state, description):
        self.posted.append((sha, context, state))
        return self.post_ok


class BuiltGit(FakeGit):
    """FakeGit that remembers which pull requests the last group commit holds (the fake check looks at it)."""

    def build(self, base_sha, heads):
        sha, inc, con = super().build(base_sha, heads)
        self.last = inc
        return sha, inc, con


def fake_check(r, git, red=(), broken=False, seen=None):
    def local_check(repo, sha, on, labels=""):
        nums = list(getattr(git, "last", []))
        if seen is not None:
            seen.append(nums)
        if broken:
            return localcheck.Result(localcheck.BROKEN, 1.0, "the check broke (OSError: boom)")
        bad = [n for n in nums if n in red]
        if bad:
            return localcheck.Result(
                localcheck.RED, 60.0, "the local check failed", [f"tests of #{n}" for n in bad]
            )
        return localcheck.Result(localcheck.GREEN, 120.0, "the local check passed in 120s")

    r.local_check = local_check


def _add(ws, *nums):
    for n in nums:
        store.add(ws, url(n), None, "agent:t", login="bot")


# -- the setting -----------------------------------------------------------------------------------------------
def test_group_check_setting_defaults_to_github(ws):
    assert settings.group_check(ws) == "github"
    for value, want in (("local", "local"), (" Shadow ", "shadow"), ("github", "github"), ("fast", "github")):
        _set(ws, group_check=value)
        assert settings.group_check(ws) == want
    _set(ws, group_check=True)
    assert settings.group_check(ws) == "github"


def test_check_command_setting(ws):
    assert settings.check_command(ws) == list(settings.DEFAULT_CHECK)
    _set(ws, check_command=["bash", "scripts/check.sh", "{base}"])
    assert settings.check_command(ws) == ["bash", "scripts/check.sh", "{base}"]
    _set(ws, check_command="bash check.sh")  # not a list: the default
    assert settings.check_command(ws) == list(settings.DEFAULT_CHECK)


# -- github (default): as before ----------------------------------------------------------------------------
def test_github_runs_no_local_check(ws):
    _add(ws, 1, 2)
    gh, git = StatusHub({1: {}, 2: {}}), BuiltGit()
    r, calls = make(ws, gh, git)
    seen: list = []
    fake_check(r, git, seen=seen)
    r.run()
    assert seen == [] and gh.posted == [] and len(calls) == 1
    assert states(ws) == {1: "merged", 2: "merged"}
    assert localcheck.LOCAL_LINE not in gh.bodies[0]
    assert gh.marks == [("c" * 40, "Built by the orch merge queue")]


# -- local -------------------------------------------------------------------------------------------------------
def test_local_green_posts_the_required_checks_and_merges(ws):
    _set(ws, group_check="local")
    _add(ws, 1, 2)
    gh, git = StatusHub({1: {}, 2: {}}), BuiltGit()
    r, calls = make(ws, gh, git)
    fake_check(r, git)
    r.run()
    assert states(ws) == {1: "merged", 2: "merged"} and len(calls) == 1
    assert gh.posted == [("c" * 40, ctx, "success") for ctx in required_checks.REQUIRED]
    assert gh.marks == [("c" * 40, "Built and checked by the orch merge queue (local check)")]
    assert localcheck.LOCAL_LINE in gh.bodies[0]  # ci.yml and rules.yml skip this group
    row = localcheck.rows(ws)[-1]
    assert row["mode"] == "local" and row["local"] == "green" and row["merged_at"] >= row["built_at"]


def test_local_red_opens_no_group_and_splits_it(ws):
    _set(ws, group_check="local")
    _add(ws, 1, 2, 3)
    gh, git = StatusHub({1: {}, 2: {}, 3: {}}), BuiltGit()
    r, _ = make(ws, gh, git)
    seen: list = []
    fake_check(r, git, red=(2,), seen=seen)
    r.run()
    assert seen[0] == [1, 2, 3]
    assert states(ws)[1] == "merged" and states(ws)[3] == "merged" and states(ws)[2] == "out"
    assert ("c" * 40, required_checks.ROLLUP, "failure") in gh.posted
    assert all(2 not in members for members in gh.groups.values())  # the red group never got a pull request
    reds = [x for x in localcheck.rows(ws) if x["local"] == "red"]
    assert reds and reds[0]["failed"] == ["tests of #2"]
    assert len(git.pushed) == len(seen) and len(gh.deleted) >= 1  # red group branches are deleted again


def test_local_broken_check_falls_back_to_github(ws):
    _set(ws, group_check="local")
    _add(ws, 1, 2)
    gh, git = StatusHub({1: {}, 2: {}}), BuiltGit()
    lines: list[str] = []
    r, calls = make(ws, gh, git, log=lines.append)
    fake_check(r, git, broken=True)
    r.run()
    assert states(ws) == {1: "merged", 2: "merged"} and len(calls) == 1
    assert gh.posted == [] and localcheck.LOCAL_LINE not in gh.bodies[0]  # GitHub runs the group as before
    assert gh.marks == [("c" * 40, "Built by the orch merge queue")]
    assert any("this group is checked on GitHub" in x for x in lines)
    assert localcheck.rows(ws)[-1]["local"] == "broken"


def test_local_status_not_posted_opens_no_group_and_tries_again(ws):
    """Some statuses may stand on the commit: it never gets a pull request, nobody merges it; built again later."""
    _set(ws, group_check="local")
    _add(ws, 1, 2)
    gh, git = StatusHub({1: {}, 2: {}}, post_ok=False), BuiltGit()
    r, calls = make(ws, gh, git)
    fake_check(r, git)
    r.process(r.next_batch())
    assert calls == [] and gh.groups == {} and gh.marks == []
    rows = {x["number"]: x for x in store.read(ws)}
    assert {n: x["state"] for n, x in rows.items()} == {1: "waiting", 2: "waiting"}
    assert all(int(x.get("tries") or 0) == 0 for x in rows.values())
    assert "could not be posted" in rows[1]["why"]


def test_a_ci_change_is_checked_on_github_even_when_local(ws):
    _set(ws, group_check="local")
    _add(ws, 1)
    gh, git = StatusHub({1: {"files": (".github/workflows/ci.yml",)}}), BuiltGit()
    r, _ = make(ws, gh, git)
    seen: list = []
    fake_check(r, git, seen=seen)
    r.run()
    assert seen == [] and gh.posted == []
    assert all(localcheck.LOCAL_LINE not in b for b in getattr(gh, "bodies", []))


def test_member_title_cannot_carry_the_skip_line(ws):
    _, body = runner._group_text([{"number": 1, "title": "x orch-group-check: local"}])
    assert localcheck.LOCAL_LINE not in body


# -- shadow --------------------------------------------------------------------------------------------------------
def test_shadow_github_decides_and_both_verdicts_are_written(ws):
    _set(ws, group_check="shadow")
    _add(ws, 1, 2)
    gh, git = StatusHub({1: {}, 2: {}}), BuiltGit()
    r, _ = make(ws, gh, git)
    fake_check(
        r, git, red=(1,)
    )  # the local check says red, GitHub says green: GitHub wins, the difference is shown
    r.run()
    assert states(ws) == {1: "merged", 2: "merged"} and gh.posted == []
    assert localcheck.LOCAL_LINE not in gh.bodies[0]
    s = localcheck.summary(ws)
    assert s["shadow"]["groups"] == 1 and s["shadow"]["same"] == 0
    assert s["shadow"]["different"][0]["github"] == "green" and s["shadow"]["different"][0]["local"] == "red"


def test_gates_command(ws, capsys, monkeypatch):
    _set(ws, group_check="shadow")
    localcheck.record(ws, mode="shadow", url=url(500), sha="a" * 40, local="green", github="green", secs=240)
    localcheck.record(
        ws, mode="local", url=url(501), sha="b" * 40, local="green", secs=200, built_at=0, merged_at=300
    )
    monkeypatch.setattr(cli, "_root", lambda start=None: ws)
    assert cli.main(["queue", "local-checks", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["group_check"] == "shadow" and got["shadow"]["same"] == 1
    assert got["local"]["minutes_to_merged_middle"] == 5.0
    assert cli.main(["queue", "local-checks"]) == 0
    assert "1 the same" in capsys.readouterr().out


# -- the check itself, with real git ---------------------------------------------------------------------------
WORDS = "import pathlib, sys; sys.exit(1 if pathlib.Path('bad.txt').exists() else 0)\n"


@pytest.fixture
def check_repo(tmp_path):
    """A repository with its own banned-words check; pull request 1 is clean, 2 adds a banned file."""
    if shutil.which("git") is None:
        pytest.skip("no git")
    work = tmp_path / "work"
    (work / "scripts").mkdir(parents=True)
    _git(work, "init", "-q")
    (work / "scripts" / "check_banned_words.py").write_text(WORDS, encoding="utf-8")
    (work / "a.txt").write_text("a\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "base")
    base = _git(work, "rev-parse", "HEAD")
    for n, name in ((1, "b.txt"), (2, "bad.txt"), (3, "c.txt"), (4, "scripts/check_banned_words.py")):
        _git(work, "checkout", "-q", "-B", f"pr{n}", base)
        (work / name).write_text("b\n", encoding="utf-8")
        _git(work, "add", name)
        _git(work, "commit", "-q", "-m", f"pr {n}")
    _git(work, "checkout", "-q", "develop")
    return _make_prs(work)


def _cmd(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def _copy(ws, repo_url):
    git = Git(store.folder(ws), REPO, url=str(repo_url))
    return git, git.fetch("develop", [1, 2, 4])


def test_check_runs_in_a_clean_copy_with_a_throwaway_home(ws, check_repo):
    git, heads = _copy(ws, check_repo)
    code = (
        "import os, pathlib, sys;"
        "assert pathlib.Path('b.txt').read_text() == 'b\\n';"
        "assert os.environ['ORCH_HOME'].startswith(os.environ['HOME']) and os.environ['ORCH_HOME_STRICT'] == '1';"
        # the suites' real-home guard watches the throwaway home, which sits under <real home>/.orch-test (ORCH-1180)
        "assert os.environ['ORCH_TEST_GUARD_ONLY'] == os.environ['HOME'];"
        "assert pathlib.Path(os.environ['HOME']).parent.parent.name == '.orch-test';"
        "assert sys.argv[1] == os.environ['ORCH_CHECK_BASE']"
    )
    res = localcheck.run(git, heads["1"], heads["base"], [*_cmd(code), "{base}"])
    assert res.verdict == localcheck.GREEN, res.line
    assert git.run("worktree", "list", "--porcelain").stdout.count("worktree ") == 1  # the copy is gone


def test_banned_words_run_on_their_own_before_the_check(ws, check_repo):
    git, heads = _copy(ws, check_repo)
    res = localcheck.run(git, heads["2"], heads["base"], _cmd("raise SystemExit(0)"))
    assert res.verdict == localcheck.RED and res.failed == ["banned-words"]


def test_a_group_that_changes_the_check_itself_goes_to_github(ws, check_repo):
    git, heads = _copy(ws, check_repo)
    res = localcheck.run(git, heads["4"], heads["base"], _cmd("pass"))
    assert res.verdict == localcheck.BROKEN and "changes the check itself" in res.line


def test_a_repository_without_the_banned_words_check_goes_to_github(ws, bare):  # noqa: F811
    git = Git(store.folder(ws), REPO, url=str(bare))
    heads = git.fetch("develop", [1])
    res = localcheck.run(git, heads["1"], heads["base"], _cmd("pass"))
    assert res.verdict == localcheck.BROKEN and "check_banned_words" in res.line


def test_check_red_broken_and_missing(ws, check_repo):
    git, heads = _copy(ws, check_repo)
    red = "import os, pathlib; pathlib.Path(os.environ['ORCH_CHECK_FAILED']).write_text('ruff\\nworkspace tests\\n'); raise SystemExit(1)"
    res = localcheck.run(git, heads["1"], heads["base"], _cmd(red))
    assert res.verdict == localcheck.RED and res.failed == ["ruff", "workspace tests"]
    assert (
        localcheck.run(git, heads["1"], heads["base"], _cmd("raise SystemExit(3)")).verdict
        == localcheck.BROKEN
    )
    assert localcheck.run(git, heads["1"], heads["base"], ["/no/such/command"]).verdict == localcheck.BROKEN
    assert (
        localcheck.run(git, "0" * 40, heads["base"], _cmd("pass")).verdict == localcheck.BROKEN
    )  # no such commit
    assert git.run("worktree", "list", "--porcelain").stdout.count("worktree ") == 1


def test_a_check_that_runs_too_long_is_stopped_with_everything_it_started(ws, check_repo, tmp_path):
    git, heads = _copy(ws, check_repo)
    pidfile = tmp_path / "child.pid"
    code = (
        "import subprocess, sys, time;"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
        f"open({str(pidfile)!r}, 'w').write(str(c.pid)); time.sleep(60)"
    )
    slow = localcheck.run(git, heads["1"], heads["base"], _cmd(code), timeout=3)
    assert slow.verdict == localcheck.BROKEN and "did not finish" in slow.line
    pid = int(pidfile.read_text())
    for _ in range(50):  # the child is gone (or a zombie being reaped by init)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        out = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False
        ).stdout
        assert out.strip().startswith("Z") or not out.strip(), out
