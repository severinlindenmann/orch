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


PEER = "agent:Sales"  # another workspace's helper, as a shared ticket chat writes it (chat_groups._by_name)


def _say(root, tid, by, text, at, chat=True, via=None):
    tickets.apply_op(root, tid, lambda t: tickets.add_history(t, by, text, via, chat=chat, at=at), by=by)


def _peer_says(root, tid, text, at):
    _say(root, tid, PEER, text, at, via="relay")


@pytest.fixture
def shared(monkeypatch):
    """Sales writes in every ticket chat of these tests (the group file itself is chat_groups' own test)."""
    from orch import chat_groups

    class Everywhere(dict):
        def get(self, key, default=None):
            return {PEER}

    monkeypatch.setattr(chat_groups, "peer_writers", lambda root: Everywhere())


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
    assert {k: top["last"][k] for k in ("kind", "by", "text")} == {
        "kind": "line",
        "by": YOU,
        "text": "Looks good",
    }
    assert top["last"]["id"].startswith("m_")  # the chat line's stable id
    assert top["last_at"] == "2026-11-10T09:10:00Z"


def test_a_new_line_moves_its_ticket_to_the_top(three):
    root, _, older, newer = three
    _say(root, older, AGENT, "One more thing", "2026-11-10T10:00:00+00:00")
    assert [r["id"] for r in ticketchats.chats(root)] == [older, newer]


def test_unread_counts_only_what_another_workspace_wrote(three, shared):
    """O-18 (owner, 28 Nov): nothing that started in this workspace is unread: not the person's lines, not its
    own helper's, not a question. A line another workspace wrote into the chat is."""
    root, _, older, newer = three
    unread = {r["id"]: r["unread"] for r in ticketchats.chats(root)}
    assert unread == {older: 0, newer: 0}  # the person and this workspace's helper wrote here
    _peer_says(root, older, "Group: Sales here, the numbers are in.", "2026-11-10T11:00:00+00:00")
    _say(
        root, older, AGENT, "Group: thanks", "2026-11-10T11:01:00+00:00", via="relay"
    )  # our helper, same road
    _say(
        root,
        older,
        "agent:relay",
        "Could not add the workspace: offline",
        "2026-11-10T11:02:00+00:00",
        via="relay",
    )
    assert {r["id"]: r["unread"] for r in ticketchats.chats(root)} == {older: 1, newer: 0}


def test_a_helper_line_is_not_unread_without_a_shared_chat(three):
    root, _, older, newer = three  # no other workspace in any chat: a relay line by an unknown name is local
    _peer_says(root, older, "Group: hello", "2026-11-10T11:00:00+00:00")
    assert {r["unread"] for r in ticketchats.chats(root)} == {0}


def test_peer_writers_come_from_the_tickets_own_group(proj, monkeypatch):
    from orch import chat_groups

    tid = _ticket(proj, "Shared")
    group = {
        "ticket": tid,
        "host": "ws_aaaaaaaaaa",
        "members": {
            "ws_aaaaaaaaaa": {"name": "Marketing"},
            "ws_bbbbbbbbbb": {"name": "Sales", "left_at": "2026-11-10T12:00:00Z"},
        },
    }
    monkeypatch.setattr(chat_groups, "_load", lambda root: {"hosted": {"grp_" + tid: group, "odd": "x"}})
    assert chat_groups.peer_writers(proj) == {tid: {PEER}}  # never the host; one that left keeps its lines
    _peer_says(proj, tid, "Group: the numbers are in.", "2026-11-10T11:00:00+00:00")
    (row,) = ticketchats.chats(proj)
    assert row["unread"] == 1


def test_marking_read_resets_unread_for_that_reader_only(three, shared):
    root, _, older, newer = three
    _peer_says(root, older, "Group: first", "2026-11-10T08:20:00+00:00")
    ticketchats.mark_read(root, older, "dashboard", at="2026-11-10T08:30:00Z")
    assert {r["id"]: r["unread"] for r in ticketchats.chats(root, "dashboard")}[older] == 0
    assert {r["id"]: r["unread"] for r in ticketchats.chats(root)}[older] == 1  # "you" has not read it
    _peer_says(root, older, "Group: another answer", "2026-11-10T08:40:00+00:00")
    assert {r["id"]: r["unread"] for r in ticketchats.chats(root, "dashboard")}[older] == 1


