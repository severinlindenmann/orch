"""Usage answers the core's start question (`orch usage before-start --json`, contracts/before-start.schema.json).

1. The ticket's kind of work (first match wins):
   - the Manager or the Chat ticket, or a Factory order: Lead;
   - a Factory crew ticket by its crew role: REVIEW_ROLES -> Reviews, CODE_ROLES -> Code, BUILD_ROLES -> Builds,
     any other role -> Helpers;
   - an automation ticket that runs a script: Scripts;
   - any other ticket: Helpers.
2. The accounts that count for it: on, and `for` empty (every kind) or holding the kind, in their order, and able to
   run a helper: a subscription, or an account with a `tool` (a helper tool's registry name, data in accounts.json)
   while that tool is set up here. An API key or credit without a tool (an Anthropic API credit, the OpenAI credit
   before its helper tool ships) cannot run a helper: credit skills and scripts ask Usage for it themselves
   (asking.py), so it never holds a start back.
3. The first one with room wins. A subscription has room by the same judgement as early switching (its limits and the
   pace); when it is not the one in use, Usage switches to it first (with switching on). An API key or helper tool
   has room while its credit reader says it is under its limits and under a limit over all accounts of its provider
   (`together`: spending on any of them counts). A number Usage cannot read never blocks.
4. Nothing allowed for the kind has room: the start waits, in plain words, until the earliest reset Usage knows.
   One history line and one row for `orch usage needs` per kind, not per ticket; both go when the kind has room.
5. Whatever the kind: a start whose helper tool runs on a subscription (the request's `providers` names the tool's
   provider) waits while every subscription of that provider that is on is at its limit (same words, same warning).
6. The account's rule may narrow the model (`model`: small = the small model only; first = small first, the big one
   once orch or the helper moved the ticket up). Never wider than orch's pick; a model a person set always wins.

Only labels, numbers and times: never a key or login.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from . import left, store, switching
from .readers import cswap

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


def together_spent(accounts: list[dict], t: dict, at: datetime, root: Path | None = None) -> float | None:
    """Dollars spent over every money account of the provider in the limit's period; None when none can be read."""
    from .cli import _period_start

    lim = t["limit"]
    total = None
    for m in store.money_accounts(accounts, t["provider"]):
        c = left.credit_use(root, m, _period_start(lim["period"], lim, at))
        if c.spent is not None:
            total = round((total or 0.0) + c.spent, 4)
    return total


def _together_room(
    a: dict, at: datetime, accounts: list[dict], together: list[dict], root: Path | None = None
) -> tuple[bool, str, str | None]:
    if a["type"] not in store.MONEY_TYPES:
        return True, "", None
    for t in together:
        if t["provider"] != a.get("provider"):
            continue
        spent = together_spent(accounts, t, at, root)
        lim = t["limit"]
        if spent is not None and spent >= lim["value"]:
            word = store.PERIOD_WORDS[lim["period"]]
            return (
                False,
                f"{store.together_label(t['provider'])} reached {store.fmt_value(lim['value'], '$')} ({word})",
                _next(lim, at),
            )
    return True, "", None


