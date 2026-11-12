import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import CONTRACTS

from orch import runs, runs_live, tickets
from orch.errors import Refused


def read(proj, tid):
    return json.loads((proj / ".orch" / "tickets" / f"{tid}.json").read_text(encoding="utf-8"))


def test_example_validates(validate):
    validate(json.loads((CONTRACTS / "review" / "ticket.example.json").read_text(encoding="utf-8")))


def test_new_is_valid_and_listed(proj, run, validate, new_ticket):
    tid = new_ticket("Rename field X")
    t = read(proj, tid)
    validate(t)
    assert tid.startswith("t_") and t["status"] == "open" and t["history"][0]["text"] == "Created"
    code, out, _ = run("ticket", "list")
    assert code == 0 and tid in out and "Rename field X" in out


def test_ids_are_random(proj, new_ticket):
    assert len({new_ticket() for _ in range(5)}) == 5


def test_unknown_fields_preserved(proj, run, validate, new_ticket):
    tid = new_ticket()
    p = proj / ".orch" / "tickets" / f"{tid}.json"
    t = json.loads(p.read_text(encoding="utf-8"))
    t["future"] = {"a": 1}
    t["checklist"].append({"id": "c1", "text": "x", "done": False, "evidence": [], "extra": "keep"})
    t["ext"] = {"other": {"k": "v"}}
    p.write_text(json.dumps(t), encoding="utf-8")
    assert run("log", tid, "hello")[0] == 0
    assert run("ticket", "status", tid, "active")[0] == 0
    assert run("check", "done", tid, "c1", "--evidence", '{"type":"note","ref":"ok"}')[0] == 0
    assert run("ext", "set", tid, "dashboard", '{"pinned":true}')[0] == 0
    t2 = read(proj, tid)
    validate(t2)
    assert t2["future"] == {"a": 1}
    assert t2["checklist"][0]["extra"] == "keep"
    assert t2["ext"]["other"] == {"k": "v"} and t2["ext"]["dashboard"] == {"pinned": True}


def test_no_temp_files_left(proj, new_ticket, run):
    tid = new_ticket()
    run("log", tid, "x")
    names = [p.name for p in (proj / ".orch" / "tickets").iterdir()]
    assert names == [f"{tid}.json"]


def test_check_done_needs_evidence(proj, run, new_ticket, validate):
    tid = new_ticket()
    assert run("check", "add", tid, "Implement")[0] == 0
    code, _, err = run("check", "done", tid, "c1")
    assert code == 2 and "proof" in err
    code, _, err = run("check", "done", tid, "c1", "--evidence", '{"type":"bogus","ref":"x"}')
    assert code == 2
    assert read(proj, tid)["checklist"][0]["done"] is False
    code, out, _ = run(
        "check", "done", tid, "c1", "--evidence", '{"type":"command","ref":"pytest -q","text":"12 passed"}'
    )
    assert code == 0 and "pytest -q" in out
    t = read(proj, tid)
    validate(t)
    assert t["checklist"][0]["done"] and t["checklist"][0]["evidence"][0]["text"] == "12 passed"


def test_done_refused_when_checked_without_evidence(proj, run, new_ticket):
    tid = new_ticket()
    p = proj / ".orch" / "tickets" / f"{tid}.json"
    t = json.loads(p.read_text(encoding="utf-8"))
    t["checklist"].append({"id": "c1", "text": "x", "done": True, "evidence": []})
    p.write_text(json.dumps(t), encoding="utf-8")
    code, _, err = run("ticket", "status", tid, "done", "--by", "agent:generic")
    assert code == 2 and "c1" in err
    assert read(proj, tid)["status"] == "open"


def test_status_flow_and_history(proj, run, new_ticket, validate):
    tid = new_ticket()
    for s in ("active", "done"):
        assert run("ticket", "status", tid, s)[0] == 0
    t = read(proj, tid)
    validate(t)
    assert t["status"] == "done" and len(t["history"]) == 3
    with pytest.raises(SystemExit):
        run("ticket", "status", tid, "nonsense")


def test_log_actor(proj, run, new_ticket, monkeypatch):
    tid = new_ticket()
    run("log", tid, "by flag", "--by", "agent:codex")
    monkeypatch.setenv("CLAUDECODE", "1")
    run("log", tid, "by env")
    h = read(proj, tid)["history"]
    assert h[-2]["by"] == "agent:codex" and h[-1]["by"] == "agent:claude"
    monkeypatch.delenv("CLAUDECODE")
    run("log", tid, "human")
    assert read(proj, tid)["history"][-1]["by"].startswith("human:")


