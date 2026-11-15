"""The debug log itself lost events, so what is shown may be incomplete."""

from orch.diag_checks import data, verdict

NAME = "diag_dropped"


def check(snap):
    d = data(snap, "diag")
    if not d:
        return verdict(NAME, "cannot_check", "the debug log state was not collected")
    n = d.get("dropped_events_24h", 0) + d.get("dropped_in_this_process", 0)
    if n:
        return verdict(
            NAME,
            "problem",
            "debug log events were dropped: the picture may have holes",
            [f"{n} dropped, last {d.get('last_dropped_at')}"],
        )
    return verdict(NAME, "ok", "no debug log event was dropped")
