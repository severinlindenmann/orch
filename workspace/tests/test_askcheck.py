"""ORCH-1760: a helper ends its turn with questions for the person only in its reply, none on the ticket.

The end-of-turn hook sends a Claude helper back once to put them on the ticket with orch ask; a tool without
such a hook gets one history line; the start text says it; the diagnose check sees the stuck state."""

import io
import json
import os

import pytest

from orch import adapters, askcheck, diag_checks, runs, runs_live, tickets, workcheck

REPLY = (
    "The pre-draft is written (44.5h).\n\n"
    "Before I make the card I need three answers:\n"
    "1. Thu 19 Nov: add the Pilatus stand-up as GEN 0.5h?\n"
    "2. Should I book the ALTYCA meetings that are in your calendar?\n"
    "3. Anything to book for Swisscom on Monday?\n"
)


def _ticket(run):
    return json.loads(run("ticket", "new", "Weekly hours report", "--json", "--by", "human:t")[1])["id"]


def _claimed(proj, run, mode="live"):
    tid = _ticket(run)
    rec = runs.claim(proj, tid, "human:t", "claude", mode, pid=os.getpid())
    return tid, rec["run"]


def _env(monkeypatch, proj, tid, rn):
    for k, v in {"ORCH_RUN": rn, "ORCH_TICKET": tid, "ORCH_ROOT": str(proj)}.items():
        monkeypatch.setenv(k, v)


# ---------------------------------------------------------------- finding the questions


def test_questions_are_the_sentences_that_end_in_a_question_mark():
    got = askcheck.questions(REPLY)
    assert len(got) == 3
    assert got[0].startswith("Thu 19 Nov") and got[2] == "Anything to book for Swisscom on Monday?"


@pytest.mark.parametrize(
    "text",
    [
        "",
        None,
        "All done. The pull request is in the merge queue.",
        "```python\nif x?:\n    pass\n```\nDone.",
        "I ran `orch ask --help?` to see the flags. Done.",
        "> Can you check this? (the person's words)\nDone.",
        "See https://example.com/page?id=3 for the report.",
        "## What's next?\nThe pull request is in the merge queue.",
        "**Open points?**\nNone.",
        "Done. Anything else?",
        "Why does this matter? Because the person never sees the reply.",
    ],
)
def test_no_question_in_code_quotes_links_or_plain_reports(text):
    assert askcheck.questions(text) == []


def test_the_nudge_quotes_at_most_three_and_names_the_command():
    line = askcheck.line("ALTY-13", ["A one?", "B two?", "C three?", "D four?"])
    assert "4 questions" in line and '"C three?"' in line and "D four" not in line and "..." in line
    assert 'orch ask ALTY-13 "<question>"' in line and "not seen" in line


# ---------------------------------------------------------------- ticket state


def test_nudge_when_the_ticket_is_worked_on_and_nothing_is_open(proj, run):
    tid, _ = _claimed(proj, run)
    key, asked = askcheck.nudge(proj, tid, REPLY)
    assert key == tickets.load(proj, tid)["key"] and len(asked) == 3


def test_no_nudge_when_a_question_is_open(proj, run):
    tid, _ = _claimed(proj, run)
    tickets.ask(proj, tid, "Add the stand-up?", ["Yes", "No"], "Yes", "agent:claude")
    assert askcheck.nudge(proj, tid, REPLY) is None


@pytest.mark.parametrize("status", ["review", "done", "dropped"])
def test_no_nudge_once_the_ticket_left_the_work(proj, run, status):
    tid, _ = _claimed(proj, run)
    t = tickets.load(proj, tid)
    t["status"] = status
    tickets._write(proj, t)
    assert askcheck.nudge(proj, tid, REPLY) is None


def test_a_taken_back_question_is_not_open():
    t = {"questions": [{"id": "q1", "answer": None, "taken_back": {"why": "x"}}, {"id": "q2", "answer": "y"}]}
    assert askcheck.open_questions(t) == []


# ---------------------------------------------------------------- the end-of-turn hook (Claude)


def _stop(proj, monkeypatch, capsys, **extra):
    payload = {"hook_event_name": "Stop", "cwd": str(proj), "stop_hook_active": False, **extra}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert workcheck.hook_main(["work-check", "--hook", "claude"]) == 0
    out = capsys.readouterr().out.strip()
    return json.loads(out) if out else None


def test_the_stop_hook_sends_the_helper_back_once(proj, run, monkeypatch, capsys):
    tid, rn = _claimed(proj, run)
    _env(monkeypatch, proj, tid, rn)
    out = _stop(proj, monkeypatch, capsys, last_assistant_message=REPLY)
    assert out["decision"] == "block" and "3 questions" in out["reason"] and "orch ask" in out["reason"]
    assert _stop(proj, monkeypatch, capsys, last_assistant_message=REPLY) is None  # the same reply: once
    assert (
        _stop(proj, monkeypatch, capsys, last_assistant_message=REPLY + "\nOr?", stop_hook_active=True)
        is None
    )


