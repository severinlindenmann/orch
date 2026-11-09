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


def test_covers_add_edit_and_show(proj, run, validate, new_ticket):
    tid = new_ticket("Export invoices")
    assert run("check", "add", tid, "Add button", "--covers", "A CSV  download button")[0] == 0
    run("check", "add", tid, "Phone layout")
    t = read(proj, tid)
    validate(t)
    assert t["checklist"][0]["covers"] == "A CSV download button" and "covers" not in t["checklist"][1]
    assert run("check", "edit", tid, "c2", "--covers", "works on the phone")[0] == 0
    t = read(proj, tid)
    validate(t)
    assert t["checklist"][1]["covers"] == "works on the phone" and t["checklist"][1]["text"] == "Phone layout"
    assert run("check", "edit", tid, "c2")[0] == 2  # nothing to change
    assert run("check", "add", tid, "x", "--covers", "y" * 301)[0] == 2
    code, out, _ = run("ticket", "show", tid)
    assert code == 0 and "Proof: No checks recorded" in out