def _credit_room(
    a: dict,
    at: datetime,
    accounts: list[dict] | None = None,
    together: list[dict] | None = None,
    root: Path | None = None,
) -> tuple[bool, str, str | None]:
    """(room, why when not, next start) for an API key or helper tool. Unknown spend = room."""
    from .cli import _period_start

    if together:
        room = _together_room(a, at, accounts or [a], together, root)
        if not room[0]:
            return room
    for lim in a["rule"]["limits"]:
        if lim.get("unit") != "$":
            continue
        c = left.credit_use(root, a, _period_start(lim["period"], lim, at))
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
    """When the subscription has room again: the last reset of the windows at their limit (a weekly limit reached
    waits for the weekly reset, not the next 5-hour one); none at a limit yet (only near it): the first reset."""
    limits = dict(switching._limits(c.account))

    def norm(ws):
        out = []
        for w in ws:
            try:
                out.append(datetime.fromisoformat(w.resets_at).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
            except (TypeError, ValueError):
                continue
        return out

    reached = norm(
        w
        for name, w in c.use.windows.items()
        if w.resets_at and w.pct is not None and name in limits and w.pct >= limits[name]
    )
    if reached:
        return max(reached)
    every = norm(w for w in c.use.windows.values() if w.resets_at)
    return min(every) if every else None


def _words_time(iso: str) -> str:
    return store.to_time(iso).astimezone().strftime("%a %d %b %H:%M")


class _Subs:
    """The switcher's view, read once per answer: (go, why, wake, candidate) for a subscription."""

    def __init__(self, root: Path):
        self.root = root
        self.found = None
        self.cfg = switching.config(root)
        memory = switching._read(switching.memory_path(root))
        self.pace = memory.get("pace") if isinstance(memory.get("pace"), dict) else {}

    def check(self, a: dict) -> tuple[bool, str, str | None, switching.Candidate | None]:
        if self.found is None:
            try:
                self.found = cswap.read()
            except cswap.ReaderError:
                self.found = None
            self.found = self.found if self.found is not None else []
        f = next((x for x in self.found if x.key == a.get("source", {}).get("key")), None)
        if f is None:
            return True, "", None, None  # use cannot be read: never block on it
        c = switching.judge(a, f, self.pace, float(self.cfg["ahead_minutes"]))
        if c.good or (c.under and f.active):
            return True, "", None, c
        return False, (f"{a['label']}: {c.why}" if c.why else a["label"]), _sub_resets(c), c


def _model(a: dict, req: dict) -> str | None:
    """The model this start may use by the account's rule, only ever narrower than orch's pick."""
    m = a["rule"].get("model")
    if m not in store.MODELS or (req.get("chosen") or {}).get("model"):
        return None  # no model part, or a person set the ticket's model: theirs wins
    if m == "first" and req.get("model_up") is True:
        return None  # orch or the helper moved this ticket up: the big one is allowed now
    if req.get("model") == "haiku":
        return None  # already smaller
    return "sonnet"


def _full_subscriptions(
    accounts: list[dict], req: dict, tool: str | None, subs: _Subs
) -> tuple[list[str], list[str]] | None:
    """When the start's helper tool runs on a subscription and every subscription of that provider that is on is at
    its limit: (reasons, wake times). None when the start may go (one has room, or it does not run on one)."""
    providers = req.get("providers") if isinstance(req.get("providers"), dict) else {}
    provider = providers.get(tool)
    if not isinstance(provider, str) or not provider:
        return None
    mine = [a for a in accounts if a["on"] and a["type"] == "subscription" and a.get("provider") == provider]
    if not mine:
        return None
    reasons, wakes = [], []
    for a in mine:
        ok, why, wake, _ = subs.check(a)
        if ok:
            return None
        reasons.append(why)
        if wake:
            wakes.append(wake)
    return reasons, wakes


def decide(root: Path, req: dict, at: datetime | None = None, switch=switching._switch) -> dict:
    """The answer for one start. Writes history and held.json; never raises for missing data."""
    at = at or datetime.now(UTC)
    kind = kind_of(req)
    word = store.KIND_WORDS[kind]
    agents = [x for x in req.get("agents") or [] if isinstance(x, str)]
    given = bool((req.get("chosen") or {}).get("agent"))
    with store.change(root) as (accounts, rows):
        store.expire(accounts, rows, at)
    doc = store.load(root)
    accounts = doc["accounts"]
    allowed = [
        a
        for a in accounts
        if a["on"]
        and not a.get("removed")
        and not (a.get("credit_ends") and store.to_time(a["credit_ends"]) <= at)  # the credit itself ended
        and (not a["rule"].get("for") or kind in a["rule"]["for"])
    ]
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
    subs = _Subs(root)
    reasons: list[str] = []
    wakes: list[str] = []
    for a in usable:
        if a["type"] == "subscription":
            ok, why, wake, c = subs.check(a)
            if ok:
                return _go(root, kind, a, req, at, sub=c, found=subs.found, switch=switch)
        else:
            ok, why, wake = _credit_room(a, at, accounts, doc["together"], root)
            if ok:
                return _go(root, kind, a, req, at)  # its helper tool runs on this credit, not a subscription
        reasons.append(why)
        if wake:
            wakes.append(wake)
    if not usable:
        full = _full_subscriptions(accounts, req, req.get("agent"), subs)
        if full is None:
            _room_again(root, kind, at)
            return {"go": True}  # nothing set for this kind of work and room on the subscriptions: as usual
        why, wake = _every_full(full)
        reasons.append(why)
        wakes += [wake] if wake else []
    until = min(wakes) if wakes else None
    why = f"No room for {word}: {reasons[0]}." if reasons else f"No room for {word}."
    if until:
        why += f" Waits until {_words_time(until)}."
    _hold(root, kind, req, why, until, at)
    return {"go": False, "why": why[:200], **({"until": until} if until else {})}


def _every_full(full: tuple[list[str], list[str]]) -> tuple[str, str | None]:
    reasons, wakes = full
    why = "every subscription is at its limit" + (f" ({reasons[0]})" if reasons else "")
    return why, (min(wakes) if wakes else None)


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
    model = _model(a, req)
    if model:
        out["model"] = model
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
