"""Task ops: edit, move, remove, reopen, start, stop; derived blocked; stale 'doing' marker."""

import json
import time

from orch import tickets


def read(proj, tid):
    return json.loads((proj / ".orch" / "tickets" / f"{tid}.json").read_text(encoding="utf-8"))


def with_checks(proj, run, new_ticket, n=3):
    tid = new_ticket("Q3 invoices")
    for i in range(n):
        run("check", "add", tid, f"step {i + 1}")
    return tid


def test_edit_and_move(proj, run, validate, new_ticket):
    tid = with_checks(proj, run, new_ticket)
    code, out, _ = run("check", "edit", tid, "c2", "Ask about the date format")
    assert code == 0 and "c2 renamed" in out
    code, out, _ = run("check", "move", tid, "c3", "--after", "c1")
    assert code == 0 and "c3 now follows c1" in out
    t = read(proj, tid)
    validate(t)
    assert [c["id"] for c in t["checklist"]] == ["c1", "c3", "c2"]
    assert t["checklist"][2]["text"] == "Ask about the date format"
    assert run("check", "move", tid, "c1", "--after", "c9")[0] == 2
    assert run("check", "move", tid, "c1", "--after", "c1")[0] == 2


def test_remove_keeps_text_and_proof_in_history(proj, run, validate, new_ticket):
    tid = with_checks(proj, run, new_ticket)
    run("check", "done", tid, "c1", "--command", "pytest -q")
    f = proj / "x.csv"
    f.write_text("a")
    tickets.apply_op(
        proj,
        tid,
        lambda t: t["checklist"][0]["evidence"].append(
            {"type": "file", "ref": "out/q3.csv", "text": "12 rows"}
        ),
    )
    code, out, _ = run("check", "remove", tid, "c1")
    assert code == 0 and "c1 removed" in out
    t = read(proj, tid)
    validate(t)
    assert [c["id"] for c in t["checklist"]] == ["c2", "c3"]
    line = t["history"][-1]["text"]
    assert "step 1" in line and "was done" in line and "pytest -q" in line and "q3.csv (12 rows)" in line
    assert run("check", "remove", tid, "c2")[0] == 0  # open ones too
    assert run("check", "remove", tid, "c2")[0] == 2  # gone


def test_reopen_keeps_old_proof_in_history(proj, run, validate, new_ticket):
    tid = with_checks(proj, run, new_ticket)
    run("check", "done", tid, "c1", "--note", "looked fine")
    code, out, _ = run("check", "reopen", tid, "c1")
    assert code == 0 and "open again" in out
    t = read(proj, tid)
    validate(t)
    c = t["checklist"][0]
    assert c["done"] is False and c["evidence"] == []
    assert "looked fine" in t["history"][-1]["text"]
    assert run("ticket", "status", tid, "done", "--by", "agent:generic")[0] == 2


def test_start_stop_and_single_doing(proj, run, validate, new_ticket):
    tid = with_checks(proj, run, new_ticket)
    code, out, _ = run("check", "start", tid, "c1", "--by", "agent:claude-code")
    assert code == 0 and "agent:claude-code is on it" in out
    run("check", "start", tid, "c2", "--by", "agent:claude-code")
    t = read(proj, tid)
    validate(t)
    assert [c.get("state") for c in t["checklist"]] == [None, "doing", None]
    assert t["checklist"][1]["by"] == "agent:claude-code" and t["checklist"][1]["at"].endswith("Z")
    run("check", "done", tid, "c2", "--note", "ok")
    c2 = read(proj, tid)["checklist"][1]
    assert "state" not in c2 and "by" not in c2 and "at" not in c2
    run("check", "start", tid, "c3")
    assert run("check", "stop", tid, "c3")[0] == 0
    assert "state" not in read(proj, tid)["checklist"][2]
    assert run("check", "start", tid, "c2")[0] == 2  # done: reopen first


def test_ask_on_check_shows_waiting_and_blocked_is_not_stored(proj, run, validate, new_ticket):
    tid = with_checks(proj, run, new_ticket)
    code, out, _ = run("ask", tid, "Which date format?", "--option", "A", "--check", "c2")
    assert code == 0 and "Asked q1 on c2, waiting" in out
    t = read(proj, tid)
    validate(t)
    assert t["questions"][0]["check"] == "c2" and "blocked" not in json.dumps(t["checklist"])
    shown = run("ticket", "show", tid)[1]
    assert "waiting for your answer (q1)" in shown


def _doing(proj, tid, at):
    def op(t):
        t["checklist"][0].update({"state": "doing", "by": "agent:claude-code", "at": at})

    tickets.apply_op(proj, tid, op)


def _iso(secs_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - secs_ago))


def test_fresh_doing_is_on_it(proj, run, new_ticket):
    tid = with_checks(proj, run, new_ticket)
    _doing(proj, tid, _iso(60))
    assert "agent:claude-code is on it" in run("ticket", "show", tid)[1]


def test_old_doing_is_was_on_it(proj, run, new_ticket):
    tid = with_checks(proj, run, new_ticket)
    _doing(proj, tid, _iso(5 * 3600))
    assert "was on it (5 h ago, not running)" in run("ticket", "show", tid)[1]


