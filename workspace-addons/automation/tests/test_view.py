import json
from pathlib import Path

import jsonschema
import pytest
from conftest import T, add_ticket

from orch_automation.cli import main
from orch_automation.loop import Scheduler
from orch_automation.view import build

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts" / "addon-view.schema.json").read_text()
)


@pytest.fixture(autouse=True)
def utc(set_tz):
    """Views show local time: run these tests in UTC."""
    set_tz("UTC")


def check(view):
    jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker()).validate(view)
    assert len(json.dumps(view)) < 256_000


def blocks(view, type_, title=None):
    return [
        b
        for b in view["blocks"]
        if b["type"] == type_ and (title is None or b.get("title", "").split(" · ")[0] == title)
    ]


def test_empty_view_is_valid(ws):
    v = build(ws, T(8))
    check(v)
    assert {b["type"] for b in v["blocks"]} == {"list", "footnote"}  # no schedules: no table, no week
    (sch,) = blocks(v, "list", "Schedules")
    assert sch["items"] == [] and sch["empty"]["title"] == "No schedules yet"
    assert "stopped" in v["notice"] and "Ask your helper" not in v["notice"] and "Press" not in v["notice"]
    assert v["button"] == {"label": "Start", "action": {"op": "addon.start"}}


def test_schedule_listed_as_a_table_with_the_week_ahead(ws, monkeypatch):
    from orch_automation import service

    monkeypatch.setattr(service, "running_pid", lambda root, clean=False: 1)
    add_ticket(
        ws,
        "t_rec00001",
        title="Weekly <b>report</b>",
        ext={"automation": {"recurring": True, "cron": "0 7 * * 1"}},
    )
    v = build(ws, T(8))
    check(v)
    assert not blocks(v, "stat")
    (table,) = blocks(v, "table")
    assert [c["label"] for c in table["columns"]] == ["Schedule", "Repeats", "Next run", "Last result"]
    (row,) = table["rows"]
    assert row["cells"]["schedule"] == "Weekly breport/b" and row["cells"]["repeats"] == "Mondays at 07:00"
    assert row["cells"]["last"] == "Not yet" and row["link"] == "t_rec00001"
    (week,) = blocks(v, "calendar")
    assert len(week["days"]) == 7 and any(d["items"] for d in week["days"])


def test_recent_runs_short_list_with_titles(ws):
    add_ticket(
        ws, "t_wake002", title="Bank check", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"}
    )
    s = Scheduler(ws)
    s.tick(T(8))
    (ws / "ended-t_wake002").write_text("")  # ended at once, wrote nothing: a fast fail
    s.tick(T(8, 1))
    v = build(ws, T(9))
    check(v)
    (lst,) = blocks(v, "list", "Recent runs")
    assert (
        lst["items"][0]["title"] == "Bank check"
        and lst["items"][0]["chips"][0] == {"label": "Stopped", "tone": "bad"}
        and lst["items"][0]["link"] == "t_wake002"
    )
    assert "exit" not in json.dumps(lst).lower()


