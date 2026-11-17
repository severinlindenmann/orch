"""Usage answers the core's start question (`orch usage before-start --json`, contracts/before-start.schema.json).

1. The ticket's kind of work (first match wins):
   - the Manager or the Chat ticket, or a Factory order: Lead;
   - a Factory crew ticket by its crew role: REVIEW_ROLES -> Reviews, CODE_ROLES -> Code, BUILD_ROLES -> Builds,
     any other role -> Helpers;
   - an automation ticket that runs a script: Scripts;
   - any other ticket: Helpers.
2. The accounts that count for it: on, and `for` empty (every kind) or holding the kind, in their order, and able to
   run a helper: a subscription, or an account with a `tool` (a helper tool's registry name, data in accounts.json)
   while that tool is set up here. An API key or credit without a tool (the Claude API credit, the OpenAI credit
   before Codex helpers ship) cannot run a helper: credit skills and scripts ask Usage for it themselves (next step),
   so it never holds a start back.
3. The first one with room wins. A subscription has room by the same judgement as early switching (its limits and the
   pace); when it is not the one in use, Usage switches to it first (with switching on). An API key or helper tool
   has room while its credit reader says it is under its limits. A number Usage cannot read never blocks.
4. Nothing allowed for the kind has room: the start waits, in plain words, until the earliest reset Usage knows.
   One history line and one row for `orch usage needs` per kind, not per ticket; both go when the kind has room.

Only labels, numbers and times: never a key or login.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from . import store, switching
from .readers import credit_reader, cswap

REVIEW_ROLES = ("reviewer", "checker", "challenger", "critic", "review", "challenge")
CODE_ROLES = ("builder", "coder", "developer", "implementer", "fixer", "code")
BUILD_ROLES = ("build", "release", "packager", "ci")
_TOOL = re.compile(r"[a-z][a-z0-9_-]{0,31}")
HELD = "held.json"


def kind_of(req: dict) -> str:
    ext = req.get("ext") if isinstance(req.get("ext"), dict) else {}
    fac = ext.get("factory") if isinstance(ext.get("factory"), dict) else {}
    auto = ext.get("automation") if isinstance(ext.get("automation"), dict) else {}
    if req.get("manager") is True or req.get("chat") is True or fac.get("role") == "order":
        return "lead"
    if fac.get("role") == "crew":
        role = str(fac.get("crew_role") or "").lower()
        if role in REVIEW_ROLES:
            return "reviews"
        if role in CODE_ROLES:
            return "code"
        if role in BUILD_ROLES:
            return "builds"
        return "helpers"
    if auto.get("script"):
        return "scripts"
    return "helpers"


def _held_path(root: Path) -> Path:
    return store.usage_dir(root) / HELD


def held(root: Path) -> dict:
    data = switching._read(_held_path(root))
    return {k: v for k, v in data.items() if k in store.KINDS and isinstance(v, dict)}


def _credit_room(a: dict, at: datetime) -> tuple[bool, str, str | None]:
    """(room, why when not, next start) for an API key or helper tool. Unknown spend = room."""
    from .cli import _period_start

    src = a.get("source", {})
    reader = credit_reader(src.get("reader", "none")) or credit_reader("none")
    for lim in a["rule"]["limits"]:
        if lim.get("unit") != "$":
            continue
        c = reader(src, _period_start(lim["period"], lim, at))
        if c.spent is not None and c.spent >= lim["value"]:
            word = store.PERIOD_WORDS[lim["period"]]
            return (
                False,
                f"{a['label']} reached {store.fmt_value(lim['value'], '$')} ({word})",
                _next(lim, at),
            )
    return True, "", None


def _next(lim: dict, at: datetime) -> str | None:
    if lim["period"] == "month":
        return store.utc_text(store.month_window(lim, at)[1])
    if lim["period"] == "until":
        return None  # the limit holds until its date passes; no wake time to give
    return None


def _sub_resets(c: switching.Candidate) -> str | None:
    times = [w.resets_at for w in c.use.windows.values() if w.resets_at]
    norm = []
    for t in times:
        try:
            norm.append(datetime.fromisoformat(t).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        except ValueError:
            continue
    return min(norm) if norm else None


def _words_time(iso: str) -> str:
    return store.to_time(iso).astimezone().strftime("%a %d %b %H:%M")


def decide(root: Path, req: dict, at: datetime | None = None, switch=switching._switch) -> dict:
    """The answer for one start. Writes history and held.json; never raises for missing data."""
    at = at or datetime.now(UTC)
    kind = kind_of(req)
    word = store.KIND_WORDS[kind]
    agents = [x for x in req.get("agents") or [] if isinstance(x, str)]
    given = bool((req.get("chosen") or {}).get("agent"))
    with store.change(root) as (accounts, rows):
        store.expire(accounts, rows, at)
    accounts = store.load(root)["accounts"]
    allowed = [a for a in accounts if a["on"] and (not a["rule"].get("for") or kind in a["rule"]["for"])]
    usable = []
    for a in allowed:
        tool = a.get("tool")
        if a["type"] != "subscription" and tool is None:
            continue  # a credit without a helper tool: used by skills and scripts, not by a helper start
        if tool is not None and (
            not isinstance(tool, str) or not _TOOL.fullmatch(tool) or tool not in agents
        ):
            continue  # its helper tool is not set up here
        if given and tool and tool != req.get("agent"):
            continue  # the tool for this start was chosen: an account of another tool cannot serve it
        usable.append(a)
    if not usable:
        _room_again(root, kind, at)
        return {"go": True}  # nothing set for this kind of work: start as usual

    found = None
    reasons: list[str] = []
    wakes: list[str] = []
    cfg = switching.config(root)
    memory = switching._read(switching.memory_path(root))
    for a in usable:
        if a["type"] == "subscription":
            if found is None:
                try:
                    found = cswap.read()
                except cswap.ReaderError:
                    found = None
                found = found if found is not None else []
            f = next((x for x in found if x.key == a.get("source", {}).get("key")), None)
            if f is None:
                return _go(root, kind, a, req, at)  # use cannot be read: never block on it
            pace = memory.get("pace") if isinstance(memory.get("pace"), dict) else {}
            c = switching.judge(a, f, pace, float(cfg["ahead_minutes"]))
            if c.good or (c.under and f.active):
                return _go(root, kind, a, req, at, sub=c, found=found, switch=switch)
            reasons.append(f"{a['label']}: {c.why}" if c.why else a["label"])
            r = _sub_resets(c)
            if r:
                wakes.append(r)
        else:
            room, why, nxt = _credit_room(a, at)
            if room:
                return _go(root, kind, a, req, at)
            reasons.append(why)
            if nxt:
                wakes.append(nxt)
    until = min(wakes) if wakes else None
    why = f"No room for {word}: {reasons[0]}." if reasons else f"No room for {word}."
    if until:
        why += f" Waits until {_words_time(until)}."
    _hold(root, kind, req, why, until, at)
    return {"go": False, "why": why[:200], **({"until": until} if until else {})}


def _go(
    root: Path,
    kind: str,
    a: dict,
    req: dict,
    at: datetime,
    sub: switching.Candidate | None = None,
    found=None,
    switch=switching._switch,
) -> dict:
    _room_again(root, kind, at)
    out: dict = {"go": True, "account": a["label"][:64]}
    tool = a.get("tool")
    if tool and tool != req.get("agent") and not (req.get("chosen") or {}).get("agent"):
        out["agent"] = tool
    if sub is not None and not sub.use.active:
        word = store.KIND_WORDS[kind]
        before = next((x.label for x in found or [] if x.active), None)
        if not switching.switching_on(root):
            out["say"] = f"{a['label']} has room for {word}; switching is off, so the account in use stays."
        elif switch(sub.use.slot):
            out["say"] = f"Switched to {a['label']} for {word}."
            row = switching._row(f"switched to {a['label']}", a, before, a["label"], f"for {word}", at)
            with store._lock(root):
                store._append_history(root, [row])
        else:
            out["say"] = f"Could not switch to {a['label']}; the account in use stays."
    return out


def _hold(root: Path, kind: str, req: dict, why: str, until: str | None, at: datetime) -> None:
    with store._lock(root):
        data = held(root)
        cur = data.get(kind)
        first = cur is None
        tickets = list(cur.get("tickets", [])) if cur else []
        tid = req.get("ticket")
        if isinstance(tid, str) and tid not in tickets:
            tickets.append(tid)
        data[kind] = {
            "since": cur.get("since") if cur else switching._iso(at),
            "why": why[:200],
            "until": until,
            "tickets": tickets[-50:],
        }
        switching._write(_held_path(root), data)
        if first:  # one warning per kind of work, not one per ticket or per try
            row = {
                "at": switching._iso(at),
                "who": store.USAGE,
                "what": f"warning: work for {store.KIND_WORDS[kind]} waits",
                "account": None,
                "label": "Usage",
                "before": None,
                "after": None,
                "why": why[:200],
            }
            store._append_history(root, [row])


def _room_again(root: Path, kind: str, at: datetime) -> None:
    if kind not in held(root):
        return
    with store._lock(root):
        data = held(root)
        if data.pop(kind, None) is None:
            return
        switching._write(_held_path(root), data)
        row = {
            "at": switching._iso(at),
            "who": store.USAGE,
            "what": f"room again for {store.KIND_WORDS[kind]}",
            "account": None,
            "label": "Usage",
            "before": None,
            "after": None,
        }
        store._append_history(root, [row])


def needs_rows(root: Path) -> list[dict]:
    """One row per kind of work that waits (contracts/needs.schema.json), for Home and the phone."""
    out = []
    for kind, h in sorted(held(root).items(), key=lambda kv: store.KINDS.index(kv[0])):
        n = len(h.get("tickets") or [])
        text = str(h.get("why") or "")
        text += f" {n} ticket{'s' if n != 1 else ''} wait{'s' if n == 1 else ''}." if n else ""
        text += " Raise the limit or allow another account for it on the Usage page."
        out.append(
            {
                "id": f"usage:no-room-{kind}",
                "source": "usage",
                "kind": "usage:no-room",
                "ticket": None,
                "title": f"No room for {store.KIND_WORDS[kind]}",
                "text": text.strip()[:500],
                "tone": "warn",
                "since": h.get("since") or store.now(),
            }
        )
    return out
