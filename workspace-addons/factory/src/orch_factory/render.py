"""Owner-facing question text, rendered only from frozen files (authority compares against it)."""

START_OPTIONS = ("Start", "Edit", "Not now")


def question_text(p, n):
    # A version in the text also prevents core's text/options dedup from returning an older proposal.
    minutes = p["time"]["active_min"]
    duration = f"~{minutes / 60:g} h" if minutes >= 60 else f"~{minutes} min"
    parts = [f"Start “{p['title']}”? {duration}"]
    if "api_usd_target" in p["budget"]:
        parts.append(f"target ${p['budget']['api_usd_target']:g}")
    if "owner_min" in p["time"]:
        parts.append(f"you’re needed for ~{p['time']['owner_min']} min")
    return " · ".join(parts) + ". Done means: " + "; ".join(p["done_means"]) + f" (Proposal {n})"