def test_bad_actor_refused(proj, run, new_ticket):
    tid = new_ticket()
    assert run("log", tid, "x", "--by", "robot")[0] == 2


def test_link_and_ext(proj, run, new_ticket, validate):
    tid = new_ticket()
    assert run("ref", "add", tid, "https://j/1", "--kind", "jira", "--title", "J-1")[0] == 0
    assert run("ref", "add", tid, "https://example.com", "--kind", "Bad Type")[0] == 2
    assert run("ext", "set", tid, "scheduler", '{"cron":"0 8 * * 1"}')[0] == 0
    assert run("ext", "set", tid, "scheduler", "not json")[0] == 2
    t = read(proj, tid)
    validate(t)
    assert t["refs"][0]["title"] == "J-1" and t["ext"]["scheduler"]["cron"] == "0 8 * * 1"


def test_ask_answer(proj, run, new_ticket, validate):
    tid = new_ticket()
    code, _, _ = run(
        "ask", tid, "DATE or TIMESTAMP?", "--option", "DATE", "--option", "TIMESTAMP", "--recommend", "DATE"
    )
    assert code == 0
    t = read(proj, tid)
    validate(t)
    assert t["status"] == "waiting" and t["waiting_on"] == {"kind": "question", "ref": "q1"}
    assert t["questions"][0]["recommended"] == "DATE"
    assert run("answer", tid, "q1", "TIMESTAMP", "--by", "human:Severin", "--via", "phone")[0] == 0
    t = read(proj, tid)
    validate(t)
    q = t["questions"][0]
    assert (q["answer"], q["answered_by"], q["via"]) == ("TIMESTAMP", "human:Severin", "phone")
    assert t["status"] == "ready" and t["waiting_on"] is None  # answered, no agent runs: Ready, not Working
    assert run("answer", tid, "q1", "DATE")[0] == 2


def test_ask_recommend_must_be_option(proj, run, new_ticket):
    tid = new_ticket()
    assert run("ask", tid, "q?", "--option", "A", "--recommend", "B")[0] == 2


def test_wait_until_and_on(proj, run, new_ticket, validate):
    tid = new_ticket()
    assert run("wait", tid, "--until", "2026-11-05T08:00:00+01:00")[0] == 0
    t = read(proj, tid)
    validate(t)
    assert t["status"] == "waiting"
    assert t["waiting_on"] == {"kind": "time", "until": "2026-11-05T07:00:00Z"}
    assert "wake_at" not in t and "type" not in t
    for on, want in (
        ("ticket:t_other1", {"kind": "ticket", "ref": "t_other1"}),
        ("question:q1", {"kind": "question", "ref": "q1"}),
        ("external:wh_1", {"kind": "external", "ref": "wh_1"}),
    ):
        assert run("ticket", "wait", tid, "--on", on)[0] == 0
        t = read(proj, tid)
        validate(t)
        assert t["waiting_on"] == want and t["status"] == "waiting"
    assert run("wait", tid, "--until", "garbage")[0] == 2
    assert run("wait", tid, "--on", "nokind:x")[0] == 2
    assert run("wait", tid, "--on", "time:2026-11-05T08:00:00Z")[0] == 2  # a time is --until
    assert run("wait", tid, "--on", "webhook:wh_1")[0] == 2  # old kinds are gone
    assert run("wait", tid)[0] == 2
    assert run("wait", tid, "--clear")[0] == 0
    t = read(proj, tid)
    assert t["waiting_on"] is None and t["status"] == "active"


def test_core_ticket_has_no_type_or_recurring(proj, run, validate):
    with pytest.raises(SystemExit):
        run("ticket", "new", "Weekly", "--recurring", "0 7 * * 1")
    code, out, _ = run("ticket", "new", "Plain", "--json")
    t = json.loads(out)
    validate(t)
    assert "type" not in t and "wake_at" not in t and t["revision"] == 1


def test_revision_goes_up_on_every_write(proj, run, new_ticket):
    tid = new_ticket()
    assert read(proj, tid)["revision"] == 1
    run("log", tid, "x")
    run("ticket", "status", tid, "active")
    assert read(proj, tid)["revision"] == 3


