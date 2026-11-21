"""Team chat 2.3: @ asks one helper, and a helper only asks before a workspace is added (chat-groups v2
`body.mentions`, design note step 2). Same fake relay and helpers as test_chat_groups.py."""

import json

import pytest
import test_chat_groups as tcg
from fakes import WS
from test_chat_groups import (
    BANK,
    FIN,
    HOME,
    MEMBERS,
    all_contract_clean,
    from_host,
    group_msg,
    inbox,
    mid,
    sent,
)

from orch import chat_groups as cg
from orch import relay, runs, tickets

host, grp, member = tcg.host, tcg.grp, tcg.member  # the same fixtures as the group chat tests


def _pending(proj, tid):
    return runs._pending_read(proj, tid)


def _seen(proj, m):
    s = relay.seen(proj)
    return m["id"] in s or f"{m['from']}/{m['id']}" in s


# ---- host: who is asked --------------------------------------------------------------------------------


def test_at_a_member_carries_only_that_member_and_wakes_no_one_here(proj, run, rel, grp):
    tid, gid, _ = grp
    code, out, err = run("relay", "group", "say", tid, "Bank, which account?", "--dashboard", "--to", "Bank")
    assert code == 0, err
    assert "Asked: Bank helper." in out
    for ws in (HOME, BANK):  # every member sees the line, only Bank is named
        (c,) = sent(rel, to=ws)
        assert c["body"]["mentions"] == [BANK]
    assert _pending(proj, tid) == []  # this workspace's own helper was not named
    all_contract_clean(rel)


def test_without_at_every_helper_stays_quiet_and_the_chat_says_so(proj, run, rel, grp):
    tid, gid, _ = grp
    code, out, _ = run("relay", "group", "say", tid, "Thanks all", "--dashboard")
    assert code == 0 and cg.QUIET_HINT in out
    assert all(c["body"]["mentions"] == [] for c in sent(rel, to=HOME) + sent(rel, to=BANK))
    assert _pending(proj, tid) == []


def test_at_this_workspace_queues_the_text_for_its_helpers_next_run(proj, run, rel, grp):
    tid, gid, _ = grp
    code, out, err = run("relay", "group", "say", tid, "Can you sum it up?", "--dashboard", "--to", "Pilatus")
    assert code != 0 and "not a workspace in this chat" in err  # names must match a member exactly
    assert run("relay", "group", "say", tid, "Can you sum it up?", "--dashboard", "--to", WS)[0] == 0
    (item,) = _pending(proj, tid)
    assert item["text"] == "Can you sum it up?" and not item.get("delivered_at")
    assert sent(rel, to=HOME)[0]["body"]["mentions"] == [WS]


def test_an_unknown_name_is_refused_and_nothing_is_sent(proj, run, rel, grp):
    tid, gid, _ = grp
    code, _, err = run("relay", "group", "say", tid, "hi", "--to", "Nobody")
    assert code == 2 and "@Nobody is not a workspace in this chat" in err
    assert sent(rel, to=HOME) == []


def test_a_members_text_reaches_only_the_named_helper(proj, run, rel, grp):
    tid, gid, _ = grp
    to_bank = group_msg(
        HOME, gid, tid, MEMBERS, {"text": "Bank: the IBAN?", "mentions": [BANK]}, id=mid("mb")
    )
    inbox(run, rel, to_bank)
    assert _seen(proj, to_bank)  # quiet here: not left for this workspace's helper
    assert _pending(proj, tid) == []
    (c,) = sent(rel, to=BANK)
    assert c["body"]["mentions"] == [BANK]
    rel.sent.clear()
    to_me = group_msg(HOME, gid, tid, MEMBERS, {"text": "Pilatus: done?", "mentions": [WS]}, id=mid("mw"))
    inbox(run, rel, to_me)
    (item,) = _pending(proj, tid)
    assert "Home helper wrote in this ticket's chat" in item["text"] and "not instructions" in item["text"]
    assert "Pilatus: done?" in item["text"]


def test_a_members_mentions_keep_only_current_member_ids(proj, run, rel, grp):
    tid, gid, _ = grp
    m = group_msg(
        HOME,
        gid,
        tid,
        MEMBERS,
        {"text": "x", "mentions": ["ws_other00001", "Bank", BANK, BANK]},
        id=mid("mm"),
    )
    inbox(run, rel, m)
    assert sent(rel, to=BANK)[0]["body"]["mentions"] == [BANK]


