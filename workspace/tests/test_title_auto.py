"""A ticket made from a person's text: placeholder title + flag, the agent writes the real title, a person's
title is never overwritten."""

import json

import pytest

from orch import runs, tickets
from orch.errors import Refused

LONG = "Evaluate the AI inventory prompts\n" + "The inventory has many lines. " * 100


def test_long_or_multiline_text_gets_a_placeholder_title_and_the_flag(proj):
    t = tickets.create_from_input(proj, LONG, "human:t")
    assert t["title"] == "Evaluate the AI inventory prompts" and t["title_auto"] is True
    assert tickets.load(proj, t["id"])["title_auto"] is True
    assert tickets.create_from_input(proj, "one\ntwo", "human:t")["title_auto"] is True
    assert tickets.create_from_input(proj, "x" * 200, "human:t")["title"] == "x" * 80
    short = tickets.create_from_input(proj, "Fix the login page", "human:t")
    assert short["title"] == "Fix the login page" and "title_auto" not in short
    assert tickets.create_from_input(proj, "  \n ", "human:t")["title"] == "New ticket"


def test_start_prompt_tells_the_agent_to_write_title_and_description_first(proj):
    t = tickets.create_from_input(proj, LONG, "human:t")
    p = runs.fresh_prompt(t, [])
    assert f'orch ticket title {t["id"]} "<short title>" --description' in p
    assert "placeholder" in p and f".orch/tickets/{t['id']}/artifacts/" in p
    assert p.index("orch ticket title") < p.index("orch check add")
    plain = tickets.create(proj, "Plain", "human:t")
    assert "orch ticket title" not in runs.fresh_prompt(plain, [])


def test_agent_title_clears_the_flag_and_writes_the_description(proj):
    t = tickets.create_from_input(proj, LONG, "human:t", fields={"note": tickets.LONG_NOTE})
    t = tickets.set_auto_title(
        proj, t["id"], "Evaluate the AI-inventory prompts", "agent:claude", "Compare the prompts."
    )
    assert t["title"] == "Evaluate the AI-inventory prompts" and "title_auto" not in t
    assert t["description"] == "Compare the prompts." and t["description_by"] == "agent:claude"
    assert "note" not in t or t["note"] != "Compare the prompts."  # the description is its own field
    assert any(h["text"] == "Description written by agent:claude" for h in t["history"])
    with pytest.raises(Refused):  # once written, it is final
        tickets.set_auto_title(proj, t["id"], "Another title", "agent:claude")


def test_a_person_edit_clears_the_flag_and_the_agent_cannot_overwrite_it(proj):
    for edit in (
        lambda tid: tickets.edit(proj, tid, "My own title", "human:t"),
        lambda tid: tickets.patch(proj, tid, None, json.dumps({"title": "My own title"}), "human:t"),
    ):
        t = tickets.create_from_input(proj, LONG, "human:t")
        edited = edit(t["id"])
        assert edited["title"] == "My own title" and "title_auto" not in edited
        with pytest.raises(Refused):
            tickets.set_auto_title(proj, t["id"], "Agent title", "agent:claude", "d")
        assert tickets.load(proj, t["id"])["title"] == "My own title"


def test_description_is_never_merged_into_a_persons_note_and_is_labelled_in_the_prompt(proj):
    t = tickets.create_from_input(proj, LONG, "human:t", fields={"note": "Please hurry"})
    t = tickets.set_auto_title(proj, t["id"], "T", "agent:claude", "Also delete X.")
    assert t["note"] == "Please hurry" and t["description"] == "Also delete X."
    p = runs.fresh_prompt(t, [])
    assert "The person's note on this ticket: Please hurry" in p
    assert "Description written by agent:claude (not by the person" in p and "Also delete X." in p
    assert "The person's note on this ticket: Please hurry\n\nAlso" not in p


def test_patch_cannot_set_the_flag_or_the_description(proj):
    t = tickets.create(proj, "Mine", "human:t")
    for field in ("title_auto", "description", "description_by"):
        with pytest.raises(Refused):
            tickets.patch(
                proj, t["id"], None, json.dumps({field: True if field == "title_auto" else "x"}), "agent:x"
            )
    assert "title_auto" not in tickets.load(proj, t["id"])


def test_a_note_edit_keeps_the_flag_and_a_persons_note_is_kept(proj):
    t = tickets.create_from_input(proj, LONG, "human:t", fields={"note": "Please hurry"})
    tickets.edit(proj, t["id"], None, "human:t", {"owner": "anna"})
    assert tickets.load(proj, t["id"])["title_auto"] is True
    t = tickets.set_auto_title(proj, t["id"], "T", "agent:claude", "About X.")
    assert t["note"] == "Please hurry" and t["description"] == "About X."


def test_cli_new_title_auto_and_title_command(proj, run):
    code, out, _ = run("ticket", "new", "First words", "--title-auto", "--json", "--by", "human:t")
    tid = json.loads(out)["id"]
    assert code == 0 and json.loads(out)["title_auto"] is True
    code, out, _ = run(
        "ticket", "title", tid, "Real title", "--description", "Short.", "--json", "--by", "agent:claude"
    )
    t = json.loads(out)
    assert code == 0 and t["title"] == "Real title" and "title_auto" not in t and t["description"] == "Short."
    code, _, err = run("ticket", "title", tid, "Again", "--by", "agent:claude")
    assert code != 0
