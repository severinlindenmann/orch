"""ORCH-2157: a text or file from another workspace arrived, but nothing handled it or passed it on."""

from orch.diag_checks import data, verdict

NAME = "relay_unhandled"  # over an hour: diag_collect.UNHANDLED_S
FIX = "Read them with orch relay inbox; one that stays there after that is an orch bug: report the problem."


def check(snap):
    queues = data(snap, "queues")
    if "relay_outbox" not in queues:
        if queues:
            return None  # the relay is off: nothing to check, nothing to show
        return verdict(NAME, "cannot_check", "queues were not collected")
    q = queues.get("relay_inbox")
    if q is None:
        return verdict(NAME, "cannot_check", "the inbox was not collected")
    age = q.get("oldest_age_s")
    if q.get("stuck") and age is not None:
        hours = int(age // 3600)
        return verdict(
            NAME,
            "problem",
            f"{q['stuck']} message(s) from other workspaces were never handled, the oldest for {hours} h",
            q.get("ids") or [],
        )
    return verdict(NAME, "ok", "every message from another workspace was handled or passed on")