def test_patch_with_revision_check(proj, run, new_ticket, validate):
    tid = new_ticket()
    code, out, _ = run("ticket", "patch", tid, "--if-revision", "1", '{"title": "Renamed"}', "--json")
    assert code == 0 and json.loads(out)["revision"] == 2
    validate(read(proj, tid))
    code, out, err = run("ticket", "patch", tid, "--if-revision", "1", '{"title": "Late"}', "--json")
    assert code == 2 and "revision" in json.loads(out) and "Refused:" in err
    assert read(proj, tid)["title"] == "Renamed"
    w = '{"status": "waiting", "waiting_on": {"kind": "time", "until": "2030-01-01T00:00:00Z"}}'
    assert run("ticket", "patch", tid, "--if-revision", "2", w)[0] == 0
    t = read(proj, tid)
    validate(t)
    assert t["status"] == "waiting" and t["waiting_on"]["kind"] == "time"
    assert run("ticket", "patch", tid, "--if-revision", "3", '{"status": "active"}')[0] == 0
    assert read(proj, tid)["waiting_on"] is None


def test_patch_only_allowed_fields(proj, run, new_ticket):
    tid = new_ticket()
    for bad in ('{"id": "t_x"}', '{"history": []}', '{"revision": 9}', '{"ext": {}}', "[]", "{}", "nope"):
        assert run("ticket", "patch", tid, "--if-revision", "1", bad)[0] == 2, bad
    assert run("ticket", "patch", tid, "--if-revision", "1", '{"status": "bogus"}')[0] == 2
    assert run("ticket", "patch", tid, "--if-revision", "1", '{"waiting_on": {"kind": "time"}}')[0] == 2
    assert run("ticket", "patch", tid, "--if-revision", "1", '{"waiting_on": {"kind": "ticket"}}')[0] == 2
    assert read(proj, tid)["revision"] == 1
    run("check", "add", tid, "step")
    assert (
        run("ticket", "patch", tid, "--if-revision", "2", '{"status": "done"}', "--by", "agent:generic")[0]
        == 2
    )  # same rule as status


def test_concurrent_write_is_refused_not_lost(proj, new_ticket):
    from orch import tickets

    tid = new_ticket()
    a = tickets.load(proj, tid)
    b = tickets.load(proj, tid)
    a["title"] = "A"
    tickets.save(proj, a)
    b["title"] = "B"
    with pytest.raises(Refused):
        tickets.save(proj, b)
    assert tickets.load(proj, tid)["title"] == "A"


def test_stale_lock_does_not_block(proj, run, new_ticket):
    import os

    tid = new_ticket()
    lock = proj / ".orch" / "tickets" / f".lock-{tid}"
    lock.write_text("", encoding="utf-8")
    old = lock.stat().st_mtime - 120
    os.utime(lock, (old, old))
    assert run("log", tid, "x")[0] == 0 and not lock.exists()


def test_edit_and_show_json(proj, run, new_ticket):
    tid = new_ticket()
    assert run("ticket", "edit", tid, "--title", "New title")[0] == 0
    code, out, _ = run("ticket", "show", tid, "--json")
    assert json.loads(out)["title"] == "New title"
    code, out, _ = run("ticket", "show", tid)
    assert "Status: Backlog" in out


def test_missing_ticket_refused(proj, run):
    code, _, err = run("ticket", "show", "t_abcdef")
    assert code == 2 and "doesn't exist" in err
    assert run("ticket", "show", "nope")[0] == 2


def test_works_without_git(proj, new_ticket):
    assert not (Path(proj) / ".git").exists()
    new_ticket()


def test_answer_matches_options_case_insensitively_or_free_text(proj, run, new_ticket):
    tid = new_ticket()
    run("ask", tid, "Which day?", "--option", "Friday", "--option", "Monday")
    assert run("answer", tid, "q1", "monday")[0] == 0
    assert read(proj, tid)["questions"][0]["answer"] == "Monday"
    run("ask", tid, "Which day?", "--option", "Friday", "--option", "Monday")
    assert run("answer", tid, "q2", "next Tuesday please", "--via", "phone", "--by", "human:x")[0] == 0
    assert read(proj, tid)["questions"][1]["answer"] == "next Tuesday please"


def test_agent_cannot_answer_a_phone_question(proj, run, new_ticket):
    import json

    tid = new_ticket()
    run("ask", tid, "Which?", "--option", "A")
    d = proj / ".orch" / "secrets"
    d.mkdir(parents=True, exist_ok=True)
    sent = {"m1": {"ticket": tid, "question_id": "q1", "to": "phones"}}
    (d / "questions-sent.json").write_text(json.dumps(sent))
    assert run("answer", tid, "q1", "A", "--by", "agent:claude-code")[0] == 2
    assert read(proj, tid)["questions"][0]["answer"] is None