def test_the_stop_hook_reads_the_transcript_when_the_reply_is_not_in_the_payload(
    proj, run, monkeypatch, capsys, tmp_path
):
    tid, rn = _claimed(proj, run)
    _env(monkeypatch, proj, tid, rn)
    tr = tmp_path / "session.jsonl"
    rows = [
        {"type": "user", "message": {"content": "go"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": REPLY}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}},
    ]
    tr.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    out = _stop(proj, monkeypatch, capsys, transcript_path=str(tr))
    assert out and out["decision"] == "block"


def test_the_stop_hook_is_quiet_outside_a_run_and_for_another_run(proj, run, monkeypatch, capsys):
    tid, rn = _claimed(proj, run)
    for k in ("ORCH_RUN", "ORCH_TICKET", "ORCH_ROOT"):
        monkeypatch.delenv(k, raising=False)
    assert _stop(proj, monkeypatch, capsys, last_assistant_message=REPLY) is None
    _env(monkeypatch, proj, tid, "r_someoneelse")
    assert _stop(proj, monkeypatch, capsys, last_assistant_message=REPLY) is None


def test_the_stop_hook_is_quiet_when_the_question_is_on_the_ticket(proj, run, monkeypatch, capsys):
    tid, rn = _claimed(proj, run)
    _env(monkeypatch, proj, tid, rn)
    tickets.ask(proj, tid, "Add the stand-up?", ["Yes", "No"], "Yes", "agent:claude")
    assert _stop(proj, monkeypatch, capsys, last_assistant_message=REPLY) is None


def test_the_stop_hook_goes_only_into_the_runs_own_settings(proj):
    a = adapters.load("claude", proj)
    assert "Stop" in a["stop_hooks"] and "Stop" not in a["reminder_hooks"]  # never the workspace's own file
    doc = adapters.reminder_doc("claude", proj)
    if doc is None:
        pytest.skip("the hook's python cannot import orch here")
    (group,) = doc["hooks"]["Stop"]
    assert group["hooks"][0]["command"].endswith("work-check --hook claude") and "matcher" not in group


# ---------------------------------------------------------------- a tool without the hook (Codex)


def test_codex_stream_reply_and_one_history_line(proj, run):
    tid, _ = _claimed(proj, run, mode="oneshot")
    out = "\n".join(
        json.dumps(x)
        for x in (
            {"type": "thread.started", "thread_id": "t1"},
            {"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": REPLY}},
            {"type": "turn.completed"},
        )
    )
    assert askcheck.last_reply_from_stream(out) == REPLY
    runs._ask_left_in_reply(proj, tid, out)
    texts = [h["text"] for h in tickets.load(proj, tid)["history"]]
    assert askcheck.history_text(3) in texts
    runs._ask_left_in_reply(proj, tid, json.dumps({"type": "result", "result": "Done."}))
    assert [h["text"] for h in tickets.load(proj, tid)["history"]].count(askcheck.history_text(3)) == 1


# ---------------------------------------------------------------- the start text


def test_the_start_text_says_questions_go_on_the_ticket(proj, run):
    tid = _ticket(run)
    prompt = runs.fresh_prompt(tickets.load(proj, tid), [], proj)
    assert f'orch ask {tid} "<question>"' in prompt and "a question only in your reply is not seen" in prompt


# ---------------------------------------------------------------- the diagnose check


def _snap(status="active", open_q=0, live="idle", idle=600, process="alive"):
    return {
        "now": 0,
        "events": [],
        "collected": {
            "tickets": {"data": {"tickets": {"t_a": {"status": status, "open_questions": open_q}}}},
            "runs": {
                "data": {
                    "runs": {
                        "t_a": {"run": "r_1", "process": process, "live_state": live, "live_age_s": idle}
                    }
                }
            },
        },
    }


def _check(snap):
    (mod,) = [m for m in diag_checks.modules() if m.NAME == "idle_working_no_question"]
    return mod.check(snap)


def test_diag_flags_an_idle_helper_on_a_working_ticket_with_nothing_asked():
    c = _check(_snap())
    assert c["verdict"] == "problem" and "t_a" in c["evidence"][0] and "600 s" in c["evidence"][0]


@pytest.mark.parametrize(
    "kw",
    [
        {"open_q": 1},
        {"status": "waiting"},
        {"status": "review"},
        {"live": "working"},
        {"idle": 30},
        {"process": "dead"},
    ],
)
def test_diag_is_ok_otherwise(kw):
    assert _check(_snap(**kw))["verdict"] == "ok"


def test_diag_collects_the_open_question_count(proj, run):
    from orch import diag_collect

    tid, _ = _claimed(proj, run)
    tickets.ask(proj, tid, "Add the stand-up?", ["Yes", "No"], "Yes", "agent:claude")
    data, _ = diag_collect.tickets_data(proj, {"ticket": tid}, 0)
    assert data["tickets"][tid]["open_questions"] == 1


# ---------------------------------------------------------------- a live run sent back works on


def test_a_nudged_live_run_works_on_and_the_parallel_idle_is_swallowed(proj, run, monkeypatch, capsys):
    tid, rn = _claimed(proj, run)
    _env(monkeypatch, proj, tid, rn)
    assert _stop(proj, monkeypatch, capsys, last_assistant_message=REPLY)["decision"] == "block"
    assert runs.read(proj, tid)["live"]["state"] == "working"
    runs_live.event(proj, "idle", rn, tid, None)  # the run's own Stop hook of the same turn
    assert runs.read(proj, tid)["live"]["state"] == "working"
    runs_live.event(proj, "idle", rn, tid, None)  # the next real end of a turn counts
    assert runs.read(proj, tid)["live"]["state"] == "idle"


def test_an_old_nudge_mark_does_not_swallow_a_later_idle(proj, run, monkeypatch):
    tid, rn = _claimed(proj, run)
    assert runs_live.hold_for_nudge(proj, tid, rn)
    rec = runs.read(proj, tid)
    rec["nudged_at"] -= runs_live.NUDGE_SAME_STOP_SECONDS + 1
    runs._write(proj, rec)
    runs_live.event(proj, "idle", rn, tid, None)
    rec = runs.read(proj, tid)
    assert rec["live"]["state"] == "idle" and "nudged_at" not in rec
