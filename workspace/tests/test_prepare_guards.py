"""ORCH-741: the guards that keep Prepare cheap and calm (accepted draft ORCH-730, section 4).

- a program check skips Prepare with no AI call when every field is filled (sub-tickets, Factory, automation);
- one Prepare per ticket, also for tickets from the phone, Chat, the relay and automation;
- a daily limit per workspace, shown in Usage;
- a person's later edit wins and an old Prepare result never changes a newer status;
- a Settings switch, on by default.
"""

import json
import os
import time

import pytest

from orch import config, prepare, runs, runs_live, tickets
from orch.errors import Refused
from orch.runs import Busy


@pytest.fixture
def starts(monkeypatch):
    """No helper is spawned: the inner prepare start is recorded instead (an AI call would happen there)."""
    calls: list[str] = []

    def fake_start(root, tid, by, **kw):
        if kw.get("prepare") and not kw.get("_prepare"):  # the CLI's way in
            return runs.start_prepare(root, tid, by, agent=kw.get("agent"))
        assert kw.get("_prepare") is True
        calls.append(tid)
        return {"ticket": tid, "run": f"r_{len(calls)}", "agent": "fake", "log": "x", "mode": "oneshot"}

    monkeypatch.setattr(runs, "start", fake_start)
    monkeypatch.setattr(runs_live, "_full", lambda root: 0)
    monkeypatch.setattr(runs_live, "_held", lambda root, by="agent:tend": None)
    return calls


def _complete(proj, tid, by="agent:claude"):
    tickets.tidy(
        proj, tid, "Monthly sales report", by, fields={"done_when": "The report is in the shared folder"},
        description="Make the monthly sales report for the team.", estimate={"minutes": 30, "cost": 2},
    )  # fmt: skip


def _history(proj, tid):
    return [h["text"] for h in tickets.load(proj, tid)["history"]]


# ---------------------------------------------------------------- skip when complete, no AI call


def test_a_ticket_with_every_field_filled_is_not_prepared_and_nothing_changes(proj, new_ticket, starts):
    tid = new_ticket("Monthly sales report")
    _complete(proj, tid)
    before = tickets.load(proj, tid)
    r = runs.start_prepare(proj, tid, "human:t")
    assert r["skipped"] == "every field is filled already"
    assert starts == []  # no helper, no AI call
    after = tickets.load(proj, tid)
    assert "prepare" not in after and after["history"] == before["history"]
    assert prepare.used(proj)["used"] == 0  # a skip does not count against the daily limit


@pytest.mark.parametrize("missing", ["description", "done_when", "estimate"])
def test_one_missing_field_still_prepares(proj, new_ticket, starts, missing):
    tid = new_ticket("Monthly sales report")
    _complete(proj, tid)
    tickets.apply_op(proj, tid, lambda t: t.pop(missing), by=tickets.SYSTEM)
    assert prepare.skip_reason(proj, tickets.load(proj, tid)) is None
    assert "skipped" not in runs.start_prepare(proj, tid, "human:t") and starts == [tid]


def test_a_placeholder_title_still_prepares_even_with_every_other_field(proj, starts):
    t = tickets.create_from_input(
        proj, "please make the sales report\nwith the numbers from october", "human:t"
    )
    tickets.apply_op(
        proj, t["id"],
        lambda x: x.update(description="d", done_when="w", estimate={"minutes": 5, "cost": 1}),
        by=tickets.SYSTEM,
    )  # fmt: skip
    assert tickets.load(proj, t["id"]).get("title_auto") is True
    assert prepare.skip_reason(proj, tickets.load(proj, t["id"])) is None


def test_an_agent_ticket_with_every_field_skips_factory_and_automation_alike(proj, starts):
    for by in ("agent:factory", "agent:automation", "agent:claude"):
        t = tickets.create(proj, "Collect the numbers", by)
        _complete(proj, t["id"], by)
        assert runs.start_prepare(proj, t["id"], "human:t")["skipped"] == "every field is filled already"
    assert starts == []


def test_a_sub_ticket_a_helper_made_is_never_prepared_again_but_a_persons_is(proj, new_ticket, starts):
    parent = new_ticket("Big report")
    sub = tickets.create(proj, "Part one", "agent:claude", parent=parent)  # e.g. a split Prepare suggested
    assert runs.start_prepare(proj, sub["id"], "human:t")["skipped"] == "a helper made this sub-ticket"
    mine = tickets.create(proj, "Part two", "human:t", parent=parent)
    assert "skipped" not in runs.start_prepare(proj, mine["id"], "human:t")
    assert starts == [mine["id"]]


# ---------------------------------------------------------------- once per ticket


def test_a_prepared_ticket_is_never_prepared_a_second_time(proj, new_ticket, starts):
    tid = new_ticket("sales report pls")
    assert "skipped" not in runs.start_prepare(proj, tid, "human:t")
    tickets.set_prepare(proj, tid, "prepared", "agent:fake", run="r_1")
    r = runs.start_prepare(proj, tid, "human:t")  # a second Save, or a repeated delivery
    assert r["skipped"] == "it was prepared already" and starts == [tid]


