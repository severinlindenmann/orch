"""Skills add-on: what helpers get here, and Turn off / Turn on for this workspace only."""

import json

import pytest

from orch_skills import cli, model, switches


def _item(data, kind, name):
    return next(i for i in data[kind] if i["name"] == name)


def _settings(root):
    return json.loads((root / ".claude/settings.local.json").read_text())


def test_lists_every_kind_and_place(ws):
    data = model.build(ws)
    assert data["schema"] == "orch.skills-page/1" and data["tools"] == ["Claude"]
    where = {i["name"]: i["where"] for i in data["skills"]}
    assert where == {
        "orch": "orch",
        "orch-hello": "orch",
        "release-walk": "workspace",
        "github": "admin",
        "status-page": "mine",
    }
    assert _item(data, "skills", "orch")["locked"] and not _item(data, "skills", "orch")["can_off"]
    names = [i["name"] for i in data["instructions"]]
    assert names[:2] == ["Your rules for every project", "AGENTS.md"] and "orch blocks" not in names[:2]
    assert all(len(i["id"]) <= 200 for k in ("skills", "instructions") for i in data[k])


def test_needs_a_look(ws):
    data = model.build(ws)
    assert "Has no real description" in _item(data, "skills", "orch-hello")["problems"]
    assert _item(data, "skills", "github")["problems"] == []


def test_needs_a_look_from_the_header_fields(ws):
    pytest.importorskip("orch.skillmeta")  # the one header reader (ORCH-532); without it only the description
    data = model.build(ws)
    assert "Retired, but helpers still see it" in _item(data, "skills", "status-page")["problems"]
    assert "Not ready here: no-such-program-834 is missing" in _item(data, "skills", "release-walk")["problems"]
    assert _item(data, "skills", "github")["problems"] == []


def test_off_and_on_for_an_orch_skill_unlinks_and_relinks(ws):
    res = model.turn(ws, "skill:orch:orch-hello", on=False)
    assert res["changed"] and not res["item"]["on"]
    assert not (ws / ".agents/skills/orch-hello").exists() and not (ws / ".claude/skills/orch-hello").exists()
    assert (ws / ".orch/harness/skills/orch-hello/SKILL.md").is_file()  # nothing deleted
    assert model.turn(ws, "skill:orch:orch-hello", on=False)["changed"] is False
    assert model.turn(ws, "skill:orch:orch-hello", on=True)["changed"]
    assert (ws / ".agents/skills/orch-hello").exists()


def test_the_core_skill_stays_on(ws):
    with pytest.raises(switches.Refused, match="always on"):
        model.turn(ws, "skill:orch:orch", on=False)


def test_a_workspace_skill_uses_claude_settings_and_keeps_other_settings(ws):
    (ws / ".claude").mkdir(exist_ok=True)
    (ws / ".claude/settings.local.json").write_text(
        json.dumps({"hooks": {"SessionStart": []}, "skillOverrides": {"x": "on"}})
    )
    res = model.turn(ws, "skill:workspace:release-walk", on=False)
    assert res["changed"] and res["item"]["tools"] == {"Claude": "off"} and "note" not in res["item"]
    s = _settings(ws)
    assert s["skillOverrides"] == {"x": "on", "release-walk": "off"} and s["hooks"] == {"SessionStart": []}
    assert (ws / ".agents/skills/release-walk/SKILL.md").is_file()  # nothing moved
    model.turn(ws, "skill:workspace:release-walk", on=True)
    assert _settings(ws) == {"hooks": {"SessionStart": []}, "skillOverrides": {"x": "on"}}


def test_a_line_written_by_hand_is_left_alone(ws):
    (ws / ".claude").mkdir(exist_ok=True)
    (ws / ".claude/settings.local.json").write_text(json.dumps({"skillOverrides": {"status-page": "off"}}))
    it = _item(model.build(ws), "skills", "status-page")
    assert not it["on"] and it["locked"].startswith("Turned off by hand")
    with pytest.raises(switches.Refused, match="by hand"):
        model.turn(ws, "skill:mine:status-page", on=True)
    assert _settings(ws) == {"skillOverrides": {"status-page": "off"}}


