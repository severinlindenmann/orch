"""Sessions without a ticket (ORCH-364, draft D): empty helper, chat helper, plain terminal, Manager; one
start path."""

import json
import os
import time

import pytest

from orch import manager, runs, runs_live, sessions, tend, tickets
from orch.errors import Refused


@pytest.fixture
def fake_start(monkeypatch):
    started = []

    def start(root, tid, by, fresh=False, mode=None, **kw):
        started.append((tid, mode))
        return {"run": "r_x", "notes": []}

    monkeypatch.setattr(runs, "start", start)
    monkeypatch.setattr(runs, "running", lambda root, tid: tid in [s[0] for s in started])
    return started


def test_the_empty_helper_and_terminal_are_hidden_tickets_made_once(proj, run):
    e = tickets.ensure_session(proj, "empty", "human:t")
    term = tickets.ensure_session(proj, "terminal", "human:t")
    assert tickets.ensure_session(proj, "empty", "human:t") == e and e != term
    t = tickets.load(proj, e)
    assert t["session"] == "empty" and t["title"] == "Empty helper" and not t.get("key")
    assert tickets.is_session(proj, e) and not tickets.is_manager(proj, e) and not tickets.is_general(proj, e)
    assert tickets.manager_id(proj) is None and tickets.general_id(proj) is None
    listed = json.loads(run("ticket", "list", "--all", "--json")[1])
    assert not {e, term} & {x["id"] for x in listed}
    ignore = (proj / ".orch" / ".gitignore").read_text(encoding="utf-8")
    assert f"tickets/{e}.json" in ignore and f"tickets/{term}.json" in ignore
    with pytest.raises(Refused, match="No such session"):
        tickets.ensure_session(proj, "chat", "human:t")


@pytest.mark.parametrize("status", ["done", "review", "dropped", "open", "active"])
def test_a_session_without_a_ticket_is_never_finished_or_moved(proj, status):
    tid = tickets.ensure_session(proj, "empty", "human:t")
    with pytest.raises(Refused, match="session without a ticket is not a ticket"):
        tickets.set_status(proj, tid, status, "human:t")


def test_new_starts_each_helper_live_through_one_path(proj, fake_start, monkeypatch):
    monkeypatch.setattr(
        manager,
        "start",
        lambda root, by, fresh=False: {
            "started": True,
            "notes": [],
            "ticket": tickets.ensure_manager(root, by),
        },
    )
    d = sessions.new(proj, "empty", "human:t")
    e = tickets.session_id(proj, "empty")
    assert d["id"] == e and d["started"] and d["open"] and d["title"] == "Empty helper"
    c = sessions.new(proj, "chat", "human:t")
    assert c["id"] == tickets.general_id(proj) and c["started"]
    assert fake_start == [(e, "live"), (c["id"], "live")]
    again = sessions.new(proj, "empty", "human:t")
    assert again["started"] is False and len(fake_start) == 2  # already open: goes to it
    m = sessions.new(proj, "manager", "human:t")
    assert m["id"] == tickets.manager_id(proj) and m["kind"] == "manager"
    with pytest.raises(Refused, match="No such session"):
        sessions.new(proj, "ticket", "human:t")


def test_the_empty_helper_says_its_model_and_starts_on_the_persons_pick(proj, fake_start, run):
    """ORCH-710: the New menu shows the model the Empty helper starts on and the person can pick another."""
    from orch import modelpick

    tid = tickets.ensure_session(proj, "empty", "human:t")
    first = sessions.one(proj, "empty")
    assert (
        first["model"]
        == tickets.next_model(tickets.load(proj, tid))
        == modelpick.pick(tickets.load(proj, tid))[0]
    )
    d = sessions.new(proj, "empty", "human:t", model="haiku")
    assert d["started"] and d["model"] == "haiku"
    m = tickets.load(proj, tid)["model"]
    assert m["name"] == "haiku" and modelpick.by_person(tickets.load(proj, tid))
    assert sessions.listing(proj)[0]["model"] == "haiku"
    again = sessions.new(
        proj, "empty", "human:t", model="opus"
    )  # already running: goes to it, model unchanged
    assert again["started"] is False and tickets.load(proj, tid)["model"]["name"] == "haiku"
    with pytest.raises(Refused, match="Only the Empty helper takes a model"):
        sessions.new(proj, "chat", "human:t", model="opus")


