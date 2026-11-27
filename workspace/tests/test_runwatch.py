"""orch run list, screen and status: spot a stuck helper through orch alone (ORCH-25)."""

import json
import shutil
import subprocess
import sys
import time

import pytest

from orch import runs, runwatch, ticketindex, tickets

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
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
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


def _transcript(path, command, description=None, answered=False):
    use = {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": command}}
    if description:
        use["input"]["description"] = description
    rows = [
        {"type": "user", "message": {"role": "user", "content": "Merge it"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [use]}},
    ]
    if answered:
        result = {"type": "tool_result", "tool_use_id": "toolu_1"}
        rows.append({"type": "user", "message": {"content": [result]}})
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return {"notification_type": "permission_prompt", "message": "Claude needs your permission to use Bash",
            "transcript_path": str(path)}  # fmt: skip


def test_permission_prompt_shows_the_command_it_waits_on(
    proj, new_ticket, run, child, tmp_path, monkeypatch, collect_claude
):
    """ORCH-1808 (report r-1123-1145-ws): a helper waited for a Yes on a terminal permission prompt and the
    ticket page only said Needs you / Your OK on the screen. The waiting command now stands next to it."""
    from orch import runs_live

    tid = new_ticket()
    rec = _live(proj, tid, "working", child)
    rec["agent"] = "claude"
    runs._write(proj, rec)
    monkeypatch.setattr(runwatch, "_table", lambda: [])
    payload = _transcript(tmp_path / "s.jsonl", "gh pr merge 105 --squash", "Squash-merge PR 105")
    runs_live.event(proj, "attention", rec["run"], tid, None, payload)
    assert runs.read(proj, tid)["live"]["asks"] == "gh pr merge 105 --squash"
    data = json.loads(run("run", "status", tid, "--json")[1])
    assert data["helper"]["detail"] == "Your OK on the screen: gh pr merge 105 --squash"
    assert "waiting for your OK on the screen: gh pr merge 105 --squash" in run("run", "status", tid)[1]
    # a command the secret scan flags never goes on the page: the tool's plain words stand there instead
    token = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
    payload = _transcript(tmp_path / "s.jsonl", f"GH_TOKEN={token} gh pr merge 105", "Squash-merge PR 105")
    runs_live.event(proj, "attention", rec["run"], tid, None, payload)
    assert runs.read(proj, tid)["live"]["asks"] == "Squash-merge PR 105"
    # the call already has its result (or another tool, or another notice): only "Your OK on the screen"
    payload = _transcript(tmp_path / "s.jsonl", "gh pr merge 105", answered=True)
    runs_live.event(proj, "attention", rec["run"], tid, None, payload)
    assert "asks" not in runs.read(proj, tid)["live"]
    assert json.loads(run("run", "status", tid, "--json")[1])["helper"]["detail"] == "Your OK on the screen"
    runs_live.event(proj, "working", rec["run"], tid, None, None)  # answered: the line goes with the state
    assert "asks" not in runs.read(proj, tid)["live"]


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
    # The ticket index is a cache `run list` may bring up to date. Whether ticket B's own command already did
    # depends on the clock: history.sync_enabled keeps its "no" while the .orch folder times stay put, and
    # where file times move in 4 ms steps (orch edge, Linux 6.12) B can land in A's step. Refresh it first.
    ticketindex.rows(proj, include_hidden=True)
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


def test_list_with_no_runs(proj, run, monkeypatch):
    monkeypatch.setattr(runwatch, "_table", lambda: pytest.fail("no runs need a process table"))
    code, out, _ = run("run", "list")
    assert code == 0 and "No runs right now." in out


def test_list_shows_the_tickets_waiting_for_a_helper_place(proj, new_ticket, run):
    """ORCH-1026: during the server move the owner could not see which tickets waited for a slot."""
    from orch import runs_live

    a, b = new_ticket("A"), new_ticket("B")
    runs_live._queue_for_slot(proj, a, "human:tester", "Start when a slot is free.", "normal")
    runs_live._queue_for_slot(proj, b, "human:tester", "Start when a slot is free.", "high")
    code, out, _ = run("run", "list")
    assert code == 0 and "No runs right now." in out
    assert f"Waiting for a free helper place, in this order: {_key(proj, b)} (high), {_key(proj, a)}." in out
    line = json.loads(run("run", "list", "--json")[1])["line"]
    assert [(q["ticket"], q["priority"]) for q in line] == [(b, "high"), (a, "normal")]


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


@pytest.mark.parametrize(
    "sig, waits, idle, want",
    [
        ("none", [], None, None),
        ("ended", [], None, None),
        ("working", [], None, ("working", "Working", "")),
        ("working", [{"kind": "command", "label": "pytest", "what": "pytest (running 1 min)"}], None,
         ("working", "Working", "Running tests")),
        ("starting", [], None, ("starting", "Starting", "")),
        ("waiting", [{"kind": "person", "what": "an answer from the person", "ref": "q1"}], 60,
         ("you", "Needs you", "Your answer")),
        ("waiting", [{"kind": "person", "what": "the person's OK on the screen"}], None,
         ("you", "Needs you", "Your OK on the screen")),
        ("waiting", [{"kind": "person", "what": "x", "ref": "q1"}, {"kind": "person", "what": "y"}], None,
         ("you", "Needs you", "Your answer and your OK on the screen")),
        ("waiting", [{"kind": "command", "label": "pr-green.sh", "seconds": 360, "what": "x"}], 60,
         ("waiting", "On hold", "Running a script · 6 min")),
        ("waiting", [{"kind": "command", "label": "sleep", "seconds": 240, "what": "x"}], 60,
         ("waiting", "On hold", "Waiting · 4 min")),
        ("waiting", [{"kind": "command", "label": "the pull request checks", "seconds": 1080, "what": "x"}],
         60,
         ("waiting", "On hold", "Waiting for the pull request checks · 18 min")),
        ("idle", [], 300, ("idle", "Idle", "Nothing running for 5 min")),
        ("idle", [], runwatch.STUCK_MINUTES * 60, ("stuck", "Stuck", "Nothing running for 20 min")),
        ("stale", [], None, ("stuck", "Stuck", "No update for a while")),
    ],
)  # fmt: skip
def test_helper_state_is_one_word_per_signal(sig, waits, idle, want):
    got = runwatch.helper_state(sig, waits, idle)
    assert (got if got is None else (got["state"], got["word"], got["detail"])) == want


@pytest.mark.parametrize(
    "cmd, want",
    [
        ("orch check done t_1 c1 --note x", "Updating the ticket"),
        ("orch pull-requests queue add https://x/pull/1 --wait", "Waiting"),
        ("orch ref wait t_1 --merge", "Waiting for the pull request checks"),
        ("sleep 240", "Waiting"),
        ("node /tmp/release/walk.cjs --port 8790", "Running a script"),
        ("bash ~/x/pr-green.sh 12 repo", "Running a script"),
        ("env -i HOME=/tmp/t uv run python -m pytest -q -n 2 tests/test_x.py", "Running tests"),
        ("node --test tests/home.test.js", "Running tests"),
        ("cargo test", "Running tests"),
        ("cargo build --release", "Building"),
        ("git push -u origin fix/x", "Working on the code"),
        ("ls -la", "Running a command"),
        ("pytest", "Running tests"),
        ("the GitHub merge limit", "Waiting for the GitHub merge limit"),
        ("helper: read the logs", "Working with its own helper"),
        ("", "Running a command"),
    ],
)  # fmt: skip
def test_doing_says_plain_words_never_a_program_name(cmd, want):
    """Report r-1118-0544 (ORCH-407): Home said 'Running orch', 'Running sleep', 'Running walk.cjs'."""
    assert runwatch.doing(cmd) == want


def test_working_helper_with_several_commands_says_each_activity_once():
    waits = [{"kind": "command", "label": "orch", "doing": "Updating the ticket"},
             {"kind": "command", "label": "orch", "doing": "Updating the ticket"},
             {"kind": "command", "label": "pytest", "doing": "Running tests"}]  # fmt: skip
    assert runwatch.helper_state("working", waits, None)["detail"] == "Updating the ticket, Running tests"


def test_status_carries_the_helper_state_and_last_activity(proj, new_ticket, run, monkeypatch, child):
    tid = new_ticket()
    run("ask", tid, "Which colour?", "--option", "red", "--option", "blue", "--by", "agent:helper")
    _live(proj, tid, "idle", child)
    monkeypatch.setattr(runwatch, "_table", lambda: [])
    data = json.loads(run("run", "status", tid, "--json")[1])
    assert data["helper"] == {"state": "you", "word": "Needs you", "detail": "Your answer"}
    last = data["last_activity"]
    assert last["at"].endswith("Z") and last["seconds"] >= 0 and last["text"]
    rows = json.loads(run("run", "list", "--json")[1])["runs"]
    assert rows[0]["helper"]["word"] == "Needs you"  # orch run list says the same
    data = json.loads(run("run", "status", new_ticket("B"), "--json")[1])
    assert data["helper"] is None and data["last_activity"] is None


def test_a_helper_noted_at_the_usage_limit_shows_stopped_with_the_time_it_continues(
    proj, new_ticket, run, monkeypatch, child
):
    """ORCH-643 (report r-1118-1812-ws): a helper the watcher noted as stopped on the usage limit showed as
    working or waiting for an OK on Home. Now every page reads 'Stopped: usage limit' and when it goes on."""
    from orch import limitstop

    tid, other = new_ticket(), new_ticket("B")
    _live(proj, tid, "attention", child)
    monkeypatch.setattr(runwatch, "_table", lambda: [])
    at = time.time() + 3600
    limitstop.note(proj, tid, {"until": at, "text": "Usage limit reached"})
    data = json.loads(run("run", "status", tid, "--json")[1])
    assert data["helper"] == {
        "state": "limit",
        "word": "Stopped: usage limit",
        "detail": f"Continues at {limitstop.clock(at + limitstop.GRACE)}",
    }
    rows = json.loads(run("run", "list", "--json")[1])["runs"]
    assert rows[0]["helper"]["word"] == "Stopped: usage limit"
    # the reset passed but the watcher has not started it yet; a ticket that is not noted keeps its state
    assert runwatch.limit_state(proj, tid, now=at + limitstop.GRACE + 1)["detail"] == "Continues shortly"
    # a helper that works again after the note (a person's prompt) is no longer shown as stopped
    rec = runs.read(proj, tid)
    working = {**rec, "live": {"state": "working", "since": _since(-5)}}
    assert runwatch.limit_state(proj, tid, working) is None
    # still "working" from before the note (the tool ended the turn without its hook, ORCH-642): stopped
    assert (
        runwatch.limit_state(proj, tid, {**rec, "live": {"state": "working", "since": _since(600)}})["state"]
        == "limit"
    )
    assert runwatch.limit_state(proj, other) is None
    # no helper runs: no state at all, also when the ticket is still noted
    assert json.loads(run("run", "status", other, "--json")[1])["helper"] is None
    limitstop.forget(proj, [tid])
    assert json.loads(run("run", "status", tid, "--json")[1])["helper"]["state"] == "you"


def test_last_activity_skips_settings_writes(monkeypatch):
    from orch import history

    rows = [
        {"at": "2026-11-18T08:00:00Z", "by": "agent:helper", "text": "Check c1 done"},
        {"at": "2026-11-18T09:00:00Z", "by": "agent:automation", "text": "Set ext.automation"},
        {"at": "2026-11-18T09:01:00Z", "by": "agent:focus", "text": "Removed ext.focus.mode"},
    ]
    monkeypatch.setattr(history, "lines", lambda root, ticket: rows)
    assert runwatch.last_activity(None, {})["text"] == "Check c1 done"
    monkeypatch.setattr(history, "lines", lambda root, ticket: rows[1:])
    assert runwatch.last_activity(None, {}) is None


def test_label_names_the_pull_request_wait_in_plain_words():
    assert runwatch.label("orch ref wait ORCH-46 --merge") == "the pull request checks"
    assert runwatch.label("/opt/bin/orch github wait merge --for a/b#1") == "the GitHub merge limit"
    assert runwatch.label("orch ticket show x") == "orch"


ORCH = "/u/.local/share/uv/tools/orch-workspace/bin/python /u/.local/bin/orch"
SHELL = "/bin/zsh -c source /h/.claude/shell-snapshots/s.sh && eval 'x'"


@pytest.mark.parametrize(
    "cmd,want",
    [
        (f"{ORCH} ref wait t_abc --merge", True),
        (f"{ORCH} github wait merge --for owner/repo#12", True),
        ("python -m orch --json ref wait ORCH-1", True),
        (f"{ORCH} ref add t_abc https://x", False),
        (f"{ORCH} run start t_abc", False),
        ("uv run python -m pytest -q", False),
        ("bash /x/pr-green.sh 12 owner/repo", False),  # a hand-made script may do anything: it counts
    ],
)
def test_is_check_wait_knows_only_orchs_own_check_waits(cmd, want):
    assert runwatch.is_check_wait(cmd) is want


def _waiter_table(agent, *inner):
    """An agent with one tool shell per inner command (pids from agent*10)."""
    rows = [
        (agent, 1, 900, "claude --resume abc"),
        (agent * 10 + 99, agent, 800, "npm exec @playwright/mcp@latest"),
    ]
    for i, cmd in enumerate(inner):
        sh = agent * 10 + i
        rows += [(sh, agent, 300, SHELL), (agent * 100 + i, sh, 299, cmd)]
    return rows


def test_only_waits_for_checks_needs_every_command_to_be_a_check_wait():
    wait = f"{ORCH} ref wait t_abc --merge"
    assert runwatch.only_waits_for_checks(7, _waiter_table(7, wait)) is True
    assert runwatch.only_waits_for_checks(7, _waiter_table(7, wait, "uv run pytest")) is False
    assert runwatch.only_waits_for_checks(7, _waiter_table(7)) is False  # nothing running: plain idle
    assert runwatch.only_waits_for_checks(7, TABLE) is False


def test_helpers_that_only_wait_for_checks_leave_their_slot_free(proj, new_ticket, monkeypatch):
    """ORCH-148: 7 of 9 slots were held by helpers idle at their prompt while `orch ref wait` ran for them,
    with tickets in line and the machine nearly idle. Such a helper no longer counts toward the limit; a
    working one, an idle one with nothing running and one running real work still do,
    under the hard ceiling."""
    from orch import config, runs_live

    wait = f"{ORCH} ref wait t_abc --merge"
    table = (
        _waiter_table(11, wait)  # idle, only waits for checks: free
        + _waiter_table(12, f"{ORCH} github wait merge --for o/r#1")  # idle, waits for the write limit: free
        + _waiter_table(13, wait)  # working while a wait runs: counts
        + _waiter_table(14, wait, "uv run pytest")  # idle with tests running too: counts
        + _waiter_table(15)  # idle, nothing running: counts
    )
    monkeypatch.setattr(runwatch, "_table", lambda: table)
    procs_ = [subprocess.Popen(["sleep", "120"]) for _ in range(5)]
    try:
        states = {11: "idle", 12: "idle", 13: "working", 14: "idle", 15: "idle"}
        ids = {}
        for agent, state in states.items():
            tid = new_ticket(f"T{agent}")
            ids[agent] = tid
            rec = _live(proj, tid, state, procs_[agent - 11].pid, agent_pid=agent)
            rec["run"] = f"r_test{agent:04d}"
            runs._write(proj, rec)
        counted = {r["ticket"] for r in runs_live.live_alive(proj)}
        assert counted == {ids[13], ids[14], ids[15]}
        config.set_live_max(proj, "4")
        assert runs_live._full(proj) is None  # 3 of 4 slots used: the next ticket starts instead of waiting
        config.set_live_max(proj, "3")
        assert runs_live._full(proj) == 3
        config.set_live_max(proj, "2")
        assert runs_live._full(proj) == 2
        monkeypatch.setattr(runs_live, "HARD_EXTRA", 0)  # the ceiling still holds waiters: 5 open >= 4 + 0
        config.set_live_max(proj, "4")
        assert runs_live._full(proj) == 4
    finally:
        for p in procs_:
            p.kill()
            p.wait()


def test_the_idle_close_never_kills_a_wait_for_checks(proj, new_ticket, monkeypatch):
    """ORCH-221: six helpers idle at their prompt while `orch ref wait --merge` ran for them in the
    background (CI took 30-50 min plus re-runs) were closed after the idle hour; the close killed the wait,
    so their green pull requests stayed unmerged and nobody was told. A session running a wait on checks
    stays open; one with nothing running, or only real work, still closes after the limit."""
    from orch import runs_live

    wait = f"{ORCH} ref wait t_abc --merge"
    table = (
        _waiter_table(21, wait)  # idle, only waits for checks: stays
        + _waiter_table(22, wait, "uv run pytest")  # a wait and tests: stays (the wait would die too)
        + _waiter_table(23, f"{ORCH} github wait merge --for o/r#1")  # write-limit wait before a merge: stays
        + _waiter_table(24)  # idle, nothing running: closes
        + _waiter_table(25, "uv run pytest")  # no wait on checks: closes as before
    )
    monkeypatch.setattr(runwatch, "_table", lambda: table)
    monkeypatch.setattr(runs_live, "_close", lambda root, rec, interrupt: None)
    monkeypatch.setattr(runs_live, "start_waiting", lambda root: None)
    monkeypatch.setenv("ORCH_RUN_IDLE_SECONDS", "3600")
    assert runwatch.runs_check_wait(22, table) is True
    assert runwatch.runs_check_wait(25, table) is False
    procs_ = [subprocess.Popen(["sleep", "120"]) for _ in range(5)]
    try:
        ids = {}
        for agent in range(21, 26):
            tid = new_ticket(f"T{agent}")
            ids[agent] = tid
            rec = _live(proj, tid, "idle", procs_[agent - 21].pid, since=_since(2 * 3600), agent_pid=agent)
            rec["run"] = f"r_test{agent:04d}"
            runs._write(proj, rec)
        assert sorted(runs_live.cleanup(proj)) == sorted([ids[24], ids[25]])
    finally:
        for p in procs_:
            p.kill()
            p.wait()


def _fake_chain(gone=()):
    """A tmux that runs a chain of display-message / capture-pane like the real one: it stops at the first
    session that is gone (ORCH-359)."""
    calls = []

    def fake(root, *args, **kw):
        calls.append(args)
        out, rc, cmds, cur = [], 0, [], []
        for a in args:
            if a == ";":
                cmds.append(cur)
                cur = []
            else:
                cur.append(a)
        cmds.append(cur)
        for c in cmds:
            if c[0] == "display-message":
                out.append(c[-1])
            elif c[0] == "capture-pane":
                tid = c[c.index("-t") + 1].strip("=:")
                if tid in gone:
                    rc = 1
                    break
                out.append(f"\x1b[32m{tid} first\nlast of {tid}  \n\n")
            else:
                raise AssertionError(f"not read-only: {c}")

        class R:
            returncode, stdout, stderr = rc, "\n".join(out) + "\n", ""

        return R()

    return fake, calls


def _use_fake_tmux(monkeypatch, fake):
    """Stand in for tmux, also where tails() looks for it: CI's macOS machines have no tmux at all."""
    from orch import runs_live

    which = shutil.which

    def fake_which(name, *a, **kw):
        return "/usr/bin/tmux" if name == "tmux" else which(name, *a, **kw)

    monkeypatch.setattr(runwatch.shutil, "which", fake_which)
    monkeypatch.setattr(runs_live, "tmux", fake)


def test_tails_reads_every_session_in_one_tmux_call(proj, new_ticket, monkeypatch, child):
    ids = [new_ticket() for _ in range(3)]
    for t in ids:
        _live(proj, t, "working", child)
    fake, calls = _fake_chain()
    _use_fake_tmux(monkeypatch, fake)
    got = runwatch.tails(proj, ids, 1)
    assert len(calls) == 1
    assert got == {t: {"lines": [f"last of {t}"]} for t in ids}


def test_tails_leaves_out_a_gone_session_and_reads_the_rest(proj, new_ticket, monkeypatch, child):
    a, b, c = (new_ticket() for _ in range(3))
    for t in (a, b, c):
        _live(proj, t, "working", child)
    none = new_ticket()  # no run: never asked
    fake, calls = _fake_chain(gone={b})
    _use_fake_tmux(monkeypatch, fake)
    got = runwatch.tails(proj, [a, b, none, c], 5)
    assert set(got) == {a, c} and got[c]["lines"] == [f"{c} first", f"last of {c}"]
    assert len(calls) == 2 and none not in " ".join(calls[0])


def _oneshot(proj, tid, pid, log_text=None):
    """A one-step run with its log (ORCH-1797: Windows has no live backend, every helper runs like this)."""
    rec = {
        **_live(proj, tid, "working", pid),
        "mode": "oneshot",
        "log": f".orch/run/logs/{tid}-r_test1234.log",
    }
    rec.pop("live")
    runs._write(proj, rec)
    if log_text is not None:
        p = proj / rec["log"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(log_text.encode("utf-8"))
    return rec


def test_a_one_step_run_gives_its_log_lines_where_a_live_one_gives_its_screen(
    proj, new_ticket, monkeypatch, child
):
    a, b, none = new_ticket(), new_ticket(), new_ticket()
    _live(proj, a, "working", child)
    secret = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    _oneshot(
        proj,
        b,
        child,
        "Reading the ticket\r\n\x1b[32mRunning pytest\x1b[0m\r\n\r\ntoken "
        + secret
        + "\r\nDone, 3 passed\r\n\r\n",
    )
    _oneshot(proj, none, child)  # no log written yet: no lines, never an error
    fake, calls = _fake_chain()
    _use_fake_tmux(monkeypatch, fake)
    got = runwatch.tails(proj, [a, b, none], 3)
    assert got[a] == {"lines": [f"{a} first", f"last of {a}"]}
    assert got[b]["log"] is True and got[b]["lines"][0] == "" and got[b]["lines"][2] == "Done, 3 passed"
    assert secret not in " ".join(got[b]["lines"]) and got[b]["lines"][1].startswith("token ")
    assert got[none] == {"lines": [], "log": True}
    assert len(calls) == 1 and b not in " ".join(
        calls[0]
    )  # the log is read from its file, never through tmux
    one = runwatch.screen(proj, b, 2)  # the one-ticket answer the dashboard reads for a single session
    assert one["lines"][-1] == "Done, 3 passed" and one["log"].endswith(".log")


def test_a_log_outside_the_run_logs_is_never_read(proj, new_ticket, child):
    tid = new_ticket()
    rec = _oneshot(proj, tid, child)
    (proj / "notes.txt").write_text("private\n")
    assert runwatch.log_tail(proj, {**rec, "log": "notes.txt"}) == []
    assert runwatch.log_tail(proj, {**rec, "log": ".orch/run/logs/../../../notes.txt"}) == []


def test_run_screen_several_tickets_cli_and_in_process(proj, new_ticket, run, monkeypatch, child):
    from orch import reads

    a, b = new_ticket(), new_ticket()
    for t in (a, b):
        _live(proj, t, "working", child)
    fake, _ = _fake_chain()
    _use_fake_tmux(monkeypatch, fake)
    code, out, err = run("run", "screen", _key(proj, a), b, "--lines", "1", "--json")
    assert code == 0, err
    want = {"screens": {a: {"lines": [f"last of {a}"]}, b: {"lines": [f"last of {b}"]}}}
    assert json.loads(out) == want
    assert reads.answer(proj, ["run", "screen", a, b, "--lines", "1", "--json"]) == want


def test_rows_drop_the_prompt_frame():
    rule = "\u2500" * 40
    text = "\n".join(["did the work", "ran 3 tests", "", rule, "\u276f ", rule, "  ? for shortcuts", ""])
    rows, hint = runwatch._rows(text, 40)
    assert rows == ["did the work", "ran 3 tests"]
    assert hint is None


def test_rows_drop_the_tools_right_aligned_update_notice():
    # report r-1127-0540-ws-2: Live showed the notice with its long run of spaces
    pad = " " * 60
    text = "\n".join(
        [
            "did the work",
            pad + "Update installed \u00b7 /restart to apply",
            "ran 3 tests" + pad + "Update installed",
        ]
    )
    rows, _ = runwatch._rows(text, 40)
    assert rows == ["did the work", "ran 3 tests"]


def test_rows_keep_a_line_that_only_mentions_an_update():
    rows, _ = runwatch._rows("Update installed, tests pass", 40)
    assert rows == ["Update installed, tests pass"]


def test_rows_keep_typed_prompt_text():
    rule = "\u2500" * 40
    rows, _ = runwatch._rows("\n".join(["work", rule, "\u276f fix it", rule]), 40)
    assert rows == ["work", "\u276f fix it"]


def test_rows_drop_status_rows_under_the_prompt_box():
    rule = "\u2500" * 40
    text = "\n".join(
        [
            "did the work",
            "",
            "",
            "",
            rule,
            "\u276f ",
            rule,
            "  Opus 5.5 \u00b7 week 21%",
            "  \u23f5\u23f5 auto mode on",
        ]
    )
    rows, _ = runwatch._rows(text, 8)
    assert rows == ["did the work"]


def test_rows_keep_rows_after_a_lone_rule():
    rule = "\u2500" * 40
    rows, _ = runwatch._rows("\n".join(["step one", rule, "step two", "", "", "step three"]), 8)
    assert rows == ["step one", "step two", "", "step three"]


def test_rows_drop_a_fresh_start_banner_notice_and_tips():
    # ORCH-707: what a new helper's pane holds right after start (report r-1119-0537)
    rule = "─" * 40
    text = "\n".join(
        [
            " ▐▛███▜▌   Tool v2.1.328",
            "▝▜█████▛▘  Opus 5.5 · API",
            "  ▘▘ ▝▝    /Users/someone/ws/Walk",
            "",
            "  ⎿  tmux focus-events off · add set -g focus-events on to ~/.tmux.conf",
            "",
            "❯ Your task for orch ticket t_aeztli is ready. Read it with: orch run input t_aeztli",
            "",
            "✻ Cerebrating…",
            "",
            "❯ New input on orch ticket t_aeztli. Read it with: orch run input t_aeztli",
            "  ※ Tip: Use /memory to keep notes",
            rule,
            "❯ ",
            rule,
        ]
    )
    rows, _ = runwatch._rows(text, 40)
    assert rows == ["✻ Cerebrating…"]


def test_rows_drop_a_boxed_banner_with_a_version():
    text = "\n".join(
        [
            "╭" + "─" * 20 + "╮",
            "│ >_ Tool (v0.9.1) │",
            "│ dir: /Users/someone │",
            "╰" + "─" * 20 + "╯",
            "",
            "working",
        ]
    )
    rows, _ = runwatch._rows(text, 40)
    assert rows == ["working"]


def test_rows_keep_work_that_looks_a_little_like_frame():
    rows = [
        "\u2502 pkg \u2502 1.2.3 \u2502",
        "\u2588\u2588\u2588\u2588\u2591\u2591 60.5%",
        "edited tmux.conf: set -g focus-events on",
    ]
    assert runwatch._rows("\n".join(rows), 40)[0] == rows


def test_rows_keep_a_progress_bar_and_typed_notice_like_text():
    rows, _ = runwatch._rows("\n".join(["████░░ 60%", "❯ Your task for orch ticket is ready"]), 40)
    assert rows == ["████░░ 60%", "❯ Your task for orch ticket is ready"]


def test_time_wait_reads_waiting_until_and_a_past_time_is_no_reason():
    future = {"kind": "time", "what": "until today 07:50", "ref": "2999-01-01T07:50:00Z"}
    past = {"kind": "time", "what": "until today 02:15", "ref": "2000-01-01T02:15:00Z"}
    assert runwatch.helper_state("waiting", [future], None)["detail"] == "Waiting until today 07:50"
    assert runwatch.helper_state("waiting", [past], None)["detail"] == ""
    other = {"kind": "ticket", "what": "ticket ORCH-9"}
    assert runwatch.helper_state("waiting", [other], None)["detail"] == "Waiting for ticket ORCH-9"
