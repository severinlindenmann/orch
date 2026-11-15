"""Little free disk space where the workspace lives."""

from orch.diag_checks import data, verdict

NAME = "disk_low"
LOW_BYTES = 500 * 1024 * 1024


def check(snap):
    d = data(snap, "disk")
    if "free_bytes" not in d:
        return verdict(NAME, "cannot_check", "disk space was not collected")
    free_mb = d["free_bytes"] // (1024 * 1024)
    if d["free_bytes"] < LOW_BYTES or d["free_percent"] < 2:
        return verdict(
            NAME, "problem", "the disk is nearly full", [f"{free_mb} MB free ({d['free_percent']} %)"]
        )
    return verdict(NAME, "ok", f"{free_mb} MB free")
