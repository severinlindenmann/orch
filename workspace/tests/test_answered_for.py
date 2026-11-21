"""ORCH-547: every answer says who really gave it. The person ("Severin"), a role standing in for them
("Manager for Severin", "Away mode for Severin", "Script for Severin"); the person lists what was answered for
them in one place and undoes it."""

import json

import pytest

from orch import config, history, tickets

pytestmark = pytest.mark.no_terminal  # the real check: these tests run with no terminal, like a script


def read(proj, tid):
    return json.loads((proj / ".orch" / "tickets" / f"{tid}.json").read_text(encoding="utf-8"))


@pytest.fixture
def no_agent(monkeypatch):
    for k in ("ORCH_RUN", "ORCH_TICKET", "ORCH_AGENT", "ORCH_ROOT", "CLAUDECODE", "CODEX_SANDBOX"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)


def asked(run, new_ticket, *extra):
    tid = new_ticket()
    code, out, err = run(
        "ask", tid, "Which one?", "--option", "A", "--option", "B", "--recommend", "A", *extra
    )
    assert code == 0, out + err
    return tid


def test_words_for_each_answerer():
    assert history.answered_words("human:Severin") == "Severin"
    assert history.answered_words("agent:manager", "human:Severin") == "Manager for Severin"
    assert history.answered_words("agent:reviewer", "human:Severin") == "Away mode for Severin"
    assert history.answered_words("agent:script", "human:Severin") == "Script for Severin"
    assert history.answered_words("agent:claude", "human:Severin") == "Helper for Severin"


def test_a_program_answering_as_the_person_is_recorded_as_a_script_for_them(proj, run, new_ticket, no_agent):
    tid = asked(run, new_ticket)
    code, out, err = run("answer", tid, "q1", "B", "--by", "human:Severin")
    assert code == 0, out + err
    t = read(proj, tid)
    q = t["questions"][0]
    assert q["answered_by"] == "agent:script" and q["answered_for"] == "human:Severin"
    line = next(h for h in t["history"] if h["text"] == "Answered q1: B")
    assert line["by"] == "agent:script" and line["for"] == "Severin"


def test_the_person_at_a_terminal_is_the_person(proj, run, new_ticket, no_agent, monkeypatch):
    monkeypatch.setattr(tickets, "answer_terminal", lambda: True)
    tid = asked(run, new_ticket)
    assert run("answer", tid, "q1", "B", "--by", "human:Severin")[0] == 0
    q = read(proj, tid)["questions"][0]
    assert q["answered_by"] == "human:Severin" and "answered_for" not in q


def test_the_dashboard_click_is_the_person(proj, run, new_ticket, no_agent):
    tid = asked(run, new_ticket)
    assert run("answer", tid, "q1", "B", "--by", "human:Severin", "--via", "dashboard")[0] == 0
    q = read(proj, tid)["questions"][0]
    assert q["answered_by"] == "human:Severin" and "answered_for" not in q


def test_the_manager_says_for_whom(proj, run, new_ticket, no_agent):
    tid = asked(run, new_ticket)
    code, out, err = run("answer", tid, "q1", "A", "--by", "agent:manager", "--for", "Severin")
    assert code == 0, out + err
    q = read(proj, tid)["questions"][0]
    assert q["answered_by"] == "agent:manager" and q["answered_for"] == "human:Severin"
    code, out, _ = run("answer", tid, "q1", "A", "--by", "agent:reviewer", "--for", "Severin")
    assert code == 2 and "orch's own role" in out + _


def test_a_helper_never_answers_as_a_person_but_may_answer_for_them(
    proj, run, new_ticket, monkeypatch, no_agent
):
    tid = asked(run, new_ticket)
    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    code, out, err = run("answer", tid, "q1", "A", "--by", "human:Severin")
    assert code == 2 and "--for" in out + err
    assert read(proj, tid)["questions"][0]["answer"] is None
    assert run("answer", tid, "q1", "A", "--for", "Severin")[0] == 0
    q = read(proj, tid)["questions"][0]
    assert q["answered_by"] == "agent:claude" and q["answered_for"] == "human:Severin"


def test_a_card_answered_for_the_person_and_the_list_and_undo(proj, run, new_ticket, no_agent, monkeypatch):
    tid = new_ticket()
    code, out, err = run(
        "ask", tid, "Go with this plan?", "--plan", "Plan", "--then", "I build it.", "--by", "agent:x"
    )
    assert code == 0, out + err
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", "agent:manager", "--for",
                         "Severin", "--json")  # fmt: skip
    assert code == 0, out + err
    q = read(proj, tid)["questions"][0]
    assert q["answered_by"] == "agent:manager" and q["answered_for"] == "human:Severin"
    # a card answer from a role that does not say for whom is still refused
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", "agent:manager", "--json")
    assert code != 0

    code, out, _ = run("review", "list", "--answered", "--for-me", "--json")
    (e,) = json.loads(out)
    assert e["key"] == "q1" and e["who"] == "Manager for Severin" and e["for"] == "human:Severin"
    code, out, _ = run("review", "list", "--answered", "--for-me")
    assert "Manager for Severin" in out

    # only the person undoes
    code, out, err = run("review", "undo", tid, "q1", "--by", "agent:manager", "--json")
    assert code != 0
    monkeypatch.setattr(tickets, "answer_terminal", lambda: True)
    code, out, err = run("review", "undo", tid, "q1", "--by", "human:Severin", "--json")
    assert code == 0, out + err
    assert json.loads(out)["again"] == "q2"
    t = read(proj, tid)
    old, again = t["questions"]
    assert old["undone"]["again"] == "q2" and old["decision"]["replaced_by"] == "q2"
    assert again["answer"] is None and again["card"] == old["card"] and again["again"] == "q1"
    assert t["status"] == "waiting" and t["waiting_on"] == {"kind": "question", "ref": "q2"}
    assert any(h["text"].startswith("Undid q1 (answered by Manager for Severin)") for h in t["history"])
    code, out, _ = run("review", "list", "--answered", "--for-me", "--json")
    assert json.loads(out)[0]["undone"] is True
    assert run("review", "undo", tid, "q1", "--by", "human:Severin")[0] != 0  # once


