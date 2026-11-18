"""The dispatcher (ORCH-507): a target from the budget pace and the load, then Factory work, Ready and Backlog
tickets started in order up to it, without an AI call; off unless the owner turned it on."""

import json
import time

import pytest

from orch import brake, config, dispatcher, limitstop, runs, runs_live, tend, tickets

NOW = 1_800_000_000.0


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


@pytest.fixture
def starts(monkeypatch):
    """runs.start recorded instead of spawning an agent."""
    calls = []

    def fake(root, tid, by, **kw):
        calls.append((tid, by))
        return {"run": "r_fresh0001", "mode": "live", "resumed": False, "notes": []}

    monkeypatch.setattr(runs, "start", fake)
    return calls


@pytest.fixture
def calm(monkeypatch):
    """A quiet computer, nobody working, no limit, no hold: only the test's own numbers count."""
    state = {"working": 0}
    monkeypatch.setattr(dispatcher, "working", lambda root: state["working"])
    monkeypatch.setattr(runs_live, "_pressure", lambda root: None)
    monkeypatch.setattr(runs_live, "_full", lambda root: None)
    monkeypatch.setattr(runs_live, "_held", lambda root, by="": None)
    monkeypatch.setattr(dispatcher, "_load", lambda: (1.0, 8))
    return state


def _on(proj, helpers=None):
    config.set_dispatcher(proj, True)
    if helpers:
        config.set_dispatcher_helpers(proj, str(helpers))


def _budget(proj, rows, at=NOW, name="usage"):
    d = proj / ".orch" / "addons" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "budget.json").write_text(json.dumps({"schema": "orch.budget/1", "at": _iso(at), "accounts": rows}))


def _week(used, hours_left, cap=100.0, short=None):
    row = {"week_used": used, "week_cap": cap, "week_resets_at": _iso(NOW + hours_left * 3600)}
    if short is not None:
        row.update(short_used=short, short_cap=100.0)
    return row


def _ticket(proj, title, status="open", **fields):
    _ticket.n = getattr(_ticket, "n", 0) + 1
    n = _ticket.n
    fields.setdefault(
        "created_at", f"2026-11-01T{n // 3600 % 24:02d}:{n // 60 % 60:02d}:{n % 60:02d}Z"
    )  # one second apart: a fixed age order
    t = tickets.create(proj, title, "human:tester")
    t = tickets.load(proj, t["id"])
    t["status"] = status
    t.update(fields)
    tickets.save(proj, t)
    return t["id"]


# ---------------------------------------------------------------- the target


def test_off_by_default_does_nothing(proj, starts, calm):
    _ticket(proj, "Ready one", "ready")
    assert dispatcher.run(proj, now=NOW) == {"on": False}
    assert starts == []
    assert dispatcher.text({"on": False}) == ""


def test_on_pace_keeps_the_set_number(proj, calm):
    _on(proj, 3)
    _budget(proj, [_week(50, 84)])  # half used, half the week left
    t = dispatcher.target(proj, NOW)
    assert (t["target"], t["pace"], t["held"]) == (3, 1.0, None)
    assert "on pace" in t["why"]


def test_behind_pace_aims_higher_but_at_most_twice(proj, calm):
    _on(proj, 3)
    _budget(proj, [_week(20, 84)])  # 80 left over half a week: ratio 1.6
    assert dispatcher.target(proj, NOW)["target"] == 5
    _budget(proj, [_week(10, 10)])  # nearly all left near the reset
    t = dispatcher.target(proj, NOW)
    assert t["target"] == 6 and "behind pace" in t["why"]


def test_ahead_of_pace_aims_lower_and_used_up_is_zero(proj, calm):
    _on(proj, 4)
    _budget(proj, [_week(80, 84)])  # 20 left over half a week: ratio 0.4
    t = dispatcher.target(proj, NOW)
    assert t["target"] == 2 and "ahead of pace" in t["why"]
    _budget(proj, [_week(100, 30)])
    assert dispatcher.target(proj, NOW)["target"] == 0
    _budget(proj, [_week(20, 84, short=100)])  # the 5-hour window is full
    assert dispatcher.target(proj, NOW)["target"] == 0


def test_two_accounts_and_a_lower_week_limit_count_together(proj, calm):
    _on(proj, 2)
    # main at its own 90 % week limit, the second fresh with a full week: 100 left, on pace 45 + 100 -> 0.69
    _budget(proj, [_week(90, 84, cap=90), _week(0, 168)])
    t = dispatcher.target(proj, NOW)
    assert (t["target"], t["pace"]) == (1, 0.69) and t["used"] == pytest.approx(47.4, abs=0.1)


