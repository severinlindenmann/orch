"""Properties rows: every label above its value (W-031); an add-on word starts with a capital (ORCH-1715)."""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
PAGE = ROOT / "workspace-addons/dashboard/src/orch_dashboard/web/pages/ticket.js"
CSS = ROOT / "workspace/src/orch_ui/static/widgets.css"


def test_every_property_row_has_its_label_above_its_value():
    """W-031 (owner chose B, 28 Nov): the column is rebuilt with labels above values, on the master's row."""
    page = PAGE.read_text(encoding="utf-8")
    assert "const RAIL_ROW = 'rail-long';" in page
    assert "field('Helper strength', modelField(t), 'model') : null" in page
    assert "'rail-top'" not in page
    css = CSS.read_text(encoding="utf-8")
    assert ".rail-sheet dl>div.rail-long{grid-template-columns:minmax(0,1fr);align-items:start;gap:var(--s1)}" in css


def test_addon_property_word_is_capitalised():
    page = PAGE.read_text(encoding="utf-8")
    assert "v0.charAt(0).toUpperCase() + v0.slice(1)" in page
