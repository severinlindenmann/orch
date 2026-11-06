import json

import pytest
from conftest import add_ticket, calls, runs_started

from orch_automation.actions import Bad, act
from orch_automation.cli import main


def ext(ws, tid):
    return json.loads((ws / ".orch" / "tickets" / f"{tid}.json").read_text()).get("ext", {}).get("automation")


def sched(ws):
    return add_ticket(ws, "t_rec00001", ext={"automation": {"recurring": True, "cron": "0 8 * * *"}})


def test_off_on_toggle(ws):
    sched(ws)
    act(ws, "off", "t_rec00001")
    assert ext(ws, "t_rec00001")["paused"] is True
    act(ws, "toggle", "t_rec00001")
    assert ext(ws, "t_rec00001")["paused"] is False


def test_run_now_starts_one_run(ws):
    sched(ws)
    act(ws, "run", "t_rec00001")
    assert runs_started(ws) == ["t_rec00001"]


def test_delete_removes_the_schedule_and_keeps_the_ticket(ws):
    sched(ws)
    assert act(ws, "delete", "t_rec00001")["deleted"] is True
    assert not ext(ws, "t_rec00001")
    assert (ws / ".orch" / "tickets" / "t_rec00001.json").exists()


@pytest.mark.parametrize("verb,target", [("rm", "t_rec00001"), ("on", "../x"), ("on", "t_nothere1")])
def test_bad_requests_are_refused(ws, verb, target):
    sched(ws)
    with pytest.raises(Bad):
        act(ws, verb, target)
    assert not [c for c in calls(ws) if c["args"][:1] == ["ext"]]


def test_cli_act(ws, capsys):
    sched(ws)
    assert main(["--dir", str(ws), "act", "off", "t_rec00001", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["paused"] is True
    assert main(["--dir", str(ws), "act", "on", "t_bad", "--json"]) == 2