def test_one_full_5_hour_window_is_not_all_and_a_past_reset_aims_high(proj, calm):
    _on(proj, 2)
    _budget(proj, [_week(20, 84, short=100), _week(20, 84)])  # the second reports no 5-hour number
    assert dispatcher.target(proj, NOW)["target"] == 3
    _budget(proj, [_week(50, -1)])  # the reset just passed: whatever is left is free
    assert dispatcher.target(proj, NOW)["target"] == 4


@pytest.mark.parametrize(
    "doc",
    [
        {"accounts": 1},
        {"accounts": [1, "x", {"week_used": 10**400}, {"week_used": True}]},
        {"accounts": [{"week_used": 10, "week_cap": "a", "week_resets_at": 5, "short_used": 10**400}]},
    ],
)
def test_a_bad_budget_file_never_breaks_the_pass(proj, calm, doc):
    _on(proj, 3)
    d = proj / ".orch" / "addons" / "usage"
    d.mkdir(parents=True, exist_ok=True)
    (d / "budget.json").write_text(json.dumps({"schema": "orch.budget/1", "at": _iso(NOW), **doc}))
    assert dispatcher.target(proj, NOW)["target"] in (3, 4)


def test_unknown_or_stale_budget_uses_the_set_number(proj, calm):
    _on(proj, 3)
    assert dispatcher.target(proj, NOW)["target"] == 3
    _budget(proj, [_week(95, 84)], at=NOW - 3600)  # an hour old: unknown
    t = dispatcher.target(proj, NOW)
    assert t["target"] == 3 and "unknown" in t["why"]


def test_the_helper_limit_caps_the_target(proj, calm, monkeypatch):
    _on(proj, 5)
    monkeypatch.setattr(runs_live, "max_live", lambda root: 4)
    _budget(proj, [_week(0, 10)])
    assert dispatcher.target(proj, NOW)["target"] == 4


def test_a_busy_computer_paused_automation_or_a_limit_stop_holds_new_starts(proj, calm, monkeypatch, starts):
    _on(proj, 3)
    _ticket(proj, "Ready one", "ready")
    monkeypatch.setattr(dispatcher, "_load", lambda: (11.0, 8))
    res = dispatcher.run(proj, now=NOW)
    assert "busy" in res["held"] and starts == []
    assert "no new helper" in dispatcher.text(res)
    monkeypatch.setattr(dispatcher, "_load", lambda: (1.0, 8))
    monkeypatch.setattr(runs_live, "_pressure", lambda root: "the disk is almost full")
    assert dispatcher.run(proj, now=NOW)["held"] == "the disk is almost full"
    monkeypatch.setattr(runs_live, "_pressure", lambda root: None)
    monkeypatch.setattr(limitstop, "held_words", lambda root: "the usage limit is reached until 18:00")
    assert "usage limit" in dispatcher.run(proj, now=NOW)["held"]
    monkeypatch.setattr(limitstop, "held_words", lambda root: None)
    monkeypatch.setattr(brake, "paused", lambda root: {"by": "human:x"})
    assert dispatcher.run(proj, now=NOW)["held"] == "automation is paused"
    assert starts == []


# ---------------------------------------------------------------- the line


def test_factory_work_first_then_ready_then_backlog_by_due_and_age(proj, calm):
    _on(proj)
    old_backlog = _ticket(proj, "Old backlog")
    ready_late = _ticket(proj, "Ready, due late", "ready", due="2026-12-30")
    ready_soon = _ticket(proj, "Ready, due soon", "ready", due="2026-11-20")
    ready_none = _ticket(proj, "Ready, no date", "ready")
    crew = _ticket(proj, "Crew task", "open", ext={"factory": {"role": "crew", "order": "t_aaaaaa"}})
    order = _ticket(proj, "Running order", "ready", ext={"factory": {"role": "order", "stage": "running"}})
    _ticket(proj, "Draft order", "open", ext={"factory": {"role": "order", "stage": "draft"}})  # backlog rank
    order_ids = [c["ticket"] for c in dispatcher.candidates(proj)]
    assert order_ids[:6] == [crew, order, ready_soon, ready_late, ready_none, old_backlog]
    ranks = [c["rank"] for c in dispatcher.candidates(proj)]
    assert ranks[:2] == ["factory", "factory"] and ranks[-1] == "backlog"


