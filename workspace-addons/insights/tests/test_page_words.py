"""ORCH-232: the page never shows a control that is off with its only reason in a hover tooltip."""

import re
from pathlib import Path

HTML = Path(__file__).resolve().parents[1] / "src/orch_insights/web/index.html"


def test_no_control_disabled_with_only_a_tooltip_reason():
    page = HTML.read_text()
    for tag in re.findall(r"<(?:button|input|select)\b[^>]*>", page):
        assert not ("disabled" in tag and "title=" in tag), tag
    assert "data-range" not in page  # only 30 days exists; no placeholder choice


def test_orch300_plain_words_on_the_page():
    """ORCH-300: approved words shown, old ones gone (health check, helper strength, undo, times helpers worked)."""
    from pathlib import Path

    web = Path(__file__).resolve().parents[1] / "src" / "orch_insights" / "web"
    text = "".join((web / n).read_text() for n in ("index.html", "insights.js", "checkup.js", "settings.js"))
    for new in (
        "Health check",
        "Run a health check",
        "No health check yet",
        "Helper strength",
        "Undo",
        "Undone",
        "Trying it safely",
        "You can undo it",
        "times helpers worked",
        "<summary>More</summary>",
    ):
        assert new in text, new
    text = text.replace("Run a check-up, the Monday", "")
    for old in (
        "Check-up",
        "Run a check-up",
        "Roll back",
        "Rolled back",
        "Testing in a copy",
        "roll it back",
    ):
        assert old not in text, old
    assert "<h2>Model</h2>" not in text


def test_orch1687_the_health_check_line_repeats_no_old_count():
    """ORCH-1687: "helpers worked 4 times" (counted at the last check) sat above "Times helpers worked 5" (now)."""
    web = Path(__file__).resolve().parents[1] / "src" / "orch_insights" / "web"
    line = (web / "checkup.js").read_text()
    assert "helpers worked ${" not in line and "plural(last.tickets" not in line
    assert "plural(last.found, 'proposal')" in line


def test_orch1694_health_check_is_not_the_main_button_and_says_who_ran_it():
    """A paid helper start is no filled button; the last time is the hand-run one, beside a weekly switch that is off."""
    js = (Path(__file__).resolve().parents[1] / "src/orch_insights/web/checkup.js").read_text()
    assert "'Run a health check', 'btn')" in js and "'Run a health check', 'btn primary')" not in js
    assert "Last health check (run by hand): ${when(last.at)}" in js
