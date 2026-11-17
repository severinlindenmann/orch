"""A run's process is alive but its heartbeat is old. Progress is unknown: that is not the same as hung."""

from orch.diag_checks import data, verdict

NAME = "no_heartbeat"
QUIET_S = 10 * 60


def check(snap):
    run_recs = data(snap, "runs").get("runs")
    if run_recs is None:
        return verdict(NAME, "cannot_check", "runs were not collected")
    bad = []
    for tid, r in run_recs.items():
        age = r.get("heartbeat_age_s")
        if r.get("process") == "alive" and age is not None and age > QUIET_S:
            bad.append(f"{tid} run {r['run']} - process alive, last heartbeat {int(age // 60)} min ago")
    if bad:
        return verdict(
            NAME, "problem", "progress unknown: the process is alive but has not reported for a while", bad
        )
    return verdict(NAME, "ok", "every live run reported recently")