def test_done_refused_while_an_item_is_unchecked(proj, run, new_ticket):
    tid = new_ticket()
    assert run("check", "add", tid, "never done")[0] == 0
    code, _, err = run("ticket", "status", tid, "done", "--by", "agent:generic")
    assert code == 2 and "c1" in err and "not checked" in err
    assert read(proj, tid)["status"] == "open"
    assert run("ticket", "status", tid, "dropped")[0] == 0  # a dropped ticket is not affected


def test_new_with_ext_is_one_write_and_checked(proj, run, validate):
    code, out, _ = run(
        "ticket", "new", "Child", "--ext", 'foo={"occurrence":"t_x:1"}', "--ext", 'bar-1={"a":1}', "--json"
    )
    assert code == 0
    t = read(proj, json.loads(out)["id"])
    validate(t)
    assert t["ext"] == {"foo": {"occurrence": "t_x:1"}, "bar-1": {"a": 1}}
    assert t["history"][0]["text"] == "Created"


@pytest.mark.parametrize("bad", ["foo", "Foo={}", "foo=[1]", "foo=notjson"])
def test_new_with_bad_ext_makes_no_ticket(proj, run, bad):
    code, _, err = run("ticket", "new", "Nope", "--ext", bad)
    assert code == 2 and "ext" in err.lower()
    assert not list((proj / ".orch" / "tickets").glob("t_*.json"))


@pytest.mark.parametrize(
    "stored,shown",
    [
        ("Created", "Created"),
        ("Asked q1, waiting", "Asked a question"),
        ("Asked q1 on c2, waiting", "Asked q1 on c2, waiting"),
        ("Answered q1: Yes please", "Answered a question: Yes please"),
        ("Edited due, owner", "Changed the due date and owner"),
        ("Edited title", "Changed the title"),
        ("Edited note, summary, due", "Changed the note, summary and due date"),
        ("Patched owner, status (status open -> active)", "Changed the owner and status (now Working)"),
        ("Status open -> done", "Moved to Done"),
        ("Status done -> open", "Moved to Backlog"),
        ("Added check c1", "Added a task"),
        ("Check c1 done", "Finished a task"),
        ("Set ext.focus", "Updated Focus settings"),
        ("Set ext.my-addon", "Updated My addon settings"),
        ("Removed ext.focus", "Removed Focus settings"),
        ("Removed ext.focus.a", "Removed Focus settings"),
        ("Something the agent wrote", "Something the agent wrote"),
    ],
)
def test_history_line_is_plain_words(stored, shown):
    assert tickets.history_line(stored) == shown


def test_history_line_names_the_task():
    checks = [{"id": "c1", "text": "Write the test"}]
    assert tickets.history_line("Added check c1", checks) == "Added a task: Write the test"
    assert tickets.history_line("Check c1 done", checks) == "Finished a task: Write the test"
    assert tickets.history_line("Check c9 done", checks) == "Finished a task"


def test_cli_shows_task_text_in_history_but_stores_machine_text(proj, run, new_ticket):
    tid = new_ticket()
    run("check", "add", tid, "Write the test")
    out = run("ticket", "show", tid)[1]
    assert "Added a task: Write the test" in out
    assert read(proj, tid)["history"][-1]["text"] == "Added check c1"


def test_cli_shows_plain_history_but_stores_the_machine_text(proj, run, new_ticket):
    tid = new_ticket()
    run("ticket", "edit", tid, "--due", "2026-12-01", "--owner", "Anna")
    out = run("ticket", "show", tid)[1]
    assert "Changed the due date and owner" in out and "Edited due, owner" not in out
    assert read(proj, tid)["history"][-1]["text"] == "Edited due, owner"
    code, out, _ = run("log", tid, "Edited by hand")
    assert code == 0 and "Edited by hand" in out


@pytest.mark.parametrize("method", ["set_status", "patch"])
@pytest.mark.parametrize("target", ["open", "ready"])
@pytest.mark.parametrize(
    "actor,env_agent,cleared",
    [
        ("human:me", None, True),
        ("agent:test", None, False),
        ("human:me", "codex", False),
    ],
)
def test_started_reset_only_by_person(
    proj, new_ticket, monkeypatch, method, target, actor, env_agent, cleared
):
    monkeypatch.setattr(tickets, "agent_tool", lambda: env_agent)
    tid = new_ticket()
    tickets.mark_working(proj, tid, "agent:test", "Test")
    if method == "set_status":
        result = tickets.set_status(proj, tid, target, actor)
    else:
        result = tickets.patch(
            proj, tid, tickets.load(proj, tid)["revision"], json.dumps({"status": target}), actor
        )
    assert ("started" not in result) if cleared else result["started"] is True


