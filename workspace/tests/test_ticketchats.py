"""Team chat step 1 (ORCH-1167): the list of ticket chats. Tickets with chat lines or an open question, newest
first, with the last line and an unread count per reader; a ticket without chat is not listed."""

import json

import pytest

from orch import ticketchats, tickets
from orch.errors import Refused

AGENT = "agent:claude"
YOU = "human:lume"


def _ticket(root, title):
    return tickets.create(root, title, AGENT)["id"]


def _say(root, tid, by, text, at, chat=True):
    tickets.apply_op(root, tid, lambda t: tickets.add_history(t, by, text, chat=chat, at=at), by=by)


@pytest.fixture
def three(proj):
    quiet = _ticket(proj, "No chat here")
    _say(proj, quiet, AGENT, "Started the work", "2026-11-10T09:30:00+00:00", chat=False)  # no chat line
    older = _ticket(proj, "Older chat")
    _say(proj, older, YOU, "Can you look at the logo?", "2026-11-10T08:00:00+00:00")
    _say(proj, older, AGENT, "Yes, done.", "2026-11-10T08:05:00+00:00")
    newer = _ticket(proj, "Newer chat")
    _say(proj, newer, AGENT, "First draft is up.", "2026-11-10T09:00:00+00:00")
    _say(proj, newer, YOU, "Looks good", "2026-11-10T09:10:00+00:00")
    return proj, quiet, older, newer


def test_newest_first_and_a_ticket_without_chat_is_not_listed(three):
    root, quiet, older, newer = three
    rows = ticketchats.chats(root)
    assert [r["id"] for r in rows] == [newer, older]
    assert quiet not in {r["id"] for r in rows}
    top = rows[0]
    assert top["title"] == "Newer chat" and top["lines"] == 2 and top["open_questions"] == 0
    assert top["last"] == {"kind": "line", "by": YOU, "text": "Looks good"}
    assert top["last_at"] == "2026-11-10T09:10:00Z"


def test_a_new_line_moves_its_ticket_to_the_top(three):
    root, _, older, newer = three
    _say(root, older, AGENT, "One more thing", "2026-11-10T10:00:00+00:00")
    assert [r["id"] for r in ticketchats.chats(root)] == [older, newer]


def test_unread_counts_lines_from_others_never_your_own(three):
    root, _, older, newer = three
    unread = {r["id"]: r["unread"] for r in ticketchats.chats(root)}
    assert unread == {older: 1, newer: 1}  # one helper line each; the person's own lines are not unread


def test_marking_read_resets_unread_for_that_reader_only(three):
    root, _, older, newer = three
    ticketchats.mark_read(root, older, "dashboard", at="2026-11-10T08:30:00Z")
    assert {r["id"]: r["unread"] for r in ticketchats.chats(root, "dashboard")}[older] == 0
    assert {r["id"]: r["unread"] for r in ticketchats.chats(root)}[older] == 1  # "you" has not read it
    _say(root, older, AGENT, "Another answer", "2026-11-10T08:40:00+00:00")
    assert {r["id"]: r["unread"] for r in ticketchats.chats(root, "dashboard")}[older] == 1


def test_a_read_mark_never_moves_back(three):
    root, _, older, _ = three
    ticketchats.mark_read(root, older, "dashboard", at="2026-11-10T08:30:00Z")
    r = ticketchats.mark_read(root, older, "dashboard", at="2026-11-10T07:00:00Z")
    assert r["read_at"].startswith("2026-11-10T08:30:00")


def test_a_ticket_with_only_an_open_question_is_listed_and_unread(proj):
    tid = _ticket(proj, "Needs a choice")
    tickets.ask(proj, tid, "Which colour?", ["Blue", "Green"], "Blue", AGENT)
    (row,) = ticketchats.chats(proj)
    assert row["id"] == tid and row["lines"] == 0 and row["open_questions"] == 1
    assert row["last"]["kind"] == "question" and row["last"]["text"] == "Which colour?"
    assert row["unread"] == 1
    tickets.answer(proj, tid, "q1", "Blue", YOU, "cli")
    assert ticketchats.chats(proj) == []  # answered and no chat lines: no longer a ticket chat


def test_hidden_tickets_are_not_ticket_chats(proj):
    gid = tickets.ensure_general(proj, YOU)
    _say(proj, gid, YOU, "hello", "2026-11-10T09:00:00+00:00")
    assert ticketchats.chats(proj) == []
    with pytest.raises(Refused):
        ticketchats.mark_read(proj, gid)


def test_a_bad_reader_is_refused(proj):
    with pytest.raises(Refused):
        ticketchats.chats(proj, "../x")


def test_long_last_line_is_clipped(proj):
    tid = _ticket(proj, "Long")
    _say(proj, tid, AGENT, "word " * 100, "2026-11-10T09:00:00+00:00")
    (row,) = ticketchats.chats(proj)
    assert len(row["last"]["text"]) <= ticketchats.LAST_CLIP and row["last"]["text"].endswith("…")


def test_orch_chat_list_and_read_commands(three, run):
    root, _, older, newer = three
    code, out, err = run("chat", "list", "--json")
    assert code == 0, err
    assert [r["id"] for r in json.loads(out)] == [newer, older]
    code, out, err = run("chat", "list")
    assert code == 0 and "Newer chat" in out and "1 new" in out
    key = tickets.load(root, older)["key"]
    code, out, err = run("chat", "read", key, "--reader", "dashboard", "--json")
    assert code == 0, err
    assert json.loads(out)["ticket"] == older
    code, out, _ = run("chat", "list", "--reader", "dashboard", "--json")
    assert {r["id"]: r["unread"] for r in json.loads(out)}[older] == 0


def test_no_ticket_chats_yet(proj, run):
    code, out, _ = run("chat", "list")
    assert code == 0 and "No ticket chats yet." in out
