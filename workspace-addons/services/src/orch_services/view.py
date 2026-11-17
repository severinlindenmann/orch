"""`orch services view`: the Services page (orch.addon-view/1), list and panel as in the mockup (layout C).

One `split` block with every managed service (state, since when, starts by itself, made by, health and depends on
when known, the last 20 log lines masked), a second group "Found on this computer" when there are found items, and a
footnote to Automation. The dashboard draws the block; every button sends `addon.act <verb> -- <service id>`.

`found` (filled by the Found list): [{"id", "name", "what"?, "since"? (RFC 3339 UTC)}]; an empty list adds nothing."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import store

LOG_LINES = 20
WORD = {"running": "Running", "stopped": "Stopped", "failing": "Failing"}
TONE = {"running": "good", "stopped": "neutral", "failing": "bad"}
AUTO_WORDS = {True: "Yes, after this computer restarts", False: "No, you start it by hand"}
TICKET_ID = re.compile(r"t_[a-z0-9]{6,16}")
ITEM_ID = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,63}")


def _plain(text: str, n: int = 200) -> str:
    """Page text is plain: no angle brackets, no control characters, at most n characters."""
    t = re.sub(r"[\x00-\x1f\x7f]", " ", str(text)).replace("<", "‹").replace(">", "›").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def _when(stamp: str | None, now: datetime | None = None) -> str | None:
    """'today 07:58', 'yesterday 22:40' or 'Mon 16 Nov, 09:12' in this computer's local time."""
    if not stamp:
        return None
    try:
        t = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).astimezone()
    except ValueError:
        return None
    today = (now or datetime.now(UTC)).astimezone().date()
    hm = t.strftime("%H:%M")
    if t.date() == today:
        return f"today {hm}"
    if t.date() == today - timedelta(days=1):
        return f"yesterday {hm}"
    return f"{t.strftime('%a')} {t.day} {t.strftime('%b')}, {hm}"


def _act(verb: str, sid: str) -> dict:
    return {"op": "addon.act", "args": {"verb": verb, "target": sid}}


def _btn(label: str, verb: str, sid: str) -> dict:
    return {"label": label, "action": _act(verb, sid)}


def _ticket_id(root: Path, key: str) -> str | None:
    """The ticket id behind a ticket key (DM1-12 -> t_...), so Made by links to the ticket."""
    if TICKET_ID.fullmatch(key):
        return key
    try:
        from orch import tickets

        tid = tickets.resolve(root, key)
    except Exception:  # noqa: BLE001 - a ticket that is gone keeps its plain key
        return None
    return tid if isinstance(tid, str) and TICKET_ID.fullmatch(tid) else None


def _made_by(root: Path, made: object) -> dict:
    made = made if isinstance(made, dict) else {}
    if isinstance(made.get("ticket"), str):
        fact = {"label": "Made by", "value": _plain(made["ticket"], 40)}
        tid = _ticket_id(root, made["ticket"])
        if tid:
            fact["link"] = tid
        return fact
    if isinstance(made.get("addon"), str):
        return {"label": "Made by", "value": _plain(made["addon"].capitalize() + " add-on", 60)}
    if made.get("found"):
        return {"label": "Made by", "value": "Found, now managed"}
    return {"label": "Made by", "value": "Added by hand"}


def _log(root: Path, sid: str) -> list[str]:
    from .cli import tail_masked

    try:
        lines = tail_masked(root, store.log_path(root, sid), LOG_LINES * 2)  # blank lines are dropped below
    except store.Refused:
        return []
    return [_plain(ln) for ln in lines if ln.strip()][-LOG_LINES:]


def _remove_lines(r: dict, depends: list[str]) -> list[str]:
    stopped = r["state"] == "stopped"
    lines = [
        "It stays stopped and leaves this list." if stopped else "It stops now and leaves this list.",
        "It will not start by itself again.",
    ]
    if depends:
        lines.append(_plain("These stop working: " + ", ".join(depends) + "."))
    made = r.get("made_by")
    if isinstance(made, dict) and isinstance(made.get("ticket"), str):
        lines.append(_plain(f"Ticket {made['ticket']} and its files stay as they are."))
    else:
        lines.append("Its files on this computer stay as they are.")
    return lines


