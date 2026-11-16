"""orch run list, screen and status: spot a stuck helper through orch alone (ORCH-25)."""

import json
import subprocess
import time

import pytest

from orch import runs, runwatch, tickets

AGENT = 100
TABLE = [  # (pid, ppid, seconds, command): a live agent with MCP servers and one tool shell watching CI
    (AGENT, 1, 900, "claude --resume abc"),
    (201, AGENT, 880, "npm exec @playwright/mcp@latest"),
    (202, AGENT, 30, "caffeinate -i -t 300"),
    (200, AGENT, 400, "/bin/zsh -c source /h/.claude/shell-snapshots/s.sh && eval 'NO_CHECKS_SECS=900 x'"),
    (300, 200, 399, "bash /Users/x/orch-dev/scripts/pr-green.sh 972 owner/repo"),
    (400, 300, 5, "sleep 30"),
    (501, 500, 3, "head -5"),
    (500, AGENT, 3, "/bin/zsh -c eval 'uv run pytest | head -5'"),
    (499, 500, 3, "uv run pytest"),
]


def _files(proj):
    """Every file and when it changed, except the debug log every command appends to."""
    return {p: p.stat().st_mtime_ns for p in proj.rglob("*") if p.is_file() and "diag" not in p.parts}


def _key(proj, tid):
    return tickets.load(proj, tid)["key"]


@pytest.fixture
def child():
    """A throwaway process to stand for the run's wrapper: never this test process, which orch's idle cleanup
    may stop (a session idle over the limit is closed with its process tree)."""
    p = subprocess.Popen(["sleep", "120"])
    yield p.pid
    p.kill()
    p.wait()


def _since(seconds_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago))


def _live(proj, tid, state, pid, since=None, agent_pid=None):
    rec = {
        "schema": "orch.run/1",
        "ticket": tid,
        "run": "r_test1234",
        "by": "human:tester",
        "agent": "generic",
        "mode": "live",
        "pid": pid,  # alive
        "started_at": _since(1200),
        "renewed_at": _since(1200),
        "live": {"state": state, "since": since or _since(300)},
    }
    if agent_pid:
        rec["agent_pid"] = agent_pid
    runs._write(proj, rec)
    return rec


@pytest.mark.parametrize(
    "cmd,want",
    [
        ("bash /Users/x/scripts/pr-green.sh 972 owner/repo", "pr-green.sh"),
        ("NO_CHECKS_SECS=900 /Users/x/pr-green.sh 1", "pr-green.sh"),
        ("uv run python -m pytest -q tests/x.py", "pytest"),
        ("/opt/homebrew/bin/gh pr checks 12 --watch", "gh"),
        ("node --test tests/a.test.js", "tests"),  # a path, never the arguments in full
    ],
)
def test_label_names_the_program_never_its_arguments(cmd, want):
    got = runwatch.label(cmd)
    assert (got == want) if want != "tests" else ("/" not in got and "--" not in got)


def test_tool_commands_see_the_tool_shell_not_mcp_servers():
    got = runwatch.tool_commands(AGENT, TABLE)
    assert [(c["label"], c["seconds"]) for c in got] == [("pr-green.sh", 400), ("pytest", 3)]
    assert runwatch.tool_commands(None, TABLE) == [] and runwatch.tool_commands(999, TABLE) == []


def test_waiting_on_ci_is_not_idle(proj, new_ticket, child):
    tid = new_ticket()
    rec = _live(proj, tid, "idle", child, agent_pid=AGENT)
    waits = runwatch.waiting_on(proj, rec, tickets.load(proj, tid), TABLE)
    assert [w["kind"] for w in waits] == ["command", "command"] and waits[0]["label"] == "pr-green.sh"
    assert runwatch.signal(rec, waits) == "waiting"
    assert runwatch.signal(rec, []) == "idle"  # at its prompt with nothing running: the one that may be stuck
    rec["live"]["state"] = "working"
    assert runwatch.signal(rec, waits) == "working"


