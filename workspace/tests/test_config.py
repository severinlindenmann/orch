"""orch config / orch agents / the agent question at orch init."""

import json
import os
import stat
import sys

import pytest

from orch import config


def _toml(proj):
    return (proj / ".orch" / "config.toml").read_text(encoding="utf-8")


def test_set_key_keeps_everything_else(proj):
    p = proj / ".orch" / "config.toml"
    p.parent.mkdir()
    p.write_text(
        '# mine\n[scheduler]\ninterval = 60\n\n[workspace]\nagent = "a"  # old\nother = 1\n\n[x]\ny = 2\n'
    )
    config.set_key(proj, "workspace", "agent", "b")
    t = _toml(proj)
    assert (
        'agent = "b"' in t
        and "# mine" in t
        and "interval = 60" in t
        and "other = 1" in t
        and "[x]\ny = 2" in t
    )
    config.set_key(proj, "workspace", "mode", "z")
    assert config.read(proj)["workspace"] == {"agent": "b", "other": 1, "mode": "z"}
    config.set_key(proj, "agents.n", "adapter", "generic")
    assert config.read(proj)["agents"]["n"] == {"adapter": "generic"} and config.read(proj)["x"] == {"y": 2}


def test_add_agent_and_choose_it(proj, run):
    code, out, _ = run("config", "agent", "add", "my-agent", "--command", 'my-agent --prompt "{prompt}"')
    assert code == 0 and out.strip() == "Added my-agent (starts fresh each run; no live steps)."
    assert run("config", "set", "workspace.agent", "my-agent")[0] == 0
    assert config.agent_name(proj) == "my-agent"
    assert config.agent_entries(proj)["my-agent"] == {
        "adapter": "generic",
        "command": 'my-agent --prompt "{prompt}"',
    }
    code, out, _ = run("config", "get", "workspace.agent")
    assert out.strip() == "my-agent"
    code, out, err = run("config", "set", "workspace.agent", "nobody")
    assert code == 2 and "No agent called 'nobody'" in err


def test_config_refuses_bad_input(proj, run):
    assert run("config", "agent", "add", "Bad Name", "--command", "x")[0] == 2
    assert run("config", "agent", "add", "okname")[0] == 2  # no command
    assert not (proj / ".orch" / "config.toml").exists()