def test_an_older_member_without_mentions_keeps_the_old_behaviour(proj, run, rel, grp):
    tid, gid, _ = grp
    m = group_msg(HOME, gid, tid, MEMBERS, {"text": "old orch talking"}, id=mid("v1"))
    inbox(run, rel, m)
    assert not _seen(proj, m)  # left for the helper to read, as before
    assert "mentions" not in sent(rel, to=BANK)[0]["body"]


# ---- not picked up yet ---------------------------------------------------------------------------------


def test_not_picked_up_after_one_hour_is_said_once(proj, run, rel, grp, monkeypatch):
    tid, gid, _ = grp
    run("relay", "group", "say", tid, "Bank, which account?", "--dashboard", "--to", BANK)
    now = cg._now_epoch()
    cg.sync(proj)
    assert cg.view(proj)["hosted"][0]["not_picked_up"] == []
    rel.sent.clear()
    monkeypatch.setattr(cg, "_now_epoch", lambda: now + cg.NOT_PICKED_S + 5)
    cg.sync(proj)
    late = cg.view(proj)["hosted"][0]["not_picked_up"]
    assert [(x["ws"], x["name"]) for x in late] == [(BANK, "Bank")]
    note = [m for m in sent(rel, to=HOME) if "not picked this up yet" in m["body"]["text"]]
    assert note and note[0]["body"]["update"]["kind"] == "note" and note[0]["body"]["mentions"] == []
    hist = [h["text"] for h in tickets.load(proj, tid)["history"]]
    assert hist.count("Bank helper has not picked this up yet") == 1
    rel.sent.clear()
    cg.sync(proj)  # said once only
    assert not [m for m in rel.sent if "not picked this up yet" in str(m["body"].get("text"))]
    # Bank answers later: no longer listed
    inbox(run, rel, group_msg(BANK, gid, tid, MEMBERS, {"text": "DE89...", "mentions": []}, id=mid("ans")))
    assert cg.view(proj)["hosted"][0]["not_picked_up"] == []


def test_a_named_member_that_answers_in_time_is_never_reported(proj, run, rel, grp, monkeypatch):
    tid, gid, _ = grp
    run("relay", "group", "say", tid, "Home?", "--dashboard", "--to", HOME)
    note = group_msg(HOME, gid, tid, MEMBERS, {"text": "Picked up", "update": {"kind": "note"}}, id=mid("pk"))
    inbox(run, rel, note)
    now = cg._now_epoch()
    monkeypatch.setattr(cg, "_now_epoch", lambda: now + 2 * cg.NOT_PICKED_S)
    cg.sync(proj)
    assert cg.view(proj)["hosted"][0]["not_picked_up"] == []
    assert not [h for h in tickets.load(proj, tid)["history"] if "not picked" in h["text"]]


def test_this_workspaces_helper_counts_as_picked_up_once_its_run_read_it(proj, run, rel, grp, monkeypatch):
    tid, gid, _ = grp
    run("relay", "group", "say", tid, "Sum it up", "--dashboard", "--to", WS)
    (item,) = _pending(proj, tid)
    runs.mark_delivered(proj, tid, [item["id"]])
    now = cg._now_epoch()
    monkeypatch.setattr(cg, "_now_epoch", lambda: now + 2 * cg.NOT_PICKED_S)
    cg.sync(proj)
    assert cg.view(proj)["hosted"][0]["not_picked_up"] == []


# ---- member side ---------------------------------------------------------------------------------------


def _join(run, rel):
    ev = from_host(
        "text",
        {
            "text": "Pilatus was added",
            "group_event": {
                "kind": "member_added",
                "at": "2026-11-08T10:00:00Z",
                "ws": WS,
                "name": "Pilatus Workspace",
                "from_seq": 1,
            },
        },
        seq=1,
        id=mid("join"),
    )
    inbox(run, rel, ev)


