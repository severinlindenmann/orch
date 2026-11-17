"""`orch usage act <verb> --by <actor> --json -- <target>`: the page's clicks (sent by the dashboard as the person).

Each verb's target is one plain line the add-on checks itself; it becomes the same command a person would type, so
the rules, refusals and history lines are the CLI's own:

    limit      <account>:<period>:<value>[:<YYYY-MM-DD>]   value: 90, 90%, $100 or none (remove that limit)
    period     <account>:<old period>:<new period>[:<YYYY-MM-DD>]
    order      <account>:up | <account>:down | <account>:<place>   (place: 1 is used first)
    on, off    <account>
    end        <account>:<YYYY-MM-DD> | <account>:none
    switching  on | off
"""

from __future__ import annotations

import re
from pathlib import Path

from . import store
from .store import Refused

VERBS = ("limit", "period", "order", "on", "off", "end", "switching")
_ACC = r"a_[a-z0-9]{6}"
_PERIOD = r"5h|week|month|until"
_DAY = r"\d{4}-\d\d-\d\d"
_VALUE = r"none|\$?\d{1,7}(?:\.\d{1,4})?[%$]?"
PATTERNS = {
    "limit": re.compile(rf"({_ACC}):({_PERIOD}):({_VALUE})(?::({_DAY}))?"),
    "period": re.compile(rf"({_ACC}):({_PERIOD}):({_PERIOD})(?::({_DAY}))?"),
    "order": re.compile(rf"({_ACC}):(up|down|[1-9]\d{{0,2}})"),
    "on": re.compile(rf"({_ACC})"),
    "off": re.compile(rf"({_ACC})"),
    "end": re.compile(rf"({_ACC}):({_DAY}|none)"),
    "switching": re.compile(r"(on|off)"),
}
NOT_THIS = "That is not something Usage can change. Reload the page and try again."


def argv_for(root: Path, verb: str, target: str, by: str | None) -> list[str]:
    """The CLI words for one click (no `--dir`, no `--json`). Refused when the verb or target is not one of the
    fixed shapes above: nothing of the target reaches the command line unchecked."""
    if verb not in VERBS:
        raise Refused(f"Usage has no '{verb}' action.")
    m = PATTERNS[verb].fullmatch(target or "")
    if not m:
        raise Refused(NOT_THIS)
    g = m.groups()
    # the dashboard names the person as human:<name>; a name with spaces becomes one word for the history
    who = ["--by", re.sub(r"\s+", "_", by.strip())[:70]] if by and by.strip() else []
    if verb == "limit":
        acc, period, value, until = g
        return ["limit", acc, value, "--period", period, *(["--until", until] if until else []), *who]
    if verb == "period":
        acc, old, new, until = g
        return ["period", acc, new, "--of", old, *(["--until", until] if until else []), *who]
    if verb == "order":
        acc, way = g
        accounts = store.load(root)["accounts"]
        a = store.find(accounts, acc)
        place = a["order"] - 1 if way == "up" else a["order"] + 1 if way == "down" else int(way)
        return ["order", acc, str(max(1, min(place, len(accounts)))), *who]
    if verb in ("on", "off"):
        return [verb, g[0], *who]
    if verb == "end":
        return ["end", g[0], g[1], *who]
    return ["switching", g[0], *who]
