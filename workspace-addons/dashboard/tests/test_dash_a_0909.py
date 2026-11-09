"""Round 9 Nov, dashboard A: source contracts for fb2, fb6, fb15, fb29, fb30."""

from tests import webjs


def test_home_has_no_next_step_line_and_folds_needs():
    home = (webjs.WEB / "pages/home.js").read_text()
    assert "Next step" not in home  # fb6
    assert "'Send back'" in home and "'Mark done'" in home  # fb1
    assert ">= 3 && !needsOpen" in home and "'Show all'" in home  # fb2


def test_new_ticket_button_stays_right_with_hidden_switch():
    css = (webjs.WEB / "style.css").read_text()
    assert ".mm-toggle:not([hidden])+.btn.primary{margin-left:0}" in css  # fb29
    assert ".mm-toggle+.btn.primary{margin-left:0}" not in css


def test_send_button_states_and_live_session_strip():
    chat = (webjs.WEB / "pages/chat.js").read_text()
    assert "'data-state':sending ? 'sending' : draft.trim() ? 'ready' : 'empty'" in chat  # fb30
    ticket = (webjs.WEB / "pages/ticket.js").read_text()
    assert "'Watch (read only)'" in ticket and "'Take over (you can type)'" in ticket  # fb15
    assert "' --watch'" in ticket
