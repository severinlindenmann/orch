import json
from pathlib import Path

import jsonschema
import pytest
from conftest import T, add_ticket

from orch_automation.cli import main
from orch_automation.loop import Scheduler
from orch_automation.view import build

SCHEMA = json.loads((Path(__file__).resolve().parents[3] / "contracts" / "addon-view.schema.json").read_text())


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    """Views show local time: run these tests in UTC."""
    import time

    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def check(view):
    jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker()).validate(view)
    assert len(json.dumps(view)) < 256_000


def blocks(view, type_, title=None):
    return [b for b in view["blocks"] if b["type"] == type_ and (title is None or b.get("title", "").split(" · ")[0] == title)]


def test_empty_view_is_valid(ws):
    v = build(ws, T(8))
    check(v)
    assert {b["type"] for b in v["blocks"]} == {"list"}  # no stat cards, no calendar, no table
    (sch,) = blocks(v, "list", "Schedules")
    assert sch["title"] == "Schedules · 0 on" and 'orch automation repeat ticket "daily 07:30"' in sch["items"][0]["subtitle"]
    assert "stopped" in v["notice"]
def test_schedule_listed_and_old_blocks_gone(ws):
    add_ticket(ws, "t_rec00001", title="Weekly <b>report</b>", ext={"automation": {"recurring": True, "cron": "0 7 * * 1"}})
    v = build(ws, T(8))
    check(v)
    assert not blocks(v, "stat") and not blocks(v, "calendar") and not blocks(v, "table")
    (rep,) = blocks(v, "list", "Schedules")
    assert rep["title"] == "Schedules · 1 on"
    assert [(i["title"], i["subtitle"]) for i in rep["items"]] == [("Weekly breport/b", "Mondays at 07:00 UTC · next in 4 d")]