def test_tickets_that_must_not_start_are_skipped(proj, calm, monkeypatch):
    _on(proj)
    keep = _ticket(proj, "Plain backlog")
    _ticket(proj, "Working", "active")
    _ticket(proj, "In review", "review")
    _ticket(proj, "Waits", "ready", waiting_on={"kind": "time", "until": "2030-01-01T00:00:00Z"})
    _ticket(proj, "Asks", "ready", questions=[{"id": "q1", "text": "A or B?", "answer": None}])
    _ticket(proj, "Repeats", "ready", ext={"automation": {"recurring": True, "cron": "0 9 * * *"}})
    _ticket(proj, "Persons task", "ready", owner="Severin")
    running = _ticket(proj, "Has a run", "ready")
    stopped = _ticket(proj, "A person stopped it", "ready")
    real_read = runs.read
    monkeypatch.setattr(
        runs, "read", lambda root, tid: {"run": "r"} if tid == running else real_read(root, tid)
    )
    held = runs_live._held_path(proj, stopped)
    held.parent.mkdir(parents=True, exist_ok=True)
    held.write_text("[]")
    assert [c["ticket"] for c in dispatcher.candidates(proj)] == [keep]


def test_starts_up_to_the_target_and_logs_why(proj, calm, starts):
    _on(proj, 3)
    _budget(proj, [_week(50, 84)])
    a = _ticket(proj, "First", "ready")
    b = _ticket(proj, "Second", "ready")
    _ticket(proj, "Third", "ready")
    calm["working"] = 1  # target 3, one working: two places, at most MAX_STARTS per pass
    res = dispatcher.run(proj, now=NOW)
    assert [s[0] for s in starts] == [a, b] and all(s[1] == dispatcher.BY for s in starts)
    assert [c["ticket"] for c in res["started"]] == [a, b]
    last = tickets.load(proj, b)["history"][-1]
    assert "Started by the dispatcher: 3 of 3 helpers working" in last["text"] and last["by"] == dispatcher.BY
    assert "started" in dispatcher.text(res)


def test_full_or_dry_run_starts_nothing(proj, calm, starts):
    _on(proj, 2)
    _ticket(proj, "First", "ready")
    calm["working"] = 2
    res = dispatcher.run(proj, now=NOW)
    assert res["started"] == [] and starts == []
    assert dispatcher.text(res) == "Dispatcher: 2 of 2 helpers working (budget unknown: 2 helpers)."
    calm["working"] = 0
    res = dispatcher.run(proj, dry_run=True, now=NOW)
    assert starts == [] and len(res["would"]) == 1 and "would start" in dispatcher.text(res, True)


def test_a_start_that_would_wait_in_line_stops_the_pass(proj, calm, monkeypatch):
    _on(proj, 3)
    _ticket(proj, "First", "ready")
    _ticket(proj, "Second", "ready")
    tried = []

    def busy(root, tid, by, **kw):
        tried.append(tid)
        raise runs.Busy("waits in line", {"pending": True})

    monkeypatch.setattr(runs, "start", busy)
    assert dispatcher.run(proj, now=NOW)["started"] == [] and len(tried) == 1


def test_the_watcher_pass_runs_the_dispatcher_after_the_line(proj, calm, starts, monkeypatch):
    monkeypatch.setattr(tend, "plan", lambda root, now=None: [])
    monkeypatch.setattr(runs_live, "start_waiting", lambda root: [])
    tid = _ticket(proj, "Ready one", "ready")
    res = tend.run(proj, now=NOW)
    assert res["dispatcher"] == {"on": False} and starts == []
    _on(proj, 1)
    res = tend.run(proj, now=NOW)
    assert [s[0] for s in starts] == [tid]
    assert "Dispatcher: 0 of 1 helpers working" in tend.text(res)


def test_config_keys(proj, run):
    assert run("config", "get", "workflow.dispatcher")[1].strip() in ("False", "false")
    code, _, err = run("config", "set", "workflow.dispatcher", "on", "--by", "agent:helper")
    assert code == 2 and "Only the owner" in err
    code, out, _ = run("config", "set", "workflow.dispatcher", "on", "--by", "human:owner")
    assert code == 0 and "dispatcher keeps about 3 helpers" in out
    assert config.dispatcher_on(proj)
    code, _, err = run("config", "set", "workflow.dispatcher_helpers", "12")
    assert code == 2
    assert run("config", "set", "workflow.dispatcher_helpers", "\u0664", "--by", "agent:helper")[0] == 2
    code, _, err = run("config", "set", "workflow.dispatcher_helpers", "4", "--by", "agent:helper")
    assert code == 2 and "Only the owner raises" in err
    assert run("config", "set", "workflow.dispatcher_helpers", "4", "--by", "human:owner")[0] == 0
    assert run("config", "set", "workflow.dispatcher_helpers", "2", "--by", "agent:helper")[0] == 0
    assert config.dispatcher_helpers(proj) == 2
