"""Earlier chat sessions: list and read the tool's saved conversation (Claude, Codex)."""

import json

from orch import session_history

SID = "0364ced3-ceac-463a-a68d-53a565d7e9df"
CODEX = "01a177e2-18c5-7bd0-91c0-2ac95c9f348e"


def _w(p, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _env(tmp_path):
    claude = tmp_path / "c"
    codex = tmp_path / "x"
    _w(
        claude / "projects" / "-Users-a-ws" / f"{SID}.jsonl",
        [
            {"type": "mode"},
            {"type": "user", "timestamp": "t1", "message": {"role": "user", "content": "Fix the login"}},
            {"type": "user", "message": {"content": "<system-reminder>x</system-reminder>"}},
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Done."}, {"type": "tool_use"}]},
            },
            {"type": "assistant", "isSidechain": True, "message": {"content": "hidden"}},
        ],
    )

    def msg(role, kind, text):
        return {
            "type": "response_item",
            "payload": {"type": "message", "role": role, "content": [{"type": kind, "text": text}]},
        }

    _w(
        codex / "sessions" / "2026" / "10" / "26" / f"rollout-2026-10-26T12-04-28-{CODEX}.jsonl",
        [
            {"type": "session_meta", "payload": {}},
            msg("user", "input_text", "Add tests"),
            msg("assistant", "output_text", "Added."),
        ],
    )
    return {"CLAUDE_CONFIG_DIR": str(claude), "CODEX_HOME": str(codex), "HOME": str(tmp_path)}


def test_claude_turns(tmp_path):
    h = session_history.read("claude", SID, _env(tmp_path))
    assert h["found"] and [t["role"] for t in h["turns"]] == ["user", "helper"]
    assert h["turns"][0]["text"] == "Fix the login" and h["turns"][1]["text"] == "Done."


def test_codex_turns(tmp_path):
    h = session_history.read("codex", CODEX, _env(tmp_path))
    assert [t["text"] for t in h["turns"]] == ["Add tests", "Added."]


def test_missing_and_bad_ids(tmp_path):
    env = _env(tmp_path)
    assert session_history.read("claude", "nope", env)["found"] is False
    assert session_history.read("claude", "../../etc/passwd", env)["found"] is False
    assert session_history.read("generic", SID, env)["found"] is False


def test_sessions_list_newest_first(tmp_path):
    t = {
        "sessions": [
            {"agent": "claude", "id": SID, "host": "h", "last_used": "2026-11-01"},
            {"agent": "codex", "id": CODEX, "host": "h", "last_used": "2026-11-05"},
            {"agent": "claude", "id": "gone-1", "host": "h", "last_used": "2026-11-09"},
        ]
    }
    rows = session_history.sessions(t, _env(tmp_path))
    assert [r["id"] for r in rows] == ["gone-1", CODEX, SID]
    assert rows[0]["readable"] is False and rows[2]["title"] == "Fix the login"


def test_record_session_keeps_and_continue_switches(proj, run, new_ticket, tmp_path, monkeypatch):
    from orch import runs, tickets

    root = tmp_path
    tid = new_ticket()
    for sid in ("s-one", "s-two"):
        tickets.record_session(root, tid, "claude", sid, runs.host())
    s = tickets.load(root, tid)["sessions"][0]
    assert s["id"] == "s-two" and [e["id"] for e in s["earlier"]] == ["s-one"]
    code, out, _ = run("run", "history", tid, "--json")
    assert code == 0 and [r["id"] for r in json.loads(out)["sessions"]] == ["s-two", "s-one"]
    # a helper may not pick; a person may, but only a conversation that is on this computer
    code, _, err = run("run", "history", tid, "--session", "s-one", "--continue", "--by", "agent:x")
    assert code == 2
    code, _, err = run("run", "history", tid, "--session", "s-one", "--continue", "--by", "human:p")
    assert code == 2 and "not on this computer" in err
    _w(tmp_path / "cfg" / "projects" / "-p" / "s-one.jsonl", [{"type": "mode"}])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    code, out, err = run("run", "history", tid, "--session", "s-one", "--continue", "--by", "human:p")
    assert code == 0, err
    s = tickets.load(root, tid)["sessions"][0]
    assert s["id"] == "s-one" and [e["id"] for e in s["earlier"]] == ["s-two"]


