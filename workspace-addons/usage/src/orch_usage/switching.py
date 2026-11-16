"""Early switching: every 30 seconds read the subscriptions' use and keep the first account in order that is under
its limits and would not reach one within 10 minutes at the current pace. Switches through the account switcher.

Without the switcher, or with switching turned off (`orch usage switching off`), Usage only shows and warns: it
works out the same choice and writes "would switch" in the history, but never switches.

Pace: how fast the work uses a subscription (percent per minute per window), measured on the active account over
the last minutes and applied to every candidate (the same work moves with the switch). It is remembered across a
switch, so an account left early is not taken back until its use drops (a reset) or the work slows down.

Files in .orch/addons/usage/: `settings.json` {"switching": bool} (written by the command; off until the person turns
it on) and `switching.json` (the loop's own memory: samples, pace, the last choice). Only labels, numbers and times.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import store
from .readers import SubscriptionUse, cswap

EVERY_SECONDS = 30
AHEAD_MINUTES = 10
PACE_MINUTES = 10  # samples older than this do not count for the pace
MIN_SPAN_SECONDS = 60  # the pace needs samples at least this far apart
TRUST_SPAN_SECONDS = 300  # a lower pace replaces a higher remembered one only when measured over this long
PACE_FORGET_MINUTES = 30  # a remembered pace older than this is dropped
RETRY_MINUTES = 10  # a failed switch to the same account is tried again (and written down) after this
WINDOW_OF = {"5h": "5h", "week": "week"}  # rule period -> switcher window
SWITCH_TIMEOUT = 30


# ---------------------------------------------------------------- files


def _read(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _write(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def settings_path(root: Path) -> Path:
    return store.usage_dir(root) / "settings.json"


def memory_path(root: Path) -> Path:
    return store.usage_dir(root) / "switching.json"


def switching_on(root: Path) -> bool:
    return _read(settings_path(root)).get("switching") is True


def set_switching(root: Path, who: str, on: bool) -> bool:
    """Turn switching on or off; True when it changed. Written in the history."""
    with store._lock(root):
        cur = switching_on(root)
        if cur == on:
            return False
        s = _read(settings_path(root))
        s["switching"] = on
        _write(settings_path(root), s)
        store._append_history(
            root,
            [
                {
                    "at": store.now(),
                    "who": who,
                    "what": "switching turned on" if on else "switching turned off",
                    "account": None,
                    "label": "Usage",
                    "before": cur,
                    "after": on,
                }
            ],
        )
    return True


def config(root: Path) -> dict:
    """[usage] in .orch/config.toml: every_seconds, ahead_minutes (defaults 30 and 10)."""
    out = {"every_seconds": EVERY_SECONDS, "ahead_minutes": AHEAD_MINUTES}
    p = root / ".orch" / "config.toml"
    try:
        import tomllib

        t = tomllib.loads(p.read_text(encoding="utf-8")).get("usage", {})
    except (OSError, ValueError, ImportError):
        return out
    if not isinstance(t, dict):
        return out
    for k, lo, hi in (("every_seconds", 10, 3600), ("ahead_minutes", 1, 600)):
        v = t.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi:
            out[k] = v
    return out


# ---------------------------------------------------------------- pace


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def update_pace(memory: dict, active: SubscriptionUse | None, at: datetime) -> dict[str, float]:
    """Add the active account's use to the samples and return the pace per window (percent per minute).

    Samples belong to one account and one window period (its reset time): a switch or a reset starts them anew,
    but the last measured pace stays remembered for a while."""
    samples = memory.setdefault("samples", {})
    paces = memory.setdefault("pace", {})
    if active is not None:
        for name, w in active.windows.items():
            if w.pct is None:
                continue
            cur = samples.get(name)
            if (
                not isinstance(cur, dict)
                or cur.get("key") != active.key
                or cur.get("resets_at") != w.resets_at
            ):
                cur = {"key": active.key, "resets_at": w.resets_at, "points": []}
            pts = [p for p in cur.get("points", []) if isinstance(p, list) and len(p) == 2]
            if pts and w.pct < pts[-1][1]:  # use went down: a reset the reset time did not show
                pts = []
            pts.append([_iso(at), float(w.pct)])
            cutoff = at - timedelta(minutes=PACE_MINUTES)
            pts = [p for p in pts if store.to_time(p[0]) >= cutoff]
            cur["points"] = pts
            samples[name] = cur
            span = (store.to_time(pts[-1][0]) - store.to_time(pts[0][0])).total_seconds()
            if span >= MIN_SPAN_SECONDS:
                rate = max(0.0, (pts[-1][1] - pts[0][1]) / (span / 60))
                old = paces.get(name)
                if (
                    span < TRUST_SPAN_SECONDS
                    and isinstance(old, dict)
                    and isinstance(old.get("per_minute"), (int, float))
                    and old["per_minute"] > rate
                ):
                    rate = float(old["per_minute"])  # a fresh, short look (the switcher reads use only now
                    # and then) must not undo the pace that moved us: that would switch back and forth
                paces[name] = {"per_minute": round(rate, 4), "at": _iso(at)}
    out = {}
    for name, p in list(paces.items()):
        if not isinstance(p, dict) or not isinstance(p.get("per_minute"), (int, float)):
            paces.pop(name, None)
            continue
        try:
            age = at - store.to_time(str(p.get("at")))
        except ValueError:
            paces.pop(name, None)
            continue
        if age > timedelta(minutes=PACE_FORGET_MINUTES):
            paces.pop(name, None)
            continue
        out[name] = float(p["per_minute"])
    return out


# ---------------------------------------------------------------- the choice


@dataclass
class Candidate:
    account: dict
    use: SubscriptionUse
    under: bool  # under every limit now
    good: bool  # under every limit and would not reach one within the look-ahead
    why: str = ""  # plain words when not good


@dataclass
class Choice:
    target: Candidate | None  # the account to be on (None: nothing usable)
    active: Candidate | None
    candidates: list[Candidate] = field(default_factory=list)
    all_at_limit: bool = False
    why: str = ""


def _limits(a: dict) -> list[tuple[str, float]]:
    """(window, percent) pairs of the account's rule; a subscription can never go past 100 %."""
    out = [
        (WINDOW_OF[x["period"]], float(x["value"]))
        for x in a["rule"]["limits"]
        if x.get("unit") == "%" and x.get("period") in WINDOW_OF
    ]
    seen = {w for w, _ in out}
    out += [(w, 100.0) for w in ("5h", "week") if w not in seen]
    return out


