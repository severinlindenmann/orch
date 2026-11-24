"""ORCH-1715: a Properties label stays on the line of its value; an add-on word starts with a capital."""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
PAGE = ROOT / "workspace-addons/dashboard/src/orch_dashboard/web/pages/ticket.js"
CSS = ROOT / "workspace/src/orch_ui/static/widgets.css"


def test_helper_strength_row_keeps_its_label_on_the_first_line():
    page = PAGE.read_text(encoding="utf-8")
    assert "field('Helper strength', modelField(t), 'model', 'rail-top')" in page
    css = CSS.read_text(encoding="utf-8")
    assert ".rail-sheet dl>div.rail-top{align-items:start}" in css


def test_addon_property_word_is_capitalised():
    page = PAGE.read_text(encoding="utf-8")
    assert "v0.charAt(0).toUpperCase() + v0.slice(1)" in page
