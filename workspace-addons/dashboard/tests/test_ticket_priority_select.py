"""ORCH-813: the Priority select on the ticket page builds orch ticket edit --priority."""

import pathlib

import pytest

from orch_dashboard import actions

PAGE = pathlib.Path(__file__).parent.parent / "src" / "orch_dashboard" / "web" / "pages" / "ticket.js"


@pytest.mark.parametrize("value", ["high", "normal", "low"])
def test_select_builds_the_edit(value):
    argv = actions.build_argv("ticket.edit", {"ticket": "t_abcdef", "priority": value, "if_revision": 3})
    assert f"--priority={value}" in argv
    assert "--if-revision=3" in argv


@pytest.mark.parametrize("bad", ["urgent", "", True, None, 1])
def test_select_takes_only_the_three_values(bad):
    with pytest.raises(actions.BadRequest):
        actions.build_argv("ticket.edit", {"ticket": "t_abcdef", "priority": bad})


def test_ticket_page_shows_the_priority_select():
    page = PAGE.read_text(encoding="utf-8")
    assert "field('Priority', priorityField(t))" in page
    assert "act('ticket.edit', {ticket:t.id, priority:select.value" in page
