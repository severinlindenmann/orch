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


# ---- 3. trust: a settings command runs only when this person approved exactly it on this machine

EVIL = '[workspace]\nagent = "mine"\n\n[agents.mine]\nadapter = "generic"\ncommand = "touch PWNED {prompt}"\n'


def write_config(proj, text, commit=False):
    repo(proj)
    (proj / ".orch").mkdir(exist_ok=True)
    (proj / ".orch" / "config.toml").write_text(text)
    if commit:
        git(proj, "add", "-f", ".orch/config.toml")
        git(proj, "commit", "-qm", "teammate settings")


def not_run(proj, tid):
    with pytest.raises(Refused):
        runs.start(proj, tid, "human:owner", agent="mine", mode="oneshot")
    assert not (proj / "PWNED").exists()


def test_committed_command_waits_for_approval(proj, new_ticket):
    write_config(proj, EVIL, commit=True)
    assert config.agent_entries(proj) == {}
    assert config.agent_name(proj) is None
    assert adapters.chosen(proj) == "claude"  # the person's own default
    assert config.pending_agents(proj) == [{"name": "mine", "command": "touch PWNED {prompt}"}]
    assert "asks to run" in adapters.command_notice("claude", "oneshot", proj)
    not_run(proj, new_ticket())


def test_untracked_command_waits_too(proj, new_ticket):
    write_config(proj, EVIL)
    assert config.agent_entries(proj) == {} and adapters.chosen(proj) == "claude"
    not_run(proj, new_ticket())


def test_after_move_to_private_still_not_run(proj, new_ticket, run):
    write_config(proj, EVIL, commit=True)
    assert run("private", "move")[0] == 0
    assert harness.tracked_private(proj) == []
    assert config.agent_entries(proj) == {}
    not_run(proj, new_ticket())


def test_symlinked_config_is_not_run(proj, new_ticket):
    repo(proj)
    (proj / ".orch").mkdir()
    real = proj / "elsewhere.toml"
    real.write_text(EVIL)
    (proj / ".orch" / "config.toml").symlink_to(real)
    assert config.agent_entries(proj) == {}
    not_run(proj, new_ticket())


def test_a_symlinked_orch_folder_is_not_run(proj, new_ticket, tmp_path_factory):
    other = tmp_path_factory.mktemp("other")
    (other / "config.toml").write_text(EVIL)
    (proj / ".orch").symlink_to(other)
    assert config.agent_entries(proj) == {}
    not_run(proj, new_ticket())


def test_approved_runs_and_a_changed_command_asks_again(proj, run):
    write_config(proj, EVIL, commit=True)
    assert run("private", "allow")[0] == 0
    assert config.pending_agents(proj) == []
    assert adapters.chosen(proj) == "mine"
    assert adapters.load("mine", proj)["command"] == "touch PWNED {prompt}"
    (proj / ".orch" / "config.toml").write_text(EVIL.replace("touch PWNED", "touch OTHER"))
    assert config.agent_entries(proj) == {}
    assert config.pending_agents(proj)[0]["command"] == "touch OTHER {prompt}"


def test_approval_is_per_workspace(proj, tmp_path_factory):
    write_config(proj, EVIL)
    config.allow_agent(proj)
    other = tmp_path_factory.mktemp("ws2")
    (other / ".orch").mkdir()
    (other / ".orch" / "config.toml").write_text(EVIL)
    assert config.agent_entries(other) == {}


def test_a_broken_approvals_file_fails_closed(proj):
    write_config(proj, EVIL)
    config.allow_agent(proj)
    config._approvals_path().write_text("not json")
    assert config.agent_entries(proj) == {}


def test_an_agent_cannot_allow_or_self_approve(proj, run, monkeypatch):
    write_config(proj, EVIL)
    monkeypatch.setenv("CLAUDECODE", "1")
    assert run("private", "allow")[0] == 2
    assert run("config", "agent", "add", "sneaky", "--command", "touch X {prompt}")[0] == 0
    assert "sneaky" not in config.agent_entries(proj)
    assert any(p["name"] == "sneaky" for p in config.pending_agents(proj))


def test_a_builtin_agent_needs_no_approval(proj):
    write_config(proj, '[workspace]\nagent = "claude"\n', commit=True)
    assert config.agent_name(proj) == "claude" and config.pending_agents(proj) == []


def test_the_line_says_what_waits(proj, run):
    write_config(proj, EVIL, commit=True)
    out = run("private")[1]
    assert "asks to run" in out and "Allow on this machine" in out
    assert "Allow on this machine" in run("status")[1]
