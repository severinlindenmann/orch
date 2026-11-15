"""A ticket is Working but no run holds it (or the run's process is gone)."""

from orch import runs
from orch.diag_checks import data, verdict

NAME = "run_gone_ticket_working"


def check(snap):
    tickets = data(snap, "tickets").get("tickets")
    run_recs = data(snap, "runs").get("runs") or {}
    if tickets is None:
        return verdict(NAME, "cannot_check", "tickets were not collected")
    bad = []
    for tid, t in tickets.items():
        if t.get("status") != "active":
            continue
        rec = run_recs.get(tid)
        if rec and rec.get("process") != "dead":
            continue
        if (t.get("age_s") or 0) < runs.ORPHAN_GRACE_SECONDS:
            continue  # a start writes its claim within seconds; give it the grace the product gives it
        why = "no run record" if not rec else f"run {rec['run']}: process gone"
        bad.append(f"{tid}: Working for {int(t.get('age_s') or 0)} s, {why}")
    if bad:
        return verdict(NAME, "problem", "ticket is Working but nothing runs it", bad)
    return verdict(NAME, "ok", "every Working ticket has a live run")
