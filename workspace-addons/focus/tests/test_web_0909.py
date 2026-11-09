"""Static regressions for the 0909 Focus board changes."""
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/orch_focus/web"
JS = (WEB / "focus.js").read_text()
CSS = (WEB / "focus.css").read_text()
PROOF = (WEB / "proof.js").read_text()


def test_task_form_is_visible_and_quiet():
    assert "class: 'fx-add'" not in JS
    assert "+ Add task" not in JS
    assert "placeholder: 'Add a task'" in JS
    form = JS.split("els.addForm =", 1)[1].split("const rail", 1)[0]
    assert "icon: 'plus'" in form
    assert "icon: 'send'" not in form
    assert "aria-label': 'Add task'" in form
    assert "margin-top:auto" in CSS


def test_worked_clock_and_accessible_session():
    assert "h('button', {class: 'fx-live'" in JS
    pill = JS.split("els.live =", 1)[1].split("els.stopIc", 1)[0]
    assert "'aria-expanded': 'false'" in pill
    assert "'aria-haspopup': 'dialog'" in pill
    assert "aria-live" not in pill
    assert "v.run.worked" in JS
    assert "Date.parse(v.run.started_at)" not in JS
    assert "performance.now()" in JS
    assert "v.state === 'working'" in JS
    assert "v.run.paused" in JS and "stamp(v.run.first)" in JS
    assert "if (context)" in JS and "context.reused" in JS


def test_menu_floats_and_keeps_stop_in_toolbar():
    assert "h('details', {class: 'fx-more'" not in JS
    assert "els.phone, els.stop, els.more" in JS
    assert "prepend(els.stop)" not in JS
    assert ".fx-popover{position:absolute;right:0;top:100%;z-index:40" in CSS
    assert "width:222px;padding:5px" in CSS
    assert "max-width:calc(100vw - 32px)" in CSS
    assert "height:40px" in CSS
    assert "e.key !== 'Escape'" in JS
    assert "!els.more.contains(e.target)" in JS


def test_page_preview_defaults_to_page_and_preserves_sandbox():
    assert "[['Page', showPage], ['Code', showSource]]" in PROOF
    assert "        showPage();" in PROOF
    assert "sandbox: 'allow-scripts', referrerpolicy: 'no-referrer'" in PROOF
