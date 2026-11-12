"""Insights settings view: built only from CLI answers, plain words, no raw ids on screen."""

import re

from .overview import validated

KEEP_DAYS = ("30", "90", "365")
MAX_MB = ("512", "1024", "2048", "4096")
SWITCH = ("on", "off")
# config key -> (field of `orch record settings --json`, allowed values)
KEYS = {
    "insights.keep_days": ("keep_days", KEEP_DAYS),
    "insights.max_mb": ("max_mb", MAX_MB),
    "insights.share_counts": ("share_counts", SWITCH),
    "insights.share_names": ("share_names", SWITCH),
}
NUMBERS = ("insights.keep_days", "insights.max_mb")
LABELS = {
    "30": "30 days",
    "90": "90 days",
    "365": "365 days",
    "512": "512 MB",
    "1024": "1 GB",
    "2048": "2 GB",
    "4096": "4 GB",
    "on": "On",
    "off": "Off",
}
TID = re.compile(r"t_[a-z0-9]{6,16}")
ERROR = "Insights could not read the settings."
TICKETS_ERROR = "Tickets could not be read."
PERSON = "Open Insights from the dashboard on this computer to change this."
NARROW = "Takes effect at the next cleanup; nothing is deleted now."
WHAT = "Everything agents do, in full detail. Key values never; secrets in text hidden."
WHERE = "In this workspace, kept out of git. If this folder syncs to a cloud drive, the records sync too."
SHARE_NOTE = "Daily counts only, no text, no chats. This workspace's own names stay hidden."
NAMES_NOTE = "Your own skill, connection and key names are sent too."
LOCKS = {
    "off_by_admin": "Switched off by your admin",
    "not_connected": "Not connected to an admin, so nothing is shared",
    None: "Not connected to an admin, so nothing is shared",  # no hub (or no answer): nothing leaves this computer
}


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def valid_settings(answer):
    """The settings answer, or None (unavailable, broken, or missing a value: fail closed)."""
    if not isinstance(answer, dict) or answer.get("status") == "unavailable":
        return None
    if _int(answer.get("keep_days")) is None or _int(answer.get("max_mb")) is None:
        return None
    if not all(isinstance(answer.get(k), bool) for k in ("share_counts", "share_names")):
        return None
    return answer


def current_value(answer, key):
    """The current value of one key as the string the CLI takes, or None when it can not be read."""
    answer = valid_settings(answer)
    if answer is None or key not in KEYS:
        return None
    value = answer[KEYS[key][0]]
    if isinstance(value, bool):
        return "on" if value else "off"
    return str(value)


def needs_person(key, value, current) -> bool:
    """Widening (more detail kept, more space, sharing on) needs the person. Unknown current = widening.
    A hint for the page only: it authorizes nothing, the core decides widening under its own lock."""
    if current is None:
        return True
    if key in NUMBERS:
        return int(value) > int(current)
    return value == "on"


def _options(key, current, can_act, locked=False):
    options = []
    for value in KEYS[key][1]:
        person = needs_person(key, value, current)
        disabled = locked or (person and not can_act and value != current)
        selected = value == current
        options.append(
            {
                "value": value,
                "label": LABELS[value],
                "selected": selected,
                "needs_person": person,
                "disabled": disabled,
            }
        )
    return options


def _row(key, label, current, can_act, note=None, locked=False, reason=None):
    options = [] if locked else _options(key, current, can_act)
    blocked = any(o["disabled"] for o in options)
    return {
        "key": key,
        "label": label,
        "current": current,
        "options": options,
        "locked": locked,
        "reason": reason,
        "note": note,
        "person_note": PERSON if blocked else None,
    }


def _mb(value):
    return str(round(value)) if value >= 10 else f"{value:.1f}".rstrip("0").rstrip(".")


def _usage(answer):
    numbers = [_number(answer.get(k)) for k in ("record_mb", "detail_mb", "runs")]
    if any(n is None for n in numbers):
        return None
    record, detail, runs = numbers
    return f"Using {_mb(record)} MB (detail {_mb(detail)} MB) in {round(runs)} runs"


def _sharing(counts):
    clean = validated(counts)
    if clean is None:
        return None, None
    return clean["sharing"]["counts"], clean.get("since")


def _tickets(tickets):
    if not isinstance(tickets, list):
        return {"rows": [], "error": TICKETS_ERROR}
    rows = []
    for entry in tickets:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("id"), str)
            or not TID.fullmatch(entry["id"])
        ):
            continue
        title = entry.get("title")
        title = re.sub(r"[\x00-\x1f\x7f]", " ", title).strip()[:200] if isinstance(title, str) else ""
        rows.append({"ticket": entry["id"], "title": title or "Untitled ticket"})
    return {"rows": rows, "error": None}


def _share_counts(answer, state, can_act):
    key = "insights.share_counts"
    current = current_value(answer, key)
    if state not in ("on", "off"):
        return _row(key, "Share counts with your admin", current, can_act, SHARE_NOTE, True, LOCKS.get(state))
    return _row(key, "Share counts with your admin", current, can_act, SHARE_NOTE)


def build_settings(settings_json, counts, tickets, can_act: bool) -> dict:
    """The settings view; fails closed to {"error"} when the settings can not be read."""
    answer = valid_settings(settings_json)
    if answer is None:
        return {"error": ERROR}
    can_act = can_act is True
    state, since = _sharing(counts)
    keep = _row(
        "insights.keep_days", "Keep full detail for", current_value(answer, "insights.keep_days"), can_act
    )
    keep["note"] = f"up to {answer['max_mb']} MB, oldest detail first. Counts are kept."
    size = _row("insights.max_mb", "Largest size", current_value(answer, "insights.max_mb"), can_act)
    names = _row(
        "insights.share_names",
        "Share names",
        current_value(answer, "insights.share_names"),
        can_act,
        NAMES_NOTE,
    )
    return {
        "can_act": can_act,
        "recorded": {"what": WHAT, "where": WHERE, "since": since},
        "keep": keep,
        "size": size,
        "usage": _usage(answer),
        "narrow_note": NARROW,
        "share_counts": _share_counts(answer, state, can_act),
        "share_names": names,
        "tickets": _tickets(tickets),
        "sharing": {"on": state == "on"},
    }
