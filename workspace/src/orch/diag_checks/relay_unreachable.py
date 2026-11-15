"""Phone messages wait in the outbox, or sends failed: the relay is not reachable (or refuses)."""

from orch.diag_checks import data, verdict

NAME = "relay_unreachable"
STUCK_S = 10 * 60
FAILS = 3


def check(snap):
    q = data(snap, "queues").get("relay_outbox")
    if q is None:
        if data(snap, "queues"):
            return None  # the optional part is off: nothing to check, nothing to show
        return verdict(NAME, "cannot_check", "queues were not collected")
    bad = []
    if q.get("problem"):
        bad.append(f"outbox problem: {q['problem']}")
    if q.get("oldest_age_s") is not None and q["oldest_age_s"] > STUCK_S:
        bad.append(f"{q['count']} message(s) waiting, the oldest for {int(q['oldest_age_s'] // 60)} min")
    n = sum(1 for e in snap["events"] if e.get("ev") == "relay.send_failed")
    if n >= FAILS:
        bad.append(f"{n} send failures in the log")
    if bad:
        return verdict(NAME, "problem", "the relay is not taking messages", bad)
    return verdict(NAME, "ok", f"{q.get('count', 0)} message(s) in the outbox, none stuck")