def test_global_rules_off_through_claude_md_excludes(ws):
    res = model.turn(ws, "instructions:mine:CLAUDE.md", on=False)
    assert res["changed"] and _settings(ws)["claudeMdExcludes"] == [str(ws.parent / "home/.claude/CLAUDE.md")]
    model.turn(ws, "instructions:mine:CLAUDE.md", on=True)
    assert "claudeMdExcludes" not in _settings(ws)


def test_workspace_rules_cannot_be_turned_off(ws):
    with pytest.raises(switches.Refused, match="always read"):
        model.turn(ws, "instructions:workspace:AGENTS.md", on=False)


def test_a_service_off_is_a_deny_rule(ws, monkeypatch):
    from orch import inventory

    conns = [
        {
            "name": "playwright",
            "source": "workspace",
            "command": "npx",
            "host": None,
            "state": "ready",
            "shadowed": False,
        }
    ]
    monkeypatch.setattr(inventory, "connections", lambda root, **kw: (conns, {}))
    res = model.turn(ws, "service:workspace:playwright", on=False)
    assert res["changed"] and _settings(ws)["permissions"]["deny"] == ["mcp__playwright__*"]
    model.turn(ws, "service:workspace:playwright", on=True)
    assert "permissions" not in _settings(ws)


def test_broken_settings_are_not_overwritten(ws):
    (ws / ".claude").mkdir(exist_ok=True)
    (ws / ".claude/settings.local.json").write_text("{broken")
    with pytest.raises(switches.Refused, match="not readable JSON"):
        model.turn(ws, "skill:workspace:release-walk", on=False)
    assert (ws / ".claude/settings.local.json").read_text() == "{broken"


def test_a_gone_item_is_refused(ws):
    with pytest.raises(switches.Refused, match="not here any more"):
        model.turn(ws, "skill:workspace:nothing-here", on=False)


def test_codex_still_sees_a_workspace_skill(ws, monkeypatch):
    from orch import adapters

    found = [{"name": n, "label": n.title(), "found": True, "version": None} for n in ("claude", "codex")]
    monkeypatch.setattr(adapters, "detect", lambda: found)
    it = model.turn(ws, "skill:workspace:release-walk", on=False)["item"]
    assert it["tools"] == {"Claude": "off", "Codex": "on"} and it["note"] == "Codex still sees it"
    hello = model.turn(ws, "skill:orch:orch-hello", on=False)["item"]
    assert hello["tools"] == {"Claude": "off", "Codex": "off"} and "note" not in hello  # orch's link reaches both


def test_mcp_rule_names():
    assert switches.mcp_rule("claude.ai Gmail") == "mcp__claude_ai_Gmail__*"
    assert switches.mcp_rule("my-server") == "mcp__my-server__*"


