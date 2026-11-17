"""The debug log itself lost events, so what is shown may be incomplete.

Only drops of the last hour (or of this process) are a problem: older ones are named in the fact, so a
burst in the morning does not keep the check red all day."""

from orch.diag_checks import data, verdict

NAME = "diag_dropped"


def check(snap):
    d = data(snap, "diag")
    if not d:
        return verdict(NAME, "cannot_check", "the debug log state was not collected")
    recent = d.get("dropped_last_hour", 0) + d.get("dropped_in_this_process", 0)
    if recent:
        return verdict(
            NAME,
            "problem",
            "debug log events were dropped: the picture may have holes",
            [f"{recent} dropped in the last hour, last {d.get('last_dropped_at')}"],
        )
    earlier = d.get("dropped_events_24h", 0)
    if earlier:
        return verdict(
            NAME,
            "ok",
            f"no debug log event dropped in the last hour ({earlier} earlier today, "
            f"last {d.get('last_dropped_at')})",
        )
    return verdict(NAME, "ok", "no debug log event was dropped")
