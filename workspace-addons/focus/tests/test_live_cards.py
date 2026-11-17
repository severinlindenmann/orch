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
    # ORCH-61: no made-up "Getting started"; the state word comes from the one helper state
    assert c["now"] == "" and c["steps"] == [] and c["question"] is None and c["working"] is True
    assert (c["state"], c["word"], c["step"]) == ("working", "Working", {"n": 2, "of": 2})


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


def test_s3_card_marks_unchecked_steps_and_carries_notes():
    ev = [
        {"kind": "tool.start", "text": "Read it", "at": "2026-01-01T10:00:00Z", "data": {"source": "hook"}},
        {"kind": "tool.start", "text": "Old step", "at": "2026-01-01T09:00:00Z",
         "data": {"source": "hook", "before": True}},
        {"kind": "tool.start", "text": "Checked", "at": "2026-01-01T11:00:00Z", "data": {"source": "log"}},
    ]  # fmt: skip
    v = {"ticket": ticket(), "run": {"label": "Claude", "worked": 0}, "board": {}, "events": ev,
         "record_notes": ["Some records were changed outside orch."]}  # fmt: skip
    c = livecards.card(v)
    marks = {s["text"]: s.get("unchecked") for s in c["steps"]}
    assert marks == {"Checked": None, "Read it": "agent", "Old step": "before"}
    assert c["notes"] == ["Some records were changed outside orch."]


def test_cards_read_the_views_side_by_side_in_list_order(monkeypatch):
    """ORCH-18: the start page waits for this answer; one view after the other took seconds with four helpers."""
    import threading

    monkeypatch.setattr(
        livecards,
        "card",
        lambda v: {"ticket": v["id"], "question": v.get("q"), "state": "you" if v.get("q") else "working"},
    )
    monkeypatch.setattr(livecards.areas, "label", lambda root, out: None)
    lock, now, most = threading.Lock(), [0], [0]

    class Tracker:
        root = None

        def tickets_list(self):
            return [{"id": f"t_{i:06d}", "status": "active" if i % 3 else "open"} for i in range(30)]

        def view(self, tid):
            with lock:
                now[0] += 1
                most[0] = max(most[0], now[0])
            time.sleep(0.05)
            with lock:
                now[0] -= 1
            return {"id": tid, "run": {"running": tid != "t_000001"}, "q": "x" if tid == "t_000005" else None}

    out = livecards.cards(Tracker())
    assert most[0] > 1  # more than one view was read at a time
    assert len(out) == livecards.MAX_CARDS
    # the first eight running tickets of the list, in the Helpers order (working first, then the one that waits for you)
    assert [c["ticket"] for c in out] == [f"t_{i:06d}" for i in (2, 4, 7, 8, 10, 11, 13)] + ["t_000005"]


def test_card_carries_the_core_helper_state_step_and_minutes():
    """ORCH-61: Focus shows the same state word, step and minutes as the Helpers list on Home."""
    t = ticket(
        checklist=[
            {"id": "c1", "text": "a", "done": True},
            {"id": "c2", "text": "b", "state": "doing"},
            {"id": "c3", "text": "c"},
        ]
    )
    run = {"label": "Helper", "running": True, "age_seconds": 3125, "idle_seconds": None,
           "helper": {"state": "waiting", "word": "x", "detail": "Waits on pr-green.sh (running 6 min)"}}  # fmt: skip
    c = livecards.card({"ticket": t, "run": run, "board": {"step": ""}, "state": "waiting", "events": []})
    assert (c["state"], c["word"], c["detail"]) == (
        "waiting",
        "On hold",
        "Waits on pr-green.sh (running 6 min)",
    )
    assert c["step"] == {"n": 2, "of": 3} and c["age_minutes"] == 52 and c["idle_minutes"] is None
    assert c["finished"] is False and c["now"] == "Waits on pr-green.sh (running 6 min)"


def test_card_without_the_core_field_uses_the_same_words():
    t = ticket(questions=[{"id": "q1", "text": "?", "answer": None}])
    c = livecards.card(
        {"ticket": t, "run": {"running": True}, "board": {"step": ""}, "state": "needs", "events": []}
    )
    assert (c["word"], c["detail"]) == ("Waits for you", "Your answer")
    c = livecards.card(
        {
            "ticket": ticket(),
            "run": {"running": True},
            "board": {"step": ""},
            "state": "waiting",
            "events": [],
        }
    )
    assert c["word"] == "Idle"


def test_a_finished_ticket_with_an_open_session_is_listed(tmp_path, monkeypatch):
    monkeypatch.setattr(livecards.areas, "label", lambda root, out: None)
    (tmp_path / ".orch" / "run" / "tickets").mkdir(parents=True)
    (tmp_path / ".orch" / "run" / "tickets" / "t_000002.json").write_text("{}")

    class Tracker:
        root = tmp_path

        def tickets_list(self):
            return [{"id": "t_000001", "status": "done"}, {"id": "t_000002", "status": "review"}]

        def view(self, tid):
            return {"ticket": ticket(id=tid, status="review"), "run": {"running": True, "helper": {"state": "idle", "detail": "Nothing running for 3 min"}},
                    "board": {"step": ""}, "state": "waiting", "events": []}  # fmt: skip

    out = livecards.cards(Tracker())
    assert (
        [c["ticket"] for c in out] == ["t_000002"] and out[0]["finished"] is True and out[0]["word"] == "Idle"
    )