def _stub(bindir, name, version):
    p = bindir / name
    p.write_text(f"#!/bin/sh\necho '{name} {version}'\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def fake_path(tmp_path, monkeypatch):
    d = tmp_path / "fakebin"
    d.mkdir()
    monkeypatch.setenv("PATH", str(d) + os.pathsep + "/usr/bin" + os.pathsep + "/bin")
    return d


@pytest.mark.skipif(os.name == "nt", reason="shell script stubs")
def test_orch_agents_lists_found_and_chosen(proj, run, fake_path):
    _stub(fake_path, "claude", "2.1.318")
    _stub(fake_path, "codex", "0.163.0")
    run("config", "agent", "add", "my-agent", "--command", "my-agent --prompt {prompt}")
    run("config", "set", "workspace.agent", "my-agent")
    code, out, _ = run("agents")
    lines = out.splitlines()
    assert code == 0
    assert lines[0].split() == [
        "claude",
        "found",
        "2.1.318",
        "continue,",
        "live",
        "session,",
        "live",
        "steps,",
        "helpers,",
        "usage",
    ]
    assert lines[1].split() == ["codex", "found", "0.163.0", "continue"]
    assert lines[2].split() == ["my-agent", "your", "command", "fresh", "each", "run"]
    assert lines[3] == "* my-agent does the work here"
    code, out, _ = run("agents", "--json")
    rows = {r["name"]: r for r in json.loads(out)}
    assert rows["my-agent"]["chosen"] and rows["claude"]["found"] and not rows["claude"]["chosen"]


def test_orch_agents_nothing_found_nothing_chosen(proj, run, fake_path):
    code, out, _ = run("agents")
    assert (
        "not found" in out and "No agent chosen here. Pick one: orch config set workspace.agent <name>" in out
    )


@pytest.mark.skipif(os.name == "nt", reason="shell script stubs")
def test_init_yes_takes_first_found(proj, run, fake_path):
    _stub(fake_path, "codex", "0.163.0")
    code, out, _ = run("init", "--yes")
    assert code == 0 and "Agent: Codex (found first)." in out
    assert config.agent_name(proj) == "codex"
    code, out, _ = run("init", "--yes")  # asked once: the second run keeps it
    assert "Agent: Codex." in out and _toml(proj).count("agent =") == 1


def test_init_nothing_found(proj, run, fake_path):
    code, out, _ = run("init", "--yes")
    assert code == 0 and "No agent found; set one later: orch config set workspace.agent <name>" in out
    assert config.agent_name(proj) is None


@pytest.mark.skipif(os.name == "nt", reason="shell script stubs")
def test_init_asks_found_agents_and_other(proj, run, fake_path, monkeypatch):
    _stub(fake_path, "claude", "2.1.318")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    answers = iter(["2", "", "my-agent --prompt {prompt}"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    code, out, _ = run("init")
    assert code == 0
    assert "Which agent does the work?" in out and "1) Claude  (found, 2.1.318)" in out
    assert "2) Other: type its command" in out and "Agent: my-agent (starts fresh each run" in out
    assert config.agent_entries(proj)["my-agent"]["command"] == "my-agent --prompt {prompt}"
    assert config.agent_name(proj) == "my-agent"
    for word in ("add-on", "scheduler", "relay", "publish"):
        assert word not in out.split("Which agent")[1].lower()


def test_command_from_settings_prints_its_notice_once(proj, run):
    cmd = "my-agent --prompt {prompt}"
    assert config.first_use_notice(cmd) == f"Using agent command from this folder's settings: {cmd}"
    assert config.first_use_notice(cmd) is None
    assert config.first_use_notice(cmd + " --other").startswith("Using agent command")


def test_cannot_add_an_agent_named_like_a_builtin(proj, run):
    code, _, err = run("config", "agent", "add", "claude", "--command", "x {prompt}")
    assert code == 2 and "built-in" in err and not (proj / ".orch" / "config.toml").exists()


def test_array_lines_are_not_tables_and_del_is_escaped(proj):
    p = proj / ".orch" / "config.toml"
    p.parent.mkdir()
    p.write_text('[x]\nlist = [\n  [1, 2]\n]\ntext = """\n[workspace]\n"""\n[workspace]\nagent = "a"\n')
    config.set_key(proj, "workspace", "agent", "b\x7fc")
    t = p.read_text(encoding="utf-8")
    assert "\x7f" not in t and config.read(proj)["workspace"]["agent"] == "b\x7fc"
    assert config.read(proj)["x"]["list"] == [[1, 2]] and config.read(proj)["x"]["text"] == "[workspace]\n"
    assert not list(p.parent.glob("*.tmp"))


def test_init_other_asks_a_name_and_keeps_existing(proj, run, fake_path, monkeypatch):
    config.add_agent(proj, "my-agent", "old {prompt}", approve=True)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    answers = iter(["", "new {prompt}"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    code, _, err = run("init")
    assert code == 2 and "already an agent called 'my-agent'" in err
    assert config.agent_entries(proj)["my-agent"]["command"] == "old {prompt}"


def test_cannot_add_an_agent_that_already_exists(proj, run):
    assert run("config", "agent", "add", "my-agent", "--command", "first {prompt}")[0] == 0
    code, _, err = run("config", "agent", "add", "my-agent", "--command", "second {prompt}")
    assert code == 2 and "already set up" in err
    assert config.agent_entries(proj)["my-agent"]["command"] == "first {prompt}"


# ---------------------------------------------------------------- orch agents test


def _script(tmp_path, body):
    p = tmp_path / "fake-agent.py"
    p.write_text(body)
    return f"{sys.executable} {p} {{prompt}}"


def test_agents_test_passes_and_writes_nothing(proj, run, capsys):
    cmd = _script(proj, "import sys; print('ok')")
    run("config", "agent", "add", "fake", "--command", cmd)
    capsys.readouterr()
    before = sorted(p.name for p in (proj / ".orch").rglob("*"))
    with pytest.raises(SystemExit) as e:
        run("agents", "test", "fake")
    assert e.value.code == 0
    assert "fake answered in" in capsys.readouterr().out
    assert sorted(p.name for p in (proj / ".orch").rglob("*")) == before


def test_agents_test_json_and_stdin(proj, run, capsys):
    cmd = f'{sys.executable} -c "import sys; print(sys.stdin.read())"'
    run("config", "agent", "add", "fake", "--command", cmd, "--prompt-via", "stdin")
    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        run("agents", "test", "fake", "--json")
    assert e.value.code == 0
    r = json.loads(capsys.readouterr().out)
    assert r["ok"] and r["name"] == "fake"


def test_agents_test_failed_command_shows_first_stderr_line(proj, run, capsys):
    cmd = _script(proj, "import sys; sys.stderr.write('boom one\\nsecond\\n'); sys.exit(3)")
    run("config", "agent", "add", "fake", "--command", cmd)
    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        run("agents", "test", "fake")
    assert e.value.code == 1
    assert capsys.readouterr().out.strip() == "The command failed: boom one"


def test_agents_test_timeout(proj, run, capsys, monkeypatch):
    from orch import cli_config

    monkeypatch.setattr(cli_config, "TEST_TIMEOUT", 1)
    cmd = _script(proj, "import time; time.sleep(30)")
    run("config", "agent", "add", "fake", "--command", cmd)
    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        run("agents", "test", "fake")
    assert e.value.code == 1
    assert capsys.readouterr().out.strip() == "No answer within 1 s."


def test_agents_test_not_installed_and_unknown(proj, run, capsys, fake_path):
    with pytest.raises(SystemExit) as e:
        run("agents", "test", "codex")
    assert e.value.code == 1
    assert capsys.readouterr().out.strip() == "Codex is not installed."
    code, _, err = run("agents", "test", "nobody")
    assert code == 2 and "No agent called" in err


RESERVED = [
    ("focus", "live_session", True, False),
    ("focus", "session_typing", False, True),
    ("record", "keep_days", 90, 30),  # an allowed value (others are snapped: test_insights_settings.py)
    ("record", "max_mb", 2048, 512),
    ("insights", "share_counts", True, False),
    ("insights", "share_names", False, True),
]


@pytest.mark.parametrize("section,key,default,valid", RESERVED)
def test_reserved_config(proj, section, key, default, valid):
    # the FILE parsing; record_* / insights_* are the effective values (with the person's record), tested in
    # test_insights_settings.py
    def getter(root):
        if section == "focus":  # the focus getters are the file value itself
            assert getattr(config, f"{section}_{key}")(root) == config.file_value(root, section, key)
        return config.file_value(root, section, key)

    assert getter(None) == default
    assert getter(proj) == default
    config.set_key(proj, section, key, valid)
    assert getter(proj) == valid
    wrong = ['"wrong"', "[]", "{}", "1.5", "1" if isinstance(default, bool) else "true"]
    for value in wrong:
        config.path(proj).write_text(f"[{section}]\n{key} = {value}\n")
        assert getter(proj) == default
    if not isinstance(default, bool):  # a whole number <= 0 means "as little as possible": the floor (L2)
        from orch import humanproof

        floor = humanproof.RETENTION_FLOOR[config._RETENTION_SETTINGS[(section, key)]]
        for value in ("0", "-1"):
            config.path(proj).write_text(f"[{section}]\n{key} = {value}\n")
            assert getter(proj) == floor < default
    config.path(proj).write_text("invalid toml [")
    assert getter(proj) == default
    config.path(proj).write_text(f"{section} = 4\n")
    assert getter(proj) == default
