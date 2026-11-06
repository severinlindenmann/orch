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
    assert ext(ws, "t_rec00001") is None  # the key is gone
    assert any(c["args"][:2] == ["ext", "unset"] and "--if-revision" in c["args"] for c in calls(ws))
    t = json.loads((ws / ".orch" / "tickets" / "t_rec00001.json").read_text())
    assert t["title"] and t["history"]  # ticket and history stay
    from orch_automation.cli import describe

    assert describe(ws) == []


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


def test_on_sets_paused_false(ws):
    sched(ws)
    act(ws, "off", "t_rec00001")
    act(ws, "on", "t_rec00001")
    assert ext(ws, "t_rec00001")["paused"] is False


def test_run_now_works_on_a_ticket_without_a_schedule(ws):
    add_ticket(ws, "t_plain001")
    assert act(ws, "run", "t_plain001")["result"] == "started"
    assert runs_started(ws) == ["t_plain001"]
    with pytest.raises(Bad):
        act(ws, "off", "t_plain001")  # nothing to switch


def test_stale_revision_is_refused(ws, monkeypatch):
    from orch_automation import orchcli

    t = sched(ws)
    stale = {**t, "revision": 0}
    monkeypatch.setattr(orchcli, "tickets", lambda root: [stale])
    with pytest.raises(Bad, match="Try again"):
        act(ws, "off", "t_rec00001")
    assert "paused" not in ext(ws, "t_rec00001")


def test_list_shows_a_paused_repeat_as_off(ws, capsys):
    add_ticket(ws, "t_rec00001", ext={"automation": {"recurring": True, "cron": "0 8 * * *", "paused": True}})
    from orch_automation.cli import describe

    (row,) = describe(ws)
    assert row["at"] is None and row["off"] is True
    assert main(["--dir", str(ws), "list"]) == 0
    assert "off" in capsys.readouterr().out
