"""Git step 1 (9 Nov): personal files stay out of a team repo, a warning when they are already tracked, and a
committed config.toml never decides which command runs."""

import json
import os
import subprocess
import sys

import pytest

from orch import adapters, config, harness, runs, tickets
from orch.errors import Refused


@pytest.fixture(autouse=True)
def claude_found(monkeypatch):
    monkeypatch.setattr(
        adapters, "detect", lambda: [{"name": "claude", "label": "Claude", "found": True, "version": None}]
    )


def git(proj, *args, check=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["git", *args], cwd=proj, env=env, capture_output=True, text=True, check=check)


def repo(proj):
    git(proj, "init", "-q")
    git(proj, "config", "user.email", "t@example.com")
    git(proj, "config", "user.name", "t")


def make_files(proj, run):
    run("init", "--json")  # may or may not exist in this build; tolerate below
    d = proj / ".orch"
    d.mkdir(exist_ok=True)
    (d / "tickets").mkdir(exist_ok=True)
    (d / "tickets" / "DM1-1.json").write_text("{}")
    (d / "tickets" / "DM1-1" / "artifacts").mkdir(parents=True, exist_ok=True)
    (d / "tickets" / "DM1-1" / "artifacts" / "r.md").write_text("x")
    (d / "ticket-counter.json").write_text('{"last": 1}')
    (d / "addons.json").write_text('{"active": {}}')
    (d / "config.toml").write_text('[workspace]\ncode = "DM1"\n')


# ---- 1. ignored by default

def test_personal_files_are_ignored_in_a_git_repo(proj, run):
    repo(proj)
    harness.protect_local(proj)
    for rel in (
        ".orch/tickets/DM1-1.json",
        ".orch/tickets/DM1-1/artifacts/r.md",
        ".orch/ticket-counter.json",
        ".orch/config.toml",
        ".orch/addons.json",
    ):
        assert git(proj, "check-ignore", "-q", rel, check=False).returncode == 0, rel
    assert git(proj, "check-ignore", "-q", "AGENTS.md", check=False).returncode == 1


def test_fixed_patterns_only(proj):
    """No line comes from data: the ignore list is the constant plus the validated Chat-ticket stems."""
    (proj / ".orch" / "tickets").mkdir(parents=True)
    (proj / ".orch" / "tickets" / "t_abcdef12.json").write_text(
        json.dumps({"id": "t_abcdef12\n!*", "general": True})
    )
    repo(proj)
    harness.protect_local(proj)
    text = (proj / ".orch" / ".gitignore").read_text()
    assert "!" not in text and "tickets/" in text


# ---- 2. warning for tracked files

def test_no_warning_when_nothing_is_tracked(proj):
    repo(proj)
    (proj / ".orch").mkdir()
    (proj / ".orch" / "config.toml").write_text("[workspace]\n")
    harness.protect_local(proj)
    assert harness.private_summary(proj)["files"] == []
    assert harness.tracked_private(proj) == []


def test_no_git_no_warning(proj):
    (proj / ".orch").mkdir()
    (proj / ".orch" / "config.toml").write_text("[workspace]\n")
    assert harness.tracked_private(proj) == []


def test_warning_lists_tracked_files_and_status_says_the_next_step(proj, run):
    repo(proj)
    make_files(proj, run)
    git(proj, "add", "-f", ".orch")
    git(proj, "commit", "-qm", "oops")
    s = harness.private_summary(proj)
    assert s["counts"] == {"tickets": 2, "ticket-counter.json": 1, "config.toml": 1, "addons.json": 1}
    code, out, _ = run("private", "--json")
    d = json.loads(out)
    assert code == 0 and d["count"] == 5 and d["committed"]["tickets"] == 2
    assert "Move to private" in "\n".join(d["lines"])
    code, out, _ = run("status")
    assert "Committed in your team repo" in out and "Move to private" in out


