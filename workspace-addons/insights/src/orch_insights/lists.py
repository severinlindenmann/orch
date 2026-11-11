"""Full lists of skills, connections and keys, each row with its read-only detail panel."""

from datetime import datetime

from .overview import LABELS, TABS, order, prepare

KINDS = {tab: kind for kind, tab in TABS.items()}
COLUMNS = {
    "skills": ["Skill", "From", "Uses", "State"],
    "connections": ["Connection", "From", "Allowed actions", "State"],
    "keys": ["Key", "From", "Uses", "State"],
}
TONES = {"working": "success", "look": "warning", "idle": "", "new": "info", "unknown": ""}
KEY_TYPES = {"token": "token", "password": "password", "key-file": "key file", "json": "JSON file"}
CONNECTION_STATES = {
    "ok": ("Working", "success"),
    "not-started": ("Not started", ""),
    "missing-key": ("Needs attention", "warning"),
}
TRANSPORTS = {"stdio": ("program on this computer", "Program"), "http": ("web address", "Address")}
PLACES = {
    "workspace": "this workspace",
    "admin": "your admin's shared items",
    "builtin": "orch's built-in skills",
    "marketplace": "the marketplace",
    "harness": "your agent tool's settings",
}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
CANT_TELL = "Can't tell yet"
NOT_PROOF = "Errors are not proof that this is bad."
FILTERS = (("all", "All"), ("look", "Needs a look"), ("idle", "Not used"))


def _plural(n, word):
    return f"{n} {word if n == 1 else word + 's'}"


def _date(value):
    moment = datetime.fromisoformat(value)
    return f"{moment.day} {MONTHS[moment.month - 1]} {moment.year}"


def last_used(item, health, generated):
    """Relative to when the counts were made, never the clock."""
    if health == "unknown" or item["seen"] == "unknown":
        return CANT_TELL
    if item["seen"] == "not_seen":
        return "Never used in 30 days"
    if not item.get("last_seen"):
        return CANT_TELL
    days = (datetime.fromisoformat(generated) - datetime.fromisoformat(item["last_seen"])).days
    if days <= 0:
        return "Last used today"
    return "Last used yesterday" if days == 1 else f"Last used {days} days ago"


def connection_state(state):
    text, tone = CONNECTION_STATES.get(state, (CANT_TELL, ""))
    return {"text": text, "tone": tone}


def key_state(item, row):
    health = row["health"]
    if health == "look" and item["refused"]:
        return {"text": f"Refused {_plural(item['refused'], 'time')}", "tone": "warning"}
    if health in ("look", "idle", "unknown"):
        text = {"look": LABELS["look"], "idle": "Not used 30+ days", "unknown": CANT_TELL}[health]
        return {"text": text, "tone": TONES[health]}
    if item["source"] == "admin":
        return {"text": "Managed by your admin", "tone": "info"}
    return {"text": "In use", "tone": "success"}


def allowed_actions(inventory):
    if not inventory:
        return CANT_TELL
    if inventory["allow_all"]:
        return "All allowed"
    actions = inventory["actions"]
    allowed = sum(action["allowed"] for action in actions)
    if not allowed:
        return "Not allowed by this workspace"
    return f"{allowed} of {len(actions)} allowed"


def versions_line(item):
    versions = item.get("versions") or []
    if len(versions) < 2:
        return None
    latest = max(versions, key=lambda version: datetime.fromisoformat(version["first_seen"]))
    changes = len(versions) - 1
    return (
        f"Changed {_plural(changes, 'time')}; since the latest change: {latest['ok']} of {latest['uses']} ok"
    )


def also_line(counts, kind, name):
    """inventory.md: both entries of a name are listed; say where the other one is and which is used."""
    others = [
        entry["source"]
        for entry in counts["inventory"][TABS[kind]]
        if entry["name"] == name and entry.get("shadowed")
    ]
    if not others:
        return None
    return (
        f"Also in {' and '.join(PLACES.get(source, 'another place') for source in others)}; this one is used"
    )


