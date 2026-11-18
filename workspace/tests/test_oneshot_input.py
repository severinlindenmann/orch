"""#1268 (ORCH-299): a one-step (oneshot) run reads a person's input that arrived while it works, at its next
tool step: the step hook prints the fixed notice once, `orch run input` hands the input over and marks it
delivered, and the ticket can then move to Review. Nobody else reads it; a live session is unchanged."""

import io
import json
import os

import pytest

from orch import adapters, runs, runs_live, tickets, workcheck


def _ticket(run):
    return json.loads(run("ticket", "new", "Plan the fair", "--json", "--by", "human:t")[1])["id"]


def _oneshot(proj, run):
    tid = _ticket(run)
    rec = runs.claim(proj, tid, "human:t", "claude", "oneshot", pid=os.getpid())
    return tid, rec["run"]


def _env(proj, tid, rn):
    return {"ORCH_RUN": rn, "ORCH_TICKET": tid, "ORCH_ROOT": str(proj)}


def test_a_oneshot_run_reads_input_that_came_while_it_works(proj, run):
    tid, rn = _oneshot(proj, run)
    runs.pending_add(proj, tid, "human:lume", "message", "Please add a rain plan.")
    text, n = runs_live.read_input(proj, tid, rn, True)
    assert n == 1 and "Please add a rain plan." in text
    assert runs.undelivered(proj, tid) == []
    assert runs_live.read_input(proj, tid, rn, True)[1] == 0  # read once
    tickets._check_not_too_early(proj, tickets.load(proj, tid))  # the done check no longer waits on it


def test_a_oneshot_run_never_reads_a_start_or_slot_request(proj, run):
    tid, rn = _oneshot(proj, run)
    runs.pending_add(proj, tid, "human:lume", "message", "start it", via="start")
    _, n = runs_live.read_input(proj, tid, rn, True)
    assert n == 0 and len(runs.undelivered(proj, tid)) == 1


@pytest.mark.parametrize("who", [None, "r_someoneelse"])
def test_only_the_oneshot_run_holding_the_ticket_reads(proj, run, who):
    tid, _ = _oneshot(proj, run)
    runs.pending_add(proj, tid, "human:lume", "message", "Please add a rain plan.")
    with pytest.raises(Exception, match="Only the run working on"):
        runs_live.read_input(proj, tid, who, True)
    assert len(runs.undelivered(proj, tid)) == 1


def test_a_finished_oneshot_run_reads_nothing(proj, run, monkeypatch):
    tid, rn = _oneshot(proj, run)
    runs.pending_add(proj, tid, "human:lume", "message", "Please add a rain plan.")
    monkeypatch.setattr(runs, "state", lambda rec, at=None: "dead")
    with pytest.raises(Exception, match="Only the run working on"):
        runs_live.read_input(proj, tid, rn, True)
    assert len(runs.undelivered(proj, tid)) == 1


def test_the_step_hook_tells_the_oneshot_run_once(proj, run):
    tid, rn = _oneshot(proj, run)
    env = _env(proj, tid, rn)
    assert workcheck.input_notice(env) is None  # nothing waits
    runs.pending_add(proj, tid, "human:lume", "message", "Please add a rain plan.")
    line = workcheck.input_notice(env)
    assert line == runs_live.notice_line(tid, False) and "rain" not in line  # fixed words only
    assert workcheck.input_notice(env) is None  # once per set of waiting items
    runs.pending_add(proj, tid, "human:lume", "message", "And a tent.")
    assert workcheck.input_notice(env) == line  # a new item: told again


@pytest.mark.parametrize(
    "change",
    [
        {"ORCH_RUN": "r_someoneelse"},
        {"ORCH_ROOT": "relative/path"},
        {"ORCH_TICKET": "../../etc"},
        {"ORCH_RUN": ""},
    ],
)
def test_the_step_hook_stays_quiet_for_anyone_else(proj, run, change):
    tid, rn = _oneshot(proj, run)
    runs.pending_add(proj, tid, "human:lume", "message", "Please add a rain plan.")
    assert workcheck.input_notice({**_env(proj, tid, rn), **change}) is None


def test_the_step_hook_stays_quiet_for_a_live_session(proj, run):
    tid = _ticket(run)
    rec = runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    runs.pending_add(proj, tid, "human:lume", "message", "Please add a rain plan.")
    assert workcheck.input_notice(_env(proj, tid, rec["run"])) is None  # it gets the notice at its prompt


def test_hook_main_answers_a_tool_step_in_the_tools_protocol(proj, run, monkeypatch, capsys):
    tid, rn = _oneshot(proj, run)
    runs.pending_add(proj, tid, "human:lume", "message", "Please add a rain plan.")
    for k, v in _env(proj, tid, rn).items():
        monkeypatch.setenv(k, v)
    # a big tool result cut off at 64 KB: the event name is still found
    payload = f'{{"hook_event_name": "PostToolUse", "cwd": "{proj}", "tool_response": "{"x" * 70000}'
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    assert workcheck.hook_main(["work-check", "--hook", "claude"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": runs_live.notice_line(tid, False),
        }
    }


def test_the_step_hooks_go_only_into_the_runs_own_settings(proj):
    doc = adapters.reminder_doc("claude", proj)
    if doc is None:
        pytest.skip("the hook's python cannot import orch here")
    cmds = {g["hooks"][0]["command"] for g in doc["hooks"]["PostToolUse"]}
    # the record hook and the work-check step hook; on Windows there is no record hook (adapters.reminder_doc)
    assert len(cmds) == (1 if adapters._is_windows() else 2)
    a = adapters.load("claude", proj)
    assert "PostToolUse" not in a["reminder_hooks"]  # never in the workspace's own settings file
