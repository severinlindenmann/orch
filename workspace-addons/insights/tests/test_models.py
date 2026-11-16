"""T0 model section: tokens per model, tickets moved up, the top tickets, and the fenced /api/models route."""

import json

from test_overview import request

from orch_insights.models import EMPTY, build_models
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
    assert view["moved_text"] == "1 of 4 tickets moved up to Opus"
    assert [t["key"] for t in view["tickets"]] == ["ORCH-2", "ORCH-1"]
    assert view["tickets"][0]["parts"] == [
        {"name": "sonnet", "label": "Sonnet", "tokens": 5000},
        {"name": "opus", "label": "Opus", "tokens": 1000},
    ]
    assert len(build_models(usage(tickets=usage()["tickets"] * 5))["tickets"]) == 5


def test_empty_and_errors():
    assert build_models(usage(totals={}, tickets=[])) == {"empty": True, "text": EMPTY}
    assert EMPTY == "No model use in the last 30 days."
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
    assert json.loads(body)["moved_text"] == "1 of 4 tickets moved up to Opus"
    assert json.loads((fake_orch.parent / "call.json").read_text())["args"] == [
        "usage",
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
