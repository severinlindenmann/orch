"""`orch ticket list --search/--waiting/--blocked`: the dashboard's search and waiting split, from the CLI
(R4.3), each output ending in a next step (R2.7)."""

import json

import pytest


def _last(out):
    return [x for x in out.strip().splitlines() if x][-1]


def _new(run, title):
    return json.loads(run("ticket", "new", title, "--json")[1])["key"]


def test_search_finds_title_tasks_note_and_number_and_says_where_next(proj, run):
    run("init", "--yes")
    a = _new(run, "Write the newsletter")
    b = _new(run, "Plan the trip")
    c = _new(run, "Fix the printer")
    run("check", "add", b, "Book the Zürich hotel")
    run("ticket", "edit", c, "--note", "the toner is EMPTY")
    run("ticket", "status", a, "done")

    code, out, _ = run("ticket", "list", "--search", "zürich")
    assert code == 0 and b in out and c not in out
    assert _last(out).startswith("Next: ") and b in _last(out)

    assert c in run("ticket", "list", "--search", "Toner")[1]
    assert c in run("ticket", "list", "--search", c.split("-")[-1])[1]  # its number alone
    rows = json.loads(run("ticket", "list", "--search", "PLAN", "--json")[1])
    assert [r["key"] for r in rows] == [b]

    code, out, _ = run("ticket", "list", "--search", "newsletter")  # done: only with --all
    assert code == 0 and 'No tickets match "newsletter".' in out
    assert _last(out) == 'Next: look in finished tickets too: orch ticket list --search "newsletter" --all'
    code, out, _ = run("ticket", "list", "--search", "newsletter", "--all")
    assert a in out and _last(out) == f"Next: orch ticket show {a}"


def test_waiting_is_on_a_person_and_blocked_on_something_else(proj, run):
    run("init", "--yes")
    asks = _new(run, "Pick a colour")
    waits = _new(run, "Wait for the supplier")
    _new(run, "Still open")
    run("ask", asks, "Which one?", "--option", "red", "--option", "blue", "--recommend", "red")
    run("wait", waits, "--on", "external:supplier")

    out = run("ticket", "list", "--waiting")[1]
    assert asks in out and waits not in out and "Still open" not in out
    out = run("ticket", "list", "--blocked")[1]
    assert waits in out and asks not in out and _last(out).startswith("Next: ")
    rows = json.loads(run("ticket", "list", "--blocked", "--json")[1])
    assert [r["key"] for r in rows] == [waits]
    assert json.loads(run("ticket", "list", "--blocked", "--search", "colour", "--json")[1]) == []

    run("ask", waits, "Still wait?", "--option", "yes", "--option", "no", "--recommend", "yes")
    code, out, _ = run("ticket", "list", "--blocked")
    assert code == 0 and "No tickets wait on something else." in out
    assert _last(out) == "Next: see every ticket: orch ticket list"
    with pytest.raises(SystemExit):  # one or the other
        run("ticket", "list", "--blocked", "--waiting")