def test_good_run_has_duration(ws):
    add_ticket(ws, "t_wake003", title="Good", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"})
    s = Scheduler(ws)
    s.tick(T(8))
    import os
    import time

    (ws / "ended-t_wake003").write_text("")
    os.utime(ws / ".orch/run/logs/t_wake003-r1.log", (time.time() + 60, time.time() + 60))
    s.tick(T(8, 1))
    v = build(ws, T(9))
    check(v)
    item = blocks(v, "list", "Recent runs")[0]["items"][0]
    assert item["chips"][0]["label"] == "Done" and "done in" in item["subtitle"]


def test_view_is_read_only_and_cli_prints_json(ws, capsys):
    add_ticket(ws, "t_wake004")
    before = sorted(p.name for p in (ws / ".orch").rglob("*") if p.is_file())
    assert main(["--dir", str(ws), "view", "--json"]) == 0
    check(json.loads(capsys.readouterr().out))
    assert before == sorted(p.name for p in (ws / ".orch").rglob("*") if p.is_file())


def test_frequent_repeat_is_one_row(ws, monkeypatch):
    from orch_automation import service

    monkeypatch.setattr(service, "running_pid", lambda root, clean=False: 1)
    add_ticket(
        ws,
        "t_five0001",
        title="TEST: every 5 min",
        ext={"automation": {"recurring": True, "cron": "*/5 * * * *"}},
    )
    v = build(ws, T(15, 2))
    check(v)
    (rep,) = blocks(v, "table")
    assert len(rep["rows"]) == 1 and rep["rows"][0]["cells"]["repeats"] == "Every 5 minutes"


def test_notice_says_next_run_when_running(ws, monkeypatch):
    from orch_automation import service

    monkeypatch.setattr(service, "running_pid", lambda root, clean=False: 1)
    add_ticket(ws, "t_hour0001", ext={"automation": {"recurring": True, "cron": "0 * * * *"}})
    v = build(ws, T(8))
    check(v)
    assert v["notice"].startswith("On. Next: ")
    assert "button" not in v


@pytest.mark.parametrize(
    "cron,words",
    [
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
        ("0 9 31 * *", "Every month on day 31 at 09:00"),
        ("0 9 1 1 *", "On a custom plan (0 9 1 1 *)"),
    ],
)
def test_cron_in_plain_words(cron, words):
    from zoneinfo import ZoneInfo

    from orch_automation.view import cron_human

    assert cron_human(cron, ZoneInfo("UTC"), None, ZoneInfo("UTC")) == words


def test_cron_words_are_in_the_local_zone_never_utc():
    from zoneinfo import ZoneInfo

    from orch_automation.view import cron_human

    zh, ny = ZoneInfo("Europe/Zurich"), ZoneInfo("America/New_York")
    assert cron_human("0 7 * * *", None, T(8), zh) == "Every day at 08:00"
    assert cron_human("0 7 * * *", zh, T(8), zh) == "Every day at 07:00"
    assert cron_human("0 2 * * 1", None, T(8), ny) == "Sundays at 21:00"  # the day moves with the time


def test_schedule_time_is_shown_once_in_local_time(ws, set_tz, monkeypatch):
    from orch_automation import service

    monkeypatch.setattr(service, "running_pid", lambda root, clean=False: 1)
    """D15: a cron without a zone (read in UTC) must not read '07:00 UTC' next to a local '08:00'."""
    set_tz("Europe/Zurich")
    add_ticket(ws, "t_utc00001", title="Report", ext={"automation": {"recurring": True, "cron": "0 7 * * 1"}})
    add_ticket(
        ws,
        "t_zh000001",
        title="Zurich",
        ext={"automation": {"recurring": True, "cron": "30 9 * * *", "tz": "Europe/Zurich"}},
    )
    v = build(ws, T(8))
    check(v)
    (sch,) = blocks(v, "table")
    rows = {r["cells"]["schedule"]: r["cells"] for r in sch["rows"]}
    utc, zh = rows["Report"], rows["Zurich"]
    assert "UTC" not in utc["repeats"] and utc["repeats"] == "Mondays at 08:00"
    assert utc["next"].endswith("08:00")  # the next run and the words agree
    assert zh["repeats"] == "Every day at 09:30"


def test_repeats_are_one_row_each_sorted_and_monthly_stays(ws, monkeypatch):
    from orch_automation import service

    monkeypatch.setattr(service, "running_pid", lambda root, clean=False: 1)
    add_ticket(
        ws,
        "t_mon00001",
        title="Close",
        ext={"automation": {"recurring": True, "cron": "0 9 1 * *", "tz": "Europe/Zurich"}},
    )
    add_ticket(
        ws,
        "t_day00001",
        title="Daily",
        ext={"automation": {"recurring": True, "cron": "30 7 * * *", "tz": "Europe/Zurich"}},
    )
    v = build(ws, T(8))
    check(v)
    (rep,) = blocks(v, "table")
    assert [r["link"] for r in rep["rows"]] == ["t_day00001", "t_mon00001"]
    assert rep["rows"][1]["cells"]["repeats"] == "Every month on day 1 at 08:00"  # 09:00 Zurich


def test_listen_section_shows_state_and_arrivals(ws):
    from orch_automation import listen, service

    service_pid = lambda root, clean=False: 1
    import pytest as _p

    mp = _p.MonkeyPatch()
    mp.setattr(service, "running_pid", service_pid)
    try:
        listen._write(
            ws,
            listening=True,
            note="",
            recent=[
                {"id": "m_1", "type": "start", "at": "2026-11-04T07:00:00Z", "seen": True, "allowed": True},
                {
                    "id": "m_2",
                    "type": "delegate",
                    "at": "2026-11-04T07:30:00Z",
                    "seen": False,
                    "allowed": False,
                },
            ],
        )
        v = build(ws, T(8))
    finally:
        mp.undo()
    check(v)
    assert not blocks(v, "stat")
    (arr,) = blocks(v, "list", "Incoming work")
    (relay,) = arr["items"]
    assert relay["title"] == "Phone and other workspaces"
    assert [r.split(" · ")[-1] for r in relay["detail"][0]["lines"]] == ["Waiting for you", "Started a run"]


def test_schedule_row_has_a_switch_and_buttons(ws):
    add_ticket(
        ws,
        "t_rec00001",
        title="Month-end check",
        status="active",
        ext={
            "automation": {"recurring": True, "cron": "0 8 * * 1-5", "tz": "Europe/Zurich", "agent": "claude"}
        },
    )
    v = build(ws, T(8))
    check(v)
    (sch,) = blocks(v, "table")
    (row,) = sch["rows"]
    assert row["toggle"]["on"] is True and row["toggle"]["action"] == {
        "op": "addon.act",
        "args": {"verb": "toggle", "target": "t_rec00001"},
    }
    assert row["subtitle"] == "claude"
    assert [a["label"] for a in row["actions"]] == ["Run now", "Edit"]
    assert row["actions"][1]["action"] == {"op": "addon.edit", "args": {"target": "t_rec00001"}}


def test_last_result_comes_from_the_recorded_run(ws):
    add_ticket(ws, "t_rec00004", title="Daily", ext={"automation": {"recurring": True, "cron": "0 8 * * *"}})
    runs = ws / ".orch" / "addons" / "automation"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "runs.jsonl").write_text(
        json.dumps({"ticket": "t_rec00004", "at": "2026-11-04T08:00:00Z", "exit": 0}) + "\n"
    )
    v = build(ws, T(9))
    check(v)
    (row,) = blocks(v, "table")[0]["rows"]
    assert row["cells"]["last"].startswith("Done · ")


