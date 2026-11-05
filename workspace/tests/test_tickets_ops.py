"""One write path (apply_op), new ticket fields, questions with kind/via, provenance, agent sessions."""

import json
import subprocess
import sys

import pytest

from orch import tickets


def read(proj, tid):
    return json.loads((proj / ".orch" / "tickets" / f"{tid}.json").read_text(encoding="utf-8"))


def test_two_processes_race_both_land(proj, run, new_ticket):
    tid = new_ticket()
    for i in (1, 2, 3, 4):
        assert run("check", "add", tid, f"step {i}")[0] == 0
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "orch",
                "check",
                "done",
                tid,
                f"c{i}",
                "--note",
                f"n{i}",
                "--by",
                "agent:x",
            ],
            cwd=proj,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for i in (1, 2, 3, 4)
    ]
    outs = [p.communicate() for p in procs]
    assert [p.returncode for p in procs] == [0, 0, 0, 0], outs
    t = read(proj, tid)
    assert all(c["done"] for c in t["checklist"])
    assert t["revision"] == 1 + 4 + 4  # created, 4 adds, 4 dones: no lost update


def test_stale_expect_refused_with_current(proj, run, new_ticket):
    tid = new_ticket()
    run("check", "add", tid, "Ask finance which date format")
    assert run("check", "edit", tid, "c1", "Ask about dates", "--by", "agent:claude-code")[0] == 0
    code, out, err = run(
        "check", "edit", tid, "c1", "Mine", "--was", "Ask finance which date format", "--json"
    )
    assert code == 2 and "Refused:" in err
    j = json.loads(out)
    assert j["changed_by"] == "agent:claude-code" and j["current"]["text"] == "Ask about dates"
    assert j["revision"] == read(proj, tid)["revision"]
    assert read(proj, tid)["checklist"][0]["text"] == "Ask about dates"


def test_if_revision_on_check_edit_and_ticket_edit(proj, run, new_ticket):
    tid = new_ticket()
    run("check", "add", tid, "x")
    rev = read(proj, tid)["revision"]
    assert run("check", "edit", tid, "c1", "y", "--if-revision", str(rev - 1), "--json")[0] == 2
    assert run("ticket", "edit", tid, "--owner", "A", "--if-revision", str(rev - 1))[0] == 2
    assert run("ticket", "edit", tid, "--owner", "A", "--if-revision", str(rev))[0] == 0


def test_plain_op_lands_on_latest_revision(proj, new_ticket):
    tid = new_ticket()
    t = tickets.load(proj, tid)  # an old copy
    tickets.log(proj, tid, "one", "agent:x")
    tickets.apply_op(
        proj, tid, lambda x: x["history"].append({"at": tickets.now(), "by": "agent:x", "text": "two"})
    )
    assert t["revision"] < tickets.load(proj, tid)["revision"]
    assert [h["text"] for h in read(proj, tid)["history"]][-2:] == ["one", "two"]


def test_busy_message(proj, new_ticket, monkeypatch):
    tid = new_ticket()
    lock = proj / ".orch" / "tickets" / f".lock-{tid}"
    lock.write_text("")
    monkeypatch.setattr(tickets.time, "monotonic", iter([0, 100, 200, 300]).__next__)
    with pytest.raises(tickets.Refused, match="busy"):
        tickets.log(proj, tid, "x", "agent:x")


def test_fields_owner_due_note_summary(proj, run, validate, new_ticket):
    tid = new_ticket()
    code, out, _ = run(
        "ticket", "edit", tid, "--owner", "Severin", "--due", "2026-11-10", "--note", "Before close"
    )
    assert code == 0 and "Saved (revision" in out
    t = read(proj, tid)
    assert (t["owner"], t["due"], t["note"]) == ("Severin", "2026-11-10", "Before close")
    validate(t)
    code, _, err = run("ticket", "edit", tid, "--due", "10.11.2026")
    assert code == 2 and "due must be a date like 2026-11-10" in err
    assert run("ticket", "edit", tid, "--due", "2026-02-30")[0] == 2
    assert run("ticket", "edit", tid, "--owner", "x" * 65)[0] == 2
    assert run("ticket", "edit", tid, "--note", "x" * 2001)[0] == 2
    assert run("ticket", "edit", tid, "--owner", "")[0] == 0 and "owner" not in read(proj, tid)
    assert run("ticket", "edit", tid)[0] == 2  # nothing to change


def test_summary_and_show_first(proj, run, validate, new_ticket):
    tid = new_ticket("Q3 summary")
    n = len(read(proj, tid)["history"])
    code, out, _ = run("ticket", "summary", tid, "Draft ready, waiting for Anna")
    assert code == 0 and "Summary saved" in out
    t = read(proj, tid)
    validate(t)
    assert t["summary"] == "Draft ready, waiting for Anna" and len(t["history"]) == n  # no history spam
    shown = run("ticket", "show", tid)[1].splitlines()
    assert shown[1] == "Draft ready, waiting for Anna"
    code, _, err = run("ticket", "summary", tid, "x" * 201)
    assert code == 2 and "A summary is at most 200 characters" in err


