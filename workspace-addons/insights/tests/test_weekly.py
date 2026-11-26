"""`orch insights week` and the page's Last 7 days: done tickets, stuck now and time to done from ticket history."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from test_overview import request

from orch_insights import cli, weekly

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def _iso(days_ago):
    return (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def _ticket(ws, tid, status, made, changed=None, done=None, **more):
    from orch import tickets

    history = [{"at": _iso(made), "by": "human:anna", "via": "cli", "text": "Created"}]
    if done is not None:
        history.append({"at": _iso(done), "by": "human:anna", "via": "cli", "text": "Status review -> done"})
    t = {
        "schema": "orch.ticket/1",
        "id": tid,
        "key": tid.replace("t_", "ORCH-"),
        "title": f"Ticket {tid}",
        "status": status,
        "created_at": _iso(made),
        "updated_at": _iso(done if changed is None and done is not None else changed or made),
        "checklist": [],
        "refs": [],
        "questions": [],
        "history": history,
        **more,
    }
    path = tickets.ticket_path(ws, tid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(t))


@pytest.fixture
def week_ws(ws):
    _ticket(ws, "t_aaa001", "done", made=4, done=2)  # done this week, 2 days from new to Done
    _ticket(ws, "t_aaa002", "done", made=3.5, done=0.5, changed=0.4)  # done this week, 3 days
    _ticket(ws, "t_aaa003", "done", made=12, done=10)  # the 7 days before
    _ticket(ws, "t_aaa004", "done", made=30, done=20)  # older: not counted
    _ticket(ws, "t_aaa005", "done", made=3, done=1, epic=True)  # an epic: its sub-tickets are the work
    asked = {"id": "q1", "text": "Which one?", "at": _iso(3), "answer": None}
    _ticket(ws, "t_aaa006", "waiting", made=5, questions=[asked])  # a question waits 3 days: stuck
    _ticket(ws, "t_aaa007", "open", made=0.1)  # fresh: not stuck
    _ticket(ws, "t_aaa008", "dropped", made=3, changed=1)
    return ws


def test_collect_reads_done_stuck_and_time_from_history(week_ws):
    answer = weekly.collect(week_ws, NOW)
    assert answer["schema"] == weekly.SCHEMA
    assert [d["key"] for d in answer["done"]] == ["ORCH-aaa002", "ORCH-aaa001"], "newest first, no epic"
    assert [d["took"] for d in answer["done"]] == [3 * 86400, 2 * 86400]
    assert answer["done_before"] == 1
    assert answer["stuck"] == [{"key": "ORCH-aaa006", "title": "Ticket t_aaa006", "why": "question"}]


def test_view_words():
    answer = {
        "schema": weekly.SCHEMA,
        "done": [{"key": f"ORCH-{i}", "title": f"T{i}", "took": 3600 * (i + 1)} for i in range(7)],
        "done_before": 9,
        "stuck": [{"key": "ORCH-9", "title": "<b>x</b>", "why": "overdue"}, {"key": "ORCH-8", "why": "odd"}],
    }
    v = weekly.view(answer)
    assert v["done"] == 7 and v["done_text"] == "2 fewer than the 7 days before"
    assert v["typical"] == "about 4 h" and v["typical_text"] == "from new to Done; the longest took 7 h"
    assert len(v["done_rows"]) == 5 and v["more"] == 2
    assert [r["why"] for r in v["stuck_rows"]] == ["Past its due date", "Stuck"] and v["stuck"] == 2
    assert v["empty"] is False
    one = weekly.view({"schema": weekly.SCHEMA, "done": [{"key": "A", "took": 50}], "done_before": 0})
    assert one["typical"] == "about 1 min" and one["typical_text"] == "from new to Done"
    assert one["done_text"] == "1 more than the 7 days before"
    assert weekly.view({"schema": weekly.SCHEMA, "stuck": [{"key": "A", "why": "quiet"}]})["typical"] is None


def test_span():
    assert [weekly.span(s) for s in (10, 59 * 60, 3600 * 5, 86400, 86400 * 3.4)] == [
        "1 min",
        "59 min",
        "5 h",
        "1 day",
        "3 days",
    ]


def test_empty_and_unreadable():
    empty = weekly.view({"schema": weekly.SCHEMA, "done": [], "stuck": [], "done_before": 3})
    assert empty["empty"] is True and empty["text"] == weekly.EMPTY
    assert "Next:" in weekly.text(empty)
    for bad in (None, {}, {"schema": "other"}, [1]):
        assert weekly.view(bad) == {"error": weekly.ERROR}, "never a row of zeros"


def test_cli_week(week_ws, capsys):
    assert cli.main(["--dir", str(week_ws), "week", "--json"]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["schema"] == weekly.SCHEMA and len(answer["stuck"]) == 1
    assert cli.main(["--dir", str(week_ws), "week"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Last 7 days\n") and "Stuck now: 1" in out
    assert "Next: look at a stuck ticket with `orch ticket show ORCH-aaa006`." in out


def test_route_reads_the_cli_answer(server, fake_orch):
    answer = {
        "schema": weekly.SCHEMA,
        "done": [{"key": "ORCH-1", "title": "A", "took": 7200}],
        "done_before": 1,
    }
    (fake_orch.parent / "weekly.json").write_text(json.dumps(answer))
    code, _headers, body = request(server, "/api/weekly")
    assert code == 200 and json.loads(body)["done_text"] == "Same as the 7 days before"
    assert json.loads((fake_orch.parent / "call.json").read_text())["args"] == ["insights", "week", "--json"]
    (fake_orch.parent / "weekly_exit").write_text("")
    assert json.loads(request(server, "/api/weekly")[2]) == {"error": weekly.ERROR}


def test_page_has_the_section():
    from importlib import resources

    web = resources.files("orch_insights").joinpath("web")
    assert 'id="weekly"' in web.joinpath("index.html").read_text()
    script = web.joinpath("insights.js").read_text()
    assert "/api/weekly" in script and "renderWeekly" in script
