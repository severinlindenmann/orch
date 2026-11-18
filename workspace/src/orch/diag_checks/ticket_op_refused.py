"""The same ticket change is refused again and again (`ticket.op_refused` events).

Only the last hour counts, so the problem goes away by itself once the writer stops. A `conflict` is a
normal race between two writers (the loser reads again and retries), so it is not counted."""

from collections import Counter
from datetime import datetime

from orch.diag_checks import verdict

NAME = "ticket_op_refused"
TIMES = 3
RECENT_S = 60 * 60
NOT_COUNTED = ("conflict",)


def _epoch(at) -> float | None:
    try:
        return datetime.fromisoformat(str(at).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _by(actors) -> str:
    """The caller, so the person sees who keeps writing (ORCH-418: agent:pull-requests on closed tickets)."""
    return f", by {', '.join(sorted(actors))}" if actors else ""


def check(snap):
    since = snap["now"] - RECENT_S
    seen = Counter()
    who: dict = {}
    for e in snap["events"]:
        if e.get("ev") != "ticket.op_refused":
            continue
        kv = e.get("kv") or {}
        guard = kv.get("guard")
        at = _epoch(e.get("at"))
        if guard in NOT_COUNTED or at is None or at < since:
            continue
        key = (e.get("ticket"), kv.get("op"), guard)
        seen[key] += 1
        if kv.get("actor"):
            who.setdefault(key, set()).add(str(kv["actor"]))
    bad = [
        f"{t}{'' if op in (None, 'op') else ' ' + op}: refused {n}x in the last hour (guard {g}){_by(who.get((t, op, g)))}"
        for (t, op, g), n in seen.items()
        if n >= TIMES
    ]
    if bad:
        return verdict(NAME, "problem", "a ticket change is refused repeatedly", bad)
    return verdict(NAME, "ok", "no ticket change was refused repeatedly in the last hour")
