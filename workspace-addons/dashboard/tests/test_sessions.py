"""ORCH-359: every session for the new Focus (wall, bar, panes) from one API, built from the cached state plus one
read of the live screens."""

import json
import threading
import time
import urllib.request

import pytest

from orch_dashboard import sessions
from orch_dashboard.server import make_server


def _t(n, status="active", **kw):
    return {"id": f"t_sess{n:04d}", "key": f"ORCH-{n}", "title": f"Ticket {n}", "status": status, **kw}


def _run(state="working", word="Working", detail="", live=True, **kw):
    claim = {"agent": "generic", "mode": "live" if live else "oneshot", "started_at": "2026-11-17T20:00:00Z"}
    return {
        "running": True,
        "state": "alive",
        "claim": claim,
        "helper": {"state": state, "word": word, "detail": detail},
        "age_seconds": 1500,
        "idle_seconds": None,
        "waiting_on": [],
        **kw,
    }


def _state():
    tickets = [
        _t(1, warmth={"seconds_left": 1800}),
        _t(
            2, questions=[{"id": "q1", "text": "Keep  the old name?", "answer": None}], model={"name": "opus"}
        ),
        _t(3),
        _t(4),
        _t(5, status="done"),  # done, nothing runs: not a session
        _t(6, status="dropped"),
        _t(7),
        _t(8),
    ]
    runs = {
        "t_sess0001": _run(
            waiting_on=[{"kind": "command", "what": "pytest (running 1 min)", "label": "pytest"}],
            detail="Running pytest",
        ),
        "t_sess0002": _run("you", "Waits for you", "Your answer"),
        "t_sess0003": {"running": False, "pending": 0},
        "t_sess0004": _run("idle", "Idle", "Nothing running for 5 min", idle_seconds=300),
        "t_sess0005": {"running": False},
        "t_sess0007": _run(
            "waiting", "On hold", "Waiting for the pull request checks", live=False, hold="x y"
        ),
    }
    return {"tickets": tickets, "runs": runs, "start_line": {"waiting": ["t_sess0008"], "why": None}}


@pytest.fixture
def screens(monkeypatch):
    calls = []

    def fake(orch_bin, args, root, timeout=5.0):
        calls.append(args)
        ids = args[2:-3]
        return {"screens": {i: {"lines": [f"{i} one", f"{i} last"]} for i in ids}}

    monkeypatch.setattr(sessions, "run_orch", fake)
    sessions._TAILS.clear()
    return calls


def test_every_session_with_status_waits_lines_tool_model_and_open_time(tmp_path, screens):
    got = {s["key"]: s for s in sessions.build(tmp_path, "orch", _state(), 2)}
    assert [s for s in got] == ["ORCH-2", "ORCH-1", "ORCH-7", "ORCH-8", "ORCH-4", "ORCH-3"]
    need, work, hold, line, idle, closed = (got[k] for k in got)
    assert (
        need["status"] == "needs-you" and need["question"] == "Keep the old name?" and need["model"] == "Opus"
    )
    assert work["status"] == "working" and work["detail"] == "Running pytest"
    assert work["waiting_on"] == [{"kind": "command", "what": "pytest (running 1 min)"}]
    assert work["lines"] == ["t_sess0001 one", "t_sess0001 last"] and work["mode"] == "live"
    assert work["opened_at"] == "2026-11-17T20:00:00Z" and work["open_seconds"] == 1500
    assert work["closes_in_seconds"] == 1800 and work["tool"]
    assert (
        hold["status"] == "working" and hold["word"] == "On hold" and hold["lines"] == []
    )  # one step at a time
    assert {"kind": "hold", "what": "x y"} in hold["waiting_on"]
    assert line["status"] == "in-line" and line["word"] == "In line"
    assert idle["status"] == "idle" and idle["idle_seconds"] == 300
    assert closed["status"] == "closed" and closed["tool"] is None and closed["open_seconds"] is None
    # one screen read for every live session, never for a oneshot or a closed one
    assert (
        len(screens) == 1
        and screens[0][:2] == ["run", "screen"]
        and screens[0][-3:] == ["--lines", "2", "--json"]
    )
    assert sorted(screens[0][2:-3]) == ["t_sess0001", "t_sess0002", "t_sess0004"]


def test_the_screen_read_is_shared_for_a_moment(tmp_path, screens):
    sessions.build(tmp_path, "orch", _state())
    sessions.build(tmp_path, "orch", _state())
    assert len(screens) == 1
    sessions._TAILS[(str(tmp_path), sessions.LINES)] = (
        time.monotonic() - 10,
        *sessions._TAILS[(str(tmp_path), sessions.LINES)][1:],
    )
    sessions.build(tmp_path, "orch", _state())
    assert len(screens) == 2


