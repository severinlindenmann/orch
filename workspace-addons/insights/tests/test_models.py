"""T0 model section: tokens per model, tickets moved up, the top tickets, and the fenced /api/models route."""

import json

from test_overview import request

from orch_insights.models import EMPTY, build_models, build_team
from orch_insights.overview import ERROR


def usage(**changes):
    base = {
        "schema": "orch.usage/1",
        "days": 30,
        "totals": {
            "opus": {"in": 900, "out": 100},
            "sonnet": {"in": 4000, "out": 1000},
            "other": {"in": 0, "out": 0},
        },
        "moved_up": 1,
        "with_model": 4,
        "tickets": [
            {"key": "ORCH-1", "title": "Small", "total": 10, "models": {"sonnet": {"in": 5, "out": 5}}},
            {
                "key": "ORCH-2",
                "title": "<b>Big</b>",
                "total": 6000,
                "models": {"opus": {"in": 900, "out": 100}, "sonnet": {"in": 4000, "out": 1000}},
            },
        ],
    }
    base.update(changes)
    return base


def test_projection():
    view = build_models(usage())
    assert view["empty"] is False
    assert [m["label"] for m in view["models"]] == ["Sonnet", "Opus"]  # zero rows dropped, fixed order
    assert [m["tokens"] for m in view["models"]] == [5000, 1000]
    assert view["moved_text"] == "1 of 4 tickets needed the stronger helper"
    assert [t["key"] for t in view["tickets"]] == ["ORCH-2", "ORCH-1"]
    assert view["tickets"][0]["parts"] == [
        {"name": "sonnet", "label": "Sonnet", "tokens": 5000},
        {"name": "opus", "label": "Opus", "tokens": 1000},
    ]
    assert len(build_models(usage(tickets=usage()["tickets"] * 5))["tickets"]) == 5


def test_empty_and_errors():
    assert build_models(usage(totals={}, tickets=[])) == {"empty": True, "text": EMPTY, "team": None}
    assert EMPTY == "No helper work in the last 30 days."
    for bad in (None, [], {"schema": "other/1"}):
        assert build_models(bad) == {"error": ERROR}


def test_bad_numbers_do_not_break():
    view = build_models(
        usage(totals={"opus": {"in": "x", "out": -3}, "sonnet": {"in": 2, "out": True}}, moved_up="a")
    )
    assert [m["tokens"] for m in view["models"]] == [2]
    assert view["moved_up"] == 0


def test_route(server, fake_orch):
    (fake_orch.parent / "usage.json").write_text(json.dumps(usage()))
    code, _headers, body = request(server, "/api/models")
    assert code == 200
    assert json.loads(body)["moved_text"] == "1 of 4 tickets needed the stronger helper"
    assert json.loads((fake_orch.parent / "call.json").read_text())["args"] == [
        "tokens",
        "--days",
        "30",
        "--json",
    ]
    assert request(server, "/api/models", headers={"Host": "evil.example:8431"})[0] == 403
    assert request(server, "/api/models", method="POST")[0] == 405


def test_route_unreadable(server, fake_orch):
    (fake_orch.parent / "usage_exit").write_text("")
    (fake_orch.parent / "usage.json").write_text("{}")
    assert json.loads(request(server, "/api/models")[2]) == {"error": ERROR}


def test_page_has_the_section():
    from importlib import resources

    web = resources.files("orch_insights").joinpath("web")
    assert 'id="models"' in web.joinpath("index.html").read_text()
    assert "/api/models" in web.joinpath("insights.js").read_text()


def test_team_time_cost_finished_stuck_and_people():
    """ORCH-189: the manager view numbers, shown even when no model use is measured (a first day)."""
    answer = usage(
        seconds=14 * 3600 + 20 * 60,
        cost=41.8,
        finished=9,
        stuck=2,
        team=[
            {"owner": "human:anna", "finished": 5, "open": 3, "seconds": 8 * 3600 + 600, "cost": 24.1},
            {"owner": "", "finished": 4, "open": 2, "seconds": 59, "cost": 17.7},
            {"owner": "agent:claude", "finished": 0, "open": 1, "seconds": 0, "cost": 0},
            "bad row",
        ],
    )
    team = build_models(answer)["team"]
    assert team["time"] == "14 h 20 min" and team["cost"] == "$41.80"
    assert team["finished"] == 9 and team["stuck"] == 2
    assert team["each"] == "about $4.64 and 1 h 36 min each"
    assert [p["name"] for p in team["people"]] == ["anna", "No owner", "A helper"]
    assert team["people"][0] == {
        "name": "anna",
        "finished": 5,
        "open": 3,
        "time": "8 h 10 min",
        "cost": "$24.10",
    }
    assert team["people"][1]["time"] == "1 min" and team["people"][2]["time"] == "–"
    assert build_models(usage(totals={}, tickets=[], seconds=60, cost=0, finished=0))["team"]["each"] is None
    assert build_team(usage()) is None, "an older orch without the numbers: no section"
    assert build_team(usage(seconds="x", cost=True, finished=-1))["time"] == "–"
    none = build_team(
        usage(seconds=0, cost=0, finished=0, team=[{"owner": "human:anna", "seconds": 0, "cost": 0}])
    )
    assert none["cost"] == "–" and none["time"] == "–" and none["people"][0]["cost"] == "–"
    assert none["note"] == "No time or cost recorded yet" and team["note"] == ""


