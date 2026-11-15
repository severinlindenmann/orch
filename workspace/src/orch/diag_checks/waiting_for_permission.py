"""A live helper sits on a permission prompt (or another notice) nobody answered."""

from orch import runs
from orch.diag_checks import data, verdict

NAME = "waiting_for_permission"
WAIT_S = 120


def check(snap):
    run_recs = data(snap, "runs").get("runs")
    if run_recs is None:
        return verdict(NAME, "cannot_check", "runs were not collected")
    bad = []
    for tid, r in run_recs.items():
        if r.get("live_state") != "attention" or r.get("process") != "alive":
            continue
        try:
            waited = snap["now"] - runs._parse(r["live_since"])
        except (KeyError, ValueError, TypeError):
            continue
        if waited > WAIT_S:
            bad.append(f"{tid} run {r['run']}: waiting for an answer for {int(waited)} s")
    if bad:
        return verdict(NAME, "problem", "a helper is waiting for permission", bad)
    return verdict(NAME, "ok", "no helper is waiting on a prompt")