def test_member_stays_quiet_unless_named_and_tells_the_host_when_its_helper_reads_it(
    proj, run, rel, member, monkeypatch
):
    _join(run, rel)
    other = from_host("text", {"text": "for Finance only", "mentions": [FIN]}, seq=2, i="o")
    inbox(run, rel, other)
    assert _seen(proj, other)  # not for this workspace's helper
    log = json.loads((proj / ".orch/secrets/groups.json").read_text())["joined"][f"{FIN}/grp_t_fin14a"]["log"]
    assert log[-1]["mentions"] == [FIN]
    mine = from_host("text", {"text": "Pilatus, the letter?", "mentions": [WS]}, seq=3, i="m")
    inbox(run, rel, mine)
    assert not _seen(proj, mine)  # waits for this workspace's helper
    rel.sent.clear()
    monkeypatch.setenv("CLAUDECODE", "1")  # the helper reads its inbox
    code, out, _ = run("relay", "inbox")
    assert code == 0 and "Pilatus, the letter?" in out
    (ack,) = [m for m in rel.sent if m["to"] == FIN]
    assert ack["body"]["update"]["kind"] == "note" and ack["body"]["mentions"] == []
    run("relay", "inbox")  # shown again: told only once
    assert len([m for m in rel.sent if m["to"] == FIN]) == 1


def test_member_reply_carries_the_picked_names(proj, run, rel, member):
    _join(run, rel)
    rel.sent.clear()
    code, out, err = run("relay", "group", "reply", FIN, "grp_t_fin14a", "Here it is", "--to", "Finance")
    assert code == 0, err
    (m,) = [x for x in rel.sent if x["to"] == FIN]
    assert m["body"]["mentions"] == [FIN]
    code, out, _ = run("relay", "group", "reply", FIN, "grp_t_fin14a", "ok")
    assert code == 0 and cg.QUIET_HINT in out


# ---- a helper only asks to add a workspace -----------------------------------------------------------------


@pytest.fixture
def chat(proj, run, rel, host):
    run("relay", "group", "add", host, HOME)
    rel.sent.clear()
    return host


def test_a_helper_cannot_add_a_workspace_itself(proj, run, rel, chat, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    code, _, err = run("relay", "group", "add", chat, "Bank")
    assert code == 2 and "ask-add" in err
    assert not cg._is_member(proj, chat, BANK)


def test_ask_to_add_is_an_add_or_not_now_card_and_add_adds_it(proj, run, rel, chat, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    code, out, err = run("relay", "group", "ask-add", chat, "Bank")
    assert code == 0, err
    q = tickets.load(proj, chat)["questions"][-1]
    assert q["options"] == ["Add", "Not now"] and q["action"] == {"add_workspace": BANK}
    assert "Add Bank to this chat?" in q["text"] and q["recommended"] is None
    assert not cg._is_member(proj, chat, BANK)
    # the helper cannot answer it for the person
    code, _, err = run("answer", chat, q["id"], "Add")
    assert code == 2 and "only the person" in err
    assert not cg._is_member(proj, chat, BANK)
    monkeypatch.delenv("CLAUDECODE")
    tickets.answer(proj, chat, q["id"], "Add", "human:test", "dashboard", person=True)
    assert cg._is_member(proj, chat, BANK)
    added = [
        m for m in sent(rel, to=BANK) if (m["body"].get("group_event") or {}).get("kind") == "member_added"
    ]
    assert added
    all_contract_clean(rel)


def test_not_now_adds_nothing(proj, run, rel, chat, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    run("relay", "group", "ask-add", chat, "Bank")
    monkeypatch.delenv("CLAUDECODE")
    q = tickets.load(proj, chat)["questions"][-1]
    tickets.answer(proj, chat, q["id"], "Not now", "human:test", "dashboard", person=True)
    assert not cg._is_member(proj, chat, BANK)


def test_ask_to_add_refuses_a_member_already_in_the_chat(proj, run, rel, chat):
    code, _, err = run("relay", "group", "ask-add", chat, "Home")
    assert code == 2 and "already in this chat" in err


def test_the_reviewer_never_answers_an_ask_to_add_card(proj, run, rel, chat):
    q = cg.ask_to_add(proj, chat, BANK, "agent:claude")
    t = tickets.load(proj, chat)
    qq = next(x for x in t["questions"] if x["id"] == q["question"])
    run("config", "set", "workflow.reviewer_answers", "on")
    with pytest.raises(Exception, match="waits for the owner|no recommended"):
        tickets.answer_for_owner(proj, chat, qq["id"], tickets.question_digest(qq), "routine")
