import json
import time

from conftest import add_ticket

from orch_scheduler import service
from orch_scheduler.cli import describe, main


def test_start_status_stop(ws):
    pid = service.start(ws)
    assert service.running_pid(ws) == pid
    assert service.start(ws) == pid  # no second one
    assert main(["--dir", str(ws), "status"]) == 0
    assert service.stop(ws)
    for _ in range(30):
        if service.running_pid(ws) is None:
            break
        time.sleep(0.1)
    assert main(["--dir", str(ws), "status"]) == 1
    assert not service.stop(ws)


def test_list(ws):
    add_ticket(ws, "t_wake009", status="waiting", waiting_on={"kind": "time", "until": "2026-11-05T08:00:00Z"})
    add_ticket(ws, "t_rep00001", ext={"scheduler": {"recurring": True, "cron": "0 7 * * 1"}})
    rows = describe(ws)
    assert {r["ticket"] for r in rows} == {"t_wake009", "t_rep00001"}


def test_repeat_sets_ext_and_off(ws, capsys):
    add_ticket(ws, "t_rep00002")
    assert main(["--dir", str(ws), "repeat", "t_rep00002", "--cron", "0 7 * * 1", "--agent", "codex", "--json"]) == 0
    t = json.loads((ws / ".orch/tickets/t_rep00002.json").read_text())
    assert t["ext"]["scheduler"] == {"recurring": True, "cron": "0 7 * * 1", "agent": "codex"}
    assert main(["--dir", str(ws), "repeat", "t_rep00002", "--off"]) == 0
    t = json.loads((ws / ".orch/tickets/t_rep00002.json").read_text())
    assert t["ext"]["scheduler"]["recurring"] is False and t["ext"]["scheduler"]["cron"] == "0 7 * * 1"


def test_repeat_refuses_plainly(ws, capsys):
    add_ticket(ws, "t_rep00003")
    assert main(["--dir", str(ws), "repeat", "t_rep00003", "nonsense", "--json"]) == 2
    assert "cron" in json.loads(capsys.readouterr().out)["error"]
    assert main(["--dir", str(ws), "repeat", "t_nothere1", "0 7 * * 1"]) == 2
    assert capsys.readouterr().err.startswith("Refused: ")


def test_planted_module_in_the_workspace_is_not_run(ws):
    (ws / "orch_scheduler.py").write_text("open('PLANTED', 'w').write('x')\n")
    (ws / "json.py").write_text("open('PLANTED', 'w').write('x')\n")
    pid = service.start(ws)
    try:
        for _ in range(30):  # give the child time to import
            if (ws / ".orch/addons/scheduler/scheduler.log").read_text().strip():
                break
            time.sleep(0.1)
        assert service.running_pid(ws) == pid
    finally:
        service.stop(ws)
    assert not (ws / "PLANTED").exists()