def test_a_plain_answer_for_the_person_is_listed_and_undone(proj, run, new_ticket, no_agent, monkeypatch):
    tid = asked(run, new_ticket)
    assert run("answer", tid, "q1", "A")[0] == 0  # a script, no --by: the picked person or the login
    code, out, _ = run("review", "list", "--answered", "--for-me", "--json")
    (e,) = json.loads(out)
    assert e["who"].startswith("Script for ") and e["decision"]["summary"] == "A"
    code, out, _ = run("review", "list", "--answered", "--json")
    assert [e["key"] for e in json.loads(out)] == ["q1"]  # listed with the cards, to look through and undo
    monkeypatch.setattr(tickets, "answer_terminal", lambda: True)
    assert run("review", "undo", tid, "q1", "--by", "human:Severin")[0] == 0
    assert read(proj, tid)["questions"][1]["options"] == ["A", "B"]


def test_the_persons_own_answer_cannot_be_undone_here(proj, run, new_ticket, no_agent, monkeypatch):
    monkeypatch.setattr(tickets, "answer_terminal", lambda: True)
    tid = asked(run, new_ticket)
    assert run("answer", tid, "q1", "A", "--by", "human:Severin")[0] == 0
    code, out, err = run("review", "undo", tid, "q1", "--by", "human:Severin")
    assert code != 0 and "not answered for you" in out + err


def test_away_mode_answers_for_the_owner(proj, run, new_ticket, no_agent):
    config.set_reviewer_answers(proj, True, "human:Severin")
    tid = asked(run, new_ticket)
    q = read(proj, tid)["questions"][0]
    tickets.answer_for_owner(proj, tid, "q1", tickets.question_digest(q), "routine")
    q = read(proj, tid)["questions"][0]
    assert q["answered_by"] == tickets.REVIEWER and q["answered_for"].startswith("human:")
    assert history.answered_words(q["answered_by"], q["answered_for"]).startswith("Away mode for ")


def test_nobody_merges_for_the_person(proj, no_agent):
    from orch import review

    url = "https://github.com/o/r/pull/1"
    q = {
        "id": "q1",
        "action": {"merge": url, "head": "abc"},
        "card": {"kind": "link", "open": url, "ok_label": "Merge"},
    }
    with tickets.standing_in("human:Severin"), pytest.raises(Exception, match="Only a person merges"):
        review._merge_first(proj, "t_x", q, {"action": "approve"}, "agent:manager", "cli")


def test_drafts_and_designs_wait_for_the_person(proj, run, new_ticket, no_agent):
    tid = new_ticket()
    assert (
        run("ask", tid, "Use this text?", "--draft", "Intro", "--then", "I use it.", "--by", "agent:x")[0]
        == 0
    )
    code, out, err = run("review", "answer", tid, "q1", "--verdict", "ok", "--by", "agent:manager", "--for",
                         "Severin", "--json")  # fmt: skip
    # refused by the draft rule (ORCH-582, said first) or the stand-in rule (ORCH-547): both keep it for the person
    assert code != 0 and ("own answer" in out + err or "Only a person picks a draft" in out + err)
    assert read(proj, tid)["questions"][0]["answer"] is None


def test_the_morning_list_says_who_answered_for_the_person(proj, run, new_ticket, no_agent):
    from orch import reviewer

    tid = asked(run, new_ticket)
    assert run("answer", tid, "q1", "B", "--by", "agent:manager", "--for", "Severin")[0] == 0
    rows = reviewer.accepted(proj, "2000-01-01T00:00:00Z")
    (r,) = [x for x in rows if x.get("answer")]
    assert r["who"] == "Manager for Severin" and r["question"] == "q1"
    text = reviewer.accepted_text(rows)
    assert "Answered for you today: 1 question" in text and "q1 = B (Manager for Severin)" in text


def test_a_helper_never_answers_for_the_person_on_its_own_ticket(
    proj, run, new_ticket, monkeypatch, no_agent
):
    tid = asked(run, new_ticket)
    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    monkeypatch.setenv("ORCH_TICKET", tid)
    code, out, err = run("answer", tid, "q1", "A", "--for", "Severin")
    assert code == 2 and "its own ticket" in out + err
    code, out, err = run("review", "answer", tid, "review", "--verdict", "ok", "--for", "Severin", "--json")
    assert code != 0 and "its own ticket" in out + err
    assert read(proj, tid)["questions"][0]["answer"] is None


def test_roles_cannot_be_borrowed(proj, run, new_ticket, monkeypatch, no_agent):
    tid = asked(run, new_ticket)
    for role in ("agent:Reviewer", "agent:SCRIPT", "agent:release-keeper"):
        code, out, err = run("answer", tid, "q1", "A", "--by", role, "--for", "Severin")
        assert code == 2 and "orch's own role" in out + err, role
    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    code, out, err = run("answer", tid, "q1", "A", "--by", "agent:boss", "--for", "Severin")
    assert code == 2 and "as itself or as the manager" in out + err
