"""Quick wins of the 14 Nov sweep (section 4): wording and toasts that name the ticket."""

from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src" / "orch_dashboard" / "web"
KIT = Path(__file__).resolve().parents[3] / "workspace" / "src" / "orch_ui" / "static"


def test_toasts_name_the_ticket_and_the_helper():
    app = (WEB / "app.js").read_text()
    assert "'Helper started'" in app and "'Helper stopped'" in app and "' on ' +" in app
    assert "toast(result.ok ? (op === 'run.start' ? 'Started'" not in app


def test_history_says_step_not_task():
    helpers = (WEB / "helpers.js").read_text()
    assert "'Finished a task" not in helpers and "'Finished a step" in helpers


def test_tab_counts_are_body_size_grey_not_mono():
    css = (KIT / "components.css").read_text()
    line = next(x for x in css.splitlines() if x.startswith(".tabs sup"))
    assert "13px" in line and "mono" not in line


def test_chat_draft_is_never_filled_from_the_url():
    chat = (WEB / "pages" / "chat.js").read_text()
    assert "say=" not in chat and "'orch.say'" in chat and "e.origin !== location.origin" in chat


def test_person_switch_stays_inside_the_sidebar_and_truncates_long_names():
    """The sidebar footer's person switch never overflows sideways (release-18 finding, owner-fb-fix-g)."""
    css = (KIT / "widgets.css").read_text()
    assert ".person-switch .menu{" in css and "width:min(216px,100%)" in css
    assert ".person-switch>summary .nav-label{min-width:0;overflow:hidden;text-overflow:ellipsis" in css
    assert ".person-switch .menu-pop{grid-template-columns:minmax(0,1fr)}" in css
    assert "node('span', {className: 'truncate'}, n)" in (WEB / "people.js").read_text()
