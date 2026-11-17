"""The phone warns when a tool login, connection or key a helper needs runs out soon or stopped (ORCH-47).

The same warning as dashboard Home, as one text to `phones` per change (contracts/tool-alert.md,
vectors/tool-alert-v1.json). It is built from the last check (`orch logins`, health.py) and carries only the
tool's name, its state, the end date and the display keys of the tickets whose helpers it stops: never a
secret, an account, a command or a ticket title.

Sent only while the relay add-on is on and a phone is paired with this workspace; otherwise nothing is sent
and nothing is remembered. What was sent: .orch/secrets/tool-alerts.json, {name: {state, ends_at, id, at}}.
`sync` runs on every relay inbox pull (relay.sync_phone_views) and never runs a check itself.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path

from orch import health, net

FRESH = timedelta(hours=1)  # an older check is not sent: the warning could be out of date
WARN = ("soon", "renew", "unreachable")
KINDS = ("login", "connection", "key")
STOPS_MAX = 20
LABEL_MAX = 60
TEXT_MAX = 500
_KEY = re.compile(r"[A-Z0-9]{2,4}-[1-9][0-9]{0,8}")
_NAME = re.compile(r"[a-z][a-z0-9-]{0,31}")
_TIME = "%Y-%m-%dT%H:%M:%SZ"
_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip


def _line(text: str, n: int) -> str:
    """One plain line: control, line-break, zero-width and bidi characters become spaces, then cut to n."""
    t = re.sub(r"[\x00-\x1f\x7f-\x9f؜​-‏  ‪-‮⁠-⁤⁦-⁩﻿]", " ", text)
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def label(item: dict) -> str:
    """The tool's name as dashboard Home says it (helpers.js needName): "GitHub login", "Payments key"."""
    kind = item.get("kind") if item.get("kind") in KINDS else "login"
    base = _line(str(item.get("label") or item.get("name") or ""), LABEL_MAX)
    low = base.lower()
    name = base if low == kind or low.endswith(" " + kind) else f"{base} {kind}".strip()
    return _line(name, LABEL_MAX)


def _when(ends_at: str, tz: tzinfo | None) -> str:
    """ "Friday 20 November at 21:24" in the computer's local time (tz None) or the given one."""
    d = datetime.strptime(ends_at, _TIME).replace(tzinfo=UTC).astimezone(tz)
    return f"{_DAYS[d.weekday()]} {d.day} {_MONTHS[d.month - 1]} at {d:%H:%M}"


def _tickets(n: int) -> str:
    return f"{n} ticket" if n == 1 else f"{n} tickets"


def alert(item: dict) -> dict | None:
    """body.tool_alert for one health item, or None when it is not one (unknown state, bad name)."""
    name, state = str(item.get("name") or ""), item.get("state")
    if not _NAME.fullmatch(name) or state not in (*WARN, "works"):
        return None
    ends = item.get("ends_at")
    try:
        ends = datetime.strptime(ends, _TIME).strftime(_TIME) if ends else None
    except (TypeError, ValueError):
        ends = None
    keys: list[str] = []
    if state != "works":
        for t in item.get("stops") or []:
            k = t.get("key") if isinstance(t, dict) else None
            if isinstance(k, str) and _KEY.fullmatch(k) and k not in keys:
                keys.append(k)
    return {
        "name": name,
        "label": label(item),
        "kind": item.get("kind") if item.get("kind") in KINDS else "login",
        "state": state,
        "ends_at": ends,
        "stops": keys[:STOPS_MAX],
        "no_new_work": bool(item.get("chosen")) and state == "renew",
    }


def text(a: dict, tz: tzinfo | None = None) -> str:
    """The warning in the words of dashboard Home (contracts/tool-alert.md, The words)."""
    lab, keys, state = a["label"], a["stops"], a["state"]
    if state == "works":
        return _line(f"The {lab} works again.", TEXT_MAX)
    if state == "soon":
        out = f"The {lab} ends on {_when(a['ends_at'], tz)}." if a["ends_at"] else f"The {lab} runs out soon."
        if keys:
            out += f" After that helpers stop on {_tickets(len(keys))}: {', '.join(keys)}."
        return _line(out + " Renew it on your computer.", TEXT_MAX)
    out = f"The {lab} " + ("cannot be reached." if state == "unreachable" else "stopped working.")
    if keys:
        more = " and start no new work" if a["no_new_work"] else ""
        out += f" Helpers stopped on {_tickets(len(keys))}{more}: {', '.join(keys)}."
    elif a["no_new_work"]:
        out += " Helpers start no new work."
    out += " Check it on your computer." if state == "unreachable" else " Renew it on your computer."
    return _line(out, TEXT_MAX)


def due(items: list, sent: dict, tz: tzinfo | None = None) -> list[dict]:
    """The bodies to send now, in item order: a warning that is new or changed (state or end date), and works
    once after a warning. A changed list of stopped tickets alone sends nothing."""
    out = []
    for item in items:
        a = alert(item) if isinstance(item, dict) else None
        if a is None:
            continue
        before = sent.get(a["name"]) if isinstance(sent.get(a["name"]), dict) else None
        if before and before.get("state") == a["state"] and before.get("ends_at") == a["ends_at"]:
            continue
        if a["state"] == "works" and not (before and before.get("state") in WARN):
            continue
        out.append({"text": text(a, tz), "tool_alert": a})
    return out


def _state_path(root: Path) -> Path:
    return net.secrets_dir(root) / "tool-alerts.json"


def _fresh(doc: dict | None, now: datetime) -> bool:
    try:
        at = datetime.strptime(doc["checked_at"], _TIME).replace(tzinfo=UTC)  # type: ignore[index]
    except (KeyError, TypeError, ValueError):
        return False
    return now - at <= FRESH


def sync(root: Path, now: datetime | None = None, tz: tzinfo | None = None) -> list[str]:
    """Send the warnings that changed since the last send. Nothing at all while the relay add-on is off or no
    phone is paired. Returns the sent message ids."""
    from orch import addons, phone_view, relay  # relay imports this module's caller; keep it lazy

    if "relay" not in addons.active(root) or not phone_view._paired(root):
        return []
    now = now or datetime.now(UTC)
    doc = health.last(root)
    if not doc or not _fresh(doc, now):
        return []
    path = _state_path(root)
    sent = net.read_json(path, {})
    sent = sent if isinstance(sent, dict) else {}
    ids = []
    for body in due(doc["items"], sent, tz):
        a = body["tool_alert"]
        try:
            relay.scan_outgoing(root, body)  # never a secret leaves (R5.2); refused before anything is kept
        except Exception as exc:  # noqa: BLE001
            relay.log_send_failure(root, f"tool warning {a['name']} not sent", exc)
            continue
        rec = {"state": a["state"], "ends_at": a["ends_at"], "id": relay.new_id(), "at": now.strftime(_TIME)}
        sent[a["name"]] = rec
        net.write_json(path, sent, private=True)  # fixed before the send: a retry is the same message
        try:
            msg = relay._message(root, "phones", "text", body, mid=rec["id"], created_at=rec["at"])
            if not msg.get("sent", True):
                relay.log_send_failure(
                    root, f"tool warning {rec['id']} not sent yet", "kept for the next try"
                )
        except Exception as exc:  # noqa: BLE001  a refusal is only logged; the next change sends again
            relay.log_send_failure(root, f"tool warning {rec['id']} failed", exc)
            continue
        ids.append(rec["id"])
    return ids
