"""When an agent tool's login runs out (logins.py, `orch agents login`): two facts and nothing else."""

import json
import os
import subprocess
from datetime import UTC, datetime

import pytest

from orch import adapters, cli_config, logins, runs

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
SPEC = {"status": ["auth", "status", "--json"], "logged_in": "loggedIn", "ends": "loginExpiresAt"}
HIDDEN = "sk-test-NOT-A-REAL-KEY-0000"


def _answers(monkeypatch, stdout, seen=None):
    def fake(argv, **kw):
        if seen is not None:
            seen.append((argv, kw))
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=HIDDEN)

    monkeypatch.setattr(logins.subprocess, "run", fake)


@pytest.mark.parametrize(
    ("value", "want"),
    [
        ("2026-11-17T21:24:57.990Z", "2026-11-17T21:24:57Z"),
        ("2026-11-17T22:24:57+01:00", "2026-11-17T21:24:57Z"),
        ("2026-11-17T21:24:57", "2026-11-17T21:24:57Z"),
        (1794950697, "2026-11-17T21:24:57Z"),
        (1794950697990, "2026-11-17T21:24:57Z"),
        (HIDDEN, None),
        ("x" * 41, None),
        (True, None),
        (None, None),
        ({"a": 1}, None),
    ],
)
def test_end_is_a_real_time_or_nothing(value, want):
    assert logins._end(value) == want


@pytest.mark.parametrize(
    ("logged_in", "ends", "want"),
    [
        (True, "2026-11-30T00:00:00Z", "ok"),
        (True, None, "ok"),
        (True, "2026-11-19T12:00:00Z", "soon"),  # exactly WARN_DAYS ahead
        (True, "2026-11-19T12:00:01Z", "ok"),
        (True, "2026-11-16T12:00:00Z", "out"),
        (False, "2026-11-30T00:00:00Z", "out"),
        (False, None, "out"),
        (None, None, "unknown"),
        (None, "2026-11-17T00:00:00Z", "soon"),
    ],
)
def test_state(logged_in, ends, want):
    assert logins.state(logged_in, ends, NOW) == want


def test_ask_keeps_two_facts_and_runs_the_fixed_command(monkeypatch):
    seen = []
    doc = {
        "loggedIn": True,
        "loginExpiresAt": "2026-11-17T21:24:57.990Z",
        "email": "a@b.example",
        "key": HIDDEN,
    }
    _answers(monkeypatch, json.dumps(doc), seen)
    assert logins.ask("/bin/tool", SPEC) == (True, "2026-11-17T21:24:57Z")
    argv, kw = seen[0]
    assert argv == ["/bin/tool", "auth", "status", "--json"]
    assert kw["stdin"] == subprocess.DEVNULL and kw["timeout"] == logins.TIMEOUT


@pytest.mark.parametrize("stdout", ["", "not json", "[1]", '"text"', json.dumps({"loggedIn": "yes"})])
def test_ask_unreadable_answer_is_unknown(monkeypatch, stdout):
    _answers(monkeypatch, stdout)
    assert logins.ask("/bin/tool", SPEC) == (None, None)


def test_ask_survives_a_tool_that_fails(monkeypatch):
    def boom(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 1)

    monkeypatch.setattr(logins.subprocess, "run", boom)
    assert logins.ask("/bin/tool", SPEC) == (None, None)


def test_tool_without_end_field(monkeypatch):
    _answers(monkeypatch, json.dumps({"loggedIn": True}))
    assert logins.ask("/bin/tool", {"status": ["status"], "logged_in": "loggedIn"}) == (True, None)


@pytest.fixture
def tool(monkeypatch):
    """The claude adapter looks installed and answers `doc` (set by the test)."""
    box = {"doc": {"loggedIn": True, "loginExpiresAt": "2026-11-17T21:24:57.990Z", "token": HIDDEN}}
    monkeypatch.setattr(logins.shutil, "which", lambda b: f"/bin/{b}" if b == "claude" else None)
    monkeypatch.setattr(
        logins.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=json.dumps(box["doc"]), stderr=HIDDEN),
    )
    return box


def test_overview_names_the_tickets_that_stop_and_leaks_nothing(proj, run, new_ticket, tool):
    tid = new_ticket("Plan the newsletter")
    other = new_ticket("Idle one")
    runs.claim(proj, tid, "agent:scheduler", "claude", pid=os.getpid())
    rows = logins.overview(proj, NOW)
    assert [r["tool"] for r in rows] == ["claude"]
    r = rows[0]
    assert (r["state"], r["logged_in"], r["ends_at"]) == ("soon", True, "2026-11-17T21:24:57Z")
    assert [t["id"] for t in r["stops"]] == [tid] and other not in json.dumps(rows)
    assert r["stops"][0]["title"] == "Plan the newsletter"
    assert set(r) == {"tool", "label", "state", "logged_in", "ends_at", "chosen", "stops"}
    assert HIDDEN not in json.dumps(rows)


def test_overview_skips_tools_that_are_not_installed(proj, monkeypatch):
    monkeypatch.setattr(logins.shutil, "which", lambda b: None)
    assert logins.overview(proj, NOW) == []


def test_command_text_and_json(proj, run, new_ticket, tool):
    tid = new_ticket("Plan the newsletter")
    runs.claim(proj, tid, "agent:scheduler", "claude", pid=os.getpid())
    tool["doc"] = {"loggedIn": False, "token": HIDDEN}
    code, out, err = run("agents", "login")
    assert code == 0, err
    label = adapters.load("claude")["label"]
    assert out.startswith(f"{label} is logged out. The helper cannot go on with 1 ticket: ")
    assert "Plan the newsletter" in out
    assert HIDDEN not in out + err
    code, out, err = run("agents", "login", "--json")
    rows = json.loads(out)
    assert code == 0 and rows[0]["state"] == "out" and HIDDEN not in out + err


def test_command_with_no_tool(proj, run, monkeypatch):
    monkeypatch.setattr(logins.shutil, "which", lambda b: None)
    code, out, err = run("agents", "login")
    assert code == 0 and "No agent tool here" in out


@pytest.mark.parametrize(
    ("row", "want"),
    [
        (
            {"state": "ok", "ends_at": None, "stops": [], "chosen": True},
            "The Tool login is good; the tool tells no end date.",
        ),
        (
            {"state": "unknown", "ends_at": None, "stops": [], "chosen": True},
            "Tool did not say whether its login is good.",
        ),
        (
            {"state": "out", "ends_at": None, "stops": [], "chosen": True},
            "Tool is logged out. No new work starts until it is renewed.",
        ),
    ],
)
def test_login_line(row, want):
    assert cli_config.login_line({"label": "Tool", **row}) == want


def test_login_line_soon_names_the_time_and_the_tickets():
    stops = [{"key": "DM-1", "title": "A"}, {"key": "DM-2", "title": "B"}]
    row = {
        "label": "Tool",
        "state": "soon",
        "ends_at": "2030-01-05T10:00:00Z",
        "stops": stops,
        "chosen": False,
    }
    line = cli_config.login_line(row)
    assert line.startswith("The Tool login runs out ") and "5 Jan" in line
    assert line.endswith(" The helper then stops on 2 tickets: DM-1 A; DM-2 B.")


def test_login_line_ran_out_names_the_time():
    row = {"label": "Tool", "state": "out", "ends_at": "2020-01-05T10:00:00Z", "stops": [], "chosen": False}
    line = cli_config.login_line(row)
    assert line.startswith("The Tool login ran out ") and "5 Jan" in line and line.endswith(".")