def _service_item(root: Path, r: dict) -> dict:
    sid, name, state = r["id"], _plain(r["name"], 80), r["state"]
    word, tone = WORD.get(state, "Stopped"), TONE.get(state, "neutral")
    since = _when(r.get("since"))
    stopped = state == "stopped"
    main = _btn("Start", "start", sid) if stopped else _btn("Stop", "stop", sid)
    auto = bool(r.get("auto"))
    facts: list[dict] = [
        {"label": "State", "value": f"{word} since {since}" if since else word, "tone": tone},
        {
            "label": "Starts by itself",
            "value": AUTO_WORDS[auto],
            "switch": {
                "on": auto,
                "label": _plain(f"Starts by itself: {name}", 60),
                "action": _act("auto-off" if auto else "auto-on", sid),
            },
        },
        _made_by(root, r.get("made_by")),
    ]
    health = r.get("health")
    if isinstance(health, dict) and isinstance(health.get("text"), str) and health["text"].strip():
        facts.append(
            {
                "label": "Health check",
                "value": _plain(health["text"]),
                "tone": "good" if health.get("ok") else "bad",
            }
        )
    depends = [_plain(d, 80) for d in r.get("depends") or [] if isinstance(d, str) and d.strip()][:6]
    if depends:
        facts.append({"label": "Depends on it", "value": _plain(", ".join(depends))})
    return {
        "id": sid,
        "title": name,
        "state": {"label": word, "tone": tone},
        "action": main,
        "panel": {
            "buttons": [main] if stopped else [main, _btn("Restart", "restart", sid)],
            "facts": facts,
            "log": {"lines": _log(root, sid), "empty": _plain(f"{name} has not written anything yet.")},
            "danger": {
                "label": "Remove",
                "note": "Remove takes it off this list for good.",
                "action": _act("remove", sid),
                "confirm": {
                    "title": _plain(f"Remove {name}?", 80),
                    "lines": _remove_lines(r, depends),
                    "keep": "Keep it",
                },
            },
        },
    }


def _found_item(f: dict) -> dict | None:
    sid, name = f.get("id"), f.get("name")
    if not (isinstance(sid, str) and 0 < len(sid) <= 200 and isinstance(name, str) and name.strip()):
        return None
    # Found ids keep the platform's label (often with capitals); the page takes only a plain id, so the item gets
    # a stable one of its own and Manage with orch still sends the real found id.
    vid = sid if ITEM_ID.fullmatch(sid) else "found-" + hashlib.sha1(sid.encode("utf-8")).hexdigest()[:12]
    since = _when(f.get("since"))
    facts = [
        {"label": "Found", "value": (f"Running since {since}" if since else "Running") + ", not made by orch"}
    ]
    if isinstance(f.get("what"), str) and f["what"].strip():
        facts.append({"label": "What it is", "value": _plain(f["what"])})
    return {
        "id": vid,
        "title": _plain(name, 80),
        "state": {"label": "Running, not managed", "tone": "neutral"},
        "panel": {
            "facts": facts,
            "note": "orch leaves it alone until you say so.",
            "buttons": [_btn("Manage with orch", "adopt", sid)],
        },
    }


def _summary(rows: list[dict]) -> str:
    n = {s: sum(1 for r in rows if r["state"] == s) for s in WORD}
    return " · ".join([f"{n['running']} running"] + [f"{n[s]} {s}" for s in ("stopped", "failing") if n[s]])


def build(root, listing: tuple[list[dict], int, str | None], found: list[dict] | None = None) -> dict:
    rows, bad, note = listing
    order = [r for r in rows if r["state"] == "failing"] + [r for r in rows if r["state"] != "failing"]
    groups: list[dict] = []
    if order:
        items = [_service_item(Path(root), r) for r in order[:50]]
        groups.append({"title": "Managed with orch", "meta": _summary(rows), "items": items})
    found_items = [i for i in (_found_item(f) for f in found or [] if isinstance(f, dict)) if i][:50]
    if found_items:
        groups.append({"title": "Found on this computer", "items": found_items})
    view: dict = {
        "schema": "orch.addon-view/1",
        "generated_at": store.now(),
        "blocks": [
            {
                "type": "split",
                "title": "Services",
                "param": "svc",
                "groups": groups,
                "empty": {
                    "title": "No services yet",
                    "text": "When a ticket needs something to keep running on this computer, it shows up here.",
                    "button": {"label": "Ask the helper", "to": "app:chat"},
                },
            },
            {
                "type": "footnote",
                "text": "Timed jobs that run and end are in Automation.",
                "link": {"label": "Open Automation", "to": "app:addon/automation"},
            },
        ],
    }
    if note:
        view["notice"] = _plain(note)
        view["notice_tone"] = "warn"
    elif bad:
        view["notice"] = f"{bad} service file(s) could not be read and are left out."
        view["notice_tone"] = "warn"
    return view
