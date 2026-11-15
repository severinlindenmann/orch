"""The agent's tool hooks do not reach the activity record (hook-lost alerts)."""

from collections import Counter

from orch.diag_checks import data, verdict

NAME = "hook_lines_missing"
REASONS = ("hooks_missing", "hooks_off")


def check(snap):
    if "runs" not in snap["collected"]:
        return verdict(NAME, "cannot_check", "runs were not collected")
    lost = [h for h in data(snap, "runs").get("hook_failures") or [] if h.get("reason") in REASONS]
    if lost:
        c = Counter((h.get("run"), h.get("reason")) for h in lost)
        return verdict(
            NAME,
            "problem",
            "hook lines are missing from the record",
            [f"run {r}: {why} x{n}" for (r, why), n in c.items()],
        )
    return verdict(NAME, "ok", "no hook delivery failure recorded")