def test_started_guard_writes_once_without_history(proj, new_ticket):
    tid = new_ticket()
    tickets.set_status(proj, tid, "waiting", "human:me")
    before = tickets.load(proj, tid)
    tickets.mark_working(proj, tid, "agent:test", "Test")
    first = tickets.load(proj, tid)
    assert first["started"] is True
    assert first["status"] == "waiting"
    assert first["history"] == before["history"]
    tickets.mark_working(proj, tid, "agent:test", "Test")
    assert tickets.load(proj, tid) == first


def _t(items, done_when=None):
    t = {"checklist": items}
    if done_when:
        t["done_when"] = done_when
    return t


def _c(cid, done=True, types=("command",), **kw):
    return {"id": cid, "text": cid, "done": done, "evidence": [{"type": x, "ref": "r"} for x in types], **kw}


def test_proof_state_counts_line():
    ps = tickets.proof_state(_t([_c("c1"), _c("c2"), _c("c3", types=("note",))]))
    assert ps["per_item"] == {"c1": "passed", "c2": "passed", "c3": "note"}
    assert ps["line"] == "2 checks passed · 1 note" and ps["uncovered"] == []


def test_proof_state_missing_and_empty():
    ps = tickets.proof_state(_t([_c("c1", done=False, types=())]))
    assert ps["per_item"] == {"c1": "missing"} and ps["line"] == "No checks recorded"
    assert tickets.proof_state(_t([]))["line"] == "No checks recorded"


def test_proof_state_failed_only_when_exit_recorded():
    ok = _c("c1")
    assert tickets.proof_state(_t([ok]))["per_item"]["c1"] == "passed"  # no exit = unknown, not failed
    bad = _c("c1")
    bad["evidence"][0]["exit"] = 1
    ps = tickets.proof_state(_t([bad, _c("c2")]))
    assert ps["per_item"]["c1"] == "failed" and ps["line"] == "1 check failed"
    zero = _c("c1")
    zero["evidence"][0]["exit"] = 0
    assert tickets.proof_state(_t([zero]))["per_item"]["c1"] == "passed"


def test_proof_state_real_coverage_count_and_level():
    dw = "A CSV download button on the invoice list; and it works on the phone"
    ps = tickets.proof_state(
        _t([_c("c1", covers='"A CSV download button on the invoice list"')], done_when=dw)
    )
    assert ps["uncovered"] == ["and it works on the phone"]
    assert ps["line"] == '1 part of "Done when" has no task' and ps["level"] == "warn"
    ps = tickets.proof_state(_t([_c("c1", covers="Alpha"), _c("c2")], done_when="Alpha; Beta; Gamma"))
    assert ps["uncovered"] == ["Beta", "Gamma"]
    ps = tickets.proof_state(_t([_c("c1")], done_when="One.\nTwo; Three"))
    assert ps["line"] == '3 parts of "Done when" have no task'
    ps = tickets.proof_state(
        _t(
            [_c("c1", covers="one"), _c("c2", covers="two"), _c("c3", covers="three")],
            done_when="One.\nTwo; Three",
        )
    )
    assert ps["uncovered"] == [] and ps["line"] == "3 checks passed" and ps["level"] == "ok"
    assert tickets.proof_state(_t([_c("c1")]))["uncovered"] == []  # no done_when, nothing to cover


def test_proof_state_levels():
    assert tickets.proof_state(_t([]))["level"] == "note"
    assert tickets.proof_state(_t([_c("c1", types=("note",))]))["level"] == "note"
    bad = _c("c1")
    bad["evidence"][0]["exit"] = 2
    assert tickets.proof_state(_t([bad]))["level"] == "fail"
    assert tickets.proof_state(_t([_c("c1", done=False, types=())]))["per_item"]["c1"] == "missing"
    stale = _c("c1")
    stale["evidence"][0]["stale"] = True  # a stored flag is never trusted
    assert tickets.proof_state(_t([stale]))["per_item"]["c1"] == "passed"


@pytest.fixture
def stopped(monkeypatch):
    """runs_live.stop's real work (kill the agent, tmux) faked: records the ticket ids it closed."""
    got = []
    monkeypatch.setattr(runs_live, "_close", lambda root, rec, interrupt: got.append(rec["ticket"]))
    monkeypatch.setattr(runs_live, "start_waiting", lambda root: None)
    return got


