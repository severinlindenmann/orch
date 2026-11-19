"""GET /api/docs: the Documentation page (book icon next to Settings). The pages come from orch.docs.collect (orch's
own pages and each add-on's docs file); the live facts are read here from this workspace: no network, no AI, never
a secret (a relay or publish address shows only its host name). Drawn by the master's UI.docs (orch_ui docs.js)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit


def _host(url) -> str:
    try:
        return urlsplit(str(url)).hostname or ""
    except ValueError:
        return ""


def _service(root: Path, name: str, on: bool, label: str, host_word: bool) -> dict:
    """relay / publish: Off (add-on off here), Not connected, or Connected (to <host>)."""
    if not on:
        return {"label": label, "value": "Off", "tone": "off", "note": "turn it on in Settings when you need it"}
    try:
        from orch import net

        host = _host(net.load_service(root, name).get("url"))
    except Exception:  # noqa: BLE001 - not connected (Refused) or an unreadable file: say so, never guess
        return {"label": label, "value": "Not connected", "tone": "", "note": ""}
    value = f"Connected to {host}" if host and host_word else "Connected"
    return {"label": label, "value": value, "short": "Connected", "tone": "done", "note": ""}


def live(root: Path, state: dict, rows: list[dict]) -> dict:
    settings = state.get("settings") if isinstance(state.get("settings"), dict) else {}
    on = {r["name"]: bool(r.get("active")) for r in rows}
    tickets = state.get("tickets") if isinstance(state.get("tickets"), list) else []
    working = sum(1 for t in tickets if isinstance(t, dict) and t.get("status") in ("active", "working"))  # stored as active
    limit = settings.get("live_max")
    out = {
        "relay": _service(root, "relay", on.get("relay", False), "Relay", True),
        "publish": _service(root, "publish", on.get("publish", False), "Publish", False),
        "helper-limit": {
            "label": "Helper limit",
            "value": f"{limit} at once" if isinstance(limit, int) and not isinstance(limit, bool) else "No limit",
            "tone": "",
            "note": f"{working} working now",
        },
        "reviewer": {
            "label": "Reviewer",
            "value": "On" if settings.get("reviewer_on") else "Off",
            "tone": "done" if settings.get("reviewer_on") else "off",
            "note": "accepts small, safe changes for you" if settings.get("reviewer_on") else "only you move tickets to Done",
        },
    }
    shown = [r for r in rows if r["name"] not in ("relay", "publish") and (r.get("active") or r.get("docs_pages"))]
    n_on = sum(1 for r in shown if r.get("active"))
    out["addons"] = {"label": "Add-ons", "value": f"{n_on} on, {len(shown) - n_on} off", "tone": "", "note": ""}
    mm = state.get("mobile_mode")
    if isinstance(mm, dict):
        phones = mm.get("phones")
        out["phone"] = {
            "label": "Phone",
            "value": "Questions go to your phone" if mm.get("on") else "Off",
            "tone": "done" if mm.get("on") else "off",
            "note": f"{phones} phone{'' if phones == 1 else 's'} paired" if isinstance(phones, int) else "",
        }
    return out


def build(root: Path, state: dict) -> dict:
    from orch import addons, docs

    try:
        rows = addons.docs_rows(root)
    except Exception:  # noqa: BLE001 - no readable add-on registry here: the shipped pages, all shown as off
        rows = [
            {"name": n, "active": False, "running": False, "background": bool(m.get("background")),
             "docs_pages": m.get("docs_pages") or []}
            for n, m in {**addons.core_manifests(), **addons.bundled_manifests()}.items()
        ]
    data = docs.collect(rows)
    data["live"] = {"read": datetime.now().strftime("%H:%M"), "rows": live(root, state, rows)}
    return data
