"""`orch manager` (cli_manager.py), `orch session` (cli_session.py), session ID syntax (session_ids.py)."""

import json
import shutil

import pytest

from orch import manager, runs, runs_live, session_ids, tickets


@pytest.fixture
def fake_manager(monkeypatch):
    started = []
    monkeypatch.setattr(
        runs,
        "start",
        lambda root, tid, by, fresh=False, **kw: started.append(tid) or {"run": "r_x", "notes": []},
    )
    monkeypatch.setattr(runs, "running", lambda root, tid: bool(started))
    monkeypatch.setattr(runs_live, "stop", lambda root, tid, hold=False: bool(started.clear()) or True)
    return started


def test_manager_start_status_stop_text_and_json(proj, run, fake_manager):
    code, out, _ = run("manager", "status")
    assert code == 0 and "Start it: orch manager start" in out
    code, out, _ = run("manager", "start")
    mid = tickets.manager_id(proj)
    assert code == 0 and "Started the Manager." in out and f"orch run attach {mid}" in out
    code, out, _ = run("manager", "start")
    assert code == 0 and "already on" in out
    d = json.loads(run("manager", "status", "--json")[1])
    assert d["running"] is True and d["ticket"] == mid
    code, out, _ = run("manager", "start", "--fresh")
    assert code == 0 and "fresh" in out
    code, out, _ = run("manager", "stop")
    assert code == 0 and "Its conversation is kept" in out
    assert json.loads(run("manager", "stop", "--json")[1])["stopped"] is False
    assert "The Manager is off. Start it: orch manager start" in run("manager", "status")[1]


def test_manager_start_json_is_pure_json_and_notes_go_to_stderr(proj, run, fake_manager, monkeypatch):
    real = manager.start
    monkeypatch.setattr(manager, "start", lambda *a, **k: {**real(*a, **k), "notes": ["a note"]})
    code, out, err = run("manager", "start", "--json")
    assert code == 0 and json.loads(out)["started"] is True and "a note" in err


def test_session_new_list_end_text_and_json(proj, run, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert "No session without a ticket yet." in run("session", "list")[1]
    d = json.loads(run("session", "new", "terminal", "--json")[1])
    assert d["started"] is True
    assert "already open" in run("session", "new", "terminal")[1]
    rows = json.loads(run("session", "list", "--json")[1])["sessions"]
    assert [(r["kind"], r["open"]) for r in rows] == [("terminal", True)]
    assert "terminal" not in run("session", "list")[1] or "open" in run("session", "list")[1]
    assert json.loads(run("session", "end", "terminal", "--json")[1])["closed"] is True
    assert "is not open" in run("session", "end", "terminal")[1]


def test_session_stop_not_open_is_refused_with_a_next_step(proj, run):
    code, out, err = run("session", "stop", "empty")
    text = out + err
    assert code == 2 and "not open" in text
    assert "orch session new empty" in text


def test_session_unknown_kind_is_rejected(proj, run, capsys):
    with pytest.raises(SystemExit) as e:
        run("session", "new", "nonsense")
    assert e.value.code == 2


@pytest.mark.parametrize(
    "sid,ok",
    [
        ("0f8fad5b-d9cb-469f-a165-70867728950e", True),
        ("thread_1-A", True),
        ("a" * 128, True),
        ("a" * 129, False),
        ("", False),
        ("-leading", False),
        ("../etc", False),
        ("a b", False),
        ("a\n", False),
        (None, False),
        (7, False),
    ],
)
def test_valid_session_id(sid, ok):
    assert session_ids.valid_session_id(sid) is ok
