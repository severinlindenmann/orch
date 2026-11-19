"""Skills add-on, ORCH-842: logins on/off, sign-in state, shared skills (remove, newer version), Codex switches."""

import json
import os
import stat
import tomllib

import pytest

from orch_skills import cli, codex, model, signin, switches


def _item(data, kind, name):
    return next(i for i in data[kind] if i["name"] == name)


# ---- logins -----------------------------------------------------------------------------------------------


@pytest.fixture
def profiles(monkeypatch):
    from orch import cli_secret, inventory, keystore

    profs = {
        "github": {"env": {"GH_TOKEN": "gh-token"}, "run": ["/usr/bin/gh"], "agents_may_env": False},
        "db": {"env": {"DB_URL": "db-url"}, "files": {"DB_CA": "db-ca"}, "agents_may_env": True},
    }
    calls = []

    def set_agents(root, name, on, who):
        calls.append((name, on, who))
        changed = profs[name]["agents_may_env"] != on
        profs[name]["agents_may_env"] = on
        return changed

    monkeypatch.setattr(keystore, "read_profiles", lambda root: profs)
    monkeypatch.setattr(cli_secret, "set_agents", set_agents)
    keys = [{"name": n, "type": "token", "source": "workspace"} for n in ("gh-token", "db-url", "db-ca", "loose")]
    monkeypatch.setattr(inventory, "keys", lambda root: keys)
    return calls


def test_logins_are_profiles_with_a_switch_per_workspace(ws, profiles):
    data = model.build(ws)
    gh, db = _item(data, "logins", "github"), _item(data, "logins", "db")
    assert gh["can_off"] and not gh["on"] and db["on"]
    assert gh["off_means"] == "Off: helpers can use it only through its own command (gh)"
    assert db["off_means"] == "Off: helpers cannot use it; you still can"
    assert (
        "this workspace only" in gh["scope"]
        and db["description"] == "Uses db-ca, db-url. Helpers never see the secret."
    )
    loose = _item(data, "logins", "loose")
    assert not loose["can_off"] and "No key profile uses this key" in loose["locked"]
    assert [i["name"] for i in data["logins"]].count("gh-token") == 0  # a key in a profile is not listed twice


