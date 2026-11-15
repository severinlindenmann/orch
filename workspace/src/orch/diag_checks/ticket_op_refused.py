"""The same ticket change is refused again and again (`ticket.op_refused` events)."""

from collections import Counter

from orch.diag_checks import verdict

NAME = "ticket_op_refused"
TIMES = 3


def check(snap):
    seen = Counter()
    guards = {}
    for e in snap["events"]:
        if e.get("ev") == "ticket.op_refused":
            kv = e.get("kv") or {}
            key = (e.get("ticket"), kv.get("op"))
            seen[key] += 1
            guards[key] = kv.get("guard")
    bad = [f"{t} {op}: refused {n}x (guard {guards[(t, op)]})" for (t, op), n in seen.items() if n >= TIMES]
    if bad:
        return verdict(NAME, "problem", "a ticket change is refused repeatedly", bad)
    return verdict(NAME, "ok", "no ticket change is refused repeatedly")
