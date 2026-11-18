"""`orch usage act <verb> --by <actor> --json -- <target>`: the page's clicks (sent by the dashboard as the person).

Each verb's target is one plain line the add-on checks itself; it becomes the same command a person would type, so
the rules, refusals and history lines are the CLI's own:

    limit      <account>:<period>:<value>[:<YYYY-MM-DD>]   value: 90, 90%, $100 or none (remove that limit)
    period     <account>:<old period>:<new period>[:<YYYY-MM-DD>]
    order      <account>:up | <account>:down | <account>:<place>   (place: 1 is used first)
    on, off    <account>
    end        <account>:<YYYY-MM-DD> | <account>:none
    for        <account>:<kind>[,<kind>...] | <account>:any      kinds: lead code reviews builds scripts helpers
    model      <account>:small | <account>:first | <account>:any
    together   <provider>:<value>                                   value: $100 or none (all its accounts together)
    add        <provider>:<api-key|helper-tool>:<name>:<kinds|any>:<value|none>:<YYYY-MM-DD|->:<label>
               name: what the credit skill calls it (never the key); the day: when its month starts again
    remove     <account>
    restore    <account>                                            a removed API credit or helper tool comes back
    left       <account>:<value>                                   value: $74, 0 or none (what is left now)
    switching  on | off
"""

from __future__ import annotations

import re
from pathlib import Path

from . import store
from .store import Refused

VERBS = (
    "limit",
    "period",
    "order",
    "on",
    "off",
    "end",
    "switching",
    "for",
    "model",
    "together",
    "add",
    "remove",
    "left",
    "restore",
)
_ACC = r"a_[a-z0-9]{6}"
_PERIOD = r"5h|week|month|until"
_DAY = r"\d{4}-\d\d-\d\d"
_KIND = r"(?:lead|code|reviews|builds|scripts|helpers)"
_VALUE = r"none|\$?\d{1,7}(?:\.\d{1,4})?[%$]?"
_MONEY = r"none|\$?\d{1,7}(?:\.\d{1,4})?\$?"
_PROVIDER = r"[a-z][a-z0-9-]{0,31}"
_NAME = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}"
_LABEL = r"[A-Za-z0-9][A-Za-z0-9 /._()&+-]{0,63}"
_KINDS = rf"any|{_KIND}(?:,{_KIND}){{0,5}}"
PATTERNS = {
    "limit": re.compile(rf"({_ACC}):({_PERIOD}):({_VALUE})(?::({_DAY}))?"),
    "period": re.compile(rf"({_ACC}):({_PERIOD}):({_PERIOD})(?::({_DAY}))?"),
    "order": re.compile(rf"({_ACC}):(up|down|[1-9]\d{{0,2}})"),
    "on": re.compile(rf"({_ACC})"),
    "off": re.compile(rf"({_ACC})"),
    "end": re.compile(rf"({_ACC}):({_DAY}|none)"),
    "switching": re.compile(r"(on|off)"),
    "for": re.compile(rf"({_ACC}):({_KINDS})"),
    "model": re.compile(rf"({_ACC}):(small|first|any)"),
    "together": re.compile(rf"({_PROVIDER}):({_MONEY})"),
    "add": re.compile(
        rf"({_PROVIDER}):(api-key|helper-tool):({_NAME}):({_KINDS}):({_MONEY}):({_DAY}|-):({_LABEL})"
    ),
    "remove": re.compile(rf"({_ACC})"),
    "left": re.compile(rf"({_ACC}):({_MONEY})"),
    "restore": re.compile(rf"({_ACC})"),
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
    if verb == "for":
        return ["for", g[0], *g[1].split(","), *who]
    if verb == "model":
        return ["model", g[0], g[1], *who]
    if verb == "together":
        return ["together", g[0], g[1], *who]
    if verb == "add":
        provider, type_, name, kinds, value, resets, label = g
        out = ["add", label.strip(), "--provider", provider, "--type", type_, "--name", name]
        out += ["--for", *kinds.split(",")] if kinds != "any" else []
        out += ["--limit", value] if value != "none" else []
        out += ["--resets", resets] if resets != "-" else []
        return [*out, *who]
    if verb in ("remove", "restore"):
        return [verb, g[0], *who]
    if verb == "left":
        return ["left", g[0], g[1], *who]
    return ["switching", g[0], *who]