def test_patch_new_fields_and_conflict_json(proj, run, new_ticket):
    tid = new_ticket()
    code, out, _ = run(
        "ticket", "patch", tid, '{"due": "2026-11-12", "summary": "s"}', "--if-revision", "1", "--json"
    )
    assert code == 0
    code, out, _ = run("ticket", "patch", tid, '{"due": "2026-11-13"}', "--if-revision", "1", "--json")
    j = json.loads(out)
    assert code == 2 and j["revision"] == 2 and j["current"]["due"] == "2026-11-12" and j["changed_by"]
    assert run("ticket", "patch", tid, '{"due": "bad"}', "--if-revision", "2")[0] == 2


def test_via_is_a_free_token(proj, run, validate, new_ticket):
    tid = new_ticket()
    run("ask", tid, "Which?", "--option", "A", "--option", "B")
    code, _, err = run("answer", tid, "q1", "A", "--via", "dash board")
    assert code == 2 and "via must be a short word" in err
    code, out, _ = run("answer", tid, "q1", "a", "--via", "dashboard", "--by", "human:marco")
    assert code == 0
    t = read(proj, tid)
    validate(t)
    assert t["questions"][0]["via"] == "dashboard" and t["history"][-1]["via"] == "dashboard"
    code, _, err = run("answer", tid, "q1", "B")
    assert code == 2 and "already answered" in err  # first answer wins


def test_history_via_defaults_to_cli(proj, run, validate, new_ticket):
    tid = new_ticket()
    run("log", tid, "hello")
    t = read(proj, tid)
    validate(t)
    assert t["history"][-1]["via"] == "cli"


def test_ask_kind_action_check_and_addon_note(proj, run, validate, new_ticket):
    tid = new_ticket()
    run("check", "add", tid, "Ask finance")
    code, out, _ = run(
        "ask",
        tid,
        "Retry?",
        "--kind",
        "scheduler:failure",
        "--option",
        "Try again",
        "--option",
        "Stop",
        "--action",
        '{"run": "r1"}',
        "--check",
        "c1",
        "--json",
    )
    assert code == 0
    q = json.loads(out)
    assert (q["kind"], q["action"], q["check"]) == ("scheduler:failure", {"run": "r1"}, "c1")
    validate(read(proj, tid))
    code, out, _ = run("answer", tid, "q1", "try again")
    assert code == 0 and "Answered: Try again" in out
    assert "Recorded. The scheduler acts on it when it runs." in out
    assert run("ask", tid, "x", "--kind", "Bad Kind")[0] == 2
    assert run("ask", tid, "x", "--check", "c9")[0] == 2
    assert run("ask", tid, "x", "--action", "[1]")[0] == 2


def test_plain_answer_has_no_addon_note(proj, run, new_ticket):
    tid = new_ticket()
    run("ask", tid, "Ok?", "--option", "Yes")
    assert "Recorded" not in run("answer", tid, "q1", "Yes")[1]


def test_explicit_human_by_not_refused_under_agent(proj, run, new_ticket, monkeypatch):
    tid = new_ticket()
    monkeypatch.setenv("CLAUDECODE", "1")
    code, _, _ = run("log", tid, "from a person", "--by", "human:marco")
    assert code == 0 and read(proj, tid)["history"][-1]["by"] == "human:marco"
    run("log", tid, "default")
    assert read(proj, tid)["history"][-1]["by"] == "agent:claude-code"


def test_sessions_record_and_find(proj, validate, new_ticket):
    tid = new_ticket()
    tickets.record_session(proj, tid, "my-agent", "s-1", "laptop")
    tickets.record_session(proj, tid, "my-agent", "s-1", "vps")
    tickets.record_session(proj, tid, "my-agent", "s-2", "laptop")  # same agent+host: updated, not added
    t = tickets.load(proj, tid)
    validate(t)
    assert len(t["sessions"]) == 2
    assert tickets.sessions_for(t, "my-agent", "laptop") == "s-2"
    assert tickets.sessions_for(t, "my-agent", "vps") == "s-1"
    assert tickets.sessions_for(t, "other", "laptop") is None
    assert tickets.sessions_for(t, "my-agent", "elsewhere") is None
    for i in range(40):
        tickets.record_session(proj, tid, "a", f"s{i}", f"h{i}")
    assert len(tickets.load(proj, tid)["sessions"]) == 32


def test_core_names_no_addon_or_tool_in_new_code():
    from pathlib import Path

    for f in ("tickets.py", "cli.py"):
        text = (Path(tickets.__file__).parent / f).read_text(encoding="utf-8").lower()
        for word in ("scheduler", "netbird", "claude", "codex"):
            assert word not in text.replace("claude_code_entrypoint", ""), (f, word)
