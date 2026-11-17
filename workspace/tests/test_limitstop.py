"""ORCH-179: helpers that stopped on the usage limit are held until it resets and then started again by the
helper watcher, with no person."""

import json
import subprocess
import time

import pytest

from orch import limitstop, runs, runs_live, runwatch, tend, tickets

RESET = 1794901200  # 2026-11-17 07:40 UTC (8:40am Europe/Zurich)


def _limit_line(resets=RESET, words="You've hit your 5-hour limit · resets 8:40am (Europe/Zurich)"):
    """The line Claude Code saves when the limit stops a turn (shape seen on 17 Nov)."""
    return {
        "type": "assistant",
        "timestamp": "2026-11-17T07:18:20.850Z",
        "apiError": "usage_limit_reached",
        "apiErrorParams": {
            "rate_limit_info": {"status": "rejected", "resetsAt": resets, "rateLimitType": "five_hour"}
        },
        "error": "rate_limit",
        "isApiErrorMessage": True,
        "message": {"role": "assistant", "content": [{"type": "text", "text": words}]},
    }


def _answer(text="Done with c1."):
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


# ---------------------------------------------------------------- noticing


def test_the_limit_line_gives_the_reset_time():
    hit = limitstop.from_entries([_answer(), _limit_line()])
    assert hit["until"] == RESET
    assert hit["window"] == "five_hour"
    assert "5-hour limit" in hit["text"]


def test_an_answer_after_the_limit_means_it_went_on():
    assert limitstop.from_entries([_limit_line(), {"type": "user"}, _answer()]) is None


def test_the_words_alone_give_the_next_such_time():
    now = 1794895200  # 06:00 UTC = 07:00 Zurich
    hit = limitstop.from_output("", "You've hit your 5-hour limit · resets 8:40am (Europe/Zurich)", now)
    assert hit["until"] == RESET
    later = limitstop.reset_from_words("resets 8:40am (Europe/Zurich)", RESET + 3600)
    assert later == RESET + 86400  # 8:40 has passed: tomorrow's


def test_a_weekly_limit_with_a_date():
    at = limitstop.reset_from_words(
        "You've hit your weekly limit · resets Nov 20, 9am (Europe/Zurich)", RESET
    )
    assert time.strftime("%m-%d %H:%M", time.gmtime(at)) == "11-20 08:00"


def test_a_stream_rate_limit_event_gives_the_time_when_the_error_has_none():
    out = "\n".join(
        json.dumps(x)
        for x in (
            {"type": "rate_limit_event", "rate_limit_info": {"status": "rejected", "resetsAt": RESET}},
            {"type": "result", "is_error": True, "result": "You've hit your limit"},
        )
    )
    assert limitstop.from_output(out, None)["until"] == RESET


def test_other_errors_are_no_limit():
    assert (
        limitstop.from_output('{"type":"result","is_error":true,"result":"API Error: 500"}', "API Error")
        is None
    )
    assert limitstop.from_output("", "exit code 1") is None


def test_a_reset_time_unknown_waits_an_hour(proj, new_ticket):
    tid = new_ticket()
    now = 1_800_000_000
    assert limitstop.note(proj, tid, {"until": None, "text": "limit"}, now)
    assert limitstop.active(proj, now + 30 * 60) is not None
    assert limitstop.due(proj, now + 61 * 60) == [tid]


def test_noting_twice_says_it_once_and_keeps_the_later_reset(proj, new_ticket):
    a, b = new_ticket(), new_ticket()
    assert limitstop.note(proj, a, {"until": RESET}, RESET - 600) is True
    assert limitstop.note(proj, a, {"until": RESET}, RESET - 500) is False
    assert limitstop.note(proj, b, {"until": RESET + 600}, RESET - 400) is True
    assert limitstop.read(proj)["until"] == RESET + 600
    limitstop.forget(proj, [a, b])
    assert not (runs.run_dir(proj) / limitstop.FILE).exists()


def test_helpers_noted_at_the_same_moment_are_all_kept(proj, new_ticket):
    import threading

    tids = [new_ticket() for _ in range(8)]
    threads = [threading.Thread(target=limitstop.note, args=(proj, t, {"until": RESET})) for t in tids]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert sorted(limitstop.read(proj)["tickets"]) == sorted(tids)
    assert not (proj / ".orch" / "run" / "limit-stop.lock").exists()


def test_automatic_starts_wait_in_line_while_the_limit_holds(proj, new_ticket, monkeypatch):
    monkeypatch.setattr(runs_live, "_pressure", lambda root: None)
    monkeypatch.setattr(runs_live, "_too_soon", lambda root: False)
    limitstop.note(proj, new_ticket(), {"until": time.time() + 3600})
    assert "usage limit" in runs_live._held(proj, runs_live.AUTOMATION_BY)
    assert runs_live._held(proj, "human:tester") is None  # a person's own start is never held


# ---------------------------------------------------------------- the helper watcher


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(runwatch, "_table", lambda: [])
    monkeypatch.setattr(runs_live, "deliver", lambda root, tid, stop=None: 0)
    monkeypatch.setattr(runs_live, "session_exists", lambda root, tid: False)


@pytest.fixture
def child():
    procs = []

    def make():
        p = subprocess.Popen(["sleep", "120"])
        procs.append(p)
        return p.pid

    yield make
    for p in procs:
        p.kill()
        p.wait()