def test_paused_schedule_stays_listed_but_is_not_planned(ws):
    add_ticket(
        ws,
        "t_rec00001",
        title="Close",
        ext={"automation": {"recurring": True, "cron": "0 8 * * *", "paused": True}},
    )
    v = build(ws, T(7))
    check(v)
    (row,) = blocks(v, "table")[0]["rows"]
    assert row["toggle"]["on"] is False and row["cells"]["next"] == "Off"


def test_webhook_source_has_a_copy_field(ws):
    add_ticket(
        ws,
        "t_hook0001",
        title="Pay suppliers",
        status="waiting",
        waiting_on={"kind": "external", "ref": "wh_abc123"},
    )
    v = build(ws, T(7))
    check(v)
    items = blocks(v, "list", "Incoming work")[0]["items"]
    assert items[0]["detail"][0] == {"label": "Webhook address", "value": "wh_abc123", "copy": True}


def test_rows_show_the_ticket_key_first(ws):
    add_ticket(
        ws,
        "t_rec00002",
        title="Weekly report",
        key="MEC-7",
        ext={"automation": {"recurring": True, "cron": "0 7 * * 1"}},
    )
    v = build(ws, T(8))
    check(v)
    (rep,) = blocks(v, "table")
    assert rep["rows"][0]["cells"]["schedule"] == "MEC-7 · Weekly report"


def test_repeat_takes_a_key_and_list_shows_it(ws):
    from orch_automation.cli import describe, repeat

    add_ticket(ws, "t_rec00003", title="Bank check", key="MEC-9")
    assert repeat(ws, "mec-9", "0 7 * * 1", False)["ticket"] == "t_rec00003"
    assert [r["key"] for r in describe(ws) if r["ticket"] == "t_rec00003"] == ["MEC-9"]


def test_stopped_scheduler_shows_paused_not_a_countdown(ws):
    add_ticket(ws, "t_rec00003", title="Weekly", ext={"automation": {"recurring": True, "cron": "0 7 * * 1"}})
    v = build(ws, T(8))  # no running service
    check(v)
    (rep,) = blocks(v, "table")
    assert rep["rows"][0]["cells"]["next"] == "Paused"


def test_countdown_words_are_written_in_full():
    from datetime import timedelta

    from orch_automation.view import _in

    assert _in(timedelta(days=3)) == "in 3 days"
    assert _in(timedelta(days=1, hours=2)) == "in 1 day"
    assert _in(timedelta(hours=5)) == "in 5 hours"
    assert _in(timedelta(minutes=1)) == "in 1 minute"


def test_page_has_the_accepted_headings_and_footnote(ws, monkeypatch):
    """Coming up (with the week), Recent runs (heading above its card, empty state) and the incoming-work footnote."""
    from orch_automation import service

    monkeypatch.setattr(service, "running_pid", lambda root, clean=False: 1)
    add_ticket(
        ws, "t_rec00009", title="Weekly report", ext={"automation": {"recurring": True, "cron": "0 8 * * 1"}}
    )
    v = build(ws, T(7))
    check(v)
    (table,) = blocks(v, "table")
    assert "title" not in table
    (week,) = blocks(v, "calendar")
    assert week["title"] == "Coming up" and week["meta"].endswith("Workspace time")
    (runs,) = blocks(v, "list", "Recent runs")
    assert runs["above"] is True and runs["meta"] == "Latest activity" and runs["items"] == []
    assert runs["empty"]["title"] == "Nothing has run yet" and "run it now" in runs["empty"]["text"]
    foot = v["blocks"][-1]
    assert foot["type"] == "footnote" and foot["link"]["to"] == "app:addon/relay"
    assert foot["text"].startswith("Incoming from your phone and other workspaces")