def test_time_without_cost_has_no_dash_sentence_and_says_why():
    team = build_team(usage(seconds=240, cost=0, finished=2, team=[]))
    assert team["each"] == "about 2 min each" and "–" not in team["each"]
    assert team["cost"] == "–" and team["note"] == "No cost recorded yet"
    assert build_team(usage(seconds=0, cost=6, finished=2, team=[]))["each"] == "about $3.00 each"


def test_orch1694_a_dash_for_helper_time_says_why():
    no_time = build_team(usage(seconds=0, cost=6, finished=2, team=[]))
    assert no_time["time"] == "–" and no_time["time_note"] == "Not recorded in the last 30 days"
    assert build_team(usage(seconds=240, cost=0, finished=2, team=[]))["time_note"] == "Last 30 days"


def test_page_has_the_team_section():
    from importlib import resources

    web = resources.files("orch_insights").joinpath("web")
    html, js = web.joinpath("index.html").read_text(), web.joinpath("insights.js").read_text()
    for part in ('id="team"', 'id="team-stats"', ">By person<", 'id="people-rows"', 'id="lost-note"'):
        assert part in html
    checkup = web.joinpath("checkup.js").read_text()
    assert "hour12: false" in checkup, "check-up time is 24 hours like the rest of orch"
    for word in ("Helper time", "at list price", "Tickets finished", "Stuck now"):
        assert word in js


def _acct(unit, value, use, on=True, label="Team"):
    return {
        "on": on,
        "label": label,
        "rule": {"limits": [{"period": "week", "unit": unit, "value": value}]},
        "use": {"week": use},
    }


def test_week_bar_dollar_budget():
    from orch_insights.models import build_week

    got = build_week({"accounts": [_acct("$", 200, {"spent": 50.5})]})
    assert got == {"label": "$50.50 of $200.00 this week · Team", "percent": 25, "over": False}
    over = build_week({"accounts": [_acct("$", 100, {"spent": 130, "estimated": True})]})
    assert over["percent"] == 100 and over["over"] and "(estimated)" in over["label"]


def test_week_bar_subscription_percent_and_skips():
    from orch_insights.models import build_week

    assert build_week({"accounts": [_acct("%", 100, {"pct": 62})]})["label"] == "62% used this week · Team"
    assert build_week({"accounts": [_acct("%", 80, {"pct": 40})]})["percent"] == 50
    skipped = [
        _acct("$", 100, {"spent": 5}, on=False),
        _acct("$", 100, {"note": "no reading"}),
        _acct("$", 0, {"spent": 1}),
    ]
    assert build_week({"accounts": skipped}) is None  # off, no reading, no budget: no bar, never a fake zero
    assert build_week(None) is None and build_week({"accounts": "x"}) is None and build_week({}) is None


def test_tickets_without_owner_count_for_the_chosen_person():
    """ORCH-410: 'You: Severin' is chosen but no ticket has an owner: one row under that name, not 'No owner'."""
    rows = [
        {"owner": "", "finished": 2, "open": 3, "seconds": 3600, "cost": 1.5},
        {"owner": "human:Severin", "finished": 1, "open": 0, "seconds": 600, "cost": 0.5},
        {"owner": "human:anna", "finished": 1, "open": 1, "seconds": 0, "cost": 0},
    ]
    people = build_team(usage(seconds=4200, cost=2.0, finished=4, team=rows), "Severin")["people"]
    assert [(p["name"], p["finished"], p["open"], p["time"], p["cost"]) for p in people] == [
        ("Severin", 3, 3, "1 h 10 min", "$2.00"),
        ("anna", 1, 1, "–", "–"),
    ]
    assert build_team(usage(seconds=1, team=rows[:1]))["people"][0]["name"] == "No owner"