def test_a_crashed_prepare_may_try_again_once_more(proj, new_ticket, starts):
    tid = new_ticket("sales report pls")
    tickets.set_prepare(proj, tid, "not_prepared", "orch", why="the helper stopped with an error")
    assert "skipped" not in runs.start_prepare(proj, tid, "human:t") and starts == [tid]


def test_a_prepare_already_running_is_not_started_twice(proj, new_ticket, starts):
    tid = new_ticket("sales report pls")
    runs.claim(proj, tid, "human:t", "fake", pid=os.getpid(), prepare=True)
    with pytest.raises(Refused, match="already works"):
        runs.start_prepare(proj, tid, "human:t")
    assert starts == []


@pytest.mark.parametrize("origin", ["phone", "chat", "relay", "automation"])
def test_tickets_from_phone_chat_relay_and_automation_are_prepared_once(proj, starts, origin):
    by = {"phone": "relay:ph_abc", "chat": "human:t", "relay": "relay:ws_x", "automation": "agent:automation"}
    t = tickets.create_from_input(proj, "the email from Anna about the october numbers", by[origin])
    tickets.ext_set(proj, t["id"], "relay", json.dumps({"origin": origin, "message": "m_1"}), by[origin])
    assert "skipped" not in runs.start_prepare(proj, t["id"], by[origin])
    tickets.set_prepare(proj, t["id"], "prepared", "agent:fake", run="r_1")
    for _ in range(3):  # the same message delivered again
        assert runs.start_prepare(proj, t["id"], by[origin])["skipped"] == "it was prepared already"
    assert starts == [t["id"]]


def test_a_skipped_prepare_gives_up_its_place_in_line(proj, new_ticket, starts):
    tid = new_ticket("sales report pls")
    tickets.set_prepare(proj, tid, "prepared", "agent:fake", run="r_1")
    runs_live._queue_for_slot(proj, tid, "human:t", "saved", "low", prepare=True)
    assert tid in [t for t, _ in runs_live.waiting_line(proj)]
    assert runs_live.start_waiting(proj) == []
    assert tid not in [t for t, _ in runs_live.waiting_line(proj)]  # not tried again on every pass
    assert starts == []


def test_a_persons_queued_start_keeps_its_place_when_prepare_is_skipped(proj, new_ticket):
    tid = new_ticket("sales report pls")
    runs_live._queue_for_slot(proj, tid, "human:t", "start", "normal")
    runs._drop_prepare_slot(proj, tid)
    assert tid in [t for t, _ in runs_live.waiting_line(proj)]


# ---------------------------------------------------------------- daily limit per workspace


def test_the_daily_limit_stops_prepare_and_the_ticket_stays_as_saved(proj, new_ticket, starts, run):
    code, _, err = run("config", "set", "workflow.prepare_daily_limit", "2", "--by", "human:t")
    assert code == 0, err
    a, b, c = (new_ticket(f"report {i} pls") for i in range(3))
    assert "skipped" not in runs.start_prepare(proj, a, "human:t")
    assert "skipped" not in runs.start_prepare(proj, b, "human:t")
    r = runs.start_prepare(proj, c, "human:t")
    assert r["skipped"] == prepare.LIMIT_WHY and starts == [a, b]
    t = tickets.load(proj, c)
    assert t["status"] == "open" and t["prepare"]["state"] == "not_prepared"
    assert any(x.startswith("Not prepared yet: today's limit") for x in _history(proj, c))
    assert prepare.used(proj) == {"used": 2, "limit": 2}


def test_the_limit_counts_24_hours_back(proj):
    config.set_key(proj, "workflow", "prepare_daily_limit", 1)
    now = time.time()
    assert prepare.take(proj, now - 25 * 3600)
    assert prepare.take(proj, now)  # the old one fell out of the window
    assert not prepare.take(proj, now + 60)
    assert prepare.used(proj, now + 60)["used"] == 1


def test_a_start_that_waits_or_fails_gives_its_count_back(proj, new_ticket, monkeypatch):
    monkeypatch.setattr(runs_live, "_full", lambda root: 0)
    monkeypatch.setattr(runs_live, "_held", lambda root, by="agent:tend": None)

    def busy(*a, **k):
        raise Busy("someone else claimed it", {})

    monkeypatch.setattr(runs, "start", busy)
    with pytest.raises(Busy):
        runs.start_prepare(proj, new_ticket("x pls"), "human:t")

    def boom(*a, **k):
        raise Refused("no helper")

    monkeypatch.setattr(runs, "start", boom)
    with pytest.raises(Refused):
        runs.start_prepare(proj, new_ticket("y pls"), "human:t")
    assert prepare.used(proj)["used"] == 0


def test_limit_zero_prepares_nothing_and_start_still_works(proj, new_ticket, starts):
    config.set_key(proj, "workflow", "prepare_daily_limit", 0)
    tid = new_ticket("x pls")
    assert runs.start_prepare(proj, tid, "human:t")["skipped"] == prepare.LIMIT_WHY and starts == []
    assert tickets.load(proj, tid)["status"] == "open" and not tickets.load(proj, tid).get("started")