def test_waiting_on_a_person_and_on_the_screen(proj, new_ticket, run, child):
    tid = new_ticket()
    run("ask", tid, "Which colour?", "--option", "red", "--option", "blue", "--by", "agent:helper")
    rec = _live(proj, tid, "attention", child)
    whats = [w["what"] for w in runwatch.waiting_on(proj, rec, tickets.load(proj, tid), [])]
    assert whats == ["an answer from the person", "the person's OK on the screen"]


def test_status_takes_keys_alone_and_in_a_list(proj, new_ticket, run):
    a, b = new_ticket("A"), new_ticket("B")
    ka, kb = _key(proj, a), _key(proj, b)
    code, out, err = run("run", "status", ka.lower())
    assert code == 0, err
    code, out, err = run("run", "status", ka, kb, "--json")
    assert code == 0, err
    assert set(json.loads(out)["runs"]) == {a, b}


def test_status_shows_idle_since_and_waiting_on(proj, new_ticket, run, monkeypatch, child):
    tid = new_ticket()
    _live(proj, tid, "idle", child, agent_pid=AGENT)
    monkeypatch.setattr(runwatch, "_table", lambda: TABLE)
    code, out, err = run("run", "status", _key(proj, tid), "--json")
    data = json.loads(out)
    assert code == 0 and data["signal"] == "waiting" and data["idle_since"].endswith("Z")
    assert data["waiting_on"][0]["label"] == "pr-green.sh" and data["idle_seconds"] >= 0
    code, out, _ = run("run", "status", tid)
    assert "Waiting on: pr-green.sh (running 6 min)" in out
    monkeypatch.setattr(runwatch, "_table", lambda: [])
    code, out, _ = run("run", "status", tid)
    assert "Idle at its prompt for 5 min" in out and "nothing running" in out
    data = json.loads(run("run", "status", tid, "--json")[1])
    assert data["signal"] == "idle" and data["waiting_on"] == []


def test_status_without_a_run_says_none(proj, new_ticket, run):
    tid = new_ticket()
    data = json.loads(run("run", "status", tid, "--json")[1])
    assert data["signal"] == "none" and data["idle_since"] is None


def test_list_shows_every_run_without_writing(proj, new_ticket, run, monkeypatch, child):
    a, b = new_ticket("A"), new_ticket("B")
    _live(proj, a, "idle", child, agent_pid=AGENT)
    monkeypatch.setattr(runwatch, "_table", lambda: TABLE)
    before = _files(proj)
    code, out, err = run("run", "list", "--json")
    assert code == 0, err
    rows = json.loads(out)["runs"]
    assert [r["ticket"] for r in rows] == [a] and rows[0]["key"] == _key(proj, a)
    assert rows[0]["run"] == "r_test1234" and rows[0]["signal"] == "waiting" and rows[0]["age_seconds"] > 0
    after = _files(proj)
    assert after == before  # read-only
    code, out, _ = run("run", "list")
    assert out.splitlines()[0].split()[:5] == ["TICKET", "RUN", "MODEL", "AGE", "SIGNAL"]
    assert _key(proj, a) in out and "pr-green.sh" in out and _key(proj, b) not in out


def test_list_with_no_runs(proj, run):
    code, out, _ = run("run", "list")
    assert code == 0 and "No runs right now." in out


def test_screen_refuses_without_a_live_session(proj, new_ticket, run):
    tid = new_ticket()
    code, _, err = run("run", "screen", _key(proj, tid))
    assert code == 2 and "No live session on" in err and "not built yet" not in err


def test_screen_returns_the_last_lines_read_only(proj, new_ticket, run, monkeypatch, child):
    from orch import runs_live

    tid = new_ticket()
    _live(proj, tid, "working", child)
    calls = []

    class R:
        returncode = 0
        stdout = "one\n\x1b[31mtwo\nthree   \n\n\n"
        stderr = ""

    def fake_tmux(root, *args, **kw):
        calls.append(args)
        return R()

    monkeypatch.setattr(runs_live, "session_exists", lambda root, t: True)
    monkeypatch.setattr(runs_live, "tmux", fake_tmux)
    code, out, err = run("run", "screen", _key(proj, tid), "--lines", "2", "--json")
    assert code == 0, err
    data = json.loads(out)
    assert data["lines"] == ["two", "three"] and data["signal"] == "working"
    assert all(a[0] == "capture-pane" for a in calls)  # nothing is typed into the session