def _tickets(item):
    tickets = item.get("tickets")
    if not tickets:
        return None
    return f"{tickets['done']} done, {tickets['sent_back']} sent back, {tickets['open']} open"


def _numbers(item, row):
    if row["health"] == "unknown":
        return [CANT_TELL]
    split = (
        f"{_plural(item['uses'], 'use')}: {item.get('ok', 0)} ok, {item['failed']} failed, "
        f"{item['refused']} refused"
    )
    return [line for line in (split, f"Used in {row['numbers']}", row["unseen"]) if line]


def _seen(item, field):
    if item["seen"] == "unknown":
        return CANT_TELL
    return _date(item[field]) if item.get(field) else "Not seen"


def _details(tab, item, inventory):
    details = [{"term": "Technical name", "value": item["name"]}]
    if tab == "skills":
        details.append({"term": "Versions seen", "value": str(len(item.get("versions") or []))})
    elif tab == "keys":
        details.append({"term": "Value", "value": "Never shown or recorded"})
    elif inventory:
        kind, term = TRANSPORTS[inventory["transport"]]
        place = inventory["command"] if inventory["transport"] == "stdio" else inventory["host"]
        details += [
            {"term": "Kind", "value": "MCP server"},
            {"term": "Runs as", "value": kind},
            {"term": term, "value": place or CANT_TELL},
        ]
    return details


def _panel(tab, item, inventory, row):
    return {
        "tickets": _tickets(item),
        "note": NOT_PROOF,
        "first_seen": _seen(item, "first_seen"),
        "last_seen": _seen(item, "last_seen"),
        "numbers": _numbers(item, row),
        "details": _details(tab, item, inventory),
    }


def _list_row(tab, counts, item, inventory, row):
    result = {
        **row,
        "key": item["name"],
        "last_used": last_used(item, row["health"], counts["generated_at"]),
        "state": {"text": row["label"], "tone": TONES[row["health"]]},
        "filter": row["health"] if row["health"] in ("look", "idle") else "",
    }
    if tab == "keys":
        result["state"] = key_state(item, row)
        result["type"] = KEY_TYPES.get(inventory.get("type"), CANT_TELL) if inventory else CANT_TELL
    elif tab == "connections":
        result["state"] = connection_state(inventory.get("state")) if inventory else connection_state(None)
        result["allowed"] = allowed_actions(inventory)
    else:
        result["versions"] = versions_line(item)
    if tab != "keys":
        result["also"] = also_line(counts, KINDS[tab], item["name"])
    result["panel"] = _panel(tab, item, inventory, row)
    return result


def build_list(counts, tab) -> dict | None:
    """One tab's rows, problems first; None for an unknown tab. Fails closed like the overview."""
    if tab not in KINDS:
        return None
    ready = prepare(counts)
    if "error" in ready:
        return ready
    counts, kind = ready["counts"], KINDS[tab]
    rows = [
        _list_row(tab, counts, item, ready["inventory"].get(key, {}), ready["rows"][key])
        for key, item in ready["entries"].items()
        if key[0] == kind
    ]
    rows.sort(key=order)
    filters = [
        {"id": name, "label": label, "count": sum(name in ("all", row["filter"]) for row in rows)}
        for name, label in FILTERS
    ]
    return {
        "tab": tab,
        "window": "last 30 days",
        "complete": True,
        "columns": COLUMNS[tab],
        "count": len(rows),
        "rows": rows,
        "filters": filters,
        "can_ask_admin": counts["sharing"]["counts"] != "not_connected",
    }


def build_detail(counts, tab, key) -> dict | None:
    """The panel for one row (the page builds it from the list it already has)."""
    view = build_list(counts, tab)
    if not view or "error" in view:
        return view
    return next((row["panel"] for row in view["rows"] if row["key"] == key), None)
