import json
from pathlib import Path

import jsonschema
import pytest
from conftest import T, add_ticket

from orch_scheduler.cli import main
from orch_scheduler.loop import Scheduler
from orch_scheduler.view import build

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
    return [b for b in view["blocks"] if b["type"] == type_ and (title is None or b.get("title") == title)]


def test_empty_view_is_valid(ws):
    v = build(ws, T(8))
    check(v)
    assert blocks(v, "stat")[0]["value"] == "none planned"
    assert len(blocks(v, "calendar")[0]["days"]) == 7
    assert "stopped" in v["notice"]


def test_next_runs_calendar_and_list(ws):
    add_ticket(ws, "t_wake001", title="Check import", status="waiting",
               waiting_on={"kind": "time", "until": "2026-11-05T10:00:00Z"})
    add_ticket(ws, "t_rec00001", title="Weekly <b>report</b>", ext={"scheduler": {"recurring": True, "cron": "0 7 * * 1"}})
    v = build(ws, T(8))
    check(v)
    assert blocks(v, "stat")[0]["value"] == "in 1 d"
    (lst,) = blocks(v, "list", "Next runs")
    assert [i["link"] for i in lst["items"]] == ["t_wake001", "t_rec00001"]
    assert lst["items"][1]["subtitle"] == "Mondays at 07:00 · next Mon 07:00" and "<" not in lst["items"][1]["title"]
    (rep,) = blocks(v, "list", "Repeating")
    assert [(i["link"], i["subtitle"]) for i in rep["items"]] == [("t_rec00001", "Mondays at 07:00")]
    days = blocks(v, "calendar")[0]["days"]
    assert sum(len(d["items"]) for d in days) == 2


def test_recent_runs_and_failed_stat(ws):
    add_ticket(ws, "t_wake002", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"})
    (ws / ".orch/config.toml").write_text("[scheduler]\nagent = 'no-such-agent-xyz {prompt}'\n")
    s = Scheduler(ws)
    s.tick(T(8))  # cannot start: exit 127 recorded
    v = build(ws, T(9))
    check(v)
    stats = {b["label"]: b for b in blocks(v, "stat")}
    assert stats["Last run failed"]["tone"] == "bad" and stats["Runs today"]["value"] == 1
    (tbl,) = blocks(v, "table", "Recent runs")
    assert tbl["rows"][0]["cells"]["state"] == "bad" and tbl["rows"][0]["link"] == "t_wake002"


def test_good_run_has_duration_and_no_failed_stat(ws):
    add_ticket(ws, "t_wake003", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"})
    s = Scheduler(ws)
    s.tick(T(8))
    s.runner.reap(T(8, 1), wait=True)
    v = build(ws, T(9))
    check(v)
    assert "Last run failed" not in {b["label"] for b in blocks(v, "stat")}
    assert blocks(v, "table")[0]["rows"][0]["cells"]["exit"] == 0


def test_view_is_read_only_and_cli_prints_json(ws, capsys):
    add_ticket(ws, "t_wake004")
    before = sorted(p.name for p in (ws / ".orch").rglob("*") if p.is_file())
    assert main(["--dir", str(ws), "view", "--json"]) == 0
    check(json.loads(capsys.readouterr().out))
    assert before == sorted(p.name for p in (ws / ".orch").rglob("*") if p.is_file())


def test_frequent_repeat_is_one_card_per_day_on_every_day(ws):
    add_ticket(ws, "t_five0001", title="TEST: every 5 min", ext={"scheduler": {"recurring": True, "cron": "*/5 * * * *"}})
    add_ticket(ws, "t_three001", title="Every 3 hours", ext={"scheduler": {"recurring": True, "cron": "0 */3 * * *"}})
    v = build(ws, T(15, 2))  # 2026-11-05 15:02 UTC
    check(v)
    days = blocks(v, "calendar")[0]["days"]
    assert len(days) == 7
    for i, d in enumerate(days):
        five = [x for x in d["items"] if x["link"] == "t_five0001"]
        assert len(five) == 1, d  # one card, every day (later days are not empty)
        assert five[0]["every"] == "Every 5 min" and "288 runs/day" in five[0]["note"]
        assert five[0]["time"] == ("15:05" if i == 0 else "00:00")
        assert five[0]["note"] == ("next 15:05 · 288 runs/day" if i == 0 else "288 runs/day")
        three = [x for x in d["items"] if x["link"] == "t_three001"]  # every 3 h: each time shown
        assert all("every" not in x for x in three) and len(three) == (2 if i == 0 else 8)
    (lst,) = blocks(v, "list", "Next runs")
    assert [i["link"] for i in lst["items"]] == ["t_five0001", "t_three001"]  # one line per ticket
    assert lst["items"][0]["subtitle"].startswith("Every 5 minutes · next ")


def test_hourly_shows_times(ws):
    add_ticket(ws, "t_hour0001", ext={"scheduler": {"recurring": True, "cron": "0 * * * *"}})
    v = build(ws, T(8))
    check(v)
    d = blocks(v, "calendar")[0]["days"][1]
    assert len(d["items"]) == 20 and all("every" not in x for x in d["items"])  # 24 runs, capped at 20 cards


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
    from orch_scheduler.view import cron_human

    assert cron_human(cron) == words


def test_cron_words_use_local_time_and_shift_the_day():
    from datetime import timedelta, timezone

    from orch_scheduler.view import cron_human

    assert cron_human("0 23 * * 1", timezone(timedelta(hours=2))) == "Tuesdays at 01:00"
    assert cron_human("0 7 * * *", timezone(timedelta(hours=1))) == "Every day at 08:00"
