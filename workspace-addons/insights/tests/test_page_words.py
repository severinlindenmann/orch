"""ORCH-232: the page never shows a control that is off with its only reason in a hover tooltip."""

import re
from pathlib import Path

HTML = Path(__file__).resolve().parents[1] / "src/orch_insights/web/index.html"


def test_no_control_disabled_with_only_a_tooltip_reason():
    page = HTML.read_text()
    for tag in re.findall(r"<(?:button|input|select)\b[^>]*>", page):
        assert not ("disabled" in tag and "title=" in tag), tag
    assert "data-range" not in page  # only 30 days exists; no placeholder choice