def test_the_usual_pick_stays_orchs_choice(proj, fake_start):
    tid = tickets.ensure_session(proj, "empty", "human:t")
    usual = sessions.one(proj, "empty")["model"]
    sessions.new(proj, "empty", "human:t", model=usual)
    assert "model" not in tickets.load(proj, tid)  # same as orch's pick: no person's choice is written


def test_cli_session_new_takes_a_model(proj, run, monkeypatch):
    monkeypatch.setattr(runs, "start", lambda root, tid, by, **kw: {"run": "r_x", "notes": []})
    code, out, _ = run("session", "new", "empty", "--model", "sonnet", "--json")
    assert code == 0 and json.loads(out)["model"] == "sonnet"


def test_the_plain_terminal_is_a_placeholder_open_until_closed(proj, fake_start):
    d = sessions.new(proj, "terminal", "human:t")
    assert (
        d["started"] and d["open"] and not d["running"] and fake_start == []
    )  # no process before the terminal stage
    assert sessions.new(proj, "terminal", "human:t")["started"] is False
    shut = sessions.close(proj, "terminal", "human:t")
    assert shut["closed"] and not shut["open"]
    assert sessions.close(proj, "terminal", "human:t")["closed"] is False
    back = sessions.new(proj, "terminal", "human:t")
    assert back["started"] and back["open"] and back["id"] == d["id"]


def test_listing_names_only_what_was_made_in_menu_order(proj, fake_start):
    assert sessions.listing(proj) == []
    sessions.new(proj, "terminal", "human:t")
    sessions.new(proj, "empty", "human:t")
    rows = sessions.listing(proj)
    assert [r["kind"] for r in rows] == ["empty", "terminal"] and all(r["open"] for r in rows)


