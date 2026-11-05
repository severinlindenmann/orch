import json
import subprocess
import sys

from conftest import T, add_ticket, runs_started

from orch_automation import migrate
from orch_automation.cli import main
from orch_automation.loop import Scheduler


def tk(ws, tid):
    return json.loads((ws / f".orch/tickets/{tid}.json").read_text())


def test_ext_is_copied_once_and_the_old_data_stays(ws):
    add_ticket(ws, "t_mig00001", ext={"scheduler": {"recurring": True, "cron": "0 7 * * 1", "last_run": "2026-11-01T07:00:00Z"}})
    add_ticket(ws, "t_mig00002", ext={"scheduler": {"cron": "0 5 * * *"}, "automation": {"cron": "0 9 * * *"}})
    add_ticket(ws, "t_mig00003")
    assert migrate.tickets(ws) == 1
    t = tk(ws, "t_mig00001")
    assert t["ext"]["automation"] == t["ext"]["scheduler"]
    assert tk(ws, "t_mig00002")["ext"]["automation"] == {"cron": "0 9 * * *"}  # kept, not overwritten
    assert "ext" not in tk(ws, "t_mig00003")
    assert migrate.tickets(ws) == 0  # again: nothing changes


def test_config_table_and_files_move_once(ws):
    cfg = ws / ".orch/config.toml"
    cfg.write_text('[workspace]\nagent = "claude"\n\n[scheduler]\ninterval = 30\n')
    old = ws / ".orch/addons/scheduler"
    old.mkdir(parents=True)
    (old / "state.json").write_text('{"t_x": {"last_run": "a"}}')
    (old / "runs.jsonl").write_text("{}\n")
    new = ws / ".orch/addons/automation"
    new.mkdir(parents=True, exist_ok=True)
    (new / "runs.jsonl").write_text("keep\n")
    assert migrate.run(ws) == {"tickets": 0, "config": True, "files": 1}
    assert "[automation]\ninterval = 30" in cfg.read_text() and "[scheduler]" not in cfg.read_text()
    assert (new / "state.json").read_text().startswith('{"t_x"') and (new / "runs.jsonl").read_text() == "keep\n"
    assert migrate.run(ws) == {"tickets": 0, "config": False, "files": 0}


def test_first_pass_migrates_then_acts_on_the_new_data(ws):
    add_ticket(ws, "t_mig00004", created_at="2026-11-01T00:00:00Z",
               ext={"scheduler": {"recurring": True, "cron": "0 7 * * *", "tz": "UTC"}})
    assert Scheduler(ws).tick(T(7, 1, d=5)) == ["t_mig00004"]
    assert "automation" in tk(ws, "t_mig00004")["ext"] and runs_started(ws) == ["t_mig00004"]


def test_old_failure_kind_is_read_as_the_new_one(ws):
    q = {"id": "q1", "text": "x", "options": [], "kind": "scheduler:failure", "answer": "Try again"}
    add_ticket(ws, "t_mig00005", questions=[q])
    assert Scheduler(ws).tick(T(8)) == ["t_mig00005"]
    assert tk(ws, "t_mig00005")["ext"]["automation"]["acted"] == ["q1"]


def test_migrate_command(ws, capsys):
    add_ticket(ws, "t_mig00006", ext={"scheduler": {"cron": "0 7 * * 1"}})
    assert main(["--dir", str(ws), "migrate", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["tickets"] == 1


def test_scheduler_alias_prints_one_line_and_runs_automation(ws):
    r = subprocess.run([sys.executable, "-m", "orch_scheduler", "--dir", str(ws), "list"], check=False, capture_output=True, text=True,
                       env={"PATH": "", "ORCH_BIN": __import__("os").environ["ORCH_BIN"], "ORCH_ROOT": str(ws)})
    assert r.stdout.splitlines()[0].startswith("The scheduler is now called automation: orch automation")
    assert r.returncode == 0 and "Nothing scheduled." in r.stdout
