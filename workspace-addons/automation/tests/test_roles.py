"""ORCH-827 / ORCH-814: runs of a repeating ticket, their results, findings and the totals both pages show."""

import json
import os
from datetime import UTC, datetime, timedelta

from conftest import add_ticket, calls

from orch_automation import cli, roles, view
from orch_automation.runner import history, load_state

REPEAT = {"automation": {"recurring": True, "cron": "0 */6 * * *", "tz": "UTC"}}


def _role(ws, tid="t_role01", **kw):
    return add_ticket(ws, tid, title="Quality pass", key="ORCH-279", ext=json.loads(json.dumps(REPEAT)), **kw)


def _lines(ws, name):
    p = ws / ".orch" / "addons" / "automation" / name
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_a_run_gets_its_number_at_start_and_keeps_it(ws):
    t = _role(ws)
    history(ws, t["id"], "2026-11-01T00:00:00Z", 60, 0)  # an old line without a number: numbered by order
    n = roles.begin(ws, t["id"], "2026-11-02T00:00:00Z")
    assert n == 2
    history(ws, t["id"], "2026-11-02T00:00:00Z", 120, 0)
    assert _lines(ws, "runs.jsonl")[-1]["run"] == 2
    assert [r["run"] for r in roles.runs(ws, t)] == [2, 1]


def test_result_names_the_current_run_and_the_newest_wins(ws):
    t = _role(ws)
    roles.begin(ws, t["id"], "2026-11-02T00:00:00Z")
    roles.result(ws, t["id"], "first try", "ok")
    roles.result(
        ws,
        t["id"],
        "Tests stopped early",
        "not-finished",
        checked=["Tests: 41 passed"],
        files=["a/b.png"],
        cost=1.11,
    )
    history(ws, t["id"], "2026-11-02T00:00:00Z", 420, 0)
    r = roles.runs(ws, t)[0]
    assert (r["outcome"], r["words"], r["tone"], r["text"]) == (
        "not-finished",
        "not finished",
        "warn",
        "Tests stopped early",
    )
    assert r["checked"] == ["Tests: 41 passed"] and r["cost"] == 1.11
    assert r["files"] == [
        {"name": "b.png", "state": "unknown"}
    ]  # nothing measured yet: unknown, never unopened


def test_a_run_without_a_result_says_so(ws):
    t = _role(ws)
    history(ws, t["id"], "2026-11-01T00:00:00Z", 60, 0)
    history(ws, t["id"], "2026-11-01T06:00:00Z", 3, 1)
    assert [r["words"] for r in roles.runs(ws, t)] == ["stopped early", "finished, no result written"]


def test_a_skipped_run_costs_nothing_and_stays_out_of_recent_starts(ws):
    t = _role(ws)
    roles.skipped(ws, t["id"], "2026-11-01T06:00:00Z")
    r = roles.runs(ws, t)[0]
    assert (r["outcome"], r["cost"], r["words"]) == ("skipped", 0, "skipped, nothing changed")
    assert view._runs(ws) == []


def test_an_unwatched_run_is_kept_when_the_next_one_starts(ws):
    t = _role(ws)
    roles.begin(ws, t["id"], "2026-11-01T00:00:00Z")  # Run now on a helper: nobody writes its end line
    assert roles.runs(ws, t, running=True)[0]["outcome"] == "running"
    roles.begin(ws, t["id"], "2026-11-01T06:00:00Z")
    assert [r["run"] for r in roles.runs(ws, t)] == [2, 1]


def test_result_without_a_run_is_refused(ws):
    t = _role(ws)
    assert cli.main(["--dir", str(ws), "result", t["id"], "x", "--outcome", "ok"]) == 2


def test_finding_makes_a_ticket_naming_role_and_run_and_reuses_it(ws):
    t = _role(ws)
    roles.begin(ws, t["id"], "2026-11-01T00:00:00Z")
    assert cli.main(["--dir", str(ws), "finding", "orch-279", "Usage page cut off at 390"]) == 0
    made = [c for c in calls(ws) if c["args"][:2] == ["ticket", "new"]]
    assert len(made) == 1
    new = json.loads((ws / ".orch" / "tickets" / "t_new002.json").read_text())
    assert "Found by ORCH-279 (Quality pass), run 1" in new["history"][-1]["text"]
    roles.begin(ws, t["id"], "2026-11-01T06:00:00Z")
    assert (
        cli.main(["--dir", str(ws), "finding", t["id"], "Usage page: cut off at 390!"]) == 0
    )  # same match name
    assert len([c for c in calls(ws) if c["args"][:2] == ["ticket", "new"]]) == 1
    assert [f["run"] for f in roles.findings_of(ws, t["id"])] == [1, 2]
    assert roles.runs(ws, t)[0]["findings"] == [
        {"title": "Usage page: cut off at 390!", "ticket": "t_new002"}
    ]


