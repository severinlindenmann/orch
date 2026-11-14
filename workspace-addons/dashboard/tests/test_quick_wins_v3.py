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