def test_a_ticket_keeps_its_last_ten_sessions(proj, new_ticket, tmp_path):
    from orch import runs, tickets

    tid = new_ticket()
    for i in range(14):
        tickets.record_session(tmp_path, tid, "claude", f"s-{i:02d}", runs.host())
    s = tickets.load(tmp_path, tid)["sessions"][0]
    kept = [s["id"]] + [e["id"] for e in s["earlier"]]
    assert kept == [f"s-{i:02d}" for i in range(13, 3, -1)]  # the newest 10, newest first
    assert tickets.SESSIONS_KEPT == 10


def test_ten_counts_every_tool_and_machine_and_keeps_those_in_use(proj, new_ticket, tmp_path, monkeypatch):
    from orch import tickets

    tid = new_ticket()
    clock = iter(f"2026-11-17T10:{m:02d}:00Z" for m in range(60))
    monkeypatch.setattr(tickets, "now", lambda: next(clock))
    for i in range(6):
        tickets.record_session(tmp_path, tid, "claude", f"c-{i}", "h1")
        tickets.record_session(tmp_path, tid, "codex", f"x-{i}", "h1")
    tickets.record_session(tmp_path, tid, "claude", "other-host", "h2")
    ss = tickets.load(tmp_path, tid)["sessions"]
    ids = [x["id"] for s in ss for x in [s, *(s.get("earlier") or [])]]
    assert len(ids) == 10
    assert {"c-5", "x-5", "other-host"} <= set(ids)  # the ones in use always stay
    assert not {"c-0", "x-0", "c-1"} & set(ids)  # the oldest went first, whatever the tool


def test_reopen_is_for_a_person_and_a_conversation_on_this_computer(proj, new_ticket, tmp_path, monkeypatch):
    from orch import runs, session_history, tickets
    from orch.errors import Refused

    tid = new_ticket()
    for sid in ("s-one", "s-two"):
        tickets.record_session(tmp_path, tid, "claude", sid, runs.host())
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    for bad, why in (
        (("s-one", "agent:x"), "Only a person"),
        (("../x", "human:p"), "not a session id"),
        (("s-nine", "human:p"), "does not belong"),
        (("s-one", "human:p"), "not on this computer"),
    ):
        try:
            session_history.reopen(tmp_path, tid, bad[0], bad[1])
        except Refused as e:
            assert why in str(e)
        else:
            raise AssertionError(bad)
    _w(tmp_path / "cfg" / "projects" / "-p" / "s-one.jsonl", [{"type": "mode"}])
    rows = {r["id"]: r for r in session_history.sessions(tickets.load(tmp_path, tid), root=tmp_path)}
    assert rows["s-one"]["reopenable"] is True and rows["s-two"]["reopenable"] is False  # in use
    rec = session_history.reopen(tmp_path, tid, "s-one", "human:p")
    assert rec["agent"] == "claude"
    assert tickets.sessions_for(tmp_path, tid, tickets.load(tmp_path, tid), "claude", runs.host()) == "s-one"
    monkeypatch.setattr(runs, "read", lambda root, t: {"pid": 1, "run": "r"})
    monkeypatch.setattr(runs, "state", lambda rec: "alive")
    try:
        session_history.reopen(tmp_path, tid, "s-two", "human:p")
    except Refused as e:
        assert "Stop it first" in str(e)
    else:
        raise AssertionError("a working helper must be stopped first")


