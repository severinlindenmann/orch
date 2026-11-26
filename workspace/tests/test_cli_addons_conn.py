"""cli_addons.py (`orch addon list|add|remove|uninstall`) and cli_conn.py (`orch conn`): success, error with a
next step, and --json, in an isolated temp workspace."""

import json

import pytest

from orch import addons, cli_addons, cli_conn


def test_addon_list_json_and_text(proj, run):
    code, out, err = run("addon", "list", "--json")
    assert code == 0, err
    rows = json.loads(out)
    assert isinstance(rows, list) and all({"name", "installed", "active"} <= set(r) for r in rows)
    code, out, err = run("addon", "list")
    assert code == 0, err
    assert "orch addon add <name>" in out


def test_addon_list_empty_says_next_step(proj, run, monkeypatch):
    monkeypatch.setattr(addons, "listing", lambda root: [])
    code, out, _ = run("addon", "list")
    assert (
        code == 0
        and "No add-ons are installed. Turn one on with: orch addon add <name>" in out
        and "Next:" in out
    )


def test_addon_remove_unknown_is_refused_with_next_step(proj, run):
    code, _, err = run("addon", "remove", "never-was")
    assert code == 2
    assert "not turned on in this workspace" in err


def test_addon_add_several_refuses_a_folder(proj, run, tmp_path):
    folder = tmp_path / "some addon"
    folder.mkdir()
    code, _, err = run("addon", "add", "relay", str(folder), "--yes")
    assert code == 2
    assert "Add an add-on from a folder on its own." in err


def test_addon_add_project_only_json(proj, run, monkeypatch):
    seen = []
    monkeypatch.setattr(
        addons, "add", lambda root, name, yes, project_only=False: seen.append((name, project_only))
    )
    code, out, err = run("addon", "add", "relay", "--project-only", "--yes", "--json")
    assert code == 0, err
    assert json.loads(out)["ok"] is True
    assert seen == [("relay", True)]


def test_addon_add_failure_propagates(proj, run, monkeypatch):
    def boom(root, name, yes, project_only=False):
        raise cli_addons.Refused("Could not install. Try again in a minute.")

    monkeypatch.setattr(addons, "add", boom)
    code, _, err = run("addon", "add", "relay", "--project-only", "--yes")
    assert code == 2 and "Try again" in err


def test_addon_remove_and_uninstall_json(proj, run, monkeypatch):
    monkeypatch.setattr(addons, "listed", lambda root: ["relay"])
    monkeypatch.setattr(addons, "remove", lambda root, name, purge: None)
    monkeypatch.setattr(addons, "tool_env_change_ok", lambda: None)
    monkeypatch.setattr(addons, "uninstall", lambda root, name: None)
    code, out, err = run("addon", "remove", "relay", "--json")
    assert code == 0, err
    assert json.loads(out) == {"ok": True}
    code, out, err = run("addon", "uninstall", "relay", "--json")
    assert code == 0, err
    assert json.loads(out) == {"ok": True}
    code, out, _ = run("addon", "uninstall", "relay")
    assert "relay is uninstalled." in out and "Next:" in out


def test_addon_dispatch_ignores_other_commands(proj):
    class A:
        cmd = "ticket"

    assert cli_addons.dispatch(A(), proj) is False


@pytest.mark.parametrize("sub", cli_conn.SUBCOMMANDS)
def test_conn_subcommand_not_built(proj, run, sub):
    code, _, err = run("conn", sub)
    assert code == 2 and f"`orch conn {sub}` is not built yet." in err


def test_conn_without_subcommand_lists_them(proj, run):
    code, _, err = run("conn")
    assert code == 2
    assert "Subcommands: list, show, allow." in err


def test_conn_dispatch_ignores_other_commands(proj):
    class A:
        cmd = "ticket"

    assert cli_conn.dispatch(A(), proj) is False