def test_only_a_person_raises_the_daily_limit(proj, run):
    assert config.prepare_daily_limit(proj) == config.DEFAULT_PREPARE_DAILY_LIMIT == 30
    code, _, err = run("config", "set", "workflow.prepare_daily_limit", "50", "--by", "agent:claude")
    assert code == 2 and "Only a person" in err
    code, _, err = run("config", "set", "workflow.prepare_daily_limit", "10", "--by", "agent:claude")
    assert code == 0, err  # lowering spends less: anyone
    code, _, _ = run("config", "set", "workflow.prepare_daily_limit", "50", "--by", "human:t")
    assert code == 0 and config.prepare_daily_limit(proj) == 50
    code, _, err = run("config", "set", "workflow.prepare_daily_limit", "lots", "--by", "human:t")
    assert code == 2 and "whole number" in err
    code, out, _ = run("config", "get", "workflow.prepare_daily_limit")
    assert code == 0 and "50" in out


# ---------------------------------------------------------------- a person's later edit wins


def test_fields_a_person_wrote_while_prepare_ran_are_kept(proj, new_ticket, run):
    tid = new_ticket("sales report pls")
    code, _, err = run(
        "ticket", "edit", tid, "--title", "November sales report", "--done-when", "Anna has the report",
        "--by", "human:t",
    )  # fmt: skip
    assert code == 0, err
    # the prepare helper's result, written against the version it read
    tickets.tidy(
        proj, tid, "Monthly sales report", "agent:fake", fields={"done_when": "The report is in the folder"},
        description="Make the report.", estimate={"minutes": 30, "cost": 2},
    )  # fmt: skip
    t = tickets.load(proj, tid)
    assert t["title"] == "November sales report" and t["done_when"] == "Anna has the report"
    assert t["description"] == "Make the report." and t["estimate"]["minutes"] == 30  # empty ones are filled


@pytest.mark.parametrize("status", ["active", "ready", "dropped", "done"])
def test_an_old_prepare_result_never_changes_a_newer_status(proj, new_ticket, status):
    tid = new_ticket("sales report pls")
    tickets.set_prepare(proj, tid, "preparing", "orch", run="r_1")
    tickets.set_status(proj, tid, status, "human:t", person=True)
    for state in ("prepared", "not_prepared"):
        assert tickets.set_prepare(proj, tid, state, "agent:fake", run="r_1") is False
    assert tickets.load(proj, tid)["status"] == status


def test_the_prepare_helper_cannot_change_the_status(proj, new_ticket, monkeypatch):
    tid = new_ticket("sales report pls")
    runs.claim(proj, tid, "human:t", "fake", pid=os.getpid(), prepare=True)
    assert prepare.running_prepare(proj, tid)
    for status in ("active", "done", "dropped"):
        with pytest.raises(Refused, match="being prepared"):
            tickets.set_status(proj, tid, status, "agent:claude")
    monkeypatch.setenv("CLAUDECODE", "1")  # an agent in the environment, whatever --by says
    with pytest.raises(Refused, match="being prepared"):
        tickets.set_status(proj, tid, "active", "human:t")
    monkeypatch.delenv("CLAUDECODE")
    tickets.set_status(proj, tid, "active", "human:t")  # a person still moves it
    assert tickets.load(proj, tid)["status"] == "active"


def test_a_helper_on_a_normal_run_still_changes_the_status(proj, new_ticket):
    tid = new_ticket("sales report pls")
    runs.claim(proj, tid, "human:t", "fake", pid=os.getpid())
    assert not prepare.running_prepare(proj, tid)
    tickets.set_status(proj, tid, "ready", "agent:claude")
    assert tickets.load(proj, tid)["status"] == "ready"


# ---------------------------------------------------------------- the Settings switch


def test_prepare_on_save_is_on_by_default(proj):
    assert config.prepare_on_save_on(proj) is True


def test_switched_off_nothing_is_prepared_and_the_ticket_is_untouched(proj, new_ticket, starts, run):
    code, _, err = run("config", "set", "workflow.prepare_on_save", "off", "--by", "agent:claude")
    assert code == 0, err  # turning it off spends less: anyone
    tid = new_ticket("sales report pls")
    before = tickets.load(proj, tid)
    assert runs.start_prepare(proj, tid, "human:t")["skipped"] == "Prepare on Save is off in Settings"
    assert starts == [] and tickets.load(proj, tid) == before
    code, out, _ = run("run", "start", tid, "--prepare", "--by", "human:t")
    assert code == 0 and "Not prepared: Prepare on Save is off" in out


def test_only_a_person_turns_prepare_on_save_on(proj, run):
    config.set_prepare_on_save(proj, False)
    code, _, err = run("config", "set", "workflow.prepare_on_save", "on", "--by", "agent:claude")
    assert code == 2 and "Only a person" in err and config.prepare_on_save_on(proj) is False
    code, _, err = run("config", "set", "workflow.prepare_on_save", "on", "--by", "human:t")
    assert code == 0, err
    code, out, _ = run("config", "get", "workflow.prepare_on_save")
    assert code == 0 and "true" in out.lower()
