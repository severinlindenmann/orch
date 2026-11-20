"""Sessions without a ticket (ORCH-364, draft D): empty helper, chat helper, plain terminal, Manager; one
start path."""

import json
import os
import shutil
import subprocess
import time

import pytest

from orch import manager, runs, runs_live, sessions, tend, tickets
from orch.errors import Refused


@pytest.fixture
def fake_start(monkeypatch):
    started = []
    shells: set[str] = set()  # the plain terminal's shell without a real tmux
    monkeypatch.setattr(sessions, "shell_on", lambda root, tid: tid in shells)
    monkeypatch.setattr(sessions, "start_shell", lambda root, tid: shells.add(tid) is None)
    monkeypatch.setattr(
        sessions, "stop_shell", lambda root, tid: tid in shells and shells.discard(tid) is None
    )

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


def test_the_plain_terminal_is_a_shell_open_until_closed(proj, fake_start):
    d = sessions.new(proj, "terminal", "human:t")
    assert d["started"] and d["open"] and not d["running"] and fake_start == []  # no helper, no slot
    assert d["shell"] and d["tmux"] == {"socket": runs_live.socket_name(proj), "session": d["id"]}
    assert sessions.new(proj, "terminal", "human:t")["started"] is False
    shut = sessions.close(proj, "terminal", "human:t")
    assert shut["closed"] and not shut["open"] and not shut["shell"] and "tmux" not in shut
    assert sessions.close(proj, "terminal", "human:t")["closed"] is False
    back = sessions.new(proj, "terminal", "human:t")
    assert back["started"] and back["open"] and back["shell"] and back["id"] == d["id"]


def test_a_plain_terminal_whose_shell_ended_starts_it_again(proj, fake_start):
    d = sessions.new(proj, "terminal", "human:t")
    sessions.stop_shell(proj, d["id"])  # the person typed exit, or this computer restarted
    assert sessions.one(proj, "terminal")["open"] and not sessions.one(proj, "terminal")["shell"]
    again = sessions.new(proj, "terminal", "human:t")
    assert again["started"] and again["shell"]


def test_without_tmux_the_plain_terminal_stays_a_placeholder(proj, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    d = sessions.new(proj, "terminal", "human:t")
    assert d["started"] and d["open"] and d["shell"] is False and "tmux" not in d


@pytest.mark.skipif(os.name == "nt" or shutil.which("tmux") is None, reason="needs tmux")
def test_the_plain_terminal_runs_a_real_shell_in_the_workspace(proj):
    sock = runs_live.socket_name(proj)
    try:
        d = sessions.new(proj, "terminal", "human:t")
        assert d["shell"] and runs_live.session_exists(proj, d["id"])
        where = runs_live.tmux(
            proj, "display-message", "-p", "-t", runs_live.target(d["id"]), "#{pane_current_path}"
        )
        assert os.path.realpath(where.stdout.strip()) == os.path.realpath(proj)
        assert sessions.close(proj, "terminal", "human:t")["closed"]
        assert not runs_live.session_exists(proj, d["id"])
    finally:
        subprocess.run(["tmux", "-L", sock, "kill-server"], capture_output=True, check=False)


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


def test_the_watcher_never_nudges_the_empty_helper(proj, monkeypatch):
    tid = tickets.ensure_session(proj, "empty", "human:t")
    rec = runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    rec["live"] = {"state": "idle", "since": runs._iso(time.time() - 3600)}
    runs._write(proj, rec)
    assert tid not in [r["ticket"] for r in tend.plan(proj)]
    assert not runs.settle(proj, tid, "human:t")  # never moved to Ready: it is no piece of work


def test_cli_new_list_close(proj, run, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)  # the CLI path, without a real shell
    code, out, _ = run("session", "list")
    assert code == 0 and "No session without a ticket" in out
    code, out, _ = run("session", "new", "terminal")
    assert code == 0 and "Started the Plain terminal" in out
    d = json.loads(run("session", "list", "--json")[1])
    assert [(r["kind"], r["open"]) for r in d["sessions"]] == [("terminal", True)]
    code, out, _ = run("session", "close", "terminal")
    assert code == 0 and "Closed the Plain terminal" in out
    monkeypatch.setattr(runs_live, "stop", lambda *a, **k: pytest.fail("nothing runs"))
    code, out, _ = run("session", "close", "empty")
    assert code == 0 and "not open" in out
