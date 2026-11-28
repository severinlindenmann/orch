# ruff: noqa: E501
"""Writing in a ticket's chat (team chat step 1, ORCH-1168): the person's words become a chat line on the
ticket and go to its helper with orch's hint where to answer; the helper answers there with orch chat reply."""

import json

from orch import chat, runs, ticketchats, tickets


def _chat_lines(proj, tid):
    return [e for e in tickets.load(proj, tid)["history"] if e.get("chat_message") is True]


def test_a_person_writes_in_a_ticket_chat_and_its_helper_gets_it(proj, run, new_ticket):
    tid = new_ticket("Launch plan")
    code, out, err = run(
        "chat",
        "say",
        "--ticket",
        tid,
        "--by",
        "human:nina",
        "--name",
        "Nina",
        "--json",
        "--",
        "Start with the poster",
    )
    assert code == 0, (out, err)
    r = json.loads(out)
    assert r["ticket"] == tid and r["id"].startswith("m_") and r["send"]["state"] == "none"
    [line] = _chat_lines(proj, tid)
    assert (line["by"], line["via"], line["text"], line["id"], line["by_name"]) == (
        "human:nina",
        "dashboard",
        "Start with the poster",
        r["id"],
        "Nina",
    )
    # the words wait for the helper (they start one), orch's hint says where to answer
    assert [i["text"] for i in runs.human_waiting(proj, tid)] == ["Start with the poster"]
    waiting = runs.undelivered(proj, tid)
    hint = [i for i in waiting if i["by"] == "orch"]
    assert hint and f"orch chat reply --ticket {r['key']}" in hint[0]["text"]
    # and the ticket is in the list of ticket chats; the person's own line is never unread for them
    [row] = [x for x in ticketchats.chats(proj, "dashboard") if x["id"] == tid]
    assert row["lines"] == 1 and row["last"]["text"] == "Start with the poster"


def test_the_helper_answers_in_the_ticket_chat(proj, run, new_ticket, monkeypatch):
    tid = new_ticket("Launch plan")
    monkeypatch.setenv("CLAUDECODE", "1")
    code, out, err = run("chat", "reply", "Poster first, then the mail.", "--ticket", tid, "--json")
    assert code == 0, (out, err)
    [line] = _chat_lines(proj, tid)
    assert (
        line["by"].startswith("agent:")
        and line["text"] == "Poster first, then the mail."
        and line["id"].startswith("m_")
    )
    [row] = [x for x in ticketchats.chats(proj, "dashboard") if x["id"] == tid]
    assert row["unread"] == 0  # O-18: this workspace's own helper wrote it, so it is not a Chat number


def test_a_long_answer_carries_the_helpers_own_short_line(proj, run, new_ticket, monkeypatch):
    """O-19 (owner, 28 Nov): the helper gives the short line itself (--summary); the chat shows it and opens the
    whole text. orch never shortens a message by a program or a model, and the original is kept as written."""
    tid = new_ticket("Launch plan")
    monkeypatch.setenv("CLAUDECODE", "1")
    long = "## Plan\n\n" + "\n".join(f"- step {i}: do the thing with care" for i in range(30))
    code, out, err = run(
        "chat", "reply", long, "--ticket", tid, "--summary", "  Poster first,\n then the mail.  ", "--json"
    )
    assert code == 0, (out, err)
    [line] = _chat_lines(proj, tid)
    assert line["text"] == long and line["summary"] == "Poster first, then the mail."
    code, out, err = run("chat", "reply", "Short.", "--ticket", tid, "--summary", "x" * 201)
    assert code == 2 and "1 to 200 characters" in out + err
    assert len(_chat_lines(proj, tid)) == 1
    code, out, err = run("chat", "reply", "No short line.", "--ticket", tid)
    assert code == 0 and "summary" not in _chat_lines(proj, tid)[-1]


def test_a_short_line_is_only_for_a_chat_line(proj, new_ticket):
    import pytest

    from orch.errors import Refused

    tid = new_ticket("Launch plan")
    with pytest.raises(Refused):
        tickets.apply_op(
            proj,
            tid,
            lambda t: tickets.add_history(t, "agent:claude", "note", summary="short"),
            by="agent:claude",
        )


def test_only_a_person_says_and_only_a_helper_replies(proj, run, new_ticket, monkeypatch):
    tid = new_ticket("Launch plan")
    assert run("chat", "reply", "hi", "--ticket", tid)[0] == 2  # a person cannot answer as the helper
    monkeypatch.setenv("CLAUDECODE", "1")
    assert run("chat", "say", "--ticket", tid, "--", "I am the person")[0] == 2
    assert _chat_lines(proj, tid) == []


def test_refused_cases_leave_the_ticket_alone(proj, run, new_ticket):
    tid = new_ticket("Launch plan")
    assert run("chat", "say", "--ticket", tid, "--by", "human:nina", "--", "   ")[0] == 2
    assert (
        run("chat", "say", "--ticket", tid, "--by", "human:nina", "--", "x" * (chat.TICKET_CHAT_MAX + 1))[0]
        == 2
    )
    assert run("chat", "say", "--ticket", tid, "--new", "--by", "human:nina", "--", "hi")[0] == 2
    assert run("chat", "say", "--name", "Nina", "--by", "human:nina", "--", "hi")[0] == 2
    assert run("chat", "say", "--ticket", "t_nothere00", "--by", "human:nina", "--", "hi")[0] == 2
    assert _chat_lines(proj, tid) == []


def test_the_workspace_chat_is_not_a_ticket_chat(proj, run):
    gid = tickets.ensure_general(proj, "human:nina")
    assert run("chat", "say", "--ticket", gid, "--by", "human:nina", "--", "hi")[0] == 2