def test_a_read_mark_never_moves_back(three):
    root, _, older, _ = three
    ticketchats.mark_read(root, older, "dashboard", at="2026-11-10T08:30:00Z")
    r = ticketchats.mark_read(root, older, "dashboard", at="2026-11-10T07:00:00Z")
    assert r["read_at"].startswith("2026-11-10T08:30:00")


def test_a_ticket_with_only_an_open_question_is_listed_and_not_unread(proj):
    tid = _ticket(proj, "Needs a choice")
    tickets.ask(proj, tid, "Which colour?", ["Blue", "Green"], "Blue", AGENT)
    (row,) = ticketchats.chats(proj)
    assert row["id"] == tid and row["lines"] == 0 and row["open_questions"] == 1
    assert row["last"]["kind"] == "question" and row["last"]["text"] == "Which colour?"
    assert row["last"]["id"] == "q1" and row["last"]["by"] is None
    assert row["unread"] == 0  # this workspace's own question: it waits in Review, not as a Chat number
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


def test_orch_chat_list_and_read_commands(three, run, shared):
    root, _, older, newer = three
    code, out, err = run("chat", "list", "--json")
    assert code == 0, err
    assert [r["id"] for r in json.loads(out)] == [newer, older]
    code, out, err = run("chat", "list")
    assert code == 0 and "Newer chat" in out and " new" not in out  # only this workspace wrote: nothing new
    _peer_says(root, older, "Group: Sales here", "2026-11-10T11:00:00+00:00")
    code, out, err = run("chat", "list")
    assert code == 0 and "1 new" in out
    key = tickets.load(root, older)["key"]
    code, out, err = run("chat", "read", key, "--reader", "dashboard", "--json")
    assert code == 0, err
    assert json.loads(out)["ticket"] == older
    code, out, _ = run("chat", "list", "--reader", "dashboard", "--json")
    assert {r["id"]: r["unread"] for r in json.loads(out)}[older] == 0


def test_no_ticket_chats_yet(proj, run):
    code, out, _ = run("chat", "list")
    assert code == 0 and "No ticket chats yet." in out


def test_the_last_line_keeps_the_typed_name(proj):
    tid = _ticket(proj, "Named")
    tickets.apply_op(
        proj,
        tid,
        lambda t: tickets.add_history(
            t, YOU, "Hi all", chat=True, at="2026-11-10T09:00:00+00:00", by_name="Anna"
        ),
        by=YOU,
    )
    (row,) = ticketchats.chats(proj)
    assert row["last"]["by_name"] == "Anna" and row["last"]["by"] == YOU


def test_a_line_in_the_same_second_as_the_read_mark_is_still_unread(proj, shared):
    tid = _ticket(proj, "Same second")
    _peer_says(proj, tid, "First", "2026-11-10T09:00:00+00:00")
    ticketchats.mark_read(proj, tid)  # read now: one line seen
    t = tickets.load(proj, tid)
    _peer_says(proj, tid, "Arrived right after", t["history"][-1]["at"])  # stamped in an already-read second
    (row,) = ticketchats.chats(proj)
    assert row["unread"] == 1


def test_an_old_question_without_asked_at_stays_read_after_an_edit(proj):
    tid = _ticket(proj, "Old question")
    tickets.ask(proj, tid, "Which colour?", ["Blue", "Green"], "Blue", AGENT)

    def drop_asked_at(t):
        t["questions"][0].pop("asked_at", None)

    tickets.apply_op(proj, tid, drop_asked_at, by=AGENT)
    ticketchats.mark_read(proj, tid)
    tickets.apply_op(proj, tid, lambda t: t.update(title="Old question, renamed"), by=AGENT)
    (row,) = ticketchats.chats(proj)
    assert row["unread"] == 0


def test_a_bad_typed_name_in_the_file_is_dropped(proj):
    tid = _ticket(proj, "Edited by hand")
    _say(proj, tid, YOU, "Hi", "2026-11-10T09:00:00+00:00")

    def bad_name(t):
        t["history"][-1]["by_name"] = "x" * 500

    tickets.apply_op(proj, tid, bad_name, by=YOU)
    (row,) = ticketchats.chats(proj)
    assert "by_name" not in row["last"]
