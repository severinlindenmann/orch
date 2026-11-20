"""Early switching: every 30 seconds read the subscriptions' use and keep the first account in order that is under
its limits and would not reach one within 10 minutes at the current pace. Switches through the account switcher.

Without the switcher, or with switching turned off (`orch usage switching off`), Usage only shows and warns: it
works out the same choice and writes "would switch" in the history, but never switches.

Pace: how fast the work uses a subscription (percent per minute per window), measured on the active account over
the last minutes and applied to every candidate (the same work moves with the switch). It is remembered across a
switch, so an account left early is not taken back until its use drops (a reset) or the work slows down.

Files in the Usage folder of this computer (computer.py): `settings.json` {"switching": bool} (written by the command; off until the person turns
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

from . import computer, store, when
from .readers import SubscriptionUse, cswap

EVERY_SECONDS = 30
AHEAD_MINUTES = 10
PACE_MINUTES = 10  # samples older than this do not count for the pace
MIN_SPAN_SECONDS = (
    300  # the pace needs samples this far apart: the switcher refreshes its numbers only every few
)
# minutes, so a shorter look reads one refresh as a burst of use (ORCH-93 finding 8)
TRUST_SPAN_SECONDS = 300  # a lower pace replaces a higher remembered one only when measured over this long
PACE_FORGET_MINUTES = 30  # a remembered pace older than this is dropped
RETRY_MINUTES = 10  # a failed switch to the same account is tried again (and written down) after this
WINDOW_OF = {"5h": "5h", "week": "week"}  # rule period -> switcher window
# ORCH-642: a window the account's rule sets no limit for: switch early at this percent (the account still counts
# as having room up to 100 %). Without it an account with only a weekly limit was left only AT 100 % of its
# 5 hours, after every helper had stopped on it.
DEFAULT_EARLY = {"5h": 90.0, "week": 100.0}
SWITCH_TIMEOUT = 30
BACK_MINUTES = (
    10  # an account switched away from and active again within this is "another program switched back"
)


CLEAR_MINUTES = 10  # a warning counts as cleared only after it was gone this long (no new card per flicker)
FRESH_MINUTES = 15  # a warning from an older look is not shown: the loop stopped, so it may be out of date
WARNINGS = ("all-at-limit", "switch-failed")


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
    return store.ensure(root) / "settings.json"


def memory_path(root: Path) -> Path:
    return store.ensure(root) / "switching.json"


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


WARNING_WORDS = {
    "all-at-limit": "every account is at or near its limit",
    "switch-failed": "could not switch to an account",
}


def seen(root: Path) -> dict:
    """{warning: since} the person said Got it to (settings.json); that warning stays hidden until it comes back."""
    s = _read(settings_path(root)).get("seen")
    return {k: v for k, v in s.items() if k in WARNINGS and isinstance(v, str)} if isinstance(s, dict) else {}


def mark_seen(root: Path, who: str, warning: str, since: str | None = None) -> bool:
    """Got it: hide this warning until it clears and comes back. `since` (from the card) must be the warning that
    is showing now, so a late click never hides a newer one. True when it changed. Written in the history."""
    if warning not in WARNINGS:
        raise store.Refused(f"Usage has no warning '{warning}'. Warnings: {', '.join(WARNINGS)}.")
    with store._lock(root):
        live = _read(memory_path(root)).get("warnings")
        cur = live.get(warning) if isinstance(live, dict) else None
        if not isinstance(cur, dict) or cur.get("cleared") or not isinstance(cur.get("since"), str):
            raise store.Refused("That warning is not showing any more.")
        if since is not None and since != cur["since"]:
            raise store.Refused("That warning changed since. Reload the page and look again.")
        s = _read(settings_path(root))
        marks = s.get("seen") if isinstance(s.get("seen"), dict) else {}
        if marks.get(warning) == cur["since"]:
            return False
        s["seen"] = {**{k: v for k, v in marks.items() if k in WARNINGS}, warning: cur["since"]}
        _write(settings_path(root), s)
        store._append_history(
            root,
            [
                {
                    "at": store.now(),
                    "who": who,
                    "what": f"warning seen: {WARNING_WORDS[warning]}",
                    "account": cur.get("to"),
                    "label": cur.get("label") or "Usage",
                    "before": "shown",
                    "after": "hidden until it comes back",
                }
            ],
        )
    return True


def _episodes(old, now: dict, at: datetime) -> dict:
    """Each warning keeps the time it started (`since`) while it lasts. Gone, it is kept `cleared` for CLEAR_MINUTES:
    back within that time it is the same warning (same since); after that it is forgotten, so it starts anew."""
    old = old if isinstance(old, dict) else {}
    out = {}
    for k in WARNINGS:
        prev = old.get(k) if isinstance(old.get(k), dict) else None
        if prev and not isinstance(prev.get("since"), str):
            prev = None
        gone = prev and isinstance(prev.get("cleared"), str) and at - store.to_time(prev["cleared"])
        if gone and gone >= timedelta(minutes=CLEAR_MINUTES):
            prev = None  # gone long enough (also when no look came between): it starts anew
        if k in now:  # the same warning while it lasts, also when another account is the one that fails now
            out[k] = {**now[k], "since": prev["since"] if prev else _iso(at)}
        elif prev:
            cleared = prev.get("cleared") or _iso(at)
            if at - store.to_time(cleared) < timedelta(minutes=CLEAR_MINUTES):
                out[k] = {**prev, "cleared": cleared}
    return out


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


def _limits(a: dict) -> list[tuple[str, float, float]]:
    """(window, switch at, full at) per window: the account's rule (both the same), else DEFAULT_EARLY and 100 %
    (a subscription can never go past 100 %)."""
    out = [
        (WINDOW_OF[x["period"]], float(x["value"]), float(x["value"]))
        for x in a["rule"]["limits"]
        if x.get("unit") == "%" and x.get("period") in WINDOW_OF
    ]
    seen = {w for w, _, _ in out}
    out += [(w, DEFAULT_EARLY[w], 100.0) for w in ("5h", "week") if w not in seen]
    return out


def judge(a: dict, use: SubscriptionUse, pace: dict[str, float], ahead: float) -> Candidate:
    under, good, why = True, True, ""
    if use.disabled:
        return Candidate(a, use, False, False, "turned off in the account switcher")
    if not any(w.pct is not None for w in use.windows.values()):
        return Candidate(a, use, False, False, "use unknown")
    for window, limit, full in _limits(a):
        w = use.windows.get(window)
        word = store.PERIOD_WORDS[window]
        if w is None:
            continue  # the switcher reports no such window for this account (read fine): nothing to reach
        if w.pct is None:
            if window in {
                WINDOW_OF[x["period"]] for x in a["rule"]["limits"] if x.get("period") in WINDOW_OF
            }:
                under = good = False  # a limit Usage cannot check counts as reached
                why = why or f"{word} use unknown"
            continue
        if w.pct >= full:
            under = good = False
            why = why or f"{word} {w.pct:g}% of {full:g}%"
        elif w.pct >= limit:
            good = False  # past the early switch, not full: left when another has room, else kept
            why = why or f"{word} {w.pct:g}%, switches early at {limit:g}%"
        elif w.pct + pace.get(window, 0.0) * ahead >= limit:
            good = False
            why = why or f"{word} {w.pct:g}% of {limit:g}%, reached in under {ahead:g} min at this pace"
    return Candidate(a, use, under, good, why)


def choose(
    accounts: list[dict],
    found: list[SubscriptionUse],
    pace: dict[str, float],
    ahead: float,
    skip: frozenset[str] = frozenset(),
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
    good = [c for c in cands if c.good and c.account["id"] not in skip]  # skip: a switch to it just failed
    if good:
        return Choice(
            good[0],
            active,
            cands,
            False,
            f"{good[0].account['label']} is the first account in order that is under its limits",
        )
    if active and active.under:
        return Choice(active, active, cands, True, "every account is at or near a limit; staying")
    under = [c for c in cands if c.under and c.account["id"] not in skip]
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


def _stuck(key: str, read=cswap.read) -> bool:
    """After a switch: is the account really the one in use now? (exit 0 is not proof: another program can switch
    back at once, or the switcher can answer yes and change nothing)."""
    try:
        return any(f.active and f.key == key for f in read())
    except cswap.ReaderError:
        return False


def _recent_failures(memory: dict, at: datetime) -> dict[str, str]:
    """Accounts a switch failed to within RETRY_MINUTES: {account id: when}. (An older memory kept one {to, at}.)"""
    raw = memory.get("failed") or {}
    if "to" in raw and "at" in raw:
        raw = {raw["to"]: raw["at"]}
    out = {}
    for k, v in raw.items():
        try:
            if isinstance(v, str) and at - store.to_time(v) < timedelta(minutes=RETRY_MINUTES):
                out[k] = v
        except (ValueError, TypeError):
            pass
    return out


ALL_AT_LIMIT_ALERT = "Every account is at or near its limit."


def alerts(accounts: list[dict], ch: Choice, failed: dict[str, str]) -> list[str]:
    """What the person should see now (list, status, the page), in plain words; empty when all is well."""
    out = []
    if ch.all_at_limit:
        out.append(ALL_AT_LIMIT_ALERT)
    names = {a["id"]: a["label"] for a in accounts}
    for k in failed:
        out.append(f"Could not switch to {names.get(k, k)}; Usage tries the next account in order.")
    return out


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


def following(root: Path, shared: Path) -> str | None:
    """The name of the workspace whose Usage loop switches the accounts now, when it is not this one."""
    o = computer.owner(shared)
    if o.get("workspace") in (None, computer.key(root)):
        return None
    if o.get("running") or computer.just_taken(o, shared):  # a person just moved it there: never in between
        return o.get("name") or "another workspace"
    return None


def _switch_once(root: Path, shared: Path | None, switch, t: Candidate, before: str | None) -> str:
    """One switch under the computer's switch lock, with the switcher checked again inside it (a take-over waits
    for it). Returns "switched", "failed" or "follow" (another workspace switches now: nothing was done)."""
    if shared is None:
        return "switched" if switch(t.use.slot) and _stuck(t.use.key) else "failed"
    with computer.held(shared / "switch.lock", wait=90, busy="Another switch is running."):
        if following(root, shared):
            return "follow"
        if not (switch(t.use.slot) and _stuck(t.use.key)):
            return "failed"
        computer.note_switch(shared, root, before, t.account["label"])
    return "switched"


def look(root: Path, at: datetime | None = None, switch=_switch) -> dict:
    """One pass: read, choose, switch (or say what it would do), write the history. Returns what happened."""
    at = at or datetime.now(UTC)
    shared = computer.shared_dir(root)
    if shared is not None:
        computer.note_workspace(root, shared)
        other = following(root, shared)
        if other:
            return {
                "at": _iso(at),
                "switcher": True,
                "switching": switching_on(root),
                "did": "follow",
                "owner": other,
            }
    cfg = config(root)
    ahead = float(cfg["ahead_minutes"])
    try:
        found = cswap.read()
        error = None
    except cswap.ReaderError as e:
        found, error = None, str(e)
    if found is None:
        return {"at": _iso(at), "switcher": False, "did": "nothing", "note": error or "no account switcher"}

    tz = when.zone(root)
    with store.change(root) as (accounts, rows):
        store.expire(accounts, rows, at, say=lambda ends: when.words(ends, tz))
        store.sync_found(accounts, rows, found, provider="anthropic", reader="cswap")
    accounts = store.load(root)["accounts"]

    memory = _read(memory_path(root))
    active_use = next((f for f in found if f.active), None)
    pace = update_pace(memory, active_use, at)
    on = switching_on(root)
    failed = _recent_failures(memory, at)  # account id -> when a switch to it failed, within RETRY_MINUTES
    ch = choose(accounts, found, pace, ahead, frozenset(failed))
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
    why = ch.why
    while t and (ch.active is None or t.use.key != ch.active.use.key):
        before = ch.active.account["label"] if ch.active else None
        if ch.active and not ch.active.good and ch.active.why:
            why = f"{ch.active.account['label']}: {ch.active.why}"  # the account left, not the new one
        else:
            why = ch.why
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
            break
        else:
            memory.pop("would", None)
            done = _switch_once(root, shared, switch, t, before)
            if done == "follow":
                did = "follow"
                break
            if done == "switched":
                did = "switched"
                memory.pop("failed", None)
                failed = {}
                prev = memory.get("switched") or {}
                again = (
                    prev.get("to") == t.account["id"]
                    and isinstance(prev.get("at"), str)
                    and at - store.to_time(prev["at"]) < timedelta(minutes=BACK_MINUTES)
                )
                if not again:  # a switch is written once
                    hist.append(
                        _row(
                            f"switched to {t.account['label']}",
                            t.account,
                            before,
                            t.account["label"],
                            why,
                            at,
                        )
                    )
                elif not prev.get("back_noted"):  # something moved the account back: one row, not one per try
                    hist.append(
                        _row(
                            f"another program switched back to {before or 'the first account'}",
                            ch.active.account if ch.active else None,
                            t.account["label"],
                            before,
                            f"Usage switched to {t.account['label']} at {prev['at']} and the account in use "
                            "changed again without Usage; it is switching again",
                            at,
                        )
                    )
                memory["switched"] = {
                    "to": t.account["id"],
                    "at": prev["at"] if again else _iso(at),
                    "back_noted": bool(again),
                }
                break
            else:
                did = "switch failed"
                failed[t.account["id"]] = _iso(at)
                memory["failed"] = dict(failed)
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
                # try the next good account now, not the same one again in RETRY_MINUTES
                ch = choose(accounts, found, pace, ahead, frozenset(failed))
                t = ch.target
    else:
        memory.pop("would", None)
        if did == "stay" and failed and ch.active and not ch.active.good:
            did = "waiting to try again"  # the accounts to go to just failed; tried again after RETRY_MINUTES

    # the warnings `orch usage needs` tells the person about, once each (ORCH-644)
    # at a limit = by the limits alone: an account left out only because a switch to it failed still has room
    limits = choose(accounts, found, pace, ahead) if failed else ch
    warn_now: dict = {}
    if limits.all_at_limit:
        warn_now["all-at-limit"] = {}
    if failed:
        first = min(failed, key=lambda k: failed[k])  # the account that failed first names the warning
        label = next((a["label"] for a in accounts if a["id"] == first), first)
        warn_now["switch-failed"] = {"to": first, "label": label}
    memory["warnings"] = _episodes(memory.get("warnings"), warn_now, at)

    memory["alerts"] = alerts(accounts, limits, failed)
    memory["last"] = {
        "at": _iso(at),
        "did": did,
        "switching": on,
        "active": ch.active.account["id"] if ch.active else None,
        "target": t.account["id"] if t else None,
        "all_at_limit": ch.all_at_limit,
        "why": why,
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


def needs_rows(root: Path, at: datetime | None = None) -> list[dict]:
    """`orch usage needs --json` (needs.schema.json): one row per Usage warning (ORCH-644)."""
    return warning_rows(root, at)


def warning_rows(root: Path, at: datetime | None = None) -> list[dict]:
    """One row per live warning. Its id carries the time the warning started, so a surface that remembers what it
    showed tells the person once; a warning that cleared and came back is a new row. Got it hides it until then."""
    at = at or datetime.now(UTC)
    memory = _read(memory_path(root))
    last = memory.get("last") if isinstance(memory.get("last"), dict) else {}
    try:
        fresh = at - store.to_time(last["at"]) < timedelta(minutes=FRESH_MINUTES)
    except (KeyError, TypeError, ValueError):
        fresh = False
    live = memory.get("warnings")
    if not fresh or not isinstance(live, dict):
        return []
    hidden = seen(root)
    rows = []
    for k in WARNINGS:
        w = live.get(k)
        if not isinstance(w, dict) or w.get("cleared") or not isinstance(w.get("since"), str):
            continue
        if hidden.get(k) == w["since"]:
            continue
        if k == "all-at-limit":
            title, tone = "Usage: every account is at or near its limit", "bad"
            text = (
                "Usage has no account to switch to, so helpers may stop "
                "until a limit resets. Raise a limit or turn on another account in Usage."
            )
        else:
            label = w.get("label") or "the next account"
            title, tone = f"Usage: could not switch to {label}", "warn"
            text = (
                f"Usage could not switch to {label} and tries the next account in order; {label} is tried again "
                f"after {RETRY_MINUTES} minutes. Check that the account switcher works and that {label} is still "
                "signed in."
            )
        rows.append(
            {
                "id": f"usage:{k}:{w['since']}",
                "source": "usage",
                "kind": f"usage:{k}",
                "ticket": None,
                "title": title[:200],
                "text": text[:500],
                "tone": tone,
                "since": w["since"],
                "cli": f"orch usage list; hide it with: orch usage seen {k}",
                "actions": [
                    {
                        "label": "Got it",
                        "verb": "seen",
                        "target": f"{k}:{w['since']}",
                        "review": {"done": "Hidden until it comes back."},
                    }
                ],
            }
        )
    return rows


# ---------------------------------------------------------------- the loop


def addon_on(root: Path) -> bool | None:
    """Is Usage turned on in this workspace? None = could not find out (keep running)."""
    try:
        from orch import addons

        return "usage" in addons.active(root)
    except Exception:  # noqa: BLE001
        return None


def run_forever(root: Path, once: bool = False, clock=None, sleep=None, log=print, active=addon_on) -> None:
    """Look every `every_seconds` until Usage is turned off here (or once). clock/sleep: tests pass fakes.
    One loop per computer looks and switches (computer.Switcher); the others follow it."""
    import time

    clock = clock or (lambda: datetime.now(UTC))
    sleep = sleep or time.sleep
    shared = computer.shared_dir(root)
    lease = computer.Switcher(root, shared) if shared is not None else None
    was: bool | None = None
    try:
        while True:
            if active(root) is False:
                log("Usage is turned off in this workspace; stopping.")
                return
            try:
                if lease is not None:
                    mine = lease.hold()
                    if mine != was:
                        who = following(root, shared)
                        log(
                            "This workspace switches the accounts."
                            if mine
                            else f"{who or 'Another workspace'} switches the accounts; following."
                        )
                    was = mine
                    if (
                        not mine
                    ):  # only the switcher's loop looks and switches; a follower only says it is here
                        computer.note_workspace(root, shared)
                        if once:
                            return
                        sleep(config(root)["every_seconds"])
                        continue
                r = look(root, clock())
                if r["did"] not in ("stay", "nothing", "follow"):
                    log(f"{r['at']} {r['did']}: {r.get('active')} -> {r.get('target')}")
            except store.Refused as e:
                log(f"skipped: {e}")
            except Exception as e:  # noqa: BLE001 - one bad look must not end the loop
                log(f"skipped: {type(e).__name__}: {e}")
            if once:
                return
            sleep(config(root)["every_seconds"])
    finally:
        if lease is not None:
            lease.release()