def test_run_record_without_live_pid_is_stale(proj, run, new_ticket):
    tid = with_checks(proj, run, new_ticket)
    _doing(proj, tid, _iso(60))
    rec = proj / ".orch" / "run" / "tickets" / f"{tid}.json"
    rec.parent.mkdir(parents=True)
    rec.write_text(json.dumps({"pid": 2**22 + 12345}))
    assert "was on it" in run("ticket", "show", tid)[1]
    import os

    rec.write_text(json.dumps({"pid": os.getpid()}))
    assert "is on it" in run("ticket", "show", tid)[1]


def test_stale_check_uses_services_pid_alive_and_never_signals(proj, run, new_ticket, monkeypatch):
    import os

    from orch import services

    tid = with_checks(proj, run, new_ticket)
    _doing(proj, tid, _iso(60))
    rec = proj / ".orch" / "run" / "tickets" / f"{tid}.json"
    rec.parent.mkdir(parents=True)
    rec.write_text(json.dumps({"pid": 4242}))
    seen = []
    monkeypatch.setattr(services, "pid_alive", lambda pid: seen.append(pid) or True)
    monkeypatch.setattr(os, "kill", lambda *a: (_ for _ in ()).throw(AssertionError("os.kill called")))
    t = tickets.load(proj, tid)
    assert tickets.doing_stale(proj, t, t["checklist"][0]) is False and seen == [4242]


def test_bad_ticket_id_reads_no_run_file(proj, run, new_ticket, monkeypatch):
    tid = with_checks(proj, run, new_ticket)
    _doing(proj, tid, _iso(60))
    t = tickets.load(proj, tid)
    t["id"] = "../../x"
    opened = []
    monkeypatch.setattr(tickets.Path, "is_file", lambda self: opened.append(str(self)) or False)
    assert tickets.doing_stale(proj, t, t["checklist"][0]) is False
    assert opened == []


# ---- Won't do (a person's decision; an agent can only ask)


def test_wont_do_by_person_counts_as_resolved_and_undo(proj, run, validate, new_ticket):
    tid = with_checks(proj, run, new_ticket)
    code, out, _ = run("check", "wont-do", tid, "c2", "--reason", "Finance pulls it", "--by", "human:tester")
    assert code == 0 and "Won't do" in out
    t = read(proj, tid)
    validate(t)
    c2 = t["checklist"][1]
    assert c2["wont_do"] is True and c2["done"] is False and c2["reason"] == "Finance pulls it"
    assert t["history"][-1]["by"] == "human:tester" and t["history"][-1]["text"] == "Marked c2 as won't do"
    assert tickets.history_line(t["history"][-1]["text"], t["checklist"]) == "Marked as won't do: step 2"
    assert tickets.checks_done(t) == (1, 3)  # only c2 resolved
    code, out, _ = run("ticket", "show", tid)
    assert "Won't do: Finance pulls it" in out
    # undo by the person
    assert run("check", "reopen", tid, "c2", "--by", "human:tester")[0] == 0
    c2 = read(proj, tid)["checklist"][1]
    assert "wont_do" not in c2 and "reason" not in c2 and c2["done"] is False


def test_wont_do_counts_for_finishing_the_ticket(proj, run, new_ticket, monkeypatch):
    tid = with_checks(proj, run, new_ticket, n=2)
    run("check", "done", tid, "c1", "--note", "ok", "--by", "human:tester")
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    with_open = tickets.load(proj, tid)
    try:
        tickets._check_can_finish(with_open)
        raise AssertionError("open step must block")
    except tickets.Refused:
        pass
    run("check", "wont-do", tid, "c2", "--by", "human:tester")
    tickets._check_can_finish(tickets.load(proj, tid))  # resolved without proof: no refusal


def test_agent_can_never_set_or_undo_wont_do(proj, run, new_ticket, monkeypatch):
    tid = with_checks(proj, run, new_ticket)
    # an explicit agent actor
    code, _, err = run("check", "wont-do", tid, "c1", "--by", "agent:claude")
    assert code == 2 and "orch ask" in err
    # a person's name given from inside an agent session (environment wins)
    monkeypatch.setenv("CLAUDECODE", "1")
    code, _, err = run("check", "wont-do", tid, "c1", "--by", "human:tester")
    assert code == 2
    assert "wont_do" not in read(proj, tid)["checklist"][0]
    monkeypatch.delenv("CLAUDECODE")
    run("check", "wont-do", tid, "c1", "--by", "human:tester")
    monkeypatch.setenv("CLAUDECODE", "1")
    # an agent can neither reopen it, tick it, start it nor patch it in
    for argv in (
        ("check", "reopen", tid, "c1", "--by", "human:tester"),
        ("check", "reopen", tid, "c1"),
        ("check", "done", tid, "c1", "--note", "x"),
        ("check", "start", tid, "c1"),
    ):
        assert run(*argv)[0] == 2, argv
    assert run("ticket", "patch", tid, "--if-revision", "1", '{"checklist": []}')[0] == 2
    assert read(proj, tid)["checklist"][0]["wont_do"] is True


def test_wont_do_reason_and_done_step(proj, run, new_ticket):
    tid = with_checks(proj, run, new_ticket)
    assert run("check", "wont-do", tid, "c1", "--reason", "x" * 201, "--by", "human:tester")[0] == 2
    run("check", "done", tid, "c1", "--note", "ok", "--by", "human:tester")
    assert run("check", "wont-do", tid, "c1", "--by", "human:tester")[0] == 2  # done: reopen first
    assert run("check", "wont-do", tid, "c9", "--by", "human:tester")[0] == 2  # unknown step
