"""The "Live now" cards of the start screen (/api/live)."""

import json
import sys
import time

from orch_focus import livecards

from .conftest import TID, ticket
from .test_server import req


def _ev(kind, text, **data):
    return {"kind": kind, "text": text, "at": "2026-11-16T10:35:00Z", "data": data}


def test_card_shape_steps_newest_first_and_plain_words():
    t = ticket(
        questions=[
            {
                "id": "q1",
                "text": "Day 1 or day 2?",
                "answer": None,
                "options": ["Day 1", "Day 2"],
                "recommended": "Day 2",
            }
        ]
    )
    v = {
        "ticket": {**t, "key": "PIL-1"}, "run": {"label": "Claude", "worked": 1100, "running": True},
        "board": {"step": "Read the budget"}, "state": "needs", "done": 1, "total": 2,
        "events": [_ev("tool.start", "Old step"), _ev("task.done", "Outline"), _ev("tool.start", "Read the budget"), _ev("ask", "x", q="q1"), _ev("usage", "u")],
    }  # fmt: skip
    c = livecards.card(v)
    assert c["ticket"] == TID and c["key"] == "PIL-1" and c["agent"] == "Claude" and c["minutes"] == 18
    assert c["now"] == "Read the budget" and c["why"] == "Task 2 of 2: Review totals"
    assert [s["text"] for s in c["steps"]] == [
        "Asked you a question",
        "Read the budget",
        "Task done: Outline",
    ]
    assert len(c["question"].pop("digest")) == 64  # the question as shown: sent back with the answer
    assert c["question"] == {
        "id": "q1",
        "text": "Day 1 or day 2?",
        "options": ["Day 1", "Day 2"],
        "recommended": "Day 2",
    }
    assert c["progress"] == {"done": 1, "total": 2}


def test_card_without_events_still_says_something():
    v = {
        "ticket": ticket(),
        "run": {"label": "Codex", "worked": 0, "running": True},
        "board": {"step": ""},
        "state": "working",
        "events": [],
    }
    c = livecards.card(v)
    assert (
        c["now"] == "Getting started" and c["steps"] == [] and c["question"] is None and c["working"] is True
    )


def test_recommended_must_be_one_of_the_options():
    t = ticket(questions=[{"id": "q1", "text": "?", "answer": None, "options": ["A"], "recommended": "B"}])
    v = {
        "ticket": t,
        "run": {"label": "x", "running": True},
        "board": {"step": ""},
        "state": "needs",
        "events": [],
    }
    assert livecards.card(v)["question"]["recommended"] is None


def test_api_live_lists_running_tickets_and_nothing_when_none_run(server, fake_orch):
    assert json.loads(req(server, "GET", "/api/live")[1]) == {"cards": [], "same_file": []}
    ev = {
        "v": 1, "id": "toolu_1", "seq": 1, "run": "r_live0001", "agent": "main", "at": "2026-11-16T09:12:05Z",
        "ticket": TID, "via": "log", "kind": "step", "text": "Read the March report",
        "used": {"kind": "tool", "name": "Read", "action": None, "source": "builtin", "version": None}, "outcome": None,
    }  # fmt: skip
    line = json.dumps({"type": "event", "cursor": "rc1.x", "event": ev})
    wrap = fake_orch.parent / "wrap"
    wrap.write_text(
        f"#!{sys.executable}\nimport os, sys, time\na = sys.argv[1:]\n"
        f"if a[:2] == ['record', 'tail']:\n    print({line!r}, flush=True)\n    time.sleep(30)\n"
        f"os.execv({str(fake_orch)!r}, [{str(fake_orch)!r}, *a])\n"
    )
    wrap.chmod(0o755)
    (fake_orch.parent / "status.json").write_text(
        json.dumps({"running": True, "claim": {"run": "r_live0001", "agent": "claude", "mode": "oneshot"}})
    )
    server.tracker.orch_bin = str(wrap)
    # the fixture ticket is "active"; wait until the record line has arrived
    end, cards = time.time() + 15, []
    while time.time() < end:
        cards = json.loads(req(server, "GET", "/api/live")[1])["cards"]
        if cards and cards[0]["steps"]:
            break
        time.sleep(0.2)
    assert len(cards) == 1 and cards[0]["ticket"] == TID and cards[0]["now"] == "Read the March report"
    assert cards[0]["title"] == "Close March books"
