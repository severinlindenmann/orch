from datetime import UTC, datetime

from conftest import T

from orch_scheduler.cron import is_due, next_after, valid


def test_valid():
    assert valid("0 7 * * 1") and not valid("0 7 * *") and not valid("nope") and not valid("0 7 * * * *")


def test_due_inside_window():
    assert is_due("0 7 * * *", T(6, 59), T(7, 1))
    assert not is_due("0 7 * * *", T(7, 0), T(7, 1))  # already ran at 07:00
    assert not is_due("0 7 * * *", T(6, 0), T(6, 59))


def test_missed_runs_collapse_to_one():
    # off for 3 days: still just "due" once; after that run (since=now) nothing is due
    assert is_due("0 7 * * *", T(8, 0, d=1), T(8, 0, d=4))
    assert not is_due("0 7 * * *", T(8, 0, d=4), T(8, 5, d=4))


def test_utc_weekday():
    # 2026-11-02 is a Monday
    assert is_due("0 7 * * 1", T(0, 0, d=1), T(7, 30, d=2))
    assert next_after("0 7 * * 1", T(7, 30, d=2)).day == 9


# ---- UX-05: plain words ---------------------------------------------------------------------------------------
import json

import pytest
from conftest import add_ticket, calls, runs_started

from orch_scheduler import plain
from orch_scheduler.cli import main
from orch_scheduler.loop import Scheduler


@pytest.mark.parametrize("text,cron", [
    ("every monday 08:00", "0 8 * * 1"),
    ("Every  Friday 16:30", "30 16 * * 5"),
    ("daily 07:30", "30 7 * * *"),
    ("every 15 minutes", "*/15 * * * *"),
    ("every 1 hour", "0 */1 * * *"),
    ("every 2 hours", "0 */2 * * *"),
    ("monthly 1 09:00", "0 9 1 * *"),
])
def test_five_phrases_become_cron(text, cron):
    assert plain.parse(text, "UTC").cron == cron


def test_one_off_is_read_in_the_zone():
    now = datetime(2026, 11, 5, 6, 0, tzinfo=UTC)  # 07:00 in Zurich
    assert plain.parse("today 17:30", "Europe/Zurich", now).until == "2026-11-05T16:30:00Z"
    assert plain.parse("tomorrow 09:00", "Europe/Zurich", now).until == "2026-11-06T08:00:00Z"
    with pytest.raises(plain.Plain, match="already past"):
        plain.parse("today 06:00", "Europe/Zurich", now)


@pytest.mark.parametrize("text", ["whenever", "every 70 minutes", "every funday 08:00", "monthly 31 09:00", "every 0 hours",
                                  "daily 25:00", "0 7 * * 1 *"])
def test_anything_else_is_refused_with_examples(text):
    with pytest.raises(plain.Plain, match="every monday 08:00"):
        plain.parse(text, "UTC")


