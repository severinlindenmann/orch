"""One-tap answers are for plain questions only: every place that mounts the shared question card from a ticket
question passes its `kind`, and the needs-row dialog (permission and add-on questions) never asks for one-tap."""

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src" / "orch_dashboard" / "web"
KIT = Path(__file__).resolve().parents[3] / "workspace" / "src" / "orch_ui" / "static"
FOCUS = Path(__file__).resolve().parents[2] / "focus" / "src" / "orch_focus" / "web" / "live.js"


def test_ticket_page_passes_the_kind_with_one_tap():
    app = (WEB / "app.js").read_text()
    call = re.search(r"mountQuestion\(host, \{[^\n]*\}\);", app)
    assert call and "oneTap:true, kind:q.kind" in call.group(0)


def test_needs_row_dialog_never_asks_for_one_tap():
    ticket = (WEB / "pages" / "ticket.js").read_text()
    line = next(x for x in ticket.splitlines() if "lock:'needs-you'" in x)
    assert "oneTap" not in line


def test_focus_passes_the_kind_with_one_tap():
    live = FOCUS.read_text()
    assert "oneTap: true, kind: q.kind" in live


def test_the_shared_card_needs_both_oneTap_and_no_kind():
    card = (KIT / "question-card.js").read_text()
    assert "immediate: question.oneTap === true && question.kind == null" in card
