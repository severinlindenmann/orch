"""The Move flow: the outer (team) repository tracks .orch files, so sync does not start until a person's click
untracks them (the core's private.move, the only outer-repository write) and the state repository takes over."""

import re
import subprocess

import pytest
from orch import harness
from test_step import TICKET, configure, save, success

from orch_sync import cli, needs, repo

ID = ("-c", "user.name=t", "-c", "user.email=t@example.invalid")


def outer(root, *args):
    return subprocess.run(
        ["git", *ID, "-C", str(root), *args], capture_output=True, check=True
    ).stdout.decode()


@pytest.fixture
def team(root):
    """A workspace inside a team repository that tracks its .orch tickets and one team file."""
    outer(root, "init", "-q", "-b", "main")
    save(root)
    (root / "team.txt").write_text("a team file\n")
    outer(root, "add", "-f", "team.txt", ".orch/tickets")
    outer(root, "commit", "-q", "-m", "team")
    return root


def snapshot(root):
    return outer(root, "rev-parse", "HEAD"), outer(root, "ls-files", "-s")


def test_outer_tracks_orch_sync_refuses_and_writes_nothing(team):
    before = snapshot(team)
    assert repo.state(team) == "needs-move"
    with pytest.raises(repo.Refused, match="needs-move"):
        repo.ensure(team)
    assert cli.main(["--dir", str(team), "set", "--mode", "local"]) == 2  # refused, plainly
    assert snapshot(team) == before
    assert not (team / ".orch" / ".git").exists()
    ids = [r["id"] for r in needs.rows(team)]
    assert "sync:move:orch-files" in ids


def test_the_move_row_asks_the_core_op_with_a_sign_step_and_later(team):
    (row,) = [r for r in needs.rows(team) if r["id"] == "sync:move:orch-files"]
    move, later = row["actions"]
    assert (move["op"], move["sign"]) == ("private.move", True) and "verb" not in move
    assert later == {"label": "Not now", "later": True}
    assert "git" not in row["text"].lower() and "git" not in move["review"]["body"].lower()


def test_every_row_time_is_one_the_core_accepts():
    # the core's collector drops a row whose time has fractions of a second (the pause row vanished from `orch needs`)
    out = needs.row("paused", "k", "text", "2026-11-12T05:28:01.460324Z", "orch sync status", None)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", out["since"])
    odd = needs.row("paused", "k", "text", 12345, "orch sync status", None)  # a planted non-text time
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", odd["since"])


def test_move_untracks_orch_only_commits_nothing_then_sync_starts(team):
    head = outer(team, "rev-parse", "HEAD")
    moved = harness.move_to_private(team, "human:Pat")
    assert moved and all(p.startswith(".orch/") for p in moved)
    assert outer(team, "ls-files", ".orch") == ""  # untracked in the index
    assert outer(team, "ls-files").split() == ["team.txt"]  # every other file is still tracked
    assert outer(team, "rev-parse", "HEAD") == head  # nothing committed: the person commits the removal
    assert (team / ".orch" / TICKET).is_file()  # the files stay on disk
    assert not (team / ".orch" / ".git").exists()  # the move itself starts no state repository
    configure(team)
    success(team)
    assert repo.git(team, "ls-tree", "-r", "--name-only", "HEAD").stdout.decode().split() == [TICKET]
    assert not [r for r in needs.rows(team) if r["id"] == "sync:move:orch-files"]
    assert outer(team, "rev-parse", "HEAD") == head


def test_an_agent_cannot_move(team, monkeypatch, capsys):
    before = snapshot(team)
    from orch.errors import Refused

    with pytest.raises(Refused):
        harness.move_to_private(team, "agent:claude")
    # the command line: no proof from a person, or an agent's name on it, is refused before git runs
    from orch import cli as orch_cli

    monkeypatch.chdir(team)
    for extra in ([], ["--by", "agent:claude"], ["--by", "human:Pat"]):
        assert orch_cli.main(["private", "move", *extra]) != 0
    assert snapshot(team) == before


def test_outer_hooks_and_config_never_run(team):
    canary = team.parent / "PWNED"
    script = team.parent / "evil.sh"
    script.write_text(f'#!/bin/sh\necho "$0" >> "{canary}"\n')
    script.chmod(0o755)
    hooks = team / ".git" / "hooks"
    for name in (
        "pre-commit",
        "post-commit",
        "reference-transaction",
        "post-index-change",
        "pre-push",
        "fsmonitor-watchman",
    ):
        (hooks / name).write_text(f'#!/bin/sh\necho {name} >> "{canary}"\n')
        (hooks / name).chmod(0o755)
    config = team / ".git" / "config"
    config.write_text(
        config.read_text() + f"[core]\n\tfsmonitor = {script}\n\thooksPath = {hooks}\n"
        f"[alias]\n\trm = !{script}\n"
    )
    moved = harness.move_to_private(
        team, "human:Pat"
    )  # the Move really runs, with the hostile config neutralised
    assert moved and harness.tracked_private(team) == []
    assert not canary.exists()


def test_move_with_the_persons_proof_on_the_command_line(team, monkeypatch, capsys):
    import io

    from orch import cli as orch_cli
    from orch import humanproof

    token = humanproof.mint(
        humanproof.human_key(team), humanproof.new_payload("private.move", "move", "human:Pat")
    )
    monkeypatch.chdir(team)
    monkeypatch.setattr("sys.stdin", io.StringIO(token + "\n"))
    head = outer(team, "rev-parse", "HEAD")
    assert orch_cli.main(["private", "move", "--proof-stdin"]) in (0, None)
    assert outer(team, "ls-files", ".orch") == "" and outer(team, "rev-parse", "HEAD") == head
    assert (team / ".orch" / TICKET).is_file()
