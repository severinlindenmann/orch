"""Helper shells refuse lifecycle changes before side effects, except in isolated tests."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from orch import addons, cli, home, pagelaunch, runs, service_guard, services, worktrees

COMMANDS = [
    ["start", "--no-open"],
    ["stop"],
    ["restart", "--no-open"],
    ["update", "--project-only"],
    ["addon", "add", "relay", "--project-only"],
    ["addon", "remove", "relay"],
    ["dashboard", "stop"],
]


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    (root / ".orch").mkdir(parents=True)
    monkeypatch.chdir(root)
    monkeypatch.setenv("ORCH_AGENT", "codex")
    return root


def busy(root, kind):
    if kind == "remote":
        (root / ".orch" / "config.toml").write_text(
            '[dashboard]\nlisten = "0.0.0.0"\nlisten_name = "host.example"\nlisten_port = 8791\n'
        )
    else:
        p = runs.record_path(root, "t_abcdef")
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"ticket": "t_abcdef", "run": "r_test", "pid": os.getpid()}))


@pytest.fixture
def effects(monkeypatch):
    called = []

    def effect(name, result):
        def run(*args, **kw):
            called.append(name)
            return result

        return run

    monkeypatch.setattr(services, "start", effect("start", []))
    monkeypatch.setattr(services, "stop", effect("stop", []))
    monkeypatch.setattr(worktrees, "schedule_sweep", effect("sweep", None))
    monkeypatch.setattr(addons, "update", effect("update", []))
    monkeypatch.setattr(addons, "add", effect("add", None))
    monkeypatch.setattr(addons, "remove", effect("remove", None))
    monkeypatch.setattr(addons, "active", lambda root: ["dashboard"])
    monkeypatch.setattr(addons, "discover", lambda: {"dashboard": {"run": "orch_dashboard"}})
    monkeypatch.setattr(addons.subprocess, "run", effect("dashboard", SimpleNamespace(returncode=0)))
    from orch import runs_live

    monkeypatch.setattr(runs_live, "stop_hidden", effect("hidden", []))
    return called


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("kind", ["remote", "helper"])
def test_real_workspace_refuses_before_side_effects(workspace, effects, command, kind, capsys):
    busy(workspace, kind)
    assert cli.main(command) == 2
    assert effects == []
    err = capsys.readouterr().err
    assert "helper shell cannot change services" in err
    assert "orch ask" in err
    assert len(err.strip().splitlines()) == 1


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("kind", ["remote", "helper"])
def test_temporary_home_allows_commands(workspace, effects, command, kind, monkeypatch):
    base = workspace.parent
    monkeypatch.setenv("HOME", str(base))
    monkeypatch.setenv("USERPROFILE", str(base))
    monkeypatch.setenv("ORCH_HOME", str(base / "orch"))
    monkeypatch.setattr(addons, "real_home", lambda: base.parent)  # the temp HOME lies under the trusted home
    busy(workspace, kind)
    assert service_guard.isolated(workspace)
    assert cli.main(command) == 0
    assert effects


@pytest.mark.parametrize("command", COMMANDS)
def test_person_can_change_live_workspace(workspace, effects, command, monkeypatch):
    monkeypatch.delenv("ORCH_AGENT")
    busy(workspace, "remote")
    assert cli.main(command) == 0
    assert effects


@pytest.mark.parametrize("command", COMMANDS)
def test_helper_can_change_inactive_workspace(workspace, effects, command):
    assert cli.main(command) == 0
    assert effects


def test_temporary_home_does_not_exempt_workspace_elsewhere(workspace, monkeypatch):
    base = workspace.parent / "temporary-home"
    base.mkdir()
    monkeypatch.setenv("HOME", str(base))
    monkeypatch.setenv("USERPROFILE", str(base))
    monkeypatch.setenv("ORCH_HOME", str(base / "orch"))
    assert not service_guard.isolated(workspace)


def test_account_test_folder_allowed(workspace, monkeypatch):
    monkeypatch.setattr(home, "account_home", lambda: workspace.parent)
    root = workspace.parent / ".orch-test" / "case"
    root.mkdir(parents=True)
    assert pagelaunch.is_test_workspace(root)
    assert service_guard.isolated(root)


def test_human_flag_cannot_disguise_helper(workspace, effects, capsys):
    busy(workspace, "remote")
    assert cli.main(["start", "--by", "human:tester"]) == 2
    assert effects == []
    assert "orch ask" in capsys.readouterr().err


@pytest.mark.parametrize("all_targets", [True, False])
def test_stop_checks_targets_before_stopping_any(workspace, effects, monkeypatch, all_targets):
    live = workspace.parent / "live"
    (live / ".orch").mkdir(parents=True)
    busy(live, "remote")
    monkeypatch.setattr(services, "status", lambda: [{"workspace": str(workspace)}, {"workspace": str(live)}])
    monkeypatch.setattr(services, "find", lambda name: live)
    args = ["stop", "--all"] if all_targets else ["stop", str(live)]
    assert cli.main(args) == 2
    assert effects == []


def test_restart_stops_then_starts(workspace, effects):
    assert cli.main(["restart", "--no-open"]) == 0
    assert effects == ["stop", "hidden", "sweep", "start"]  # orch restart (#1619) also ends hidden sessions


def test_dashboard_checks_explicit_target(workspace, monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "workspace-addons/dashboard/src"))
    from orch_dashboard import cli as dashboard_cli

    live = workspace.parent / "live"
    (live / ".orch").mkdir(parents=True)
    busy(live, "remote")
    monkeypatch.setattr(addons, "active", lambda root: ["dashboard"])  # remote sign-in needs the page on
    stopped = []
    monkeypatch.setattr(dashboard_cli.service, "stop", lambda root: stopped.append(root))
    assert dashboard_cli.main(["--dir", str(live), "stop"]) == 2
    assert stopped == []
    assert "orch ask" in capsys.readouterr().err


def test_factory_stop_review_passes_with_live_helper(workspace):
    busy(workspace, "helper")
    service_guard.command(workspace, "factory", "stop", rest=["t_abcdef", "--file", "stop.json"])
    service_guard.command(workspace, "factory", "stop", rest=["t_abcdef", "--file=stop.json"])


def test_factory_watcher_stop_still_guarded(workspace, monkeypatch):
    busy(workspace, "helper")
    monkeypatch.setattr(addons, "active", lambda root: ["factory"])
    with pytest.raises(service_guard.Refused):
        service_guard.command(workspace, "factory", "stop", rest=[])


@pytest.mark.parametrize(
    "rest", [["--file", "stop.json"], ["--file=stop.json"], ["t_abcdef", "--file"], ["t_abcdef", "--file="]]
)
def test_factory_stop_without_order_or_file_still_guarded(workspace, monkeypatch, rest):
    busy(workspace, "helper")
    monkeypatch.setattr(addons, "active", lambda root: ["factory"])
    with pytest.raises(service_guard.Refused):
        service_guard.command(workspace, "factory", "stop", rest=rest)
