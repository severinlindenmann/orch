"""cli_needs.py: `orch needs` and `orch counts` in an isolated workspace."""

import json

from orch import cli_needs


def _ticket(run, title="Do it"):
    return json.loads(run("ticket", "new", title, "--json")[1])["id"]


def test_needs_and_counts_when_nothing_waits(proj, run):
    run("init")
    assert run("needs")[1].startswith("Nothing needs you.\n")
    assert json.loads(run("needs", "--json")[1]) == []
    code, out, _ = run("counts")
    assert code == 0 and "Needs you: 0 (0 questions, 0 results to review)" in out
    assert "In progress: 0 (no helper running right now)" in out and "Stuck: 0" in out
    c = json.loads(run("counts", "--json")[1])
    assert c["needs_you"]["count"] == 0 and c["stuck"] == 0


def test_needs_text_lists_question_with_options_and_ticket(proj, run):
    run("init")
    tid = _ticket(run)
    assert run("ask", tid, "Ship it?", "--option", "Yes", "--option", "No", "--recommended", "Yes")[0] == 0
    code, out, _ = run("needs")
    assert code == 0 and "Needs you (1)" in out and "Ship it?" in out and "[Yes | No]" in out
    c = run("counts")[1]
    assert "Needs you: 1 (1 question, 0 results to review)" in c


def test_hidden_background_flags_print_nothing(proj, run, monkeypatch):
    run("init")
    seen = []
    monkeypatch.setattr(cli_needs.needs_mod, "refresh", lambda root, name: seen.append(name))
    code, out, _ = run("needs", "--refresh-addon", "x")
    assert code == 0 and "Needs you" not in out and seen == ["x"]


def test_dispatch_ignores_other_commands():
    assert cli_needs.dispatch(type("A", (), {"cmd": "status"})(), None) is False


def test_counts_text_pluralises_and_names_failed_helpers():
    c = {"needs_you": {"count": 3, "questions": 1, "results": 1, "failed": 2}, "working": 4, "stuck": 1}
    text = cli_needs._counts_text(c)
    assert "Needs you: 3 (1 question, 1 result to review, 2 helpers that could not start)" in text
    assert "In progress: 0" in text and "Not started: 0" in text and "Stuck: 1" in text