def test_recent_runs_short_list_with_titles(ws):
    add_ticket(ws, "t_wake002", title="Bank check", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"})
    s = Scheduler(ws)
    s.tick(T(8))
    (ws / "ended-t_wake002").write_text("")  # ended at once, wrote nothing: a fast fail
    s.tick(T(8, 1))
    v = build(ws, T(9))
    check(v)
    (lst,) = blocks(v, "list", "Recent runs")
    assert lst["items"][0]["title"] == "Bank check" and lst["items"][0]["tone"] == "bad" and lst["items"][0]["link"] == "t_wake002"
    assert "exit" not in json.dumps(lst).lower()
def test_good_run_has_duration(ws):
    add_ticket(ws, "t_wake003", title="Good", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"})
    s = Scheduler(ws)
    s.tick(T(8))
    import os
    import time
    (ws / 'ended-t_wake003').write_text('')
    os.utime(ws / '.orch/run/logs/t_wake003-r1.log', (time.time() + 60, time.time() + 60))
    s.tick(T(8, 1))
    v = build(ws, T(9))
    check(v)
    item = blocks(v, "list", "Recent runs")[0]["items"][0]
    assert item["tone"] == "good" and "done" in item["subtitle"]
def test_view_is_read_only_and_cli_prints_json(ws, capsys):
    add_ticket(ws, "t_wake004")
    before = sorted(p.name for p in (ws / ".orch").rglob("*") if p.is_file())
    assert main(["--dir", str(ws), "view", "--json"]) == 0
    check(json.loads(capsys.readouterr().out))
    assert before == sorted(p.name for p in (ws / ".orch").rglob("*") if p.is_file())


def test_frequent_repeat_is_one_row(ws):
    add_ticket(ws, "t_five0001", title="TEST: every 5 min", ext={"automation": {"recurring": True, "cron": "*/5 * * * *"}})
    v = build(ws, T(15, 2))
    check(v)
    (rep,) = blocks(v, "list", "Schedules")
    assert len(rep["items"]) == 1 and rep["items"][0]["subtitle"].startswith("Every 5 minutes · next ")
def test_notice_says_next_run_when_running(ws, monkeypatch):
    from orch_automation import service

    monkeypatch.setattr(service, "running_pid", lambda root, clean=False: 1)
    add_ticket(ws, "t_hour0001", ext={"automation": {"recurring": True, "cron": "0 * * * *"}})
    v = build(ws, T(8))
    check(v)
    assert v["notice"].startswith("Running. Next run in ")
@pytest.mark.parametrize("cron,words", [
    ("* * * * *", "Every minute"),
    ("*/5 * * * *", "Every 5 minutes"),
    ("0 * * * *", "Every hour"),
    ("15 * * * *", "Every hour at 15 past"),
    ("0 */3 * * *", "Every 3 hours"),
    ("30 6 * * *", "Every day at 06:30"),
    ("0 8 * * 1", "Mondays at 08:00"),
    ("0 8 * * mon,thu", "Mondays and Thursdays at 08:00"),
    ("0 8 * * 1-5", "Weekdays at 08:00"),
    ("0 8 * * 6,0", "Weekends at 08:00"),
    ("0 9 1 * *", "Every month on day 1 at 09:00"),
    ("0 9 1 1 *", "On a custom plan (0 9 1 1 *, UTC)"),
])
def test_cron_in_plain_words(cron, words):
    from zoneinfo import ZoneInfo

    from orch_automation.view import cron_human

    assert cron_human(cron, ZoneInfo("UTC")) == words.replace(", UTC)", ")")


def test_cron_words_say_utc_only_when_no_zone():
    from zoneinfo import ZoneInfo

    from orch_automation.view import cron_human

    assert cron_human("0 7 * * *") == "Every day at 07:00 UTC"
    assert cron_human("0 7 * * *", ZoneInfo("Europe/Zurich")) == "Every day at 07:00"


def test_repeats_are_one_row_each_sorted_and_monthly_stays(ws):
    add_ticket(ws, "t_mon00001", title="Close", ext={"automation": {"recurring": True, "cron": "0 9 1 * *", "tz": "Europe/Zurich"}})
    add_ticket(ws, "t_day00001", title="Daily", ext={"automation": {"recurring": True, "cron": "30 7 * * *", "tz": "Europe/Zurich"}})
    v = build(ws, T(8))
    check(v)
    (rep,) = blocks(v, "list", "Schedules")
    assert [i["tickets"][0]["id"] for i in rep["items"]] == ["t_day00001", "t_mon00001"]
    assert rep["items"][1]["subtitle"] == "Every month on day 1 at 09:00 · next in 27 d"


def test_listen_section_shows_state_and_arrivals(ws):
    from orch_automation import listen, service

    service_pid = lambda root, clean=False: 1
    import pytest as _p
    mp = _p.MonkeyPatch()
    mp.setattr(service, "running_pid", service_pid)
    try:
        listen._write(ws, listening=True, note="", recent=[
            {"id": "m_1", "type": "start", "at": "2026-11-04T07:00:00Z", "seen": True, "allowed": True},
            {"id": "m_2", "type": "delegate", "at": "2026-11-04T07:30:00Z", "seen": False, "allowed": False}])
        v = build(ws, T(8))
    finally:
        mp.undo()
    check(v)
    assert not blocks(v, "stat")
    (arr,) = blocks(v, "list", "Listen")
    (relay,) = arr["items"]
    assert relay["title"] == "Phone and other workspaces"
    assert [r.split(" · ")[-1] for r in relay["detail"][0]["lines"]] == ["Waiting for you", "Started a run"]


def test_schedule_row_is_an_accordion_with_actions_and_linked_tickets(ws):
    add_ticket(ws, "t_rec00001", title="Month-end check", status="active",
               ext={"automation": {"recurring": True, "cron": "0 8 * * 1-5", "tz": "Europe/Zurich", "agent": "claude"}})
    add_ticket(ws, "t_kid00001", title="Run of Monday", status="done", parent="t_rec00001")
    v = build(ws, T(8))
    check(v)
    (sch,) = blocks(v, "list", "Schedules")
    (row,) = sch["items"]
    assert row["toggle"]["on"] is True and row["toggle"]["action"] == {"op": "addon.act", "args": {"verb": "toggle", "target": "t_rec00001"}}
    assert {d["label"] for d in row["detail"]} >= {"Repeats", "Time zone", "Next run", "Last run", "Agent"}
    assert [(t["id"], t["status"]["label"]) for t in row["tickets"]] == [("t_rec00001", "Doing"), ("t_kid00001", "Done")]
    assert [a["label"] for a in row["actions"]] == ["Run now", "Delete"]
    assert row["actions"][1]["confirm"] == "Stop and remove this schedule? Its tickets stay."


def test_paused_schedule_stays_listed_but_is_not_planned(ws):
    add_ticket(ws, "t_rec00001", title="Close", ext={"automation": {"recurring": True, "cron": "0 8 * * *", "paused": True}})
    v = build(ws, T(7))
    check(v)
    (row,) = blocks(v, "list", "Schedules")[0]["items"]
    assert row["toggle"]["on"] is False and row["subtitle"].endswith("off")
    assert next(d for d in row["detail"] if d["label"] == "Next run")["value"].startswith("Off")


def test_webhook_source_has_a_copy_field(ws):
    add_ticket(ws, "t_hook0001", title="Pay suppliers", status="waiting", waiting_on={"kind": "external", "ref": "wh_abc123"})
    v = build(ws, T(7))
    check(v)
    items = blocks(v, "list", "Listen")[0]["items"]
    assert items[1]["detail"][0] == {"label": "Webhook address", "value": "wh_abc123", "copy": True}
