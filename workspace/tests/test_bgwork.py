"""What an idle helper still has going on (ORCH-267): its own background helpers, and a person typing to it.
The watcher and the idle close leave such a session alone."""

import json
import subprocess
import time

import pytest

from orch import bgwork, runs, runs_live, runwatch, tend, tickets


def _iso(seconds_ago=0):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - seconds_ago))


def _launch(tool_id="toolu_A", what="Draft B", ago=600):
    return [
        {
            "type": "assistant",
            "timestamp": _iso(ago),
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": "Agent",
                        "input": {"description": what, "prompt": "...", "run_in_background": True},
                    }
                ],
            },
        },
        {
            "type": "user",
            "timestamp": _iso(ago),
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": [
                            {"type": "text", "text": "Async agent launched successfully.\nagentId: a1"}
                        ],
                    }
                ],
            },
        },
    ]


def _finished(tool_id="toolu_A", ago=60):
    text = (
        "<task-notification>\n<task-id>a1</task-id>\n<tool-use-id>" + tool_id + "</tool-use-id>\n"
        "<status>completed</status>\n</task-notification>"
    )
    return {"type": "user", "timestamp": _iso(ago), "message": {"role": "user", "content": text}}


def _typed(text, ago=60):
    return {"type": "user", "timestamp": _iso(ago), "message": {"role": "user", "content": text}}


def _lines(entries):
    return [json.dumps(e) for e in entries]


def test_a_background_helper_runs_until_its_finish_notice():
    found = bgwork.scan(_lines(_launch()))
    assert [a["what"] for a in found["agents"].values()] == ["Draft B"]
    assert bgwork.scan(_lines([*_launch(), _finished()]))["agents"] == {}


def test_a_finish_notice_for_another_helper_leaves_this_one_running():
    found = bgwork.scan(_lines([*_launch("toolu_A"), *_launch("toolu_B", "Draft C"), _finished("toolu_A")]))
    assert [a["what"] for a in found["agents"].values()] == ["Draft C"]


def test_orch_notices_tool_results_and_task_notices_are_not_a_person_typing():
    entries = [
        *_launch(),
        _finished(),
        _typed("New input on orch ticket t_abc123. Read it with: orch run input t_abc123"),
        _typed("Your task for orch ticket t_abc123 is ready. Read it with: orch run input t_abc123"),
        _typed("<system-reminder>x</system-reminder>"),
        {**_typed("Caveat: the messages below were generated"), "isMeta": True},
        _typed("Work on orch ticket t_abc123: Fix the header."),
        {**_typed("This session is being continued from a previous conversation."), "isCompactSummary": True},
    ]
    assert bgwork.scan(_lines(entries))["typed_at"] is None


def test_a_line_the_person_typed_is_seen_with_its_time():
    found = bgwork.scan(_lines([_typed("Make the header smaller, please.", ago=120)]))
    assert found["typed_at"] is not None and abs(time.time() - 120 - found["typed_at"]) < 5


def test_broken_lines_and_unknown_formats_find_nothing():
    found = bgwork.scan(["not json", "{}", json.dumps({"type": "user", "message": {"content": 5}})])
    assert found == {"agents": {}, "typed_at": None}


def test_reading_a_saved_conversation_and_its_limits(tmp_path, monkeypatch):
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(_lines([*_launch(ago=600), _typed("Go on.", ago=30)])) + "\n")
    rec = {"ticket": "t_x", "started_at": _iso(3600)[:19] + "Z"}
    monkeypatch.setattr(bgwork, "_path", lambda root, rec: p)
    assert [a["what"] for a in bgwork.subagents(tmp_path, rec)] == ["Draft B"]
    assert bgwork.talking(tmp_path, rec)
    later = time.time() + bgwork.MAX_AGE
    assert bgwork.subagents(tmp_path, rec, now=later) == []  # a lost finish notice does not keep it for ever
    assert not bgwork.talking(tmp_path, rec, now=time.time() + bgwork.TALK_MINUTES * 60)
    rec_new = {**rec, "started_at": _iso(60)[:19] + "Z"}  # orch's own task text right after the start
    assert not bgwork.talking(tmp_path, rec_new)
    monkeypatch.setattr(bgwork, "_path", lambda root, rec: tmp_path / "missing.jsonl")
    assert bgwork.subagents(tmp_path, rec) == [] and not bgwork.talking(tmp_path, rec)


# ------------------------------------------------------------------ the watcher and the idle close


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
def convo(tmp_path, monkeypatch):
    """The live session's saved conversation is this file."""
    monkeypatch.setattr(runwatch, "_table", lambda: [])
    monkeypatch.setattr(runs_live, "deliver", lambda root, tid, stop=None: 0)
    monkeypatch.setattr(runs_live, "session_exists", lambda root, tid: False)
    p = tmp_path / "convo.jsonl"
    p.write_text("")
    monkeypatch.setattr(bgwork, "_path", lambda root, rec: p)

    def write(entries):
        p.write_text("\n".join(_lines(entries)) + "\n")

    return write


def _live(proj, tid, pid, idle_for):
    when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - idle_for))
    start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3 * 3600))
    runs._write(
        proj,
        {
            "schema": "orch.run/1",
            "ticket": tid,
            "run": "r_test1234",
            "by": "human:tester",
            "agent": "generic",
            "mode": "live",
            "pid": pid,
            "started_at": start,
            "renewed_at": start,
            "live": {"state": "idle", "since": when},
        },
    )


def _done(proj, tid):
    tickets.apply_op(proj, tid, lambda t: t.update(status="done"), by="agent:x")


def test_the_watcher_never_ends_a_session_whose_own_helpers_still_run(proj, new_ticket, child, convo):
    tid = new_ticket()
    _done(proj, tid)
    _live(proj, tid, child(), idle_for=30 * 60)
    convo(_launch(ago=30 * 60))
    assert tend.run(proj)["actions"] == []
    assert runs.read(proj, tid) is not None
    info = runwatch.describe(proj, tid, runs.read(proj, tid))
    assert any("a helper of its own: Draft B" in w["what"] for w in info["waiting_on"])
    convo([*_launch(ago=30 * 60), _finished(ago=20 * 60)])  # it finished: the session may end now
    assert [a["action"] for a in tend.run(proj)["actions"]] == ["end"]


def test_the_watcher_leaves_a_helper_the_person_is_talking_to(proj, new_ticket, child, convo):
    tid = new_ticket()
    _done(proj, tid)
    _live(proj, tid, child(), idle_for=15 * 60)
    convo([_typed("Looks good, now the phone width.", ago=16 * 60)])
    assert tend.run(proj)["actions"] == []
    convo([_typed("Looks good, now the phone width.", ago=(bgwork.TALK_MINUTES + 1) * 60)])
    assert [a["action"] for a in tend.run(proj)["actions"]] == ["end"]


def test_the_idle_close_keeps_a_session_whose_own_helpers_still_run(proj, new_ticket, child, convo):
    tid = new_ticket()
    _live(proj, tid, child(), idle_for=2 * 3600)
    convo(_launch(ago=2 * 3600))
    assert runs_live.cleanup(proj) == []
    convo([*_launch(ago=2 * 3600), _finished(ago=90 * 60)])
    assert runs_live.cleanup(proj) == [tid]
