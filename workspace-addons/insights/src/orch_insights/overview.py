"""Turn validated counts into plain, local overview rows without record identifiers."""

import json
import re
from datetime import datetime, timedelta
from importlib import resources

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA = json.loads(resources.files("orch_insights").joinpath("answer.schema.json").read_text())
FORMATS = FormatChecker()


@FORMATS.checks("date-time", raises=(ValueError, TypeError))
def _timestamp(value):
    """Validate timestamps without optional format-checker dependencies."""
    if not isinstance(value, str):
        return True
    return "T" in value and value.endswith("Z") and datetime.fromisoformat(value).tzinfo is not None


VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FORMATS)
TABS = {"skill": "skills", "mcp": "connections", "key": "keys"}
SOURCES = {
    "workspace": "This workspace",
    "admin": "Shared by your admin",
    "builtin": "Built in",
    "marketplace": "From the marketplace",
    "harness": "From your agent tool's settings",
}
LABELS = {
    "working": "Working well",
    "look": "Needs a look",
    "idle": "Not used",
    "new": "New",
    "unknown": "Can't tell yet",
}
ERROR = "Insights could not read the workspace record."
PARTIAL = "Some runs could not be read, numbers may be low."


def _keep(entries, allowed):
    """Copy whitelisted fields of dict entries; anything else (a key value, say) is never read."""
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        return entries
    return [{k: v for k, v in entry.items() if k in allowed} for entry in entries]


def _base_name(command):
    """Program base name only: never arguments or folders."""
    if not isinstance(command, str):
        return command
    first = (command.split() or [""])[0]
    return first.replace("\\", "/").rsplit("/", 1)[-1]


def _host(address):
    """Host only: never scheme, credentials, path or query."""
    if not isinstance(address, str):
        return address
    return re.split(r"[/?#]", address.split("://")[-1])[0].rsplit("@", 1)[-1].lower()


def _clean_inventory(inventory):
    if not isinstance(inventory, dict):
        return inventory
    shapes = SCHEMA["properties"]["inventory"]["properties"]
    clean = {**inventory}
    for tab in ("skills", "connections", "keys"):
        if tab in clean:
            clean[tab] = _keep(clean[tab], shapes[tab]["items"]["properties"])
    if isinstance(clean.get("connections"), list):
        clean["connections"] = [_clean_connection(entry) for entry in clean["connections"]]
    return clean


def _clean_connection(entry):
    if not isinstance(entry, dict):
        return entry
    entry = {**entry}
    if "command" in entry:
        entry["command"] = _base_name(entry["command"])
    if "host" in entry:
        entry["host"] = _host(entry["host"])
    return entry


def validated(counts):
    """Validate the complete answer; discard unexpected item and inventory fields, including key values."""
    if not isinstance(counts, dict) or not isinstance(counts.get("items"), list):
        return None
    allowed = SCHEMA["properties"]["items"]["items"]["properties"]
    if not all(isinstance(item, dict) for item in counts["items"]):
        return None
    clean = {**counts, "items": _keep(counts["items"], allowed)}
    if "inventory" in counts:
        clean["inventory"] = _clean_inventory(counts["inventory"])
    if not VALIDATOR.is_valid(clean):
        return None
    for item in clean["items"]:
        if item["runs"]["used"] > item["runs"]["of"]:
            return None
        if sum(item[k] for k in ("ok", "failed", "refused", "unknown")) != item["uses"]:
            return None
    return clean


def _health(item, generated):
    if item["seen"] == "unknown":
        return "unknown"
    if item["seen"] == "not_seen":
        return "idle"
    bad = item["failed"] + item["refused"]
    if (item["uses"] >= 3 and bad >= 1 and bad / item["uses"] >= 0.2) or (
        item["kind"] in ("key", "mcp") and item["refused"] > 0
    ):
        return "look"
    if item["first_seen"]:
        age = datetime.fromisoformat(generated) - datetime.fromisoformat(item["first_seen"])
        if timedelta(0) <= age <= timedelta(days=7):
            return "new"
    return "working"


def _name(item, inventory):
    if item["kind"] == "key":
        return item["name"]
    if item["kind"] == "mcp" and inventory.get("label"):
        return inventory["label"]
    name = item["name"].replace("-", " ").replace("_", " ")
    return name[:1].upper() + name[1:]


