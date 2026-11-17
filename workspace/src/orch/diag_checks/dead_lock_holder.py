"""A claim or lock held by a process that is gone. The process start time is compared, not only the pid."""

from orch.diag_checks import data, verdict

NAME = "dead_lock_holder"


def check(snap):
    locks = data(snap, "locks").get("locks")
    run_recs = data(snap, "runs").get("runs") or {}
    if locks is None:
        return verdict(NAME, "cannot_check", "locks were not collected")
    bad = []
    for lk in locks:
        if lk.get("holder_dead"):
            bad.append(
                f"{lk['path']}: held by pid {lk.get('holder_pid')} (started {lk.get('holder_start')}), gone"
            )
    for tid, r in run_recs.items():
        if r.get("pid") and r.get("process") == "dead":
            bad.append(
                f"claim of {tid} run {r['run']} - pid {r['pid']} (started {r.get('pid_started')}) is gone"
            )
    if bad:
        return verdict(NAME, "problem", "a lock or claim is held by a process that no longer exists", bad)
    return verdict(NAME, "ok", f"{len(locks)} lock file(s), none held by a dead process")