def judge(a: dict, use: SubscriptionUse, pace: dict[str, float], ahead: float) -> Candidate:
    under, good, why = True, True, ""
    if not any(w.pct is not None for w in use.windows.values()):
        return Candidate(a, use, False, False, "use unknown")
    for window, limit in _limits(a):
        w = use.windows.get(window)
        word = store.PERIOD_WORDS[window]
        if w is None or w.pct is None:
            if window in {
                WINDOW_OF[x["period"]] for x in a["rule"]["limits"] if x.get("period") in WINDOW_OF
            }:
                under = good = False  # a limit Usage cannot check counts as reached
                why = why or f"{word} use unknown"
            continue
        if w.pct >= limit:
            under = good = False
            why = why or f"{word} {w.pct:g}% of {limit:g}%"
        elif w.pct + pace.get(window, 0.0) * ahead >= limit:
            good = False
            why = why or f"{word} {w.pct:g}% of {limit:g}%, reached in under {ahead:g} min at this pace"
    return Candidate(a, use, under, good, why)


def choose(
    accounts: list[dict], found: list[SubscriptionUse], pace: dict[str, float], ahead: float
) -> Choice:
    """The first account in order that is good; else stay on the active one while it is under its limits; else the
    first one under its limits. all_at_limit when no account is good."""
    by_key = {f.key: f for f in found}
    cands: list[Candidate] = []
    for a in accounts:  # store.load keeps them in order
        if a["type"] != "subscription" or not a["on"]:
            continue
        f = by_key.get(a.get("source", {}).get("key"))
        if f is None:
            continue
        cands.append(judge(a, f, pace, ahead))
    active = next((c for c in cands if c.use.active), None)
    good = [c for c in cands if c.good]
    if good:
        return Choice(good[0], active, cands, False, "first account under its limits")
    if active and active.under:
        return Choice(active, active, cands, True, "every account is at or near a limit; staying")
    under = [c for c in cands if c.under]
    if under:
        return Choice(under[0], active, cands, True, "every account is at or near a limit; this one has room")
    return Choice(None, active, cands, True, "every account is at its limit")


# ---------------------------------------------------------------- one look


