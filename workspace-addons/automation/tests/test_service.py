import json
import os
import time

import pytest
from conftest import add_ticket

from orch_automation import service
from orch_automation.cli import describe, main


def test_start_status_stop(ws):
    pid = service.start(ws)
    assert service.running_pid(ws) == pid
    assert service.start(ws) == pid  # no second one
    assert main(["--dir", str(ws), "status"]) == 0
    assert service.stop(ws) == "stopped"
    for _ in range(30):
        if service.running_pid(ws) is None:
            break
        time.sleep(0.1)
    assert main(["--dir", str(ws), "status"]) == 1
    assert service.stop(ws) == "not running"


def test_list(ws):
    add_ticket(
        ws, "t_wake009", status="waiting", waiting_on={"kind": "time", "until": "2026-11-05T08:00:00Z"}
    )
    add_ticket(ws, "t_rep00001", ext={"automation": {"recurring": True, "cron": "0 7 * * 1"}})
    rows = describe(ws)
    assert {r["ticket"] for r in rows} == {"t_wake009", "t_rep00001"}


def test_repeat_sets_ext_and_off(ws, capsys):
    add_ticket(ws, "t_rep00002")
    assert (
        main(
            [
                "--dir",
                str(ws),
                "repeat",
                "t_rep00002",
                "every monday 08:00",
                "--tz",
                "Europe/Zurich",
                "--agent",
                "codex",
                "--json",
            ]
        )
        == 0
    )
    t = json.loads((ws / ".orch/tickets/t_rep00002.json").read_text())
    assert t["ext"]["automation"] == {
        "recurring": True,
        "cron": "0 8 * * 1",
        "tz": "Europe/Zurich",
        "agent": "codex",
    }
    assert main(["--dir", str(ws), "repeat", "t_rep00002", "--off"]) == 0
    t = json.loads((ws / ".orch/tickets/t_rep00002.json").read_text())
    assert t["ext"]["automation"]["recurring"] is False and t["ext"]["automation"]["cron"] == "0 8 * * 1"


def test_repeat_refuses_plainly(ws, capsys):
    add_ticket(ws, "t_rep00003")
    assert main(["--dir", str(ws), "repeat", "t_rep00003", "nonsense", "--json"]) == 2
    assert "every monday 08:00" in json.loads(capsys.readouterr().out)["error"]
    assert main(["--dir", str(ws), "repeat", "t_nothere1", "daily 07:00"]) == 2
    assert capsys.readouterr().err.startswith("Refused: ")


def test_planted_module_in_the_workspace_is_not_run(ws):
    (ws / "orch_automation.py").write_text("open('PLANTED', 'w').write('x')\n")
    (ws / "json.py").write_text("open('PLANTED', 'w').write('x')\n")
    pid = service.start(ws)  # returns only once the child recorded itself (so it imported and ran)
    try:
        assert service.running_pid(ws) == pid
    finally:
        service.stop(ws)
    assert not (ws / "PLANTED").exists()


@pytest.fixture
def kills(monkeypatch):
    """Record every real signal; signal 0 (is it alive?) still goes to the OS."""
    sent, real = [], os.kill

    def fake(pid, sig):
        if sig == 0:
            return real(pid, 0)
        sent.append((pid, sig))

    monkeypatch.setattr(os, "kill", fake)
    return sent


@pytest.mark.parametrize("pid", [-1, 0, 1, "parent", "self"])
def test_committed_pid_file_is_never_signalled(ws, kills, capsys, pid):
    """A repo can force-add .orch/run/automation/automation.json (or the old .orch/addons/automation/scheduler.pid)."""
    pid = {"parent": os.getppid(), "self": os.getpid()}.get(pid, pid)
    started = service.proc_start(pid) or "x" if isinstance(pid, int) and pid > 1 else "x"
    d = ws / ".orch/run/automation"
    d.mkdir(parents=True)
    (d / "automation.json").write_text(json.dumps({"pid": pid, "nonce": "0" * 32, "started": started}))
    (ws / ".orch/addons/automation").mkdir(parents=True, exist_ok=True)
    (ws / ".orch/addons/automation/scheduler.pid").write_text(str(pid))
    assert service.running_pid(ws) is None
    assert main(["--dir", str(ws), "stop", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["stopped"] is False
    assert kills == []


def test_symlinks_are_refused(ws, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    d = ws / ".orch/run/automation"
    d.mkdir(parents=True)
    (d / "automation.log").symlink_to(victim)
    assert main(["--dir", str(ws), "start"]) == 2
    assert victim.read_text() == "keep me"
    (d / "automation.log").unlink()
    (d / "automation.json").symlink_to(victim)
    assert service.running_pid(ws) is None and victim.read_text() == "keep me"


def test_data_folder_symlink_is_refused(ws, tmp_path):
    from orch_automation.runner import sdir

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    import shutil

    shutil.rmtree(ws / ".orch/addons/automation", ignore_errors=True)
    (ws / ".orch/addons").mkdir(parents=True, exist_ok=True)
    (ws / ".orch/addons/automation").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symbolic link"):
        sdir(ws)
    assert list(elsewhere.iterdir()) == []


def test_command_line_must_name_exactly_this_folder(ws, kills, monkeypatch):
    """--dir /x/ws must not match a scheduler of /x/ws2 (or any longer path)."""
    from orch_automation import runfiles

    root = str(ws.resolve())
    assert runfiles.runs_args(
        f"python -P -m orch_automation --dir {root} run", ["-m", "orch_automation", "--dir", root, "run"]
    )
    assert not runfiles.runs_args(f"python -P -m orch_automation --dir {root}2 run", ["--dir", root, "run"])
    assert not runfiles.runs_args(f"python -m orch_automation --dir {root} running", ["--dir", root, "run"])
    me = os.getpid()
    d = ws / ".orch/run/automation"
    d.mkdir(parents=True)
    (d / "automation.json").write_text(
        json.dumps({"pid": me, "nonce": "1" * 32, "started": service.proc_start(me)})
    )
    monkeypatch.setattr(runfiles, "command", lambda pid: f"python -P -m orch_automation --dir {root}2 run")
    assert service.running_pid(ws, clean=False) is None
    assert service.stop(ws) == "not verified" and kills == []
    (d / "automation.json").write_text(
        json.dumps({"pid": me, "nonce": "1" * 32, "started": service.proc_start(me)})
    )
    monkeypatch.setattr(runfiles, "command", lambda pid: f"python -P -m orch_automation --dir {root} run")
    assert service.running_pid(ws, clean=False) == me  # the exact folder does match (no signal sent here)


def test_status_says_automation_and_exits_1_when_stopped(ws, capsys):
    assert main(["--dir", str(ws), "status"]) == 1
    assert "Automation is not running." in capsys.readouterr().out
