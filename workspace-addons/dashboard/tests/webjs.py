"""The dashboard page code is split into web/app.js (shell) and web/pages/*.js; source-string tests read all of it."""
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src" / "orch_dashboard" / "web"
PAGES = ("home", "tickets", "ticket", "newticket", "settings")


def all_js() -> str:
    """app.js plus every page module, as one string (order does not matter for source checks)."""
    parts = [(WEB / "pages" / f"{p}.js").read_text(encoding="utf-8") for p in PAGES]
    return "\n".join([(WEB / "app.js").read_text(encoding="utf-8"), *parts])
