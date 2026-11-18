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
            assert r.headers["Cache-Control"] == "no-store"
            body = json.loads(r.read())
        assert body["lines"] == 3 and body["age_ms"] == 250 and len(body["sessions"]) == 6
        assert body["sessions"][0]["key"] == "ORCH-2"
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
