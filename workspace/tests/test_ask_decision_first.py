"""orch ask --if-wait / --fact (ORCH-2182, Focused review A: the decision-first card). Both are optional:
"If you wait:" (what happens while nobody answers) and the "What matters" lines (the facts that decide it).
An empty one is left out, never guessed; a question without them keeps its old digest. The Review list
carries them, and the dashboard draws them first while the switch workflow.decision_first is on."""

import json

from orch import config, tickets


def _ask(run, tid, *extra):
    return run(
        "ask",
        tid,
        "Keep the old file name?",
        "--option",
        "Keep",
        "--option",
        "Rename",
        *extra,
        "--by",
        "agent:helper",
    )


def test_if_wait_and_facts_are_kept_trimmed_and_in_the_digest(proj, run, new_ticket):
    tid = new_ticket("Files")
    code, out, err = _ask(
        run,
        tid,
        "--if-wait",
        "  The  release waits. ",
        "--fact",
        " 14 links point at it ",
        "--fact",
        "Renaming breaks them",
    )
    assert code == 0, out + err
    q = tickets.load(proj, tid)["questions"][0]
    assert q["if_wait"] == "The release waits."
    assert q["facts"] == ["14 links point at it", "Renaming breaks them"]
    plain = {k: v for k, v in q.items() if k not in ("if_wait", "facts")}
    assert tickets.question_digest(q) != tickets.question_digest(plain)


def test_empty_fields_are_left_out(proj, run, new_ticket):
    tid = new_ticket("Files")
    assert _ask(run, tid, "--if-wait", "  ", "--fact", "", "--fact", " ")[0] == 0
    q = tickets.load(proj, tid)["questions"][0]
    assert "if_wait" not in q and "facts" not in q


def test_limits_one_line_each_and_four_facts(proj, run, new_ticket):
    tid = new_ticket("Files")
    code, out, err = _ask(run, tid, "--if-wait", "x" * 201)
    assert code == 2 and "at most 200" in out + err
    code, out, err = _ask(run, tid, *sum((["--fact", f"fact {i}"] for i in range(5)), []))
    assert code == 2 and "at most 4" in out + err
    assert tickets.load(proj, tid)["questions"] == []


def test_a_card_carries_them_too_and_review_list_shows_them(proj, run, new_ticket):
    tid = new_ticket("Release")
    code, out, err = run(
        "ask",
        tid,
        "Put release 0.42 live?",
        "--plan",
        "Release 0.42",
        "--then",
        "It goes live for everyone.",
        "--if-wait",
        "41 changes wait in develop.",
        "--fact",
        "All checks are green",
        "--by",
        "agent:helper",
    )
    assert code == 0, out + err
    code, out, _ = run("review", "list", "--json")
    item = next(x for x in json.loads(out)["cards"] if x.get("ticket") == tid)
    assert item["if_wait"] == "41 changes wait in develop."
    assert item["facts"] == ["All checks are green"]


def test_a_plain_question_without_them_lists_without_them(proj, run, new_ticket):
    tid = new_ticket("Files")
    assert _ask(run, tid)[0] == 0
    code, out, _ = run("review", "list", "--json")
    item = next(x for x in json.loads(out)["cards"] if x.get("ticket") == tid)
    assert "if_wait" not in item and "facts" not in item


def test_take_back_does_not_take_them(proj, run, new_ticket):
    tid = new_ticket("Files")
    assert _ask(run, tid)[0] == 0
    code, out, err = run(
        "ask", tid, "--take-back", "q1", "not needed", "--if-wait", "x", "--by", "agent:helper"
    )
    assert code == 2


def test_a_secret_in_a_fact_is_refused(proj, run, new_ticket):
    tid = new_ticket("Files")
    code, out, err = _ask(run, tid, "--fact", "the token is ghp_" + "a" * 36)
    assert code == 2
    assert tickets.load(proj, tid)["questions"] == []


def test_the_switch_is_off_by_default_and_anyone_turns_it(proj, run):
    assert config.decision_first_on(proj) is False
    assert run("config", "set", "workflow.decision_first", "on", "--by", "agent:x")[0] == 0
    assert config.decision_first_on(proj) is True
    code, out, _ = run("config", "get", "workflow.decision_first")
    assert code == 0 and ("true" in out.lower() or "on" in out.lower())
    assert run("config", "set", "workflow.decision_first", "maybe", "--by", "agent:x")[0] != 0
    assert run("config", "set", "workflow.decision_first", "off", "--by", "agent:x")[0] == 0
    assert config.decision_first_on(proj) is False
