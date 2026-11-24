"""The dispatcher (ORCH-507): keep a target number of helpers working, without an AI call.

Off until the owner turns it on (`orch config set workflow.dispatcher on`). Each `orch run tend` pass then:

1. Works out the target. `workflow.dispatcher_helpers` (H, default 3) helpers work while the weekly budget
   is exactly on pace. The pace is the budget left divided by the share of the week left, over every
   subscription an add-on reports (aiming at 100 % at each reset): behind pace (budget to spare) the target
   rises, at most to 2 H; ahead of pace it falls; a used-up week or 5-hour window makes it 0. Unknown
   budget: H. Never more than the helper limit (`workspace.live_max`) or 10.
2. Holds every new start while automation is paused, a usage-limit stop is noted, the computer is busy
   (load above LOAD_PER_CORE per core, or runs_live's own load and disk check) or the disk is almost full.
3. Starts tickets while fewer helpers work than the target: work of a started Factory run first, then
   Ready, then Backlog; inside each, the earliest due date, then the oldest. A ticket with an open
   question, a wait, its own schedule, a person as owner, a person's stop or a place in the line is never
   picked. It never stops a helper: above the target, helpers finish on their own.

Budget numbers come from any add-on that writes `.orch/addons/<name>/budget.json` (the Usage add-on does,
from its 30-second look); core never reads an add-on's own files. Schema `orch.budget/1`:

    {"schema": "orch.budget/1", "at": "<UTC ISO>", "accounts": [
        {"week_used": 40.0, "week_cap": 100.0, "week_resets_at": "<UTC ISO>",
         "short_used": 12.0, "short_cap": 100.0}]}

A file older than BUDGET_FRESH_SECONDS counts as unknown. Every start is a line in the ticket's history.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path

from orch import brake, config, runs, runs_live, tickets

BY = "agent:dispatcher"
WEEK_HOURS = 168.0
BUDGET_FRESH_SECONDS = 15 * 60
BUDGET_MAX_BYTES = 64 * 1024
LOAD_PER_CORE = 1.25  # no new helper above this 1-minute load per core (runs_live holds every start at 2.5)
MAX_STARTS = 2  # at most this many new helpers per pass: the load of a new helper shows a little later
HARD_MAX = 10
PICKABLE = ("ready", "open")  # Ready, Backlog


def _ts(iso: object) -> float | None:
    if not isinstance(iso, str):
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _num(v: object) -> float | None:
    """A finite number, else None (a bool, text, NaN, infinity or an int too big for a float is no number)."""
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except OverflowError:
        return None
    return f if math.isfinite(f) else None


# ---------------------------------------------------------------- budget


def budget_accounts(root: Path, now: float | None = None) -> list[dict]:
    """Every fresh account row from `.orch/addons/*/budget.json`; [] when none is fresh (budget unknown)."""
    now = time.time() if now is None else now
    out: list[dict] = []
    base = root / ".orch" / "addons"
    for f in sorted(base.glob("*/budget.json")) if base.is_dir() else []:
        try:
            if f.is_symlink() or f.stat().st_size > BUDGET_MAX_BYTES:
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("schema") != "orch.budget/1":
            continue
        at = _ts(data.get("at"))
        if at is None or not 0 <= now - at <= BUDGET_FRESH_SECONDS:
            continue
        rows = data.get("accounts")
        for a in rows if isinstance(rows, list) else []:
            if isinstance(a, dict) and _num(a.get("week_used")) is not None:
                out.append(a)
    return out


def pace(accounts: list[dict], now: float) -> dict | None:
    """{"ratio": budget left / budget the time left would use on pace, "used": combined week %, "short_full":
    every account reports its 5-hour window used up, "none_free": every account is at its week or 5-hour
    limit}, or None when nothing is known. ratio 1.0 = on pace."""
    left = want = cap_sum = used_sum = 0.0
    short_full = blocked = 0
    for a in accounts:
        used = max(0.0, _num(a.get("week_used")) or 0.0)
        cap = _num(a.get("week_cap"))
        cap = 100.0 if cap is None or cap <= 0 else min(cap, 100.0)
        reset = _ts(a.get("week_resets_at"))
        share = 1.0 if reset is None else min(1.0, max(0.0, (reset - now) / 3600.0 / WEEK_HOURS))
        left += max(0.0, cap - used)
        want += cap * share
        cap_sum += cap
        used_sum += min(used, cap)
        s_used, s_cap = _num(a.get("short_used")), _num(a.get("short_cap"))
        s_full = False
        if s_used is not None:
            s_cap = 100.0 if s_cap is None or s_cap <= 0 else s_cap
            s_full = s_used >= s_cap
            short_full += s_full
        blocked += s_full or used >= cap  # this account cannot take a helper now
    if not cap_sum:
        return None
    if left <= 0:
        ratio = 0.0
    elif want <= 0:
        ratio = float("inf")  # every reset is now: whatever is left is free to use
    else:
        ratio = left / want
    return {
        "ratio": ratio,
        "used": round(100.0 * used_sum / cap_sum, 1),
        "short_full": short_full == len(accounts),  # an account with no 5-hour number may still have room
        # every account at one of its limits (one at its week, another at its 5 hours): none can run a helper
        "none_free": blocked == len(accounts),
    }


# ---------------------------------------------------------------- load


def _load() -> tuple[float, int] | None:
    try:
        return os.getloadavg()[0], os.cpu_count() or 1
    except (OSError, AttributeError):
        return None


def target(root: Path, now: float | None = None, load=None) -> dict:
    """{"target": n, "helpers": H, "most": cap, "pace": ratio or None, "used": % or None, "held": plain
    reason a new start waits or None, "why": one plain line}."""
    now = time.time() if now is None else now
    h = config.dispatcher_helpers(root)
    most = min(2 * h, HARD_MAX, runs_live.max_live(root) or HARD_MAX)
    p = pace(budget_accounts(root, now), now)
    if p is None:
        n, why = h, f"budget unknown: {h} helpers"
    elif p["short_full"]:
        n, why = 0, "every 5-hour window is used up"
    elif p["none_free"]:
        n, why = 0, "every account is at its weekly or 5-hour limit"
    elif p["ratio"] <= 0:
        n, why = 0, f"the weekly budget is used up ({p['used']:g} %)"
    else:
        n = most if p["ratio"] == float("inf") else int(round(h * p["ratio"]))  # inf: the reset is now
        word = "on pace" if 0.9 <= p["ratio"] <= 1.1 else "behind pace" if p["ratio"] > 1 else "ahead of pace"
        why = f"weekly budget {p['used']:g} % used, {word}"
    n = max(0, min(n, most))
    held = None
    if brake.paused(root) is not None:
        held = "automation is paused"
    else:
        from orch import limitstop

        held = limitstop.held_words(root) or runs_live._pressure(root)
        got = (load or _load)() if held is None else None
        if got is not None and got[0] > LOAD_PER_CORE * got[1]:
            held = f"the computer is busy (load {got[0]:.1f} on {got[1]} cores)"
    return {
        "target": n,
        "helpers": h,
        "most": most,
        "pace": None if p is None else (None if p["ratio"] == float("inf") else round(p["ratio"], 2)),
        "used": None if p is None else p["used"],
        "held": held,
        "why": why,
    }


# ---------------------------------------------------------------- the line


def _factory_work(t: dict) -> bool:
    """Work of a started Factory run: a crew ticket, or an order whose run is going (its ext role/stage)."""
    for v in (t.get("ext") or {}).values():
        if isinstance(v, dict) and (
            v.get("role") == "crew" or (v.get("role") == "order" and v.get("stage") == "running")
        ):
            return True
    return False


def _scheduled(t: dict) -> bool:
    """An add-on starts this ticket on its own schedule (a repeat or a script)."""
    from orch import addons

    return addons.scheduled_by_addon(t)


def _open_question(t: dict) -> bool:
    return any(
        isinstance(q, dict) and q.get("answer") is None and not q.get("taken_back")
        for q in t.get("questions") or []
    )


def _person_owner(t: dict) -> bool:
    o = t.get("owner")
    return isinstance(o, str) and bool(o.strip()) and not o.startswith("agent:")


def _held_by_person(root: Path, tid: str) -> bool:
    with contextlib.suppress(Exception):
        return runs_live._held_path(root, tid).exists()
    return False


def candidates(root: Path) -> list[dict]:
    """Tickets the dispatcher may start, in the order it starts them."""
    queued = {tid for tid, _ in runs_live.waiting_line(root)}
    rows = []
    for t in tickets.list_all(root):
        tid = t.get("id")
        if t.get("status") not in PICKABLE or not isinstance(tid, str) or tid in queued:
            continue
        if t.get("waiting_on") or _open_question(t) or _scheduled(t) or _person_owner(t):
            continue
        if runs.read(root, tid) or _held_by_person(root, tid):
            continue
        rank = 0 if _factory_work(t) else 1 if t["status"] == "ready" else 2
        due = t.get("due") if isinstance(t.get("due"), str) else "9999-99-99"
        rows.append((rank, due, t.get("created_at") or "", tid, t))
    rows.sort(key=lambda r: r[:4])
    return [
        {"ticket": r[3], "key": r[4].get("key") or r[3], "rank": ("run", "ready", "backlog")[r[0]]}
        for r in rows
    ]


# ---------------------------------------------------------------- the pass


def working(root: Path) -> int:
    """Helpers that count: live sessions that hold a slot plus one-turn runs alive (helpers_alive)."""
    return len(runs_live.helpers_alive(root))


def run(root: Path, dry_run: bool = False, now: float | None = None, load=None) -> dict:
    """One pass: {"on", "running", "target", ..., "started": [{"ticket", "key", "rank"}], "would": [...]}."""
    if not config.dispatcher_on(root):
        return {"on": False}
    running = working(root)
    tg = target(root, now, load)
    res = {"on": True, "running": running, **tg, "started": [], "would": []}
    free = tg["target"] - running
    if free <= 0 or tg["held"]:
        return res
    picks = candidates(root)[: min(free, MAX_STARTS)]
    if dry_run:
        res["would"] = picks
        return res
    for c in picks:
        if runs_live._full(root) or runs_live._held(root, BY):
            break  # a start now would only wait in line
        try:
            runs.start(root, c["ticket"], BY)
        except runs.Busy:
            break
        except Exception as e:  # noqa: BLE001 - the reason goes into the history; the next pick may start
            with contextlib.suppress(Exception):
                tickets.log(root, c["ticket"], f"The dispatcher could not start a helper here: {e}", BY)
            continue
        res["started"].append(c)
        with contextlib.suppress(Exception):
            tickets.log(
                root,
                c["ticket"],
                f"Started by the dispatcher: {running + len(res['started'])} of {tg['target']} helpers "
                f"working ({tg['why']}).",
                BY,
            )
    return res


def text(res: dict, dry_run: bool = False) -> str:
    """One or two plain lines for `orch run tend`; "" when the dispatcher is off."""
    if not res.get("on"):
        return ""
    head = f"Dispatcher: {res['running']} of {res['target']} helpers working ({res['why']})"
    if res["held"]:
        return f"{head}; no new helper: {res['held']}."
    picked = res["would"] if dry_run else res["started"]
    if picked:
        verb = "would start" if dry_run else "started"
        return f"{head}; {verb} " + ", ".join(c["key"] for c in picked) + "."
    if res["running"] >= res["target"]:
        return f"{head}."
    return f"{head}; nothing to start in Ready or Backlog."