def test_one_live_session_takes_the_commands_own_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "run_orch", lambda *a, **k: {"lines": ["only"], "signal": "working"})
    sessions._TAILS.clear()
    assert sessions.tails(tmp_path, "orch", ["t_sess0001"], 3) == {"t_sess0001": ["only"]}


def test_no_orch_answer_means_no_lines_never_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "run_orch", lambda *a, **k: None)
    sessions._TAILS.clear()
    s = sessions.build(tmp_path, "orch", _state())
    assert all(x["lines"] == [] for x in s)


def test_24_sessions_cost_one_read_and_little_time(tmp_path, screens):
    tickets = [_t(n) for n in range(1, 25)]
    state = {"tickets": tickets, "runs": {t["id"]: _run() for t in tickets}}
    t0 = time.perf_counter()
    s = sessions.build(tmp_path, "orch", state)
    assert len(s) == 24 and len(screens) == 1 and time.perf_counter() - t0 < 0.5


def test_the_api_serves_the_sessions(tmp_path, screens):
    (tmp_path / ".orch" / "tickets").mkdir(parents=True)
    srv = make_server(tmp_path, 0, orch_bin="orch")
    srv.state_cache.get = lambda: (_state(), 0.25)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/api/sessions?lines=3") as r:
            assert r.headers["Cache-Control"] == "private, no-cache"
            tag = r.headers["ETag"]
            body = json.loads(r.read())
        assert body["lines"] == 3 and body["age_ms"] == 250 and len(body["sessions"]) == 6
        assert body["sessions"][0]["key"] == "ORCH-2"
        # an unchanged list (even with another clock and state age) answers 304 with no body
        srv.state_cache.get = lambda: (_state(), 2.5)
        again = urllib.request.Request(base + "/api/sessions?lines=3", headers={"If-None-Match": tag})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(again)
        assert e.value.code == 304 and e.value.read() == b""
        other = urllib.request.Request(base + "/api/sessions?lines=3", headers={"If-None-Match": '"x"'})
        with urllib.request.urlopen(other) as r:
            assert r.status == 200
        req = urllib.request.Request(base + "/api/sessions", headers={"Origin": "http://evil.example"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        assert e.value.code == 403
    finally:
        srv.shutdown()


def test_a_live_session_past_the_first_30_open_tickets_is_still_asked_for(tmp_path, monkeypatch):
    from orch_dashboard import data

    claims = tmp_path / ".orch" / "run" / "tickets"
    claims.mkdir(parents=True)
    tickets = [_t(n) for n in range(1, 41)]
    (claims / "t_sess0040.json").write_text("{}")
    asked = []

    def fake(orch_bin, args, root, timeout=5.0):
        asked.extend(args[2:-1])
        return {"runs": {i: {"running": False} for i in args[2:-1]}}

    monkeypatch.setattr(data, "run_orch", fake)
    data._RUNS.clear()
    data.load_runs(tmp_path, "orch", tickets, fresh=True)
    assert len(asked) == data.RUNS_MAX + 1 and "t_sess0040" in asked and "t_sess0031" not in asked


def test_open_sessions_without_a_ticket_join_the_list_by_their_title(tmp_path, screens):
    """ORCH-364: the New menu's sessions (their tickets are hidden) come from state["sessions"], open ones only."""
    st = _state()
    st["sessions"] = [
        {"id": "t_empty001", "kind": "empty", "title": "Empty helper", "open": True},
        {"id": "t_general1", "kind": "chat", "title": "Chat helper", "open": False},
        {"id": "t_term0001", "kind": "terminal", "title": "Plain terminal", "open": True},
        {"id": "t_manager1", "kind": "manager", "title": "Manager", "open": True},
        {"id": "t_oddkind1", "kind": "ticket", "title": "Not a kind", "open": True},
    ]
    st["runs"]["t_empty001"] = _run()
    st["runs"]["t_manager1"] = _run("idle", "Idle")
    got = {s["id"]: s for s in sessions.build(tmp_path, "orch", st, 2)}
    assert "t_general1" not in got and "t_oddkind1" not in got
    emp, term, man = got["t_empty001"], got["t_term0001"], got["t_manager1"]
    assert (emp["kind"], emp["key"], emp["title"], emp["status"]) == ("empty", "", "Empty helper", "working")
    assert emp["lines"] == ["t_empty001 one", "t_empty001 last"]
    assert (term["kind"], term["status"], term["word"], term["tool"], term["lines"]) == (
        "terminal",
        "idle",
        "Open",
        None,
        [],
    )
    assert (man["kind"], man["status"]) == ("manager", "idle")
    assert got["t_sess0001"]["kind"] == ""


# --- ORCH-345: groups of an epic or a factory order, small helpers inside a session ---


def _epic_state():
    tickets = [
        _t(20, title="Autumn newsletter", ext={"factory": {"role": "order"}}),
        _t(21, parent="t_sess0020", title="Write the texts"),
        _t(
            22,
            parent="t_sess0020",
            title="Build the mail page",
            questions=[{"id": "q1", "text": "Which header?", "answer": None}],
        ),
        _t(23, parent="t_sess0020", title="Send a test"),  # open, no session yet
        _t(24, parent="t_sess0020", status="done"),  # done and no session: left out
        _t(25, parent="t_sess0021", title="Proofread"),  # a sub-ticket of a sub-ticket, in line
        _t(30, title="Alone"),
        _t(
            31,
            title="Parent of one",
        ),
        _t(32, parent="t_sess0031"),
    ]
    sub = {
        "kind": "command",
        "what": "a helper of its own: Draft intro (running 2 min)",
        "label": "helper: Draft intro",
        "seconds": 120,
        "subagent": True,
    }
    runs = {
        "t_sess0020": _run(),
        "t_sess0021": _run(waiting_on=[sub]),
        "t_sess0022": _run("you", "Waits for you"),
        "t_sess0030": _run(),
        "t_sess0032": _run(),  # its parent has no session: one session only, no group
    }
    return {"tickets": tickets, "runs": runs, "start_line": {"waiting": ["t_sess0025"]}}


def test_small_helpers_and_the_parent_ride_on_the_session(tmp_path, screens):
    got = {s["key"]: s for s in sessions.build(tmp_path, "orch", _epic_state(), 2)}
    assert got["ORCH-21"]["small"] == [{"what": "Draft intro", "seconds": 120}]
    assert got["ORCH-21"]["parent"] == "t_sess0020" and got["ORCH-20"]["parent"] is None
    assert got["ORCH-20"]["small"] == [] and got["ORCH-25"]["small"] == []


def test_a_group_holds_the_main_helper_and_every_open_sub_ticket_in_tree_order(tmp_path, screens):
    st = _epic_state()
    got = sessions.groups(st, sessions.build(tmp_path, "orch", st, 2))
    assert [g["key"] for g in got] == ["ORCH-20"]  # one session under ORCH-31: no group
    g = got[0]
    assert g["kind"] == "factory" and g["title"] == "Autumn newsletter"
    rows = [(m["key"], m["depth"], m["main"], m["status"]) for m in g["members"]]
    assert rows == [
        ("ORCH-20", 0, True, "working"),
        ("ORCH-21", 1, False, "working"),
        ("ORCH-25", 2, False, "in-line"),
        ("ORCH-22", 1, False, "needs-you"),
        ("ORCH-23", 1, False, "closed"),
    ]
    assert g["members"][1]["small"] == [{"what": "Draft intro", "seconds": 120}]
    assert g["members"][4]["word"] == "No session"


def test_a_loop_in_the_parent_chain_is_never_followed(tmp_path, screens):
    st = {
        "tickets": [_t(40, parent="t_sess0041"), _t(41, parent="t_sess0040")],
        "runs": {"t_sess0040": _run(), "t_sess0041": _run()},
    }
    got = sessions.groups(st, sessions.build(tmp_path, "orch", st, 2))
    assert len(got) == 1 and sorted(m["key"] for m in got[0]["members"]) == ["ORCH-40", "ORCH-41"]


def test_the_api_answer_carries_the_groups(tmp_path, screens):
    got = sessions.answer(tmp_path, "orch", _epic_state(), 0.0, 2)
    assert [g["id"] for g in got["groups"]] == ["t_sess0020"]


def test_a_quiet_session_whose_result_waits_reads_check_like_its_ticket():
    """ORCH-674: the tile said Idle while the layer (the ticket's pill) said Check for the same session."""
    idle = sessions.session(_t(9, status="review"), _run("idle", "Idle"), False, None)
    assert (idle["status"], idle["word"]) == ("idle", "Check")
    closed = sessions.session(_t(10, status="review"), {"running": False}, False, None)
    assert (closed["status"], closed["word"]) == ("closed", "Check")
    plain = sessions.session(_t(11), _run("idle", "Idle"), False, None)
    assert plain["word"] == "Idle"
    asks = sessions.session(_t(12, status="review"), _run("you", "Waits for you"), False, None)
    assert asks["word"] == "Waits for you"
