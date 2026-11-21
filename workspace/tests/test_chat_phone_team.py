"""Team chat 2.5 (ORCH-1175): the person's Add from a ticket chat on the phone. The relay sets `body.team`
only on a phone's text (relay-api.md, POST /v1/phone/send); the ticket's workspace adds only a workspace it
may add, and only for a phone paired to it. Same fake relay and helpers as test_chat_groups.py."""

import pytest
import test_chat_groups as tcg
from test_chat_groups import BANK, HOME, PHONE, all_contract_clean, inbox, mid

from orch import chat_groups as cg
from orch import tickets

host = tcg.host  # the same fixture as the group chat tests


def team_text(ticket, add, i=1, frm=PHONE):
    return {
        "schema": "orch.msg/1",
        "id": mid(f"team{i}{add}"),
        "from": frm,
        "to": tcg.WS,
        "type": "text",
        "created_at": "2026-11-21T08:40:00Z",
        "ticket": ticket,
        "body": {"text": "Add Home to this chat", "team": {"add": add}},
    }


def _chat_lines(proj, tid):
    return [h for h in tickets.load(proj, tid).get("history", []) if h.get("chat_message") is True]


def test_the_phones_add_adds_the_workspace_and_tells_everyone(proj, run, rel, host):
    inbox(run, rel, team_text(host, HOME))
    assert cg._is_member(proj, host, HOME)
    added = [m for m in rel.sent if (m["body"].get("group_event") or {}).get("kind") == "member_added"]
    assert {m["to"] for m in added} >= {HOME, "phones"}
    assert {m["body"]["group_event"].get("added_by") for m in added} == {"you"}  # the person added it
    all_contract_clean(rel)
    # The same message again (a retry) adds nothing twice.
    rel.sent.clear()
    inbox(run, rel, team_text(host, HOME))
    assert not [m for m in rel.sent if (m["body"].get("group_event") or {}).get("kind") == "member_added"]


def test_an_unpaired_phone_adds_nothing(proj, run, rel, host):
    inbox(run, rel, team_text(host, HOME, frm="ph_unpaired001"))
    assert not cg._is_member(proj, host, HOME)


def test_a_workspace_not_connected_is_refused_in_the_chat(proj, run, rel, host):
    inbox(run, rel, team_text(host, "ws_stranger01"))
    assert not cg._is_member(proj, host, "ws_stranger01")
    assert any("Could not add the workspace" in h.get("text", "") for h in _chat_lines(proj, host))


@pytest.mark.parametrize(
    "team", [{"add": "ph_iphone0001"}, {"add": 5}, "ws_hom0000001", {"mentions": [BANK]}]
)
def test_a_bad_or_empty_choice_does_nothing(proj, run, rel, host, team):
    m = team_text(host, HOME, i=7)
    m["body"]["team"] = team
    assert cg.phone_team(proj, host, m, "human:iPhone") is None
    assert not cg._is_member(proj, host, HOME)


def test_a_workspaces_message_never_counts_as_the_persons_add(proj, run, rel, host):
    m = team_text(host, BANK, i=8, frm=HOME)
    assert cg.phone_team(proj, host, m, "human:iPhone") is None
    assert not cg._is_member(proj, host, BANK)


def test_add_works_on_a_reply_to_a_group_copy_too(proj, run, rel, host):
    inbox(run, rel, team_text(host, HOME))
    run("relay", "group", "say", host, "Hello group")
    copy = [m for m in rel.sent if m["to"] == "phones"][-1]["id"]
    m = team_text(host, BANK, i=9)
    m["reply_to"] = copy
    inbox(run, rel, m)
    assert cg._is_member(proj, host, BANK)
