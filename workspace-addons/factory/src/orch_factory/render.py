"""Owner-facing question text, rendered only from frozen files (authority compares against it).

Every agent-supplied string is cleaned first, so the owner sees one plain line per field and no hidden characters.
"""

import unicodedata

START_OPTIONS = ("Start", "Edit", "Not now")
CHANGE_OPTIONS = ("Accept", "Edit", "Save for later")
SHIP_OPTIONS = ("Ship it", "Send back")
STOP_OPTIONS = ("Continue", "Send back")
ALWAYS_ASKS = "Always asks you: ship, scope, budget, new connections, can't-undo, other workspaces."
QUOTES = str.maketrans({"“": "'", "”": "'", "‘": "'", "’": "'"})


def clean(value, cap=120):
    text = str(value).translate(QUOTES)
    text = "".join(
        " " if unicodedata.category(c) in ("Cc", "Zl", "Zp") else "" if unicodedata.category(c) == "Cf" else c
        for c in text
    )
    text = " ".join(text.split())
    return text if len(text) <= cap else text[: cap - 1].rstrip() + "…"


def minutes(n):
    h, m = divmod(int(n), 60)
    return " ".join(x for x in (f"{h} h" if h else "", f"{m} min" if m or not h else "") if x)


def lines(items):
    return "; ".join(clean(x) for x in items)


def join(segments, suffix, tail=""):
    text = ". ".join(s.rstrip(". ") for s in segments if s)
    return f"{text}. {tail} ({suffix})" if tail else f"{text} ({suffix})"


def start_text(p, n):
    # A version in the text also prevents core's text/options dedup from returning an older proposal.
    head = [f"Start '{clean(p['title'])}'? ~{minutes(p['time']['active_min'])}"]
    if "api_usd_target" in p["budget"]:
        head.append(f"target ${p['budget']['api_usd_target']:g}")
    if "owner_min" in p["time"]:
        head.append(f"you're needed for ~{p['time']['owner_min']} min")
    segments = [
        " · ".join(head),
        "Goal: " + clean(p["goal"]),
        "Done means: " + lines(p["done_means"]),
        "Stops: " + ", ".join(clean(x["stage"], 40) for x in p["line"] if x["stop"]),
        "Crew: " + ", ".join(f"{clean(x['role'], 40)} {clean(x['agent'], 40)}" for x in p["crew"]),
        f"Cap: {minutes(p['budget']['active_min_cap'])} active",
        f"Ship: {clean(p['ship']['does'])} (undo: {clean(p['ship']['undo'])})",
    ]
    if p.get("wont_do"):
        segments.append("Won't do: " + lines(p["wont_do"]))
    if p.get("handovers"):
        segments.append(
            "Handover: "
            + "; ".join(f"{clean(h['task'], 48)} → {clean(h['workspace'], 64)}" for h in p["handovers"])
        )
    unsure = [a["text"] for a in p.get("assumptions", []) if a.get("uncertain")]
    if unsure:
        segments.append("Unsure: " + lines(unsure))
    return join(segments, f"Proposal {n}")


question_text = start_text


def change_text(c, n):
    head = [f"Add '{clean(c['title'])}'? +{c['adds_min']} min"]
    if "adds_usd" in c:
        head.append(f"+${c['adds_usd']:g}")
    if "new_eta" in c:
        head.append(f"new ETA {clean(c['new_eta'], 40)}")
    head.append(f"lands in {clean(c['lands_in'], 40)}")
    segments = [" · ".join(head), "What: " + clean(c["what"])]
    if c.get("asked_by_owner"):
        segments.append("You said: " + clean(c["asked_by_owner"]))
    if c.get("adds_done_means"):
        segments.append("Adds done means: " + lines(c["adds_done_means"]))
    if c.get("adds_tasks"):
        segments.append(
            "Adds tasks: "
            + ", ".join(f"{clean(t['title'])} ({clean(t['role'], 24)})" for t in c["adds_tasks"])
        )
    return join(segments, f"Change {n}")


def stop_options(s):
    return SHIP_OPTIONS if s["stage"] == "ship" else STOP_OPTIONS


def stop_text(s, n):
    items = []
    for i in s["items"]:
        item = f"{clean(i['title'])} [{i['tag']}"
        if i.get("recommend"):
            item += f", suggested: {clean(i['recommend'], 40)}"
        for key in ("before", "after"):
            if i.get(key):
                item += f", {key}: {clean(i[key], 80)}"
        items.append(item + "]")
    segments = [f"Stop at {clean(s['stage'], 40)}. Decide", "; ".join(items)]
    segments[0] += ": " + segments.pop(1)
    for label, key in (
        ("Checked", "checked"),
        ("Not checked", "not_checked"),
        ("Changed during run", "changed_during_run"),
    ):
        if s.get(key):
            segments.append(f"{label}: {lines(s[key])}")
    return join(segments, f"Stop {n}")


def autopilot_text(a, n):
    limits = a["limits"]
    head = [
        f"Start autopilot '{clean(a['title'])}'? May decide: {', '.join(a['may_decide'])}",
        f"{limits['days']} days",
        f"up to {limits['max_orders']} orders",
        f"{limits['active_min_per_day']} min active per day",
    ]
    if "api_usd_per_day" in limits:
        head.append(f"${limits['api_usd_per_day']:g} per day")
    segments = [" · ".join(head), "Goal: " + clean(a["goal"])]
    if a.get("examples"):
        segments.append("Examples: " + lines(a["examples"]))
    segments.append("Done means: " + lines(a["done_means"]))
    if a.get("report_at"):
        segments.append("Report at " + clean(a["report_at"], 5))
    return join(segments, f"Autopilot {n}", ALWAYS_ASKS)


def render(kind, data, n):
    """(text, options) of the question Factory asks for a frozen file."""
    if kind == "factory:start":
        return start_text(data, n), list(START_OPTIONS)
    if kind == "factory:autopilot":
        return autopilot_text(data, n), list(START_OPTIONS)
    if kind == "factory:change":
        return change_text(data, n), list(CHANGE_OPTIONS)
    return stop_text(data, n), list(stop_options(data))