@pytest.fixture
def starts(monkeypatch):
    calls = []

    def fake(root, tid, by, **kw):
        calls.append((tid, by, kw))
        return {"run": "r_again0001", "mode": "live", "resumed": True, "notes": []}

    monkeypatch.setattr(runs, "start", fake)
    return calls


@pytest.fixture
def claude_home(tmp_path, monkeypatch):
    home = tmp_path / "claude-home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    return home


SID = "11111111-2222-4333-8444-555555555555"


def _since(seconds_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago))


def _live(proj, tid, pid, idle_for, run="r_test1234"):
    runs._write(
        proj,
        {
            "schema": "orch.run/1", "ticket": tid, "run": run, "by": "human:tester", "agent": "claude",
            "mode": "live", "pid": pid, "session": SID,
            "started_at": _since(7200), "renewed_at": _since(7200),
            "live": {"state": "idle", "since": _since(idle_for)},
        },
    )  # fmt: skip


def _transcript(proj, home, lines):
    from orch import adapters

    path = adapters.transcript_path("claude", SID, proj, {"CLAUDE_CONFIG_DIR": str(home)})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines))


def _history(proj, tid):
    return [h["text"] for h in tickets.load(proj, tid)["history"] if h["by"] == tend.BY]


def test_a_helper_at_the_limit_is_noted_and_not_reminded(proj, new_ticket, child, claude_home, starts):
    tid = new_ticket()
    _live(proj, tid, child(), idle_for=30 * 60)  # long past the reminder time
    _transcript(proj, claude_home, [_answer(), _limit_line(resets=time.time() + 3600)])
    res = tend.run(proj)
    assert [a["action"] for a in res["actions"]] == ["limit"]
    assert tid in limitstop.read(proj)["tickets"]
    assert any("Stopped on the usage limit" in h for h in _history(proj, tid))
    # the next passes do nothing to it: no reminder, no fresh start
    assert tend.run(proj)["actions"] == []
    assert tend.run(proj, now=time.time() + 50 * 60)["actions"] == []
    assert starts == []
    assert len([h for h in _history(proj, tid) if "usage limit" in h]) == 1


def test_other_idle_helpers_are_not_reminded_while_the_limit_holds(proj, new_ticket, child, starts):
    limitstop.note(proj, new_ticket(), {"until": time.time() + 3600})
    tid = new_ticket()
    runs._write(
        proj,
        {
            "schema": "orch.run/1", "ticket": tid, "run": "r_other0001", "by": "human:tester",
            "agent": "generic",
            "mode": "live", "pid": child(), "started_at": _since(7200), "renewed_at": _since(7200),
            "live": {"state": "idle", "since": _since(30 * 60)},
        },
    )  # fmt: skip
    assert tend.run(proj)["actions"] == []


def test_after_the_reset_the_live_helper_is_started_again_on_its_conversation(
    proj, new_ticket, child, claude_home, starts
):
    tid = new_ticket()
    _live(proj, tid, child(), idle_for=30 * 60)
    _transcript(proj, claude_home, [_limit_line(resets=time.time() - 5 * 60)])
    limitstop.note(proj, tid, {"until": time.time() - 5 * 60})
    res = tend.run(proj)
    assert [a["action"] for a in res["actions"]] == ["resume"]
    assert runs.read(proj, tid) is None  # the session at the limit was ended first
    assert starts == [(tid, runs_live.AUTOMATION_BY, {})]  # not fresh: it continues where it stood
    assert limitstop.read(proj) == {}
    assert any("usage limit reset" in h for h in _history(proj, tid))
    pending = [i["text"] for i in runs.undelivered(proj, tid)]
    assert any("Go on with" in p for p in pending)


def test_after_the_reset_a_stopped_ticket_with_no_run_starts_again(proj, new_ticket, starts):
    tid = new_ticket()
    limitstop.note(proj, tid, {"until": time.time() - 3 * 60})
    assert tend.run(proj, dry_run=True)["actions"][0]["action"] == "resume"
    assert starts == []  # a dry run only says it
    tend.run(proj)
    assert [s[0] for s in starts] == [tid]


def test_nothing_starts_before_the_reset_plus_grace(proj, new_ticket, starts):
    tid = new_ticket()
    limitstop.note(proj, tid, {"until": time.time() - 30})  # reset passed only half a minute ago
    assert tend.run(proj)["actions"] == []
    assert starts == []


def test_a_finished_or_waiting_ticket_is_only_forgotten(proj, run, new_ticket, starts):
    done, asks = new_ticket(), new_ticket()
    tickets.apply_op(proj, done, lambda t: t.update(status="done"), by="agent:x")
    assert run("ask", asks, "Which colour?", "--option", "red", "--option", "blue")[0] == 0
    for tid in (done, asks):
        limitstop.note(proj, tid, {"until": time.time() - 600})
    tend.run(proj)
    assert starts == []
    assert limitstop.read(proj) == {}


def test_a_run_that_ends_on_the_limit_is_noted(proj, new_ticket):
    tid = new_ticket()
    out = json.dumps(
        {"type": "result", "is_error": True, "result": "You've hit your 5-hour limit · resets 8:40am"}
    )
    hit = limitstop.from_output(out, runs.failure_text(1, out))
    assert hit is not None and limitstop.note(proj, tid, hit)
    assert limitstop.active(proj) is not None or limitstop.due(proj) == [tid]
