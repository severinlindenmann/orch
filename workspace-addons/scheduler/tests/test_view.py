import json
from pathlib import Path

import jsonschema
from conftest import T, add_ticket

from orch_scheduler.cli import main
from orch_scheduler.loop import Scheduler
from orch_scheduler.view import build

SCHEMA = json.loads((Path(__file__).resolve().parents[3] / "contracts" / "addon-view.schema.json").read_text())


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
    assert lst["items"][1]["subtitle"] == "Every Monday at 07:00 UTC" and "<" not in lst["items"][1]["title"]
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
