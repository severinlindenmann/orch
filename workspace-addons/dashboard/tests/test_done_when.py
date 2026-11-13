"""Done criteria are passed as plain text and available in both ticket views."""

import json

import pytest

from orch_dashboard import actions

from .webjs import WEB


@pytest.mark.parametrize("value", ["First thing.\n\n  Second thing.", "", "--literal"])
@pytest.mark.parametrize("op", ["ticket.new", "ticket.edit"])
def test_done_when_flag(op, value):
    args = {"title": "Export"} if op == "ticket.new" else {"ticket": "t_abcdef"}
    args["done_when"] = value
    argv = actions.build_argv(op, args)
    if value or op == "ticket.edit":
        assert f"--done-when={value}" in argv
    else:
        assert not any(x.startswith("--done-when") for x in argv)


@pytest.mark.parametrize("value", ["First thing.\nSecond thing.", ""])
def test_patch_accepts_done_when(value):
    data = {"done_when": value}
    argv = actions.build_argv(
        "ticket.patch",
        {
            "ticket": "t_abcdef",
            "data": data,
            "if_revision": 1,
        },
    )
    assert json.loads(argv[-1]) == data


@pytest.mark.parametrize("op", ["ticket.new", "ticket.edit", "ticket.patch"])
def test_nontext_rejected(op):
    args = (
        {"title": "Export", "done_when": 123}
        if op == "ticket.new"
        else {
            "ticket": "t_abcdef",
            "done_when": 123,
        }
    )
    if op == "ticket.patch":
        args = {"ticket": "t_abcdef", "data": {"done_when": 123}, "if_revision": 1}
    with pytest.raises(actions.BadRequest):
        actions.build_argv(op, args)


def test_optional_done_when_in_new_and_edit_dialog():
    js = (WEB / "pages" / "newticket.js").read_text()
    assert "'What should be true when it is done?'" in js
    assert "t ? ['owner', 'due', 'note', 'done_when'] : ['owner', 'due', 'done_when']" in js
    assert "input.name = field" in js
    assert "input.rows = 4; input.maxLength = 2000" in js
    assert "Optional. Say it in your own words, the helper turns it into tasks." in js
    assert js.index("'More options'") < js.index("field === 'done_when'")
    assert "optionalFields.append(label)" in js
    assert "key === 'done_when' ? input.value : input.value.trim()" in js


def test_ticket_details_and_readonly_multiline():
    js = (WEB / "pages" / "ticket.js").read_text()
    # Note sits in the Overview; empty Owner/Due/Done when hide behind "+ Add detail".
    assert "h('div', {className:'ticket-note', 'data-key':'ticket-note'}, inlineField(t, 'note'))" in js
    assert "[['owner', 'Owner'], ['due', 'Due'], ['done_when', 'Done when']]" in js
    assert "'+ Add detail'" in js
    assert "done_when:'Say what should be true when it is done'" in js
    assert "const MULTILINE = ['note', 'done_when']" in js
    assert "if (snapshot) return el('span', MULTILINE.includes(field) ? 'ed-ro preserve-lines'" in js
    assert "MULTILINE.includes(field) ? 'textarea' : 'input'" in js
    assert "MULTILINE.includes(field) && event.shiftKey" in js
    assert "MULTILINE.includes(field) ? input.value : input.value.trim()" in js
    assert (
        "actRetry('ticket.edit', () => ({ticket:t.id, [field]:value, if_revision:(ticketOf(t.id) || t).revision})"
        in js
    )


def test_tickets_carry_the_core_proof_line():
    from orch_dashboard.data import add_proof_state

    t = {
        "checklist": [{"id": "c1", "text": "a", "done": True, "evidence": [{"type": "command", "ref": "x"}]}]
    }
    add_proof_state([t])
    assert t["proof"]["line"] == "1 check passed" and t["proof"]["per_item"] == {"c1": "passed"}


def test_proof_line_says_changed_since_the_recorded_check(tmp_path):
    import subprocess

    from orch import filesig

    from orch_dashboard.data import add_proof_state

    run = lambda *a: subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *a],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    run("init", "-q")
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    run("add", ".")
    run("commit", "-q", "-m", "x")
    ev = {"type": "command", "ref": "pytest", "exit": 0, "files_sig": filesig.files_sig(tmp_path)}
    t = {"checklist": [{"id": "c1", "text": "a", "done": True, "evidence": [ev]}]}
    filesig._CACHE.clear()
    add_proof_state([t], tmp_path)
    assert t["proof"]["line"] == "1 check passed"
    (tmp_path / "a.txt").write_text("two\n", encoding="utf-8")
    filesig._CACHE.clear()
    add_proof_state([t], tmp_path)
    assert t["proof"]["line"] == "Changes haven't been checked yet"