def _switch(slot: int) -> bool:
    cmd = cswap.command()
    if not cmd:
        return False
    try:
        subprocess.run(
            [cmd, "enable", str(slot)], capture_output=True, timeout=SWITCH_TIMEOUT, check=False
        )  # a held-out account is put back first, like the guard did
        p = subprocess.run(
            [cmd, "switch", str(slot)], capture_output=True, timeout=SWITCH_TIMEOUT, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return p.returncode == 0


def _row(what: str, a: dict | None, before, after, why: str, at: datetime) -> dict:
    return {
        "at": _iso(at),
        "who": store.USAGE,
        "what": what,
        "account": a["id"] if a else None,
        "label": a["label"] if a else "Usage",
        "before": before,
        "after": after,
        "why": why,
    }


def _use_words(c: Candidate) -> str:
    bits = [f"{store.PERIOD_WORDS[n]} {w.pct:g}%" for n, w in c.use.windows.items() if w.pct is not None]
    return f"{c.account['label']}: " + ", ".join(bits) if bits else c.account["label"]


def look(root: Path, at: datetime | None = None, switch=_switch) -> dict:
    """One pass: read, choose, switch (or say what it would do), write the history. Returns what happened."""
    at = at or datetime.now(UTC)
    cfg = config(root)
    ahead = float(cfg["ahead_minutes"])
    try:
        found = cswap.read()
        error = None
    except cswap.ReaderError as e:
        found, error = None, str(e)
    if found is None:
        return {"at": _iso(at), "switcher": False, "did": "nothing", "note": error or "no account switcher"}

    with store.change(root) as (accounts, rows):
        store.expire(accounts, rows, at)
        store.sync_found(accounts, rows, found, provider="anthropic", reader="cswap")
    accounts = store.load(root)["accounts"]

    memory = _read(memory_path(root))
    active_use = next((f for f in found if f.active), None)
    pace = update_pace(memory, active_use, at)
    ch = choose(accounts, found, pace, ahead)
    on = switching_on(root)
    hist: list[dict] = []
    did = "stay"

    # all at a limit: one warning when it starts, none while it lasts
    if ch.all_at_limit and not memory.get("all_at_limit"):
        where = ch.target or ch.active
        state = "; ".join(_use_words(c) for c in ch.candidates) or "no account to read"
        hist.append(
            _row(
                "warning: every account is at or near its limit",
                where.account if where else None,
                None,
                state,
                ch.why,
                at,
            )
        )
    memory["all_at_limit"] = ch.all_at_limit

    t = ch.target
    if t and (ch.active is None or t.use.key != ch.active.use.key):
        before = ch.active.account["label"] if ch.active else None
        why = (ch.active.why if ch.active and not ch.active.good else ch.why) or ch.why
        plan = {"to": t.account["id"], "from": ch.active.account["id"] if ch.active else None}
        if not on:
            did = "would switch"
            if memory.get("would") != plan:  # once per choice, not every 30 seconds
                hist.append(
                    _row(
                        f"would switch to {t.account['label']}",
                        t.account,
                        before,
                        t.account["label"],
                        why,
                        at,
                    )
                )
            memory["would"] = plan
        else:
            memory.pop("would", None)
            last_fail = memory.get("failed") or {}
            recent = (
                last_fail.get("to") == t.account["id"]
                and isinstance(last_fail.get("at"), str)
                and at - store.to_time(last_fail["at"]) < timedelta(minutes=RETRY_MINUTES)
            )
            if recent:
                did = "waiting to try again"
            elif switch(t.use.slot):
                did = "switched"
                memory.pop("failed", None)
                hist.append(
                    _row(f"switched to {t.account['label']}", t.account, before, t.account["label"], why, at)
                )
            else:
                did = "switch failed"
                memory["failed"] = {"to": t.account["id"], "at": _iso(at)}
                hist.append(
                    _row(
                        f"could not switch to {t.account['label']}",
                        t.account,
                        before,
                        t.account["label"],
                        why,
                        at,
                    )
                )
    else:
        memory.pop("would", None)

    memory["last"] = {
        "at": _iso(at),
        "did": did,
        "switching": on,
        "active": ch.active.account["id"] if ch.active else None,
        "target": t.account["id"] if t else None,
        "all_at_limit": ch.all_at_limit,
        "why": ch.why,
    }
    with store._lock(root):
        _write(memory_path(root), memory)
        store._append_history(root, hist)
    return {
        "at": _iso(at),
        "switcher": True,
        "switching": on,
        "did": did,
        "active": ch.active.account["label"] if ch.active else None,
        "target": t.account["label"] if t else None,
        "all_at_limit": ch.all_at_limit,
        "pace": pace,
    }


# ---------------------------------------------------------------- the loop


def addon_on(root: Path) -> bool | None:
    """Is Usage turned on in this workspace? None = could not find out (keep running)."""
    try:
        from orch import addons

        return "usage" in addons.active(root)
    except Exception:  # noqa: BLE001
        return None


def run_forever(root: Path, once: bool = False, clock=None, sleep=None, log=print, active=addon_on) -> None:
    """Look every `every_seconds` until Usage is turned off here (or once). clock/sleep: tests pass fakes."""
    import time

    clock = clock or (lambda: datetime.now(UTC))
    sleep = sleep or time.sleep
    while True:
        if active(root) is False:
            log("Usage is turned off in this workspace; stopping.")
            return
        try:
            r = look(root, clock())
            if r["did"] not in ("stay", "nothing"):
                log(f"{r['at']} {r['did']}: {r.get('active')} -> {r.get('target')}")
        except store.Refused as e:
            log(f"skipped: {e}")
        except Exception as e:  # noqa: BLE001 - one bad look must not end the loop
            log(f"skipped: {type(e).__name__}: {e}")
        if once:
            return
        sleep(config(root)["every_seconds"])