def test_move_to_private_untracks_and_keeps_files_and_commits_nothing(proj, run):
    repo(proj)
    make_files(proj, run)
    git(proj, "add", "-f", ".orch")
    git(proj, "commit", "-qm", "oops")
    head = git(proj, "rev-parse", "HEAD").stdout
    code, out, _ = run("private", "move")
    assert code == 0 and "Moved 5 files" in out
    assert harness.tracked_private(proj) == []
    assert (proj / ".orch" / "config.toml").is_file() and (proj / ".orch" / "tickets" / "DM1-1.json").is_file()
    assert git(proj, "rev-parse", "HEAD").stdout == head  # nothing committed
    assert git(proj, "ls-files", ".orch/tickets", ".orch/config.toml", ".orch/addons.json").stdout.strip() == ""
    assert "D  .orch/config.toml" in git(proj, "status", "--short").stdout  # staged removal for the person
    assert git(proj, "status", "--short", "--", ".orch/tickets").stdout.strip().count("??") == 0  # now ignored


def test_move_is_for_a_person_not_an_agent(proj, run, monkeypatch):
    repo(proj)
    monkeypatch.setenv("CLAUDECODE", "1")
    code, out, err = run("private", "move")
    assert code == 2 and "person" in (out + err)


def test_a_tracked_file_with_a_hostile_name_is_handled(proj):
    repo(proj)
    d = proj / ".orch" / "tickets"
    d.mkdir(parents=True)
    weird = d / "a b$(x);'.json"
    weird.write_text("{}")
    git(proj, "add", "-f", ".orch")
    git(proj, "commit", "-qm", "x")
    assert harness.move_to_private(proj)
    assert harness.tracked_private(proj) == [] and weird.is_file()


# ---- 3. trust gap

def commit_config(proj, text):
    repo(proj)
    (proj / ".orch").mkdir(exist_ok=True)
    (proj / ".orch" / "config.toml").write_text(text)
    git(proj, "add", "-f", ".orch/config.toml")
    git(proj, "commit", "-qm", "teammate settings")


EVIL = '[workspace]\nagent = "mine"\n\n[agents.mine]\nadapter = "generic"\ncommand = "touch PWNED {prompt}"\n'


def test_committed_agent_command_is_not_used(proj):
    commit_config(proj, EVIL)
    assert config.agent_config_untrusted(proj)
    assert config.agent_entries(proj) == {}
    assert config.agent_name(proj) is None
    assert adapters.chosen(proj) == "claude"  # the person's own default
    with pytest.raises(Refused):
        adapters.load("mine", proj)
    assert "ignored" in adapters.command_notice("claude", "oneshot", proj)


def test_committed_command_is_not_run(proj, new_ticket):
    commit_config(proj, EVIL)
    tid = new_ticket()
    with pytest.raises(Refused):
        runs.start(proj, tid, "human:owner", agent="mine", mode="oneshot")
    assert not (proj / "PWNED").exists()


def test_same_config_untracked_still_works(proj):
    repo(proj)
    (proj / ".orch").mkdir()
    (proj / ".orch" / "config.toml").write_text(EVIL)
    assert not config.agent_config_untrusted(proj)
    assert adapters.chosen(proj) == "mine"
    assert adapters.load("mine", proj)["command"] == "touch PWNED {prompt}"


def test_a_committed_config_may_still_name_a_builtin_agent(proj):
    commit_config(proj, '[workspace]\nagent = "claude"\ncode = "DM1"\n')
    assert config.agent_name(proj) == "claude"
    assert config.untrusted_note(proj) is None


def test_the_line_says_why(proj, run):
    commit_config(proj, EVIL)
    code, out, _ = run("private")
    assert "agent command" in out and "committed to git" in out and "ignored" in out
    code, out, _ = run("status")
    assert "ignored" in out


def test_outside_git_nothing_changes(proj):
    (proj / ".orch").mkdir()
    (proj / ".orch" / "config.toml").write_text(EVIL)
    assert adapters.chosen(proj) == "mine"
