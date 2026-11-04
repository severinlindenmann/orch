import json
from pathlib import Path

import pytest
from conftest import CONTRACTS


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


def test_recurring_needs_cron_and_validates(proj, run, validate):
    code, out, _ = run("ticket", "new", "Weekly", "--recurring", "0 7 * * 1", "--json")
    assert code == 0
    t = read(proj, json.loads(out)["id"])
    validate(t)
    assert t["type"] == "recurring" and t["ext"]["scheduler"]["cron"] == "0 7 * * 1"


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
    code, _, err = run("ticket", "status", tid, "done")
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
    assert h[-2]["by"] == "agent:codex" and h[-1]["by"] == "agent:claude-code"
    monkeypatch.delenv("CLAUDECODE")
    run("log", tid, "human")
    assert read(proj, tid)["history"][-1]["by"].startswith("human:")


def test_bad_actor_refused(proj, run, new_ticket):
    tid = new_ticket()
    assert run("log", tid, "x", "--by", "robot")[0] == 2


def test_link_and_ext(proj, run, new_ticket, validate):
    tid = new_ticket()
    assert run("link", "add", tid, "--type", "jira", "--url", "https://j/1", "--title", "J-1")[0] == 0
    assert run("link", "add", tid, "--type", "Bad Type", "--url", "u")[0] == 2
    assert run("ext", "set", tid, "scheduler", '{"cron":"0 8 * * 1"}')[0] == 0
    assert run("ext", "set", tid, "scheduler", "not json")[0] == 2
    t = read(proj, tid)
    validate(t)
    assert t["links"][0]["title"] == "J-1" and t["ext"]["scheduler"]["cron"] == "0 8 * * 1"


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
    assert t["status"] == "active" and t["waiting_on"] is None
    assert run("answer", tid, "q1", "DATE")[0] == 2


def test_ask_recommend_must_be_option(proj, run, new_ticket):
    tid = new_ticket()
    assert run("ask", tid, "q?", "--option", "A", "--recommend", "B")[0] == 2


def test_wait_until_and_on(proj, run, new_ticket, validate):
    tid = new_ticket()
    assert run("wait", tid, "--until", "2026-11-05T08:00:00+01:00")[0] == 0
    t = read(proj, tid)
    validate(t)
    assert t["status"] == "waiting" and t["wake_at"] == "2026-11-05T07:00:00Z"
    assert run("ticket", "wait", tid, "--on", "webhook:wh_1")[0] == 0
    t = read(proj, tid)
    validate(t)
    assert t["waiting_on"] == {"kind": "webhook", "ref": "wh_1"}
    assert run("wait", tid, "--until", "garbage")[0] == 2
    assert run("wait", tid, "--on", "nokind:x")[0] == 2
    assert run("wait", tid)[0] == 2


def test_edit_and_show_json(proj, run, new_ticket):
    tid = new_ticket()
    assert run("ticket", "edit", tid, "--title", "New title")[0] == 0
    code, out, _ = run("ticket", "show", tid, "--json")
    assert json.loads(out)["title"] == "New title"
    code, out, _ = run("ticket", "show", tid)
    assert "Status: open" in out


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
    code, _, err = run("ticket", "status", tid, "done")
    assert code == 2 and "c1" in err and "not checked" in err
    assert read(proj, tid)["status"] == "open"
    assert run("ticket", "status", tid, "dropped")[0] == 0  # a dropped ticket is not affected