def test_a_person_turns_a_login_on_and_off(ws, profiles, capsys):
    assert (
        cli.main(["--dir", str(ws), "act", "on", "--by", "human:Anna", "--json", "--", "login:workspace:github"]) == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert out["changed"] and out["item"]["on"] and profiles == [("github", True, "human:Anna")]
    assert cli.main(["--dir", str(ws), "off", "login:workspace:github", "--by", "human:Anna"]) == 0
    assert profiles[-1] == ("github", False, "human:Anna")


def test_a_helper_cannot_switch_a_login(ws, profiles, monkeypatch, capsys):
    monkeypatch.setenv("ORCH_RUN", "r_1")
    assert cli.main(["--dir", str(ws), "on", "login:workspace:github", "--json"]) == 2
    assert profiles == []


# ---- sign-in ------------------------------------------------------------------------------------------------

LIST = """Checking MCP server health…

playwright: npx @playwright/mcp - ✓ Connected
linear: https://mcp.linear.app/sse (SSE) - ! Needs authentication
broken: /bin/false  - ✗ Failed to connect
fresh: /bin/echo  - ⏸ Pending (run `claude` to allow it)
claude.ai Gmail: https://gmail.mcp.claude.com/mcp - ! Needs authentication
"""


def test_parse_claude_mcp_list():
    assert signin.parse(LIST) == {
        "playwright": "connected",
        "linear": "needs-sign-in",
        "broken": "failed",
        "fresh": "pending",
        "claude.ai Gmail": "needs-sign-in",
    }


def _conns(monkeypatch, *names, **extra):
    from orch import inventory

    conns = [
        {"name": n, "source": "workspace", "command": "npx", "host": None, "state": "ready", "shadowed": False}
        | extra.get(n, {})
        for n in names
    ]
    monkeypatch.setattr(inventory, "connections", lambda root, **kw: (conns, {}))


def _fake_claude(tmp_path, monkeypatch, text, code=0):
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    out = tmp_path / "list.txt"
    out.write_text(text)
    exe = bin_ / "claude"
    exe.write_text(f"#!/bin/sh\ncat '{out}'\nexit {code}\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}/usr/bin{os.pathsep}/bin")


@pytest.mark.skipif(os.name != "posix", reason="a shell script stands in for claude")
def test_check_sign_in_keeps_the_answer_and_shows_it(ws, tmp_path, monkeypatch, capsys):
    _conns(monkeypatch, "playwright", "linear", "keyed", keyed={"profile": "kp", "state": "missing-key"})
    first = model.build(ws)
    assert _item(first, "services", "linear")["signin"].startswith("Not checked yet")
    assert _item(first, "services", "keyed")["signin"] == "Its login is not stored here"
    _fake_claude(tmp_path, monkeypatch, LIST)
    assert (
        cli.main(["--dir", str(ws), "act", "check", "--by", "human:Anna", "--json", "--", "service:workspace:linear"])
        == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert out["item"]["signin_state"] == "needs-sign-in"
    assert "Needs a sign-in in Claude (type /mcp)" in out["item"]["problems"]
    data = model.build(ws)
    assert _item(data, "services", "playwright")["signin"].startswith("Signed in and working (checked ")
    cache = json.loads((ws / ".orch/addons/skills/signin.json").read_text())
    assert set(cache) == {"schema", "checked_at", "servers"}  # names and states only


def test_check_sign_in_without_claude_is_refused(ws, tmp_path, monkeypatch, capsys):
    _conns(monkeypatch, "linear")
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert cli.main(["--dir", str(ws), "check", "service:workspace:linear", "--json"]) == 2
    assert "Claude is not installed" in json.loads(capsys.readouterr().out)["error"]
    assert not (ws / ".orch/addons/skills/signin.json").exists()


# ---- shared skills ------------------------------------------------------------------------------------------


def _offer(ws, version, **offered):
    s = ws / ".orch/secrets"
    s.mkdir(parents=True, exist_ok=True)
    (s / "shared.json").write_text(json.dumps({"version": version, "skills": ["github"], "offered": offered}))


def test_remove_a_shared_skill_and_see_a_newer_version(ws, capsys):
    _offer(ws, 5, github=2)
    assert "remove" in _item(model.build(ws), "skills", "github")["actions"]
    assert (
        cli.main(["--dir", str(ws), "act", "remove", "--by", "human:Anna", "--json", "--", "skill:admin:github"]) == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert out["changed"] and out["item"]["removed"] and out["item"]["actions"] == ["restore"]
    assert not (ws / ".agents/skills/github").exists() and not (ws / ".claude/skills/github").exists()
    assert json.loads((ws / ".orch/skills-removed.json").read_text()) == {
        "schema": "orch.skills-removed/1",
        "skills": {"github": 2},
    }
    gh = _item(model.build(ws), "skills", "github")
    assert gh["removed"] and "newer" not in gh and not gh["can_off"]
    _offer(ws, 6, github=3)  # the admin changed it after the person removed it
    assert (
        _item(model.build(ws), "skills", "github")["newer"] == "Your admin has a newer version than the one you removed"
    )
    rows = json.loads(cli.main(["--dir", str(ws), "history", "--json"]) == 0 and capsys.readouterr().out)["history"]
    assert rows[0]["what"] == "remove" and rows[0]["who"] == "human:Anna"


def test_get_a_removed_skill_back_without_a_relay(ws, capsys):
    _offer(ws, 5, github=2)
    model.act(ws, "remove", "skill:admin:github")
    res = model.act(ws, "restore", "skill:admin:github")
    assert res["next"] == "github comes back with the next update from your admin."
    assert json.loads((ws / ".orch/skills-removed.json").read_text())["skills"] == {}


def test_only_shared_skills_can_be_removed(ws):
    with pytest.raises(switches.Refused, match="not possible here"):
        model.act(ws, "remove", "skill:workspace:release-walk")
    assert (ws / ".agents/skills/release-walk/SKILL.md").exists()


def test_a_helper_cannot_remove_a_shared_skill(ws, monkeypatch, capsys):
    monkeypatch.setenv("ORCH_AGENT", "codex")
    assert cli.main(["--dir", str(ws), "remove", "skill:admin:github", "--json"]) == 2
    assert (ws / ".agents/skills/github/SKILL.md").exists()


def test_a_waiting_refresh_hint_says_newer_settings(ws):
    _offer(ws, 5, github=2)
    inbox = ws / ".orch/inbox"
    inbox.mkdir()
    (inbox / "m_a1.json").write_text(json.dumps({"id": "m_a1", "type": "refresh-hint", "body": {"version": 6}}))
    assert "newer shared settings" in _item(model.build(ws), "skills", "github")["newer"]
    (inbox / "m_a1.json").write_text(json.dumps({"id": "m_a1", "type": "refresh-hint", "body": {"version": 5}}))
    assert "newer" not in _item(model.build(ws), "skills", "github")


# ---- Codex --------------------------------------------------------------------------------------------------


@pytest.fixture
def with_codex(ws, tmp_path, monkeypatch):
    from orch import adapters

    found = [{"name": n, "label": n.title(), "found": True, "version": None} for n in ("claude", "codex")]
    monkeypatch.setattr(adapters, "detect", lambda: found)
    cx = tmp_path / "codexhome"
    cx.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(cx))
    (cx / "config.toml").write_text(
        f'[projects.{json.dumps(str(ws))}]\ntrust_level = "trusted"\n\n[mcp_servers.playwright]\ncommand = "npx"\n'
    )
    _conns(monkeypatch, "playwright")
    return cx


def test_codex_service_off_and_on_in_a_trusted_folder(ws, with_codex):
    (ws / ".codex").mkdir()
    (ws / ".codex/config.toml").write_text('model = "x"  # mine\n')
    it = model.turn(ws, "service:workspace:playwright", on=False)["item"]
    assert it["tools"] == {"Claude": "off", "Codex": "off"} and not it["on"] and "note" not in it
    text = (ws / ".codex/config.toml").read_text()
    assert text.startswith('model = "x"  # mine\n') and codex.MARK in text
    assert tomllib.loads(text)["mcp_servers"]["playwright"] == {"enabled": False}
    it = model.turn(ws, "service:workspace:playwright", on=True)["item"]
    assert it["on"] and it["tools"] == {"Claude": "on", "Codex": "on"}
    assert codex.MARK not in (ws / ".codex/config.toml").read_text()
    assert tomllib.loads((ws / ".codex/config.toml").read_text()) == {"model": "x"}


def test_codex_untrusted_folder_is_explained_not_written(ws, with_codex):
    (with_codex / "config.toml").write_text('[mcp_servers.playwright]\ncommand = "npx"\n')
    it = model.turn(ws, "service:workspace:playwright", on=False)["item"]
    assert it["tools"] == {"Claude": "off", "Codex": "on"} and it["note"] == "Codex still sees it"
    assert "until you trust this folder in Codex" in it["codex_limit"]
    assert not (ws / ".codex/config.toml").exists()


def test_codex_a_hand_written_entry_is_left_alone(ws, with_codex):
    (ws / ".codex").mkdir()
    (ws / ".codex/config.toml").write_text("[mcp_servers.playwright]\nenabled = false\n")
    it = _item(model.build(ws), "services", "playwright")
    assert it["locked"] == "Turned off by hand in Codex's settings" and not it["can_off"]
    with pytest.raises(switches.Refused, match="already list playwright"):
        codex.set_mcp(ws, "playwright", on=False)


def test_codex_a_service_codex_does_not_have_has_no_codex_row(ws, with_codex, monkeypatch):
    _conns(monkeypatch, "only-claude")
    assert _item(model.build(ws), "services", "only-claude")["tools"] == {"Claude": "on"}


def test_codex_skill_limit_is_said(ws, with_codex):
    assert (
        "Codex has no switch for one folder's skills" in _item(model.build(ws), "skills", "release-walk")["codex_limit"]
    )


def test_codex_broken_folder_file_is_not_overwritten(ws, with_codex):
    (ws / ".codex").mkdir()
    (ws / ".codex/config.toml").write_text("[broken\n")
    with pytest.raises(switches.Refused, match="not readable TOML"):
        codex.set_mcp(ws, "playwright", on=False)
    assert (ws / ".codex/config.toml").read_text() == "[broken\n"


def test_codex_block_names_are_quoted():
    assert tomllib.loads(codex.block('a "b".c'))["mcp_servers"] == {'a "b".c': {"enabled": False}}


def test_codex_settings_added_under_orchs_block_are_kept(ws, with_codex):
    model.turn(ws, "service:workspace:playwright", on=False)
    path = ws / ".codex/config.toml"
    path.write_text(path.read_text() + 'command = "mine"\n')
    before = path.read_text()
    with pytest.raises(switches.Refused, match="Someone added settings for playwright"):
        model.turn(ws, "service:workspace:playwright", on=True)
    assert path.read_text() == before
    assert json.loads((ws / ".claude/settings.local.json").read_text())["permissions"]["deny"]  # nothing half done


def test_codex_crlf_file_switches_back(ws, with_codex):
    (ws / ".codex").mkdir()
    (ws / ".codex/config.toml").write_bytes(b'model = "x"\r\n')
    codex.set_mcp(ws, "playwright", on=False)
    assert b"\r\nenabled = false\r\n" in (ws / ".codex/config.toml").read_bytes()
    assert codex.state(ws, ws)["servers"]["playwright"] == "orch"
    assert codex.set_mcp(ws, "playwright", on=True)
    assert tomllib.loads((ws / ".codex/config.toml").read_bytes().decode()) == {"model": "x"}


def test_a_refused_codex_switch_leaves_claude_alone(ws, with_codex):
    (ws / ".codex").mkdir()
    (ws / ".codex/config.toml").write_text("[broken\n")
    with pytest.raises(switches.Refused, match="not readable TOML"):
        model.turn(ws, "service:workspace:playwright", on=False)
    assert not (ws / ".claude/settings.local.json").exists()