def test_the_empty_helper_works_in_the_workspace_and_says_its_role(proj, monkeypatch):
    from orch import worktrees

    tid = tickets.ensure_session(proj, "empty", "human:t")
    monkeypatch.setattr(
        worktrees, "route", lambda *a: pytest.fail("a session without a ticket is never routed to a copy")
    )
    rec, notes = runs.claim_routed(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    assert runs.workdir_for(proj, rec, tid) == proj and notes == []
    text = sessions.empty_prompt(tickets.load(proj, tid), "- human:t: hello")
    assert tid in text and "without a task" in text
    assert "hello" in text and "never finish it" in text
    assert f"orch ticket model {tid} up" in text  # ORCH-710: it starts small and moves up when it turns hard


def test_the_empty_helper_starts_on_sonnet_and_moves_up_to_opus(proj):
    """ORCH-710 (owner 19 Nov): Sonnet by default; moved up it stays on Opus for its next starts."""
    from orch import modelpick

    tid = tickets.ensure_session(proj, "empty", "human:t")
    assert modelpick.pick(tickets.load(proj, tid)) == (
        "sonnet",
        "the Empty helper has no task yet; it moves up when the work turns hard",
    )
    assert tickets.pick_model(proj, tid, "orch") == "sonnet"
    t, moved = tickets.move_up(proj, tid, "the person asked for a new page design", "agent:claude")
    assert moved and sessions.one(proj, "empty")["model"] == "opus"


def test_the_watcher_never_nudges_the_empty_helper(proj, monkeypatch):
    tid = tickets.ensure_session(proj, "empty", "human:t")
    rec = runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    rec["live"] = {"state": "idle", "since": runs._iso(time.time() - 3600)}
    runs._write(proj, rec)
    assert tid not in [r["ticket"] for r in tend.plan(proj)]
    assert not runs.settle(proj, tid, "human:t")  # never moved to Ready: it is no piece of work


def test_cli_new_list_close(proj, run, monkeypatch):
    code, out, _ = run("session", "list")
    assert code == 0 and "No session without a ticket" in out
    code, out, _ = run("session", "new", "terminal")
    assert code == 0 and "Started the Plain terminal" in out
    d = json.loads(run("session", "list", "--json")[1])
    assert [(r["kind"], r["open"]) for r in d["sessions"]] == [("terminal", True)]
    code, out, _ = run("session", "close", "terminal")  # the older name of end still works
    assert code == 0 and "Ended the Plain terminal" in out
    monkeypatch.setattr(runs_live, "stop", lambda *a, **k: pytest.fail("nothing runs"))
    code, out, _ = run("session", "close", "empty")
    assert code == 0 and "not open" in out


# ORCH-817: Stop (the current step only) and End (the session) for every session, with a ticket or without.


def _live(proj, tid, monkeypatch, agent="claude"):
    rec = runs.claim(proj, tid, "human:t", agent, "live", pid=os.getpid())
    sent = []
    monkeypatch.setattr(runs_live, "session_exists", lambda root, t: t == tid)
    monkeypatch.setattr(runs_live, "tmux", lambda root, *a, **k: sent.append(a))
    return rec, sent


def test_interrupt_sends_the_tools_keys_once_and_keeps_the_session(proj, monkeypatch):
    tid = tickets.ensure_session(proj, "empty", "human:t")
    rec, sent = _live(proj, tid, monkeypatch)
    assert runs_live.interrupt(proj, tid) is True
    assert sent == [("send-keys", "-t", runs_live.target(tid), "Escape")]  # no kill-session
    assert runs.read(proj, tid)["run"] == rec["run"]  # the claim and the session stay


def test_interrupt_without_a_live_session_does_nothing(proj, monkeypatch):
    tid = tickets.ensure_session(proj, "empty", "human:t")
    monkeypatch.setattr(runs_live, "tmux", lambda *a, **k: pytest.fail("nothing is live"))
    assert runs_live.interrupt(proj, tid) is False
    runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    monkeypatch.setattr(runs_live, "session_exists", lambda root, t: False)
    assert runs_live.interrupt(proj, tid) is False


def test_interrupt_is_refused_for_a_tool_with_no_stop_key(proj, monkeypatch):
    from orch import adapters

    tid = tickets.ensure_session(proj, "empty", "human:t")
    _live(proj, tid, monkeypatch)
    monkeypatch.setattr(adapters, "load", lambda name, root: {"live": {"interrupt_keys": []}})
    with pytest.raises(Refused, match="End the session"):
        runs_live.interrupt(proj, tid)


def test_session_stop_interrupts_the_helper_and_never_the_terminal(proj, monkeypatch):
    with pytest.raises(Refused, match="no step to stop"):
        sessions.interrupt(proj, "terminal")
    assert sessions.interrupt(proj, "empty")["interrupted"] is False  # never made
    tid = tickets.ensure_session(proj, "empty", "human:t")
    _, sent = _live(proj, tid, monkeypatch)
    monkeypatch.setattr(runs, "running", lambda root, t: t == tid)
    d = sessions.interrupt(proj, "empty")
    assert d["interrupted"] and d["open"] and d["id"] == tid and len(sent) == 1


def test_cli_session_stop_and_end_and_run_interrupt(proj, run, monkeypatch):
    code, out, err = run("session", "stop", "empty")
    assert code == 2 and "The Empty helper is not open" in (out + err)
    code, out, err = run("session", "stop", "terminal")
    assert code == 2 and "no step to stop" in (out + err)
    run("session", "new", "terminal")
    code, out, _ = run("session", "end", "terminal")
    assert code == 0 and "Ended the Plain terminal." in out and "History" not in out
    tid = tickets.ensure_session(proj, "empty", "human:t")
    _, sent = _live(proj, tid, monkeypatch)
    monkeypatch.setattr(runs, "running", lambda root, t: t == tid)
    code, out, _ = run("session", "stop", "empty")
    assert code == 0 and "Stopped the current step of the Empty helper" in out and len(sent) == 1
    code, out, _ = run("run", "interrupt", tid)
    assert code == 0 and "Stopped the current step" in out and len(sent) == 2
    monkeypatch.setattr(runs_live, "stop", lambda root, t, hold=False: t == tid)
    code, out, _ = run("session", "end", "empty")
    assert code == 0 and "Ended the Empty helper" in out and "History" in out
    monkeypatch.setattr(runs_live, "session_exists", lambda root, t: False)
    code, out, err = run("run", "interrupt", tid)
    assert code == 2 and "no step to stop" in (out + err)