def test_default_zone_is_this_computers(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Zurich")
    assert plain.local_tz_name() == "Europe/Zurich"


def test_cron_is_read_in_the_job_zone():
    zh = plain.zone("Europe/Zurich")
    assert next_after("0 8 * * *", T(6, 0, d=5), zh).hour == 7  # 08:00 CET = 07:00 UTC
    assert is_due("0 8 * * *", T(6, 0, d=5), T(7, 5, d=5), zh)
    assert not is_due("0 8 * * *", T(6, 0, d=5), T(7, 5, d=5))  # without a zone it is 08:00 UTC


def test_repeat_cli_phrases_once_and_ux07(ws, capsys):
    add_ticket(ws, "t_pl000001")
    assert main(["--dir", str(ws), "repeat", "t_pl000001", "daily 07:30", "--tz", "Europe/Zurich"]) == 0
    out = capsys.readouterr().out
    assert "Every day at 07:30" in out and "Repeating work isn't running here. Start it: orch start" in out
    assert main(["--dir", str(ws), "repeat", "t_pl000001", "tomorrow 09:00", "--tz", "UTC"]) == 0
    t = json.loads((ws / ".orch/tickets/t_pl000001.json").read_text())
    assert t["waiting_on"]["kind"] == "time"
    assert main(["--dir", str(ws), "repeat", "t_pl000001", "every blue moon"]) == 2


def test_each_run_only_daily_or_slower(ws, capsys):
    add_ticket(ws, "t_pl000002")
    assert main(["--dir", str(ws), "repeat", "t_pl000002", "every 15 minutes", "--each-run", "sub-ticket"]) == 2
    assert "daily or slower" in capsys.readouterr().err
    assert main(["--dir", str(ws), "repeat", "t_pl000002", "daily 07:30", "--tz", "UTC", "--each-run", "sub-ticket"]) == 0
    s = json.loads((ws / ".orch/tickets/t_pl000002.json").read_text())["ext"]["scheduler"]
    assert s["each_run"] == "sub-ticket"
    assert main(["--dir", str(ws), "repeat", "t_pl000002", "daily 07:30", "--tz", "UTC"]) == 0  # opt-in: gone again
    assert "each_run" not in json.loads((ws / ".orch/tickets/t_pl000002.json").read_text())["ext"]["scheduler"]


# ---- the loop: zone, sub-tickets, agent -------------------------------------------------------------------------
def kids(ws):
    return [json.loads(p.read_text()) for p in sorted((ws / ".orch/tickets").glob("t_*.json"))
            if json.loads(p.read_text()).get("parent")]


def test_loop_runs_a_repeat_at_local_time(ws):
    add_ticket(ws, "t_zn000001", created_at="2026-11-05T00:00:00Z",
               ext={"scheduler": {"recurring": True, "cron": "0 8 * * *", "tz": "Europe/Zurich"}})
    s = Scheduler(ws)
    assert s.tick(T(6, 59, d=5)) == []
    assert s.tick(T(7, 1, d=5)) == ["t_zn000001"]  # 08:00 in Zurich


def test_each_run_makes_one_sub_ticket_per_occurrence_and_runs_on_it(ws):
    add_ticket(ws, "t_sub00001", title="Report", created_at="2026-11-01T00:00:00Z",
               ext={"scheduler": {"recurring": True, "cron": "0 7 * * *", "tz": "UTC", "each_run": "sub-ticket"}})
    s = Scheduler(ws)
    (tid,) = s.tick(T(7, 1, d=5))
    (k,) = kids(ws)
    assert tid == k["id"] and k["parent"] == "t_sub00001" and k["ext"]["scheduler"]["occurrence"] == "t_sub00001:2026-11-05T07:00:00Z"
    assert runs_started(ws) == [k["id"]]
    assert s.tick(T(7, 2, d=5)) == [] and len(kids(ws)) == 1


def test_sub_ticket_is_made_in_one_write_with_its_occurrence(ws):
    add_ticket(ws, "t_sub00002", title="Report", created_at="2026-11-01T00:00:00Z",
               ext={"scheduler": {"recurring": True, "cron": "0 7 * * *", "tz": "UTC", "each_run": "sub-ticket"}})
    Scheduler(ws).tick(T(7, 1, d=5))
    new = [c["args"] for c in calls(ws) if c["args"][:2] == ["ticket", "new"]]
    assert len(new) == 1 and new[0][-2] == "--ext" and "t_sub00002:2026-11-05T07:00:00Z" in new[0][-1]
    assert not any(c["args"][:2] == ["ext", "set"] and c["args"][2] != "t_sub00002" for c in calls(ws))  # no second write


def test_only_a_child_with_this_occurrence_id_is_reused(ws):
    add_ticket(ws, "t_sub00003", title="Report", created_at="2026-11-01T00:00:00Z",
               ext={"scheduler": {"recurring": True, "cron": "0 7 * * *", "tz": "UTC", "each_run": "sub-ticket"}})
    add_ticket(ws, "t_other001", title="Report \u00b7 2026-11-05 07:00", parent="t_sub00003")  # same title, no occurrence id
    (tid,) = Scheduler(ws).tick(T(7, 1, d=5))
    assert tid != "t_other001" and len(kids(ws)) == 2


def test_ticket_agent_goes_to_run_start(ws):
    add_ticket(ws, "t_ag000001", created_at="2026-11-01T00:00:00Z",
               ext={"scheduler": {"recurring": True, "cron": "0 7 * * *", "tz": "UTC", "agent": "codex"}})
    Scheduler(ws).tick(T(7, 1, d=5))
    start = next(c["args"] for c in calls(ws) if c["args"][:2] == ["run", "start"])
    assert start[start.index("--agent") + 1] == "codex" and "oneshot" in start
