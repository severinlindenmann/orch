"""This computer's clock differs from what the files say (a time in the future), or from the relay's."""

from orch import runs
from orch.diag_checks import data, verdict

NAME = "clock_skew"
SKEW_S = 5 * 60


def _future(snap):
    out = []
    for tid, t in (data(snap, "tickets").get("tickets") or {}).items():
        out.append((t.get("updated_at"), f"ticket {tid} updated_at"))
    for r in (data(snap, "runs").get("runs") or {}).values():
        out.append((r.get("last_heartbeat"), f"run {r.get('run')} heartbeat"))
    for iso, what in out:
        try:
            ahead = runs._parse(iso) - snap["now"]
        except (ValueError, TypeError):
            continue
        if ahead > SKEW_S:
            yield f"{what} is {int(ahead // 60)} min in the future"


def check(snap):
    if not (data(snap, "tickets").get("tickets") or data(snap, "runs").get("runs")):
        return verdict(NAME, "cannot_check", "no timestamps to compare with this clock")
    bad = list(_future(snap))
    skew = data(snap, "queues").get("relay_clock_skew_s")
    if isinstance(skew, (int, float)) and abs(skew) > SKEW_S:
        bad.append(f"relay clock differs by {int(skew)} s")
    if bad:
        return verdict(NAME, "problem", "the clock looks wrong", bad)
    return verdict(NAME, "ok", "timestamps agree with this clock")