def _row(item, inventory, generated):
    health = _health(item, generated)
    runs = item["runs"]
    unseen = runs["unseen"]
    return {
        "name": _name(item, inventory),
        "source": SOURCES.get(item["source"], "Other"),
        "health": health,
        "label": LABELS[health],
        "uses": None if health == "unknown" else item["uses"],
        "numbers": "Can't tell yet" if health == "unknown" else f"{runs['used']} of {runs['of']} runs",
        "unseen": f"{unseen} {'run' if unseen == 1 else 'runs'} can't tell" if unseen else None,
        "detail": "Not used in 30 days" if health == "idle" else "",
    }


def _inventory(counts):
    """One entry per name: the one in use wins over a shadowed one of another source."""
    found = {}
    for kind, tab in TABS.items():
        for item in counts["inventory"][tab]:
            if (kind, item["name"]) not in found or not item.get("shadowed"):
                found[(kind, item["name"])] = item
    return found


def _entries(counts, inventory):
    entries = {}
    for item in counts["items"]:
        if item["kind"] in TABS:
            # Different actions can share a name. Keep one row without inventing run unions.
            entries.setdefault((item["kind"], item["name"]), item)
    for key, item in inventory.items():
        entries.setdefault(
            key,
            {
                "kind": key[0],
                "name": key[1],
                "source": item["source"],
                "seen": "unknown",
                "uses": 0,
                "failed": 0,
                "refused": 0,
                "first_seen": None,
                "runs": {"used": 0, "of": 0, "unseen": counts["runs"]},
            },
        )
    return entries


def _cards(entries, rows):
    skills, refusals, idle = [], [], []
    for key, item in entries.items():
        row = rows[key]
        kind = "connection" if key[0] == "mcp" else key[0]
        card = {"kind": kind, "button": "Look", "tone": "warn", "target": row["name"]}
        if kind == "skill" and row["health"] == "look":
            skills.append(
                {
                    **card,
                    "title": f"{row['name']} needs a look",
                    "text": f"{item['failed']} of {item['uses']} uses failed; {item['refused']} refused.",
                }
            )
        elif kind in ("connection", "key") and item["refused"] and row["health"] == "look":
            n = item["refused"]
            times = "time" if n == 1 else "times"
            refusals.append(
                {
                    **card,
                    "title": f'{row["name"]} said "not allowed" {n} {times}',
                    "text": "Check the access this item needs.",
                }
            )
        if kind == "key" and row["health"] == "idle":
            idle.append(row["name"])
    cards = skills + refusals
    if idle:
        cards.append(
            {
                "kind": "key",
                "title": f"{len(idle)} {'key' if len(idle) == 1 else 'keys'} not used in 30 days",
                "text": "Review whether these keys are still needed.",
                "button": "Look",
                "tone": "info",
                "target": idle[0],
            }
        )
    return cards[:3]


def order(row):
    """Problems first, then the most used, then by name."""
    return (row["health"] != "look", -(row["uses"] or 0), row["name"])


def prepare(counts):
    """Validated counts with one entry and row per visible item, or the fail-closed error answer."""
    counts = validated(counts)
    if counts is None:
        return {"error": ERROR, "complete": False}
    if not counts["complete"] or counts["unavailable"]:
        return {"error": PARTIAL, "complete": False}
    inventory = _inventory(counts)
    entries = _entries(counts, inventory)
    rows = {key: _row(item, inventory.get(key, {}), counts["generated_at"]) for key, item in entries.items()}
    return {"counts": counts, "inventory": inventory, "entries": entries, "rows": rows}


def build_overview(counts) -> dict:
    """Fail closed: unavailable and partial answers contain no apparent zero totals or rows."""
    ready = prepare(counts)
    if "error" in ready:
        return ready
    counts, entries, rows = ready["counts"], ready["entries"], ready["rows"]
    # Rows live in the lists (/api/list/<tab>); the overview keeps the tab counts and the cards.
    tabs = {tab: {"count": sum(key[0] == kind for key in rows)} for kind, tab in TABS.items()}
    cards = _cards(entries, rows)
    sharing = counts["sharing"]["counts"] == "on"
    return {
        "window": "last 30 days",
        "runs": counts["runs"],
        "tickets": counts["tickets"],
        "complete": True,
        "since": counts["since"],
        "sharing": {"on": sharing, "chip": "Sharing counts with your admin" if sharing else None},
        "needs": cards,
        "empty_needs": "All good this month." if not cards else None,
        "tabs": tabs,
        "first_day": counts["runs"] == 0 and not any(item["uses"] for item in counts["items"]),
    }