def test_cli_act_list_and_history(ws, capsys):
    assert cli.main(["--dir", str(ws), "act", "off", "skill:orch:orch-hello", "--by", "human:Anna", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["changed"] and not out["item"]["on"]
    assert cli.main(["--dir", str(ws), "history", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)["history"]
    assert rows[0]["who"] == "human:Anna" and rows[0]["what"] == "off" and rows[0]["name"] == "orch-hello"
    assert cli.main(["--dir", str(ws), "list"]) == 0
    assert "skill:orch:orch-hello  off" in capsys.readouterr().out


@pytest.mark.parametrize(
    "verb,target",
    [("rm", "skill:orch:orch-hello"), ("off", "skill:orch:../x"), ("off", "--dir=/tmp"), ("off", "x" * 300)],
)
def test_cli_act_refuses_other_shapes(ws, capsys, verb, target):
    assert cli.main(["--dir", str(ws), "act", verb, "--json", "--", target]) == 2
    assert "error" in json.loads(capsys.readouterr().out)


def test_page_server_answers_with_the_model(ws):
    import threading
    import urllib.request

    from orch_skills import server

    srv = server.make_server(ws, 0, nonce="")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/page", headers={"Host": f"127.0.0.1:{port}"})
        with urllib.request.urlopen(req, timeout=5) as r:
            body = json.loads(r.read())
        assert body["schema"] == "orch.skills-page/1" and body["skills"]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            assert b"skills.js" in r.read()
    finally:
        srv.shutdown()


def test_the_manifest_is_valid():
    from pathlib import Path

    from orch import addons

    m = addons.parse_manifest(Path(__file__).parents[1] / "src/orch_skills/orch-addon.toml")
    assert m["name"] == "skills" and m["background"] is True


def test_a_helper_cannot_turn_things_off(ws, monkeypatch, capsys):
    monkeypatch.setenv("ORCH_RUN", "1")
    assert cli.main(["--dir", str(ws), "off", "skill:orch:orch-hello", "--by", "human:Anna", "--json"]) == 2
    assert "Only a person" in json.loads(capsys.readouterr().out)["error"]
    monkeypatch.delenv("ORCH_RUN")
    assert (
        cli.main(["--dir", str(ws), "act", "off", "--by", "agent:claude", "--json", "--", "skill:orch:orch-hello"]) == 2
    )


def test_a_linked_claude_folder_is_refused(ws, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (ws / ".claude").symlink_to(outside) if not (ws / ".claude").exists() else None
    if not (ws / ".claude").is_symlink():
        import shutil

        shutil.rmtree(ws / ".claude")
        (ws / ".claude").symlink_to(outside)
    with pytest.raises(switches.Refused, match="is a link"):
        model.turn(ws, "skill:workspace:release-walk", on=False)
    assert list(outside.iterdir()) == []


def test_a_recorded_line_that_is_gone_is_forgotten(ws, monkeypatch):
    from orch import inventory

    conns = [{"name": "pw", "source": "workspace", "command": "npx", "host": None, "state": "ready", "shadowed": False}]
    monkeypatch.setattr(inventory, "connections", lambda root, **kw: (conns, {}))
    model.turn(ws, "service:workspace:pw", on=False)
    (ws / ".claude/settings.local.json").write_text("{}")  # removed by hand
    model.turn(ws, "skill:workspace:release-walk", on=False)  # any change forgets the stale record
    (ws / ".claude/settings.local.json").write_text(
        json.dumps({"permissions": {"deny": ["mcp__pw__*"]}, "skillOverrides": {"release-walk": "off"}})
    )
    with pytest.raises(switches.Refused, match="by hand"):
        model.turn(ws, "service:workspace:pw", on=True)


def test_a_change_by_someone_else_wins(ws):
    (ws / ".claude").mkdir(exist_ok=True)
    path = ws / ".claude/settings.local.json"
    path.write_text("{}")
    with pytest.raises(switches.Refused, match="changed by someone else"):
        switches._write(ws, switches.tool()["settings"], {"a": 1}, expect=b"{ }")
    assert path.read_text() == "{}"


def test_a_refused_save_takes_the_record_back(ws, monkeypatch):
    real = switches._write

    def refuse_settings(root, rel, doc, expect=True):
        if rel == switches.tool()["settings"]:
            raise switches.Refused("changed by someone else just now. Try again.")
        return real(root, rel, doc, expect)

    monkeypatch.setattr(switches, "_write", refuse_settings)
    with pytest.raises(switches.Refused):
        model.turn(ws, "skill:workspace:release-walk", on=False)
    assert switches._owned(ws)["skills"] == []


def test_a_relay_copy_with_its_file_cannot_be_turned_off(ws, tmp_path):
    from conftest import _skill
    from orch import harness, skills

    skills.install_skill(
        ws, "orch-relay", _skill(tmp_path / "s" / "orch-relay", "orch-relay", "Reach other workspaces.")
    )
    link = ws / ".agents/skills/orch-relay"
    if link.is_symlink():
        link.unlink()
    link.mkdir(exist_ok=True)
    (link / harness.COPY_MARK).write_text("")
    (link / "workspaces.json").write_text("{}")
    it = _item(model.build(ws), "skills", "orch-relay")
    assert it["on"] and not it["can_off"] and "copy" in it["locked"]