def test_a_finding_seen_again_after_its_ticket_closed_gets_a_new_linked_ticket(ws):
    t = _role(ws)
    roles.begin(ws, t["id"])
    cli.main(["--dir", str(ws), "finding", t["id"], "Broken link"])
    p = ws / ".orch" / "tickets" / "t_new002.json"
    old = json.loads(p.read_text())
    old["status"] = "done"
    p.write_text(json.dumps(old))
    cli.main(["--dir", str(ws), "finding", t["id"], "Broken link"])
    new = json.loads((ws / ".orch" / "tickets" / "t_new003.json").read_text())
    assert "Seen again after t_new002 was closed" in new["history"][-1]["text"]


def test_finding_on_the_days_review_ticket_keeps_each_finding_linked(ws):
    t = _role(ws)
    add_ticket(ws, "t_daily1", title="Review today's findings")
    roles.begin(ws, t["id"])
    cli.main(["--dir", str(ws), "finding", t["id"], "One", "--ticket", "t_daily1"])
    cli.main(["--dir", str(ws), "finding", t["id"], "Two", "--ticket", "t_daily1"])
    tot = roles.totals(
        ws, t, {x: json.loads((ws / ".orch" / "tickets" / f"{x}.json").read_text()) for x in ("t_daily1",)}
    )
    assert (tot["findings"], tot["distinct_findings"], tot["tickets"], tot["open"]) == (2, 2, 1, 1)


def test_totals_count_each_ticket_once_by_its_status(ws):
    t = _role(ws)
    for i, (title, status) in enumerate([("a", "done"), ("b", "dropped"), ("c", "open")]):
        add_ticket(ws, f"t_fnd00{i}", status=status)
        roles.finding_line(ws, t["id"], 1, title, f"t_fnd00{i}", title)
    roles.finding_line(ws, t["id"], 2, "a", "t_fnd000", "a")  # seen again: one more sighting, same ticket
    tix = {
        f"t_fnd00{i}": {"id": f"t_fnd00{i}", "status": s} for i, s in enumerate(["done", "dropped", "open"])
    }
    tot = roles.totals(ws, t, tix, [])
    assert (tot["findings"], tot["distinct_findings"], tot["fixed"], tot["dropped"], tot["open"]) == (
        4,
        3,
        1,
        1,
        1,
    )


def test_file_open_state_opened_unopened_unknown(ws):
    t = _role(ws)
    art = ws / ".orch" / "tickets" / t["id"] / "artifacts"
    art.mkdir(parents=True)
    for name in ("old.png", "new.png", "seen.png"):
        (art / name).write_text("x")
    old = (datetime.now(UTC) - timedelta(days=3)).timestamp()
    os.utime(art / "old.png", (old, old))
    opens = ws / ".orch" / roles.OPENS
    opens.parent.mkdir(parents=True)
    since = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    opens.write_text(json.dumps({"since": since, "files": {t["id"]: {"seen.png": since}}}))
    roles.begin(ws, t["id"])
    roles.result(ws, t["id"], "x", "ok", files=["old.png", "new.png", "seen.png"])
    tot = roles.totals(ws, t, {})
    assert tot["files"] == {"opened": 1, "unopened": 1, "unknown": 1}
    assert view.files_words(tot) == "1 unopened, 1 unknown"


def test_grouped_scripts_count_per_script(ws):
    t = _role(ws)
    history(ws, t["id"], "2026-11-01T00:00:00Z", 1, 0, script="helper-tend")
    history(ws, t["id"], "2026-11-01T00:05:00Z", 1, 0, script="helper-tend")
    history(ws, t["id"], "2026-11-01T00:05:01Z", 1, 1, script="merge")
    tot = roles.totals(ws, t, {})
    assert tot["scripts"] == {"helper-tend": 2, "merge": 1} and tot["runs"] == 3


def test_automation_page_shows_the_same_totals(ws):
    t = _role(ws)
    history(ws, t["id"], "2026-11-01T00:00:00Z", 60, 0)
    roles.skipped(ws, t["id"], "2026-11-01T06:00:00Z")
    add_ticket(ws, "t_fnd001", status="done")
    roles.finding_line(ws, t["id"], 1, "a", "t_fnd001", "a")
    table = view.roles_table(
        ws,
        [json.loads((ws / ".orch" / "tickets" / f).read_text()) for f in ("t_role01.json", "t_fnd001.json")],
    )
    cells = table["rows"][0]["cells"]
    assert cells == {
        "role": cells["role"],
        "runs": "2 (1 skipped)",
        "findings": "1",
        "tickets": "1 fixed · 0 open · 0 dropped",
        "files": "none",
    }
    assert table["rows"][0]["link"] == t["id"]


def test_the_role_prompt_names_the_run_and_both_commands(ws):
    text = roles.prompt("t_role01", 7)
    assert (
        "run 7" in text
        and "orch automation result t_role01" in text
        and "orch automation finding t_role01" in text
    )


def test_role_command_json(ws, capsys):
    t = _role(ws)
    history(ws, t["id"], "2026-11-01T00:00:00Z", 60, 0)
    assert cli.main(["--dir", str(ws), "role", "ORCH-279", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["totals"]["runs"] == 1 and out["runs"][0]["run"] == 1
    assert load_state(ws) == {}
