"""Chat lines carry a stable id and an optional typed name (contracts/history.md "Chat lines", team chat 1.2).
Old lines (no id, no name, or no chat flag at all) still read, show and validate; nothing is backfilled."""

import json
import shutil
from pathlib import Path

import jsonschema
import pytest

from orch import history, tickets
from orch.errors import Refused

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
FIXTURES = Path(__file__).parent / "fixtures" / "tickets"
OLD = sorted(p for p in FIXTURES.iterdir() if (p / ".orch" / "tickets").is_dir())
EXAMPLE = CONTRACTS / "examples" / "ticket" / "valid-chat-line-name-and-id.json"


def _line_validator():
    schema = json.loads((CONTRACTS / "ticket.schema.json").read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator({"$defs": schema["$defs"], "$ref": "#/$defs/history"})


def _ticket():
    return {"history": []}


def test_a_chat_line_gets_a_stable_id_and_the_typed_name():
    t = _ticket()
    tickets.add_history(t, "human:lume", "Can we move it?", "dashboard", chat=True, by_name="  Anna ​ Müller ")
    line = t["history"][-1]
    assert tickets.CHAT_LINE_ID_RE.fullmatch(line["id"])
    assert line["by_name"] == "Anna Müller"  # invisible characters go, spaces collapse
    assert line["by"] == "human:lume"  # the actor stays the actor
    assert not list(_line_validator().iter_errors(line))


def test_a_chat_line_keeps_the_message_id_it_already_has():
    t = _ticket()
    tickets.add_history(t, "agent:claude", "Yes", chat=True, mid="m_q0w9e8r7t6y5u4i3")
    assert t["history"][-1]["id"] == "m_q0w9e8r7t6y5u4i3"
    assert "by_name" not in t["history"][-1]


def test_every_chat_line_gets_its_own_id():
    t = _ticket()
    for _ in range(50):
        tickets.add_history(t, "agent:claude", "x", chat=True)
    assert len({h["id"] for h in t["history"]}) == 50


@pytest.mark.parametrize("name", [None, "", "   ", "​"])
def test_no_name_means_no_field(name):
    t = _ticket()
    tickets.add_history(t, "human:lume", "hi", chat=True, by_name=name)
    assert "by_name" not in t["history"][-1]


def test_refused_values():
    t = _ticket()
    with pytest.raises(Refused):
        tickets.add_history(t, "human:lume", "hi", chat=True, by_name="x" * 61)
    with pytest.raises(Refused):
        tickets.add_history(t, "human:lume", "hi", chat=True, mid="m_SHORT")
    with pytest.raises(Refused):
        tickets.add_history(t, "human:lume", "Step c1 done", by_name="Anna")
    with pytest.raises(Refused):
        tickets.add_history(t, "human:lume", "Step c1 done", mid="m_q0w9e8r7t6y5u4i3")
    assert t["history"] == []


def test_a_plain_line_has_neither_field():
    t = _ticket()
    tickets.add_history(t, "agent:claude", "Step c1 done")
    assert "id" not in t["history"][-1] and "by_name" not in t["history"][-1]


def test_a_line_not_proven_here_is_shown_without_its_typed_name():
    shown = history._demoted_line(
        {
            "at": "x",
            "by": "human:mallory",
            "text": "hi",
            "chat_message": True,
            "id": "m_q0w9e8r7t6y5u4i3",
            "by_name": "Severin",
        }
    )
    assert shown["by"] == history.SYNC_BY and "by_name" not in shown and shown["id"] == "m_q0w9e8r7t6y5u4i3"


def test_chat_say_stores_the_message_id_on_the_history_line(proj, run):
    code, out, err = run("chat", "say", "--by", "human:marco", "--json", "--", "Hallo")
    assert code == 0, err
    sent = json.loads(out)
    line = [h for h in tickets.load(proj, sent["ticket"])["history"] if h.get("chat_message")][-1]
    assert line["id"] == sent["id"]  # one id for the message in the day file, the relay and the history


def test_the_contract_example_loads_and_shows(proj, run):
    (proj / ".orch" / "tickets").mkdir(parents=True, exist_ok=True)
    shutil.copy(EXAMPLE, proj / ".orch" / "tickets" / "t_c4at11.json")
    code, out, err = run("ticket", "show", "t_c4at11", "--json")
    assert code == 0, err
    lines = json.loads(out)["history"]
    assert [h.get("id") for h in lines if h.get("chat_message")] == [
        None,
        "m_8f3k2q9z0a1b7c6d",
        "m_q0w9e8r7t6y5u4i3",
    ]
    assert lines[2]["by_name"] == "Anna Müller"


@pytest.mark.parametrize("folder", OLD, ids=lambda p: p.name)
def test_old_tickets_still_read_and_their_lines_are_not_backfilled(folder, proj, run):
    shutil.copytree(folder / ".orch", proj / ".orch", dirs_exist_ok=True)
    v = _line_validator()
    for p in sorted((proj / ".orch" / "tickets").glob("t_*.json")):
        before = json.loads(p.read_text(encoding="utf-8"))["history"]
        for line in before:
            assert not list(v.iter_errors(line)), (p.name, line)
        code, _, err = run("ticket", "show", p.stem, "--json")
        assert code == 0, err
        # a new chat line on an old ticket: the old lines stay exactly as they were
        tickets.apply_op(
            proj, p.stem, lambda t: tickets.add_history(t, "human:lume", "new", chat=True), by="human:lume"
        )
        after = tickets.load(proj, p.stem)["history"]
        assert after[: len(before)] == before
        assert tickets.CHAT_LINE_ID_RE.fullmatch(after[-1]["id"])