@pytest.fixture
def outside_pid():
    """A live process outside this test's own process tree (a child is never an ancestor): a run's pid."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    yield child.pid
    child.kill()
    child.wait()


def _files(proj):
    """Every stored file under .orch (tickets, history, verdict and won't-do ledgers), lock files aside."""
    base = proj / ".orch"
    return {
        str(p.relative_to(base)): p.read_bytes()
        for p in sorted(base.rglob("*"))
        if p.is_file() and "lock" not in p.name
    }


@pytest.mark.parametrize("status", ["done", "dropped"])
def test_closed_by_a_person_stops_the_live_run_and_refuses_agent_checks(
    proj, new_ticket, stopped, outside_pid, status
):
    """#542: a person closes the ticket: its live run is stopped, and the agent can no longer write checks."""
    tid = new_ticket()
    tickets.check_add(proj, tid, "first step", "agent:claude")
    runs.claim(proj, tid, "human:t", "claude", "live", pid=outside_pid)
    tickets.set_status(proj, tid, status, "human:t")
    assert stopped == [tid]
    assert runs.read(proj, tid)["stop_requested"]
    before = tickets.load(proj, tid)
    for write in (
        lambda: tickets.check_add(proj, tid, "late step", "agent:claude"),
        lambda: tickets.check_done(proj, tid, "c1", ['{"type":"note","ref":"ran it"}'], "agent:claude"),
        lambda: tickets.check_edit(proj, tid, "c1", "renamed", "agent:claude"),
        lambda: tickets.check_record(proj, tid, "c1", "pytest -q", 0, None, "agent:claude"),
        lambda: tickets.check_start(proj, tid, "c1", "agent:claude"),
        lambda: tickets.check_remove(proj, tid, "c1", "agent:claude"),
    ):
        with pytest.raises(Refused, match="This ticket is closed, so the agent can't change it."):
            write()
    assert tickets.load(proj, tid) == before
    item = tickets.check_add(proj, tid, "a person's note", "human:t")[1]  # a person still can
    assert tickets.load(proj, tid)["checklist"][-1]["id"] == item["id"]


@pytest.mark.parametrize("status", ["done", "dropped"])
def test_closed_ticket_refuses_every_agent_op_and_leaves_everything_untouched(proj, new_ticket, status):
    """#542, ONE guard in apply_op: no op an agent can call changes a closed ticket (stop, won't do, proof,
    log, ref, patch of several fields, re-opening); the ticket, its history and the ledgers stay as they
    were."""
    tid = new_ticket()
    tickets.check_add(proj, tid, "first step", "human:t")
    tickets.check_add(proj, tid, "second step", "human:t")
    tickets.check_start(proj, tid, "c1", "human:t")
    tickets.set_status(proj, tid, status, "human:t")
    before, files = tickets.load(proj, tid), _files(proj)
    rev = before["revision"]
    for write in (
        lambda: tickets.check_stop(proj, tid, "c1", "agent:claude"),
        lambda: tickets.check_wont_do(proj, tid, "c2", "agent:claude", "not needed"),
        lambda: tickets.check_done(proj, tid, "c2", ['{"type":"note","ref":"ran it"}'], "agent:claude"),
        lambda: tickets.check_reopen(proj, tid, "c1", "agent:claude"),
        lambda: tickets.check_move(proj, tid, "c1", "c2", "agent:claude"),
        lambda: tickets.log(proj, tid, "late line", "agent:claude"),
        lambda: tickets.ref_add(proj, tid, "https://example.com/x", "agent:claude"),
        lambda: tickets.patch(proj, tid, rev, '{"title": "New", "note": "late"}', "agent:claude"),
        lambda: tickets.edit(proj, tid, "Renamed", "agent:claude"),
        lambda: tickets.set_summary(proj, tid, "late summary", "agent:claude"),
        lambda: tickets.ask(proj, tid, "Go on?", [], None, "agent:claude"),
        lambda: tickets.wait(proj, tid, None, "external:x", "agent:claude"),
    ):
        with pytest.raises(Refused):
            write()
    assert tickets.load(proj, tid) == before and _files(proj) == files


@pytest.mark.parametrize("status", ["done", "dropped"])
def test_an_agent_cannot_reopen_a_closed_ticket_a_person_can(proj, new_ticket, monkeypatch, status):
    tid = new_ticket()
    tickets.set_status(proj, tid, status, "human:t")
    before, files = tickets.load(proj, tid), _files(proj)
    for write in (
        lambda: tickets.set_status(proj, tid, "ready", "agent:claude"),
        lambda: tickets.set_status(proj, tid, "review", "agent:claude"),
        lambda: tickets.patch(proj, tid, before["revision"], '{"status": "active"}', "agent:claude"),
    ):
        with pytest.raises(Refused, match="This ticket is closed, so the agent can't change it."):
            write()
    assert tickets.load(proj, tid) == before and _files(proj) == files
    monkeypatch.setenv("ORCH_AGENT", "claude")  # inside an agent run a person's name is not a person
    with pytest.raises(Refused, match="This ticket is closed, so the agent can't change it."):
        tickets.set_status(proj, tid, "ready", "human:t")
    with pytest.raises(Refused, match="This ticket is closed, so the agent can't change it."):
        tickets.log(proj, tid, "late line", "human:t")
    assert _files(proj) == files
    monkeypatch.delenv("ORCH_AGENT")
    assert tickets.set_status(proj, tid, "ready", "human:t")["status"] == "ready"  # a person re-opens it
    assert tickets.check_add(proj, tid, "more work", "agent:claude")[1]["id"] == "c1"  # open again: allowed


def test_closed_without_a_live_run_or_from_inside_its_own_run_stops_nothing(
    proj, new_ticket, stopped, monkeypatch, outside_pid
):
    tid = new_ticket()
    tickets.set_status(proj, tid, "dropped", "human:t")
    assert stopped == []  # no run: nothing to stop
    other = new_ticket()
    runs.claim(proj, other, "human:t", "claude", "live", pid=outside_pid)
    monkeypatch.setenv("ORCH_TICKET", other)  # the command runs inside that ticket's own run
    tickets.set_status(proj, other, "dropped", "human:t")
    assert stopped == [] and not runs.read(proj, other)["stop_requested"]
    monkeypatch.delenv("ORCH_TICKET")
    once = new_ticket()
    runs.claim(proj, once, "human:t", "claude", "oneshot", pid=outside_pid)
    tickets.set_status(proj, once, "dropped", "human:t")
    assert stopped == []  # a one-shot run ends by itself (its copy waits for it)


def test_closed_from_inside_the_runs_process_tree_stops_nothing(proj, new_ticket, stopped):
    """No ORCH_TICKET, but this process is the run's own (its pid is an ancestor): not stopped from within."""
    tid = new_ticket()
    runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    tickets.set_status(proj, tid, "dropped", "human:t")
    assert stopped == [] and not runs.read(proj, tid)["stop_requested"]


def test_closed_by_an_agent_stops_no_run(proj, new_ticket, stopped, outside_pid):
    """An agent closing a ticket never stops that ticket's run (its writes are refused instead)."""
    tid = new_ticket()
    runs.claim(proj, tid, "human:t", "claude", "live", pid=outside_pid)
    tickets.set_status(proj, tid, "dropped", "agent:other")
    assert tickets.load(proj, tid)["status"] == "dropped"
    assert stopped == [] and not runs.read(proj, tid)["stop_requested"]


def test_stop_closed_stops_nothing_when_the_ticket_was_reopened(proj, new_ticket, stopped, outside_pid):
    tid = new_ticket()
    runs.claim(proj, tid, "human:t", "claude", "live", pid=outside_pid)
    tickets.set_status(proj, tid, "dropped", "human:t")
    assert stopped == [tid]
    tickets.set_status(proj, tid, "ready", "human:t")  # re-opened before the (late) stop came
    runs.release(proj, tid, runs.read(proj, tid)["run"])
    runs.claim(proj, tid, "human:t", "claude", "live", pid=outside_pid)
    assert runs_live.stop_closed(proj, tid, "human:t") is False
    assert stopped == [tid] and not runs.read(proj, tid)["stop_requested"]


def test_closed_the_copy_goes_even_when_stopping_the_run_fails_and_the_reverse(proj, new_ticket, monkeypatch):
    from orch import worktrees

    gone = []

    def boom(*a):
        raise RuntimeError("stop failed")

    monkeypatch.setattr(runs_live, "stop_closed", boom)
    monkeypatch.setattr(worktrees, "on_closed", lambda root, tid: gone.append(tid))
    tid = new_ticket()
    assert tickets.set_status(proj, tid, "dropped", "human:t")["status"] == "dropped"
    assert gone == [tid]
    stops = []
    monkeypatch.setattr(runs_live, "stop_closed", lambda root, tid, by: stops.append((tid, by)))
    monkeypatch.setattr(worktrees, "on_closed", boom)
    other = new_ticket()
    assert tickets.set_status(proj, other, "done", "human:t")["status"] == "done"
    assert stops == [(other, "human:t")]


def test_closed_ticket_agent_check_open_ticket_still_allowed(proj, new_ticket):
    tid = new_ticket()
    tickets.set_status(proj, tid, "review", "human:t")  # Review is not closed
    assert tickets.check_add(proj, tid, "more work", "agent:claude")[1]["id"] == "c1"


@pytest.mark.parametrize("status", ["done", "dropped"])
def test_closed_ticket_refuses_agent_ext_attach_and_attach_file_before_writing(proj, new_ticket, status):
    """#542: ext set/unset, attach, attach file take the real actor; a closed ticket refuses an agent before
    anything is written (no file copied), the ticket and the disk stay as they were; a person can."""
    tid = new_ticket()
    tickets.ext_set(proj, tid, "demo", '{"a": 1, "b": 2}', "human:t")
    (proj / "proof.txt").write_text("proof\n")
    tickets.set_status(proj, tid, status, "human:t")
    before, files = tickets.load(proj, tid), _files(proj)
    msg = "This ticket is closed, so the agent can't change it."
    for write in (
        lambda: tickets.ext_set(proj, tid, "demo", '{"a": 9}', "agent:claude"),
        lambda: tickets.ext_unset(proj, tid, "demo.a", "agent:claude"),
        lambda: tickets.ext_unset(proj, tid, "demo", "agent:claude"),
        lambda: tickets.attach(proj, tid, "note.md", b"late", "agent:claude"),
        lambda: tickets.attach_file(proj, tid, str(proj / "proof.txt"), None, None, by="agent:claude"),
    ):
        with pytest.raises(Refused, match=msg):
            write()
    assert tickets.load(proj, tid) == before and _files(proj) == files
    tickets.ext_set(proj, tid, "demo", '{"a": 9}', "human:t")  # a person can
    assert tickets.attach(proj, tid, "note.md", b"by a person", "human:t")["name"] == "note.md"
    assert tickets.attach_file(proj, tid, str(proj / "proof.txt"), None, None, by="human:t")
    tickets.ext_unset(proj, tid, "demo.a", "human:t")


def test_agent_ext_attach_and_attach_file_work_on_an_open_ticket(proj, new_ticket):
    tid = new_ticket()
    (proj / "proof.txt").write_text("proof\n")
    tickets.ext_set(proj, tid, "demo", '{"a": 1, "b": 2}', "agent:claude")
    tickets.ext_unset(proj, tid, "demo.a", "agent:claude")
    assert tickets.attach(proj, tid, "note.md", b"hello", "agent:claude")["name"] == "note.md"
    assert tickets.attach_file(proj, tid, str(proj / "proof.txt"), None, None, by="agent:claude")


def test_no_agent_callable_op_writes_as_system():
    """An op with a `by` parameter writes as that actor: none of its apply_op calls passes SYSTEM, so an
    agent op can never be disguised as a system write (which the guard does not look at)."""
    import ast

    # the only ops with a `by` that may write as SYSTEM: run bookkeeping of the automation host, and the
    # person-only ask_for_changes (refuses any non-person `by` before it writes)
    bookkeeping = {
        "mark_working",
        "agent_stopped",
        "wait_for_start",
        "resume_after_start_wait",
        "ask_for_changes",
    }
    tree = ast.parse(Path(tickets.__file__).read_text(encoding="utf-8"))
    bad = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef) or fn.name in bookkeeping:
            continue
        if "by" not in {a.arg for a in fn.args.args + fn.args.kwonlyargs}:
            continue
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "apply_op":
                for k in n.keywords:
                    if k.arg == "by" and isinstance(k.value, ast.Name) and k.value.id == "SYSTEM":
                        bad.append(f"{fn.name}:{n.lineno}")
    assert not bad, f"ops with a `by` that write as SYSTEM: {bad}"


def test_every_apply_op_call_names_its_actor():
    """apply_op takes `by` (a required keyword): the actor of an agent op, or tickets.SYSTEM. A call
    in the sources that leaves it out would skip the closed-ticket guard, so a new op cannot do that."""
    import ast
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    files = [*(repo / "workspace" / "src").rglob("*.py"), *repo.glob("workspace-addons/*/src/**/*.py")]
    assert files
    missing = []
    for f in files:
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if not isinstance(n, ast.Call):
                continue
            fn = n.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
            if name == "apply_op" and not any(k.arg == "by" for k in n.keywords):
                missing.append(f"{f.relative_to(repo)}:{n.lineno}")
    assert not missing, f"apply_op without by=: {missing}"