def test_a_helper_cannot_pass_for_a_person_to_pick_a_conversation(
    proj, run, new_ticket, tmp_path, monkeypatch
):
    """#1430: --by human:<x> from inside a helper (its tool's variables or ORCH_RUN) is still the helper."""
    from orch import runs, session_history, tickets
    from orch.errors import Refused

    tid = new_ticket()
    for sid in ("s-one", "s-two"):
        tickets.record_session(tmp_path, tid, "claude", sid, runs.host())
    _w(tmp_path / "cfg" / "projects" / "-p" / "s-one.jsonl", [{"type": "mode"}])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(runs, "start", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no start")))
    for var, val in (("ORCH_AGENT", "claude"), ("ORCH_RUN", "r_helper01")):
        monkeypatch.setenv(var, val)
        for argv in (
            ("run", "start", tid, "--session", "s-one", "--by", "human:p"),
            ("run", "history", tid, "--session", "s-one", "--continue", "--by", "human:p"),
        ):
            code, _, err = run(*argv)
            assert code == 2 and "Only a person" in err, (var, argv, err)
        try:
            session_history.reopen(tmp_path, tid, "s-one", "human:p")
        except Refused as e:
            assert "Only a person" in str(e)
        else:
            raise AssertionError(var)
        monkeypatch.delenv(var)
    assert tickets.sessions_for(tmp_path, tid, tickets.load(tmp_path, tid), "claude", runs.host()) == "s-two"


def test_start_with_session_continues_that_conversation(proj, run, new_ticket, tmp_path, monkeypatch):
    from orch import runs, tickets

    tid = new_ticket()
    for sid in ("s-one", "s-two"):
        tickets.record_session(tmp_path, tid, "claude", sid, runs.host())
    _w(tmp_path / "cfg" / "projects" / "-p" / "s-one.jsonl", [{"type": "mode"}])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    seen = {}

    def fake_start(root, t, by, **kw):
        seen.update(kw, sid=tickets.sessions_for(root, t, tickets.load(root, t), kw["agent"], runs.host()))
        done = {"notes": [], "resumed": True, "mode": "oneshot", "run": "r1", "log": "l"}
        return {**done, "agent": kw["agent"]}

    monkeypatch.setattr(runs, "start", fake_start)
    code, _, err = run("run", "start", tid, "--session", "s-one", "--fresh", "--by", "human:p")
    assert code == 2 and "Pick one" in err and not seen
    code, _, err = run("run", "start", tid, "--session", "s-one", "--agent", "codex", "--by", "human:p")
    assert code == 2 and "only be continued there" in err and not seen
    code, _, err = run("run", "start", tid, "--session", "s-one", "--by", "agent:x")
    assert code == 2 and not seen
    code, out, err = run("run", "start", tid, "--session", "s-one", "--by", "human:p", "--json")
    assert code == 0, err
    assert seen["agent"] == "claude" and seen["sid"] == "s-one" and seen["fresh"] is False


def _helper_session(tmp_path, sid, turns):
    """A helper session as orch starts it: orch's notice is the first user turn, never a person's words."""
    claude = tmp_path / "c"
    _w(claude / "projects" / "-Users-a-ws" / f"{sid}.jsonl", turns)
    return {"CLAUDE_CONFIG_DIR": str(claude), "HOME": str(tmp_path)}


def _u(text, at):
    return {"type": "user", "timestamp": at, "message": {"role": "user", "content": text}}


def _a(text, at):
    return {"type": "assistant", "timestamp": at, "message": {"content": [{"type": "text", "text": text}]}}


def _ticket(checklist, title="Daily summary"):
    return {"title": title, "checklist": checklist, "sessions": [{"agent": "claude", "id": SID, "host": "h"}]}


def test_title_never_shows_orchs_notice(tmp_path):
    """ORCH-678: the History title of a helper session was orch's start notice with an id and a command."""
    env = _helper_session(
        tmp_path,
        SID,
        [
            _u(
                "Your task for orch ticket t_72a9ii is ready. Read it with: orch run input t_72a9ii",
                "2026-11-18T20:08:00.100Z",
            ),
            _a("Reading the task.", "2026-11-18T20:08:05.000Z"),
            _u(
                "New input on orch ticket t_72a9ii. Read it with: orch run input t_72a9ii",
                "2026-11-18T20:20:00.000Z",
            ),
            _a("Done.", "2026-11-18T20:30:00.000Z"),
        ],
    )
    steps = [
        {
            "id": "c1",
            "text": "Old step from yesterday",
            "done": True,
            "evidence": [{"at": "2026-11-17T09:00:00Z"}],
        },
        {
            "id": "c2",
            "text": "Collect the orders",
            "done": True,
            "evidence": [{"at": "2026-11-18T20:10:00Z"}],
        },
        {
            "id": "c3",
            "text": "Write the summary for the team",
            "done": True,
            "evidence": [{"at": "2026-11-18T20:29:00Z"}],
        },
        {"id": "c4", "text": "Not done", "done": False, "evidence": []},
    ]
    row = session_history.sessions(_ticket(steps), env)[0]
    assert "orch run input" not in row["title"] and "t_72a9ii" not in row["title"]
    assert row["title"] == "Write the summary for the team"


def test_title_step_in_progress_then_ticket_title(tmp_path):
    turns = [
        _u(
            "Your task for orch ticket t_72a9ii is ready. Read it with: orch run input t_72a9ii",
            "2026-11-18T20:08:00Z",
        ),
        _a("Working.", "2026-11-18T20:09:00Z"),
    ]
    env = _helper_session(tmp_path, SID, turns)
    doing = [
        {
            "id": "c1",
            "text": "Collect the orders",
            "done": False,
            "state": "doing",
            "at": "2026-11-18T20:08:30Z",
        }
    ]
    assert session_history.sessions(_ticket(doing), env)[0]["title"] == "Collect the orders"
    # no step in the session's time: the ticket's own title, never the notice
    assert session_history.sessions(_ticket([]), env)[0]["title"] == "Daily summary"


def test_title_first_person_words_after_the_notice(tmp_path):
    env = _helper_session(
        tmp_path,
        SID,
        [
            _u("Work on orch ticket t_72a9ii: Daily summary.", "2026-11-18T20:08:00Z"),
            _u("Please also add the returns", "2026-11-18T20:09:00Z"),
        ],
    )
    assert session_history.sessions(_ticket([]), env)[0]["title"] == "Please also add the returns"


def test_title_step_proved_again_later_stays_with_its_session(tmp_path):
    turns = [
        _u(
            "Your task for orch ticket t_72a9ii is ready. Read it with: orch run input t_72a9ii",
            "2026-11-18T20:08:00Z",
        ),
        _a("Done.", "2026-11-18T20:30:00Z"),
    ]
    env = _helper_session(tmp_path, SID, turns)
    ev = [{"at": "2026-11-18T20:10:00Z"}, {"at": "2026-11-19T09:00:00Z"}]
    steps = [{"id": "c1", "text": "Collect the orders", "done": True, "evidence": ev}]
    assert session_history.sessions(_ticket(steps), env)[0]["title"] == "Collect the orders"


def test_title_long_session_counts_work_after_the_turns_read(tmp_path, monkeypatch):
    monkeypatch.setattr(session_history, "MAX_TURNS", 2)
    turns = [
        _u(
            "Your task for orch ticket t_72a9ii is ready. Read it with: orch run input t_72a9ii",
            "2026-11-18T20:08:00Z",
        ),
        _a("Working.", "2026-11-18T20:09:00Z"),
        _a("Still working.", "2026-11-18T21:00:00Z"),
    ]
    env = _helper_session(tmp_path, SID, turns)
    steps = [
        {"id": "c1", "text": "Write the summary", "done": True, "evidence": [{"at": "2026-11-18T20:59:00Z"}]}
    ]
    assert session_history.sessions(_ticket(steps), env)[0]["title"] == "Write the summary"


def test_reading_sessions_does_no_cleanup(proj, run, new_ticket, monkeypatch):
    """`run history` and `run session` only read: no idle cleanup, no start of the waiting line before them.
    The dashboard reads `run history` per ticket through three read workers; with the cleanup in front it took
    12-54 s on a busy computer and every other page waited (report r-1127-0535-ws)."""
    from orch import runs_live

    calls = []
    monkeypatch.setattr(runs_live, "cleanup", lambda root: calls.append(root) or [])
    tid = new_ticket()
    code, out, err = run("run", "history", tid, "--json")
    assert code == 0, err
    code, out, err = run("run", "session", tid, "--agent", "claude", "--json")
    assert code == 0, err
    assert calls == []
    run("run", "status", tid, "--json")  # a run command that is not a plain read still cleans up first
    assert calls


def test_last_keeps_the_newest_turns(tmp_path):
    """ORCH-2204: the Focus chat reads the newest turns of a long conversation, not the first ones."""
    env = _env(tmp_path)
    f = tmp_path / "c" / "projects" / "-Users-a-ws" / f"{SID}.jsonl"
    rows = [{"type": "assistant", "message": {"content": f"turn {i}"}} for i in range(450)]
    MAX = 450
    _w(f, rows)
    h = session_history.read("claude", SID, env, last=3)
    assert [t["text"] for t in h["turns"]] == [f"turn {MAX - 3}", f"turn {MAX - 2}", f"turn {MAX - 1}"]
    assert h["more"] is True
    assert session_history.read("claude", SID, env, last=500)["more"] is False
    first = session_history.read("claude", SID, env)
    assert len(first["turns"]) == session_history.MAX_TURNS and first["turns"][0]["text"] == "turn 0"
