"""`orch usage ask <kind>`: a credit skill or a helper's own subagent asks before it spends.

1. The accounts that count: on, and `for` empty (every kind) or holding the kind, in their order. With `--provider`
   (a credit skill: anthropic = Anthropic API, openai = OpenAI) only that provider's API credits; with `--name`
   only the one credit the caller was told to use (a person's own choice wins, it is only checked for room).
2. A credit skill may tell Usage the credits it knows (`--known -`, JSON on stdin); one Usage does not list yet is added
   with the skill's starting rule (a monthly $ limit from its reset day, its kinds of work) and one history line. A
   credit already listed keeps the rule the person set.
3. The first account with room wins: an API credit while its spend log says it is under its $ limits (the same reader
   and periods as the helper starts), a subscription by the same judgement as early switching. A number Usage cannot
   read never blocks. Asking never switches an account.
4. The answer, one JSON object: `{"go": true, "account": <label>, "provider", "name": <the name the skill already uses
   for it>, "left": <$ left, when known>}`; `{"go": true}` alone when nothing is set for this kind (do as today); or
   `{"go": false, "why": <plain words>, "until": <UTC time, when known>}`. A refusal for the whole kind of work (no
   `--provider` and no `--name`) shows on the Usage page and Home like a held helper start, and goes when the kind has room again.
5. An API credit is refused before the call (ORCH-627) when it was removed, is switched off, is past its end
   (`credit_ends`, a UTC time) or has nothing left (the amount the person set, `left`, minus what its spend reader
   counted since then). Off or removed only refuses a caller that spends on credits (`--provider` or `--name`): a
   subagent asking for a kind of work just skips that credit, as before. The next credit with room still wins.

Only labels, names, numbers and times: never a key or login.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from . import left, routing, store, switching
from .left import credit_use
from .readers import cswap


def _left(a: dict, at: datetime, root: Path | None = None) -> float | None:
    """Dollars left under the tightest $ limit, when the spend can be read."""
    from .cli import _period_start

    left = None
    for lim in a["rule"]["limits"]:
        if lim.get("unit") != "$":
            continue
        c = credit_use(root, a, _period_start(lim["period"], lim, at))
        if c.spent is None:
            continue
        x = round(max(0.0, lim["value"] - c.spent), 4)
        left = x if left is None else min(left, x)
    return left


def left_now(root: Path | None, a: dict, at: datetime) -> float | None:
    """Dollars left on a credit: what the person set (`left`: {value, at}) minus what was spent since, from its spend
    log and from `orch usage spent` reports (left.view). None when not set yet (calls go ahead and are counted)."""
    if not isinstance(a.get("left"), dict):
        return None
    return left.view(root, a, at)["left"]


def stopped(root: Path | None, a: dict, at: datetime) -> str | None:
    """Why an API credit may not be spent now, in one plain sentence; None when it may."""
    shut = store.closed(a, at)  # removed, off or past its end: the same check as helper starts
    if shut:
        return shut
    rest = left_now(root, a, at)
    if rest is not None and rest <= 0:
        return f"{a['label']} has nothing left. Set what is left on the Usage page."
    return None


def ask(
    root: Path,
    kind: str,
    provider: str | None = None,
    name: str | None = None,
    known: list[dict] | None = None,
    at: datetime | None = None,
) -> dict:
    at = at or datetime.now(UTC)
    if kind not in store.KINDS:
        raise store.Refused(
            f"'{kind}' is not a kind of work. Pick from: " + ", ".join(store.KIND_WORDS.values()) + "."
        )
    if provider is not None and provider not in store.PROVIDERS:
        raise store.Refused("Usage counts API credits of Anthropic (anthropic) and OpenAI (openai) only.")
    word = store.KIND_WORDS[kind]
    with store.change(root) as (accounts, rows):
        store.expire(accounts, rows, at)
        if known and provider:
            store.sync_known(accounts, rows, provider, known)
        if provider is not None or name is not None:  # a credit skill: its declared credit is listed first
            from .cli import declared

            store.sync_declared(accounts, rows, declared(root))
    doc = store.load(root)
    accounts = doc["accounts"]
    spends = (
        provider is not None or name is not None
    )  # the caller spends on a credit: an off one is a refusal
    allowed = [
        a
        for a in accounts
        if (a["on"] or (spends and a["type"] == "api-key"))
        and (not a["rule"].get("for") or kind in a["rule"]["for"])
    ]
    if provider is not None:
        allowed = [a for a in allowed if a["type"] == "api-key" and a.get("provider") == provider]
    if name is not None:
        allowed = [a for a in allowed if a.get("source", {}).get("name") == name]
    if not allowed:
        if not spends:
            routing._room_again(root, kind, at)
        return {"go": True}  # nothing set for this kind of work: do as today

    reasons: list[str] = []
    wakes: list[str] = []
    stop_first = False  # the first reason is a whole sentence about a stopped credit
    found = None
    for a in allowed:
        if a["type"] == "subscription":
            if found is None:
                try:
                    found = cswap.read()
                except cswap.ReaderError:
                    found = None
                found = found if found is not None else []
            f = next((x for x in found if x.key == a.get("source", {}).get("key")), None)
            if f is None:
                return _go(
                    root, kind, a, provider, at, accounts, doc["together"], spends
                )  # unread: never block
            memory = switching._read(switching.memory_path(root))
            pace = memory.get("pace") if isinstance(memory.get("pace"), dict) else {}
            c = switching.judge(a, f, pace, float(switching.config(root)["ahead_minutes"]))
            if c.good or (c.under and f.active):
                return _go(root, kind, a, provider, at, accounts, doc["together"], spends)
            reasons.append(f"{a['label']}: {c.why}" if c.why else a["label"])
            r = routing._sub_resets(c)
            if r:
                wakes.append(r)
        elif a["type"] == "api-key":
            stop = stopped(root, a, at)
            if stop:
                stop_first = stop_first or not reasons
                reasons.append(stop)
                continue
            room, why, nxt = routing._credit_room(a, at, accounts, doc["together"], root)
            if room:
                return _go(root, kind, a, provider, at, accounts, doc["together"], spends)
            reasons.append(why)
            if nxt:
                wakes.append(nxt)
        # a helper tool runs helpers, not skills or subagents: it is not an answer here
    if not reasons:
        if not spends:
            routing._room_again(root, kind, at)
        return {"go": True}
    until = min(wakes) if wakes else None
    why = reasons[0] if stop_first else f"No room for {word}: {reasons[0]}."
    if until:
        why += f" Waits until {routing._words_time(until)}."
    if not spends:  # the whole kind of work has no room: show it like a held helper start
        ticket = os.environ.get("ORCH_TICKET") or ""
        routing._hold(root, kind, {"ticket": ticket if ticket.startswith("t_") else None}, why, until, at)
    return {"go": False, "why": why[:200], **({"until": until} if until else {})}


def _go(
    root: Path,
    kind: str,
    a: dict,
    provider: str | None,
    at: datetime,
    accounts: list[dict] | None = None,
    together: list[dict] | None = None,
    spends: bool = False,
) -> dict:
    if provider is None and not spends:
        routing._room_again(root, kind, at)
    out: dict = {"go": True, "account": a["label"][:64]}
    if a["type"] == "api-key":
        out["provider"] = a.get("provider") or ""
        nm = a.get("source", {}).get("name")
        if isinstance(nm, str):
            out["name"] = nm
        left = _left(a, at, root)
        own = left_now(root, a, at)  # what the person set, counted down
        if own is not None:
            left = own if left is None else min(left, own)
        for t in together or []:  # a limit over every account of the provider leaves less
            if t["provider"] == a.get("provider"):
                spent = routing.together_spent(accounts or [a], t, at, root)
                if spent is not None:
                    x = round(max(0.0, t["limit"]["value"] - spent), 4)
                    left = x if left is None else min(left, x)
        if left is not None:
            out["left"] = left
    return out
