import json
import os
import time

from conftest import T, add_ticket, calls, runs_started

from orch_automation.loop import Scheduler
from orch_automation.runner import load_state


def tk(ws, tid):
    return json.loads((ws / f".orch/tickets/{tid}.json").read_text())


def end_run(ws, tid, age=60):
    """The run is over; its log was last written `age` seconds after the start (os.utime)."""
    (ws / f"ended-{tid}").write_text("")
    log = ws / f".orch/run/logs/{tid}-r1.log"
    t = time.time() + age
    os.utime(log, (t, t))


def test_wake_starts_run_through_core_once(ws):
    add_ticket(ws, "t_wake001", status="waiting", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"})
    s = Scheduler(ws)
    assert s.tick(T(7, 59)) == []
    assert s.tick(T(8, 1)) == ["t_wake001"]
    cs = calls(ws)
    start = next(c for c in cs if c["args"][:2] == ["run", "start"])
    assert start["by"] == "agent:automation" and start["args"][:3] == ["run", "start", "t_wake001"]
    t = tk(ws, "t_wake001")
    assert t["waiting_on"] is None and t["status"] == "active"
    assert s.tick(T(8, 5)) == [] and runs_started(ws) == ["t_wake001"]
    assert load_state(ws)["t_wake001"]["last_wake"] == "2026-11-04T08:00:00Z"


def test_wait_cleared_only_after_run_start_worked(ws):
    """SA-15: a refused start leaves the wait in place."""
    (ws / "noagent").write_text("")
    add_ticket(ws, "t_wake002", status="waiting", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"})
    s = Scheduler(ws)
    assert s.tick(T(8)) == []
    t = tk(ws, "t_wake002")
    assert t["waiting_on"] is not None
    (q,) = t["questions"]
    assert q["kind"] == "automation:failure" and "orch config set workspace.agent <name>" in q["text"]
    assert q["options"] == ["Try again", "Leave it"]
    s.tick(T(8, 1))  # asked once, not again
    assert len(tk(ws, "t_wake002")["questions"]) == 1


def test_busy_ticket_is_pending_not_second_agent(ws):
    add_ticket(ws, "t_wake003", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"})
    (ws / "busy-t_wake003").write_text("")
    s = Scheduler(ws)
    assert s.tick(T(8)) == []  # no new run was started
    assert tk(ws, "t_wake003")["waiting_on"] is None  # the wait is over; the running agent has it
    assert s.watch == {} and s.tick(T(8, 5)) == []


def test_done_ticket_not_woken(ws):
    add_ticket(ws, "t_wake004", status="done", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"})
    assert Scheduler(ws).tick(T(9)) == [] and runs_started(ws) == []


def test_recurring_cron_and_catch_up(ws):
    add_ticket(ws, "t_rec00001", created_at="2026-11-01T00:00:00Z",
               ext={"automation": {"recurring": True, "cron": "0 7 * * *"}})
    s = Scheduler(ws)
    assert s.tick(T(8, 0, d=4)) == ["t_rec00001"]  # 3 missed days -> one run
    assert s.tick(T(8, 2, d=4)) == []
    assert load_state(ws)["t_rec00001"]["next_run"] == "2026-11-05T07:00:00Z"
    assert s.tick(T(7, 1, d=5)) == ["t_rec00001"]
    t = tk(ws, "t_rec00001")
    assert t["ext"]["automation"]["last_run"] == "2026-11-05T07:01:00Z"


def test_cron_busy_sets_last_run_no_pile_up(ws):
    add_ticket(ws, "t_rec00002", ext={"automation": {"recurring": True, "cron": "* * * * *"}})
    (ws / "busy-t_rec00002").write_text("")
    s = Scheduler(ws)
    assert s.tick(T(8, 0)) == []
    assert tk(ws, "t_rec00002")["ext"]["automation"]["last_run"] == "2026-11-04T08:00:00Z"


def test_fast_fail_asks_and_is_not_retried(ws):
    add_ticket(ws, "t_fail0001", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"})
    s = Scheduler(ws)
    assert s.tick(T(8)) == ["t_fail0001"]
    end_run(ws, "t_fail0001", age=2)  # ended after 2 s, wrote nothing on the ticket
    s.tick(T(8, 1))
    (q,) = tk(ws, "t_fail0001")["questions"]
    assert q["kind"] == "automation:failure" and "10 seconds" in q["text"]
    s.tick(T(8, 2))
    assert runs_started(ws) == ["t_fail0001"]  # not retried
    row = json.loads((ws / ".orch/addons/automation/runs.jsonl").read_text().splitlines()[0])
    assert row["exit"] == 1


def test_slow_or_busy_run_is_not_a_failure(ws):
    add_ticket(ws, "t_fail0002", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"})
    s = Scheduler(ws)
    s.tick(T(8))
    end_run(ws, "t_fail0002", age=60)
    s.tick(T(8, 1))
    assert tk(ws, "t_fail0002").get("questions") == []


def test_try_again_runs_once_even_after_restart(ws):
    q = {"id": "q1", "text": "x", "options": ["Try again", "Leave it"], "kind": "automation:failure",
         "answer": "Try again", "answered_by": "human:s", "via": "web"}
    add_ticket(ws, "t_again001", questions=[q])
    assert Scheduler(ws).tick(T(8)) == ["t_again001"]
    assert tk(ws, "t_again001")["ext"]["automation"]["acted"] == ["q1"]
    assert Scheduler(ws).tick(T(8, 1)) == []  # a restart (new object) does not run it again
    assert runs_started(ws) == ["t_again001"]


def test_leave_it_runs_nothing_but_is_recorded(ws):
    q = {"id": "q1", "text": "x", "options": [], "kind": "automation:failure", "answer": "Leave it"}
    add_ticket(ws, "t_leave001", questions=[q])
    assert Scheduler(ws).tick(T(8)) == [] and runs_started(ws) == []
    assert tk(ws, "t_leave001")["ext"]["automation"]["acted"] == ["q1"]


def test_one_answer_leads_to_exactly_one_run(ws):
    """review-49-50 F1: an answer from the relay is applied by the CLI; the loop starts one run, then not again."""
    add_ticket(ws, "t_ask00001", status="active")
    (ws / "ended-t_ask00001").write_text("")  # no run holds it (core could not pass the answer on)
    (ws / ".orch/secrets").mkdir(parents=True)
    (ws / ".orch/secrets/relay.json").write_text("{}")
    (ws / "inbox.json").write_text(json.dumps([{"id": "m_1", "type": "answer", "ticket": "t_ask00001", "applied": True,
                                                 "body": {"question_id": "q1", "answer": "Yes"}}]))
    s = Scheduler(ws)
    assert s.tick(T(8, 0)) == ["t_ask00001"]
    (ws / "inbox.json").write_text("[]")  # the CLI marks it seen: it does not come again
    assert s.tick(T(8, 2)) == []
    assert runs_started(ws) == ["t_ask00001"]


def test_ticket_cannot_supply_a_command(ws):
    add_ticket(ws, "t_wake010", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"},
               ext={"automation": {"agent": "rm -rf / {prompt}"}})
    Scheduler(ws).tick(T(8))
    assert runs_started(ws) == ["t_wake010"]
    assert all("rm" not in " ".join(c["args"]) for c in calls(ws))


def test_invalid_ticket_id_skipped(ws):
    (ws / ".orch/tickets/t_bad.json").write_text(
        json.dumps({"id": "t_../../escape", "status": "open", "waiting_on": "2026-11-04T08:00:00Z"}))
    assert Scheduler(ws).tick(T(9)) == []


def test_not_recurring_flag_means_no_cron_run(ws):
    add_ticket(ws, "t_rec00004", ext={"automation": {"recurring": False, "cron": "* * * * *"}})
    assert Scheduler(ws).tick(T(8)) == []


def test_other_waits_are_not_woken(ws):
    add_ticket(ws, "t_wait0001", status="waiting", waiting_on={"kind": "question", "ref": "q1"})
    add_ticket(ws, "t_wait0002", status="waiting", waiting_on={"kind": "time", "until": "2026-11-04T09:00:00Z"})
    assert Scheduler(ws).tick(T(8)) == []


def test_cli_run_once(ws):
    from orch_automation.cli import main
    add_ticket(ws, "t_wake008", waiting_on={"kind": "time", "until": "2020-01-01T00:00:00Z"})
    assert main(["--dir", str(ws), "run", "--once"]) == 0
    assert runs_started(ws) == ["t_wake008"]


def test_loop_exits_when_not_active(ws):
    (ws / "inactive").write_text("1")
    add_ticket(ws, "t_wake011", waiting_on={"kind": "time", "until": "2020-01-01T00:00:00Z"})
    Scheduler(ws).run_forever(sleep=lambda _: (_ for _ in ()).throw(AssertionError("kept running")))
    assert runs_started(ws) == []


def test_own_history_entries_do_not_hide_a_fast_fail(ws):
    """H1: the scheduler's own notes (wait cleared, status, run started) never count as work on the ticket."""
    add_ticket(ws, "t_fail0003", status="waiting", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"})
    s = Scheduler(ws)
    s.tick(T(8))
    end_run(ws, "t_fail0003", age=2)
    s.tick(T(8, 1))
    assert len(tk(ws, "t_fail0003")["questions"]) == 1


def test_agent_note_makes_a_quick_run_fine(ws):
    add_ticket(ws, "t_fail0004", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"})
    s = Scheduler(ws)
    s.tick(T(8))
    t = tk(ws, "t_fail0004")
    t["history"].append({"by": "agent:claude", "text": "done"})
    (ws / ".orch/tickets/t_fail0004.json").write_text(json.dumps(t))
    end_run(ws, "t_fail0004", age=2)
    s.tick(T(8, 1))
    assert tk(ws, "t_fail0004")["questions"] == []


def test_failed_start_is_not_retried_every_pass(ws):
    """H2: the wait stays (SA-15) but the wake is recorded, so only 'Try again' retries."""
    (ws / "noagent").write_text("")
    add_ticket(ws, "t_wake020", status="waiting", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"})
    s = Scheduler(ws)
    s.tick(T(8))
    s.tick(T(8, 1))
    assert runs_started(ws).count("t_wake020") == 1
    assert tk(ws, "t_wake020")["waiting_on"] is not None


def test_failed_cron_start_is_not_retried_every_pass(ws):
    (ws / "noagent").write_text("")
    add_ticket(ws, "t_rec00020", ext={"automation": {"recurring": True, "cron": "* * * * *"}})
    s = Scheduler(ws)
    s.tick(T(8))
    s.tick(T(8, 0).replace(second=50))
    assert runs_started(ws).count("t_rec00020") == 1


def test_leave_it_never_reasks_and_try_again_clears_the_wait(ws):
    (ws / "noagent").write_text("")
    add_ticket(ws, "t_wake021", status="waiting", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"})
    s = Scheduler(ws)
    s.tick(T(8))
    t = tk(ws, "t_wake021")
    t["questions"][0]["answer"] = "Leave it"
    (ws / ".orch/tickets/t_wake021.json").write_text(json.dumps(t))
    s.tick(T(8, 1))
    s.tick(T(8, 2))
    assert len(tk(ws, "t_wake021")["questions"]) == 1 and runs_started(ws).count("t_wake021") == 1
    # a second ticket: Try again with a working agent
    (ws / "noagent").unlink()
    add_ticket(ws, "t_wake022", status="waiting", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"},
               questions=[{"id": "q1", "text": "x", "options": [], "kind": "automation:failure", "answer": "Try again"}],
               ext={"automation": {}})
    s.tick(T(8, 3))
    t = tk(ws, "t_wake022")
    assert t["waiting_on"] is None and t["status"] == "active"


def test_phone_answer_to_own_failure_question_starts_once(ws):
    add_ticket(ws, "t_ask00030", status="active",
               questions=[{"id": "q1", "text": "x", "options": [], "kind": "automation:failure", "answer": "Try again"}])
    (ws / ".orch/secrets").mkdir(parents=True)
    (ws / ".orch/secrets/relay.json").write_text("{}")
    (ws / "inbox.json").write_text(json.dumps([{"id": "m_1", "type": "answer", "ticket": "t_ask00030", "applied": True,
                                                 "body": {"question_id": "q1", "answer": "Try again"}}]))
    Scheduler(ws).tick(T(8))
    assert runs_started(ws) == ["t_ask00030"]


def test_paused_repeat_does_not_start_runs(ws):
    from conftest import T, add_ticket, runs_started

    from orch_automation.loop import Scheduler

    add_ticket(ws, "t_rec00001", ext={"automation": {"recurring": True, "cron": "0 8 * * *", "paused": True}})
    Scheduler(ws).tick(T(9))
    assert runs_started(ws) == []


def test_a_finished_repeat_runs_again_and_is_opened(ws):
    """The agent set the repeating ticket to Done: the next planned run opens it again and starts."""
    add_ticket(ws, "t_rec00009", status="done", created_at="2026-11-01T00:00:00Z",
               ext={"automation": {"recurring": True, "cron": "0 7 * * *", "last_run": "2026-11-03T07:00:00Z"}})
    add_ticket(ws, "t_done0001", status="done")  # a plain finished ticket stays finished
    s = Scheduler(ws)
    assert s.tick(T(7, 1)) == ["t_rec00009"]
    cs = [c["args"] for c in calls(ws)]
    assert ["ticket", "status", "t_rec00009", "open"] in [a[:4] for a in cs]
    assert not any(a[:3] == ["run", "start", "t_done0001"] for a in cs)


def test_a_ready_ticket_with_queued_input_gets_exactly_one_run(ws):
    """Only the automation host starts runs for queued input: a live session ended with a person's answer
    still waiting -> the ticket is Ready with that input queued -> one run, once per input item."""
    add_ticket(ws, "t_queue001", status="ready")
    (ws / "ended-t_queue001").write_text("")
    (ws / "pending-t_queue001").write_text(json.dumps(["p_answer0001"]))
    # a fresh Scheduler per pass: the fake run "ends" at once, which the fast-fail watch would report
    assert Scheduler(ws).tick(T(8)) == ["t_queue001"]
    assert Scheduler(ws).tick(T(8, 1)) == [] and Scheduler(ws).tick(T(8, 2)) == []  # same item: never again
    (ws / "pending-t_queue001").write_text(json.dumps(["p_answer0001", "p_message002"]))
    assert Scheduler(ws).tick(T(8, 3)) == ["t_queue001"]  # a new item: one more run
    starts = [c["args"] for c in calls(ws) if c["args"][:2] == ["run", "start"]]
    assert len(starts) == 2 and all("--mode" not in a for a in starts)


def test_a_text_in_chat_starts_the_helper_once(ws):
    """The Chat's hidden ticket is in no list: core names it (orch chat status); the same queued-input rules
    apply (a person's text only, once per item, nothing while a run holds it)."""
    (ws / "chat-ticket").write_text("t_chat0001")
    (ws / "pending-t_chat0001").write_text(json.dumps(["p_phone00001"]))
    (ws / "ended-t_chat0001").write_text("")
    assert Scheduler(ws).tick(T(8)) == ["t_chat0001"]
    assert Scheduler(ws).tick(T(8, 1)) == []  # same item: never again
    (ws / "pending-t_chat0001").write_text(json.dumps(["p_phone00001", "p_phone00002"]))
    assert Scheduler(ws).tick(T(8, 2)) == ["t_chat0001"]  # a new text: one more run
    (ws / "pending-t_chat0001").write_text(json.dumps(["p_phone00001", "p_phone00002", "p_phone00003"]))
    (ws / "ended-t_chat0001").unlink()  # the helper is running: it reads the text itself
    assert Scheduler(ws).tick(T(8, 3)) == []
    (ws / "pending-t_chat0001").write_text(json.dumps([]))  # only agent input (core lists none): nothing
    (ws / "ended-t_chat0001").write_text("")
    assert Scheduler(ws).tick(T(8, 4)) == []


def test_queued_input_on_a_running_or_not_ready_ticket_starts_nothing(ws):
    add_ticket(ws, "t_queue002", status="ready")  # a run holds it (no ended- file)
    (ws / "pending-t_queue002").write_text(json.dumps(["p_x00000001"]))
    add_ticket(ws, "t_queue003", status="waiting")
    (ws / "ended-t_queue003").write_text("")
    (ws / "pending-t_queue003").write_text(json.dumps(["p_x00000002"]))
    assert Scheduler(ws).tick(T(8)) == [] and runs_started(ws) == []


def test_agent_queued_input_starts_nothing(ws):
    """INVARIANT 2: core lists only a person's input; an agent's own queued input never reaches this pass."""
    add_ticket(ws, "t_queue004", status="ready")
    (ws / "ended-t_queue004").write_text("")
    (ws / "pending-t_queue004").write_text(json.dumps([]))  # core: an agent queued "continue" (not listed)
    assert Scheduler(ws).tick(T(8)) == [] and runs_started(ws) == []


def test_a_failed_start_gives_the_input_back_at_most_three_times(ws):
    add_ticket(ws, "t_queue005", status="ready")
    (ws / "ended-t_queue005").write_text("")
    (ws / "pending-t_queue005").write_text(json.dumps(["p_answer0005"]))
    (ws / "noagent").write_text("")  # every start fails
    for m in range(5):  # (a failed start also asks the person; here the ticket is put back to Ready each time)
        t = json.loads((ws / ".orch/tickets/t_queue005.json").read_text())
        t.update(status="ready", questions=[])
        (ws / ".orch/tickets/t_queue005.json").write_text(json.dumps(t))
        Scheduler(ws).tick(T(8, m))
    assert runs_started(ws).count("t_queue005") == 3
    t = json.loads((ws / ".orch/tickets/t_queue005.json").read_text())
    assert sum("could not start an agent after 3 tries" in str(h.get("text")) for h in t["history"]) == 1
    (ws / "noagent").unlink()
    (ws / "pending-t_queue005").write_text(json.dumps(["p_answer0005", "p_answer0006"]))
    assert Scheduler(ws).tick(T(9)) == ["t_queue005"]  # a new item still starts


def test_the_seen_set_keeps_only_what_still_waits(ws):
    from orch_automation.runner import load_state

    add_ticket(ws, "t_queue006", status="ready")
    (ws / "ended-t_queue006").write_text("")
    (ws / "pending-t_queue006").write_text(json.dumps(["p_a0000001"]))
    Scheduler(ws).tick(T(8))
    (ws / "pending-t_queue006").write_text(json.dumps([]))  # delivered
    Scheduler(ws).tick(T(8, 1))
    assert load_state(ws)["t_queue006"]["queued_started"] == []


def test_a_ticket_started_this_pass_or_switched_off_is_skipped(ws):
    add_ticket(ws, "t_queue007", status="ready", ext={"automation": {"paused": True}})
    (ws / "ended-t_queue007").write_text("")
    (ws / "pending-t_queue007").write_text(json.dumps(["p_b0000001"]))
    s = Scheduler(ws)
    assert s.queued_input(T(8), skip=[]) == []  # switched off
    add_ticket(ws, "t_queue008", status="ready")
    (ws / "ended-t_queue008").write_text("")
    (ws / "pending-t_queue008").write_text(json.dumps(["p_b0000002"]))
    assert s.queued_input(T(8), skip=["t_queue008"]) == []  # already started this pass
    assert runs_started(ws) == []


def test_a_start_with_an_unknown_result_gives_the_ids_back(ws, monkeypatch):
    from orch_automation import orchcli

    monkeypatch.setattr(orchcli, "run_start", lambda *a, **k: {"result": "blocked"})
    add_ticket(ws, "t_queue009", status="ready")
    (ws / "ended-t_queue009").write_text("")
    (ws / "pending-t_queue009").write_text(json.dumps(["p_c0000001"]))
    Scheduler(ws).tick(T(8))
    from orch_automation.runner import load_state

    st = load_state(ws)["t_queue009"]
    assert st["queued_started"] == [] and st["queued_tries"] == {"p_c0000001": 1}


def test_orch_json_is_read_from_stdout_only(ws, tmp_path, monkeypatch):
    """Delta-8 (6): warnings on stderr never break the JSON."""
    import stat
    import sys

    from orch_automation import orchcli

    f = tmp_path / "orch-noisy"
    f.write_text(f"#!{sys.executable}\nimport sys\nprint('orch: a warning', file=sys.stderr)\nprint('{{\"ok\": true}}')\n")
    f.chmod(f.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("ORCH_BIN", str(f))
    assert orchcli.call(ws, "run", "status", "t_x", by=False) == {"ok": True}


def test_input_a_busy_run_does_not_read_is_said_once_after_30_minutes(ws):
    add_ticket(ws, "t_queue010", status="ready")
    (ws / "ended-t_queue010").write_text("")
    (ws / "pending-t_queue010").write_text(json.dumps(["p_d0000001"]))
    (ws / "busy-t_queue010").write_text("")  # the start finds a run holding it: "pending"
    Scheduler(ws).tick(T(8))
    (ws / "ended-t_queue010").unlink()  # that run keeps holding it and does not read the input
    for m in (10, 31, 45):
        Scheduler(ws).tick(T(8, m))
    t = json.loads((ws / ".orch/tickets/t_queue010.json").read_text())
    assert sum("waited 30 minutes" in str(h.get("text")) for h in t["history"]) == 1
    assert runs_started(ws).count("t_queue010") == 1  # pending is not a retry storm either


def test_a_capped_id_is_never_tried_or_said_again(ws):
    add_ticket(ws, "t_queue011", status="ready")
    (ws / "ended-t_queue011").write_text("")
    (ws / "pending-t_queue011").write_text(json.dumps(["p_e0000001"]))
    (ws / "noagent").write_text("")
    for m in range(6):
        t = json.loads((ws / ".orch/tickets/t_queue011.json").read_text())
        t.update(status="ready", questions=[])
        (ws / ".orch/tickets/t_queue011.json").write_text(json.dumps(t))
        Scheduler(ws).tick(T(8, m))
    t = json.loads((ws / ".orch/tickets/t_queue011.json").read_text())
    assert runs_started(ws).count("t_queue011") == 3
    assert sum("after 3 tries" in str(h.get("text")) for h in t["history"]) == 1


def test_input_a_run_left_unread_may_start_one_run_after_it_ended(ws):
    add_ticket(ws, "t_queue012", status="ready")
    (ws / "ended-t_queue012").write_text("")
    (ws / "pending-t_queue012").write_text(json.dumps(["p_f0000001"]))
    (ws / "busy-t_queue012").write_text("")
    Scheduler(ws).tick(T(8))  # pending: a run holds it
    (ws / "busy-t_queue012").unlink()  # that run ended without reading it
    assert Scheduler(ws).tick(T(8, 1)) == ["t_queue012"]  # given back, then one run for it
    assert Scheduler(ws).tick(T(8, 2)) == []
