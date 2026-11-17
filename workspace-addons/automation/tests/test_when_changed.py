"""A repeat that starts only when a git branch moved since its last run (ORCH-348): no run, no tokens, by the clock."""

import json
import os
import subprocess

import pytest
from conftest import T, add_ticket, runs_started

from orch_automation import cli
from orch_automation.loop import Scheduler, change_mark

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(repo, *args):
    env = {**os.environ, **GIT_ENV}
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env
    )


@pytest.fixture
def repo(ws):
    r = ws / "proj"
    r.mkdir()
    git(r, "init", "-q", "-b", "develop")
    git(r, "commit", "-q", "--allow-empty", "-m", "one")
    return r


def commit(repo, msg):
    git(repo, "commit", "-q", "--allow-empty", "-m", msg)


def tk(ws, tid):
    return json.loads((ws / f".orch/tickets/{tid}.json").read_text())


def gated(ws, tid, spec="proj@develop", cron="0 */6 * * *"):
    return add_ticket(ws, tid, ext={"automation": {"recurring": True, "cron": cron, "when_changed": spec}})


def test_first_run_then_only_after_a_change(ws, repo):
    gated(ws, "t_chg00001")
    s = Scheduler(ws)
    assert s.tick(T(6, 1)) == ["t_chg00001"]  # never ran: the first due time runs
    assert s.tick(T(12, 1)) == []  # due again, nothing changed: no run
    assert s.tick(T(12, 30)) == []
    commit(repo, "two")
    assert s.tick(T(12, 31)) == ["t_chg00001"]  # the branch moved: it starts at once, not at 18:00
    assert s.tick(T(12, 40)) == []  # not due before its next planned time
    commit(repo, "three")
    assert s.tick(T(13, 0)) == []  # changed, but its plan says every 6 hours
    assert s.tick(T(18, 1)) == ["t_chg00001"]
    assert runs_started(ws) == ["t_chg00001"] * 3


def test_an_unreadable_branch_starts_nothing(ws, repo):
    gated(ws, "t_chg00002", spec="proj@nope")
    assert Scheduler(ws).tick(T(6, 0)) == []
    gated(ws, "t_chg00003", spec="missing@develop")
    assert Scheduler(ws).tick(T(6, 0)) == []
    assert runs_started(ws) == []


def test_a_waiting_repeat_keeps_a_planned_time_for_the_health_check(ws, repo):
    gated(ws, "t_chg00004")
    s = Scheduler(ws)
    s.tick(T(6, 1))
    t = tk(ws, "t_chg00004")
    t["ext"]["automation"]["next_run"] = "2026-11-04T12:00:00Z"
    (ws / ".orch/tickets/t_chg00004.json").write_text(json.dumps(t))
    s.tick(T(12, 1))  # waits for a change: the planned time moves on once
    assert tk(ws, "t_chg00004")["ext"]["automation"]["next_run"] == "2026-11-04T18:00:00Z"


def test_the_spec_never_leaves_the_workspace_or_passes_an_option(ws, repo):
    assert change_mark(ws, "proj@develop")
    for bad in ("../x@develop", "proj@--output=/tmp/x", "/etc@develop", "proj@-h", "proj/../..@develop"):
        assert change_mark(ws, bad) is None, bad
    outside = ws.parent / "outside"
    outside.mkdir()
    git(outside, "init", "-q")
    (ws / "link").symlink_to(outside)
    assert change_mark(ws, "link@HEAD") is None


def test_cli_sets_and_clears_the_change(ws, repo, capsys):
    add_ticket(ws, "t_chg00005")
    base = ["--dir", str(ws), "repeat", "t_chg00005", "every 6 hours"]
    assert cli.main([*base, "--when-changed", "proj@develop"]) == 0
    assert "only when proj@develop changed" in capsys.readouterr().out
    assert tk(ws, "t_chg00005")["ext"]["automation"]["when_changed"] == "proj@develop"
    assert cli.main([*base, "--when-changed", "proj@nope"]) == 2
    assert cli.main([*base, "--when-changed", "../proj@develop"]) == 2
    assert cli.main(base) == 0  # not given: kept
    assert tk(ws, "t_chg00005")["ext"]["automation"]["when_changed"] == "proj@develop"
    assert cli.main([*base, "--when-changed", "off"]) == 0
    assert "when_changed" not in tk(ws, "t_chg00005")["ext"]["automation"]


def test_packed_remote_and_worktree_refs_are_read_from_the_files(ws, repo):
    head = git(repo, "rev-parse", "develop").stdout.strip()
    git(repo, "update-ref", "refs/remotes/origin/develop", head)
    assert change_mark(ws, "proj@origin/develop") == head  # loose remote ref
    git(repo, "pack-refs", "--all")
    assert change_mark(ws, "proj@origin/develop") == head  # packed
    assert change_mark(ws, "proj@develop") == head
    assert change_mark(ws, "proj@HEAD") == head
    git(repo, "worktree", "add", "-q", str(ws / "wt"), "-b", "side")
    assert change_mark(ws, "wt@origin/develop") == head  # a worktree reads the shared refs
    assert change_mark(ws, "wt@HEAD") == head


def test_a_folders_git_settings_never_run_anything(ws, repo):
    hit = ws / "hit"
    hook = ws / "evil.sh"
    hook.write_text(f"#!/bin/sh\ntouch {hit}\n")
    hook.chmod(0o755)
    git(repo, "config", "core.fsmonitor", str(hook))
    git(repo, "config", "core.hooksPath", str(ws))
    assert change_mark(ws, "proj@develop")
    assert not hit.exists()
