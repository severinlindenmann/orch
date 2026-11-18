"""Tokens per model, how many tickets moved up to Opus, and the tickets with the most tokens (`orch tokens`)."""

from .overview import ERROR

LABELS = {"sonnet": "Sonnet", "opus": "Opus", "other": "Other"}
ORDER = ("sonnet", "opus", "other")  # no new model names on the page (owner): any other model counts as Other
EMPTY = "No helper work in the last 30 days."
TOP = 5


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _tokens(entry):
    entry = entry if isinstance(entry, dict) else {}
    return _count(entry.get("in")), _count(entry.get("out"))


def _fold(models):
    """Sonnet and Opus by name; every other model (a helper's small subagents, e.g.) adds up as Other."""
    models = models if isinstance(models, dict) else {}
    out = {}
    for name, entry in models.items():
        key = name if name in ("sonnet", "opus") else "other"
        i, o = _tokens(entry)
        a, b = _tokens(out.get(key))
        out[key] = {"in": a + i, "out": b + o}
    return out


def _parts(models):
    models = _fold(models)
    parts = []
    for name in ORDER:
        if name in models:
            i, o = _tokens(models[name])
            if i + o:
                parts.append({"name": name, "label": LABELS[name], "tokens": i + o})
    return parts


NOT_RECORDED = "Not recorded: helper actions left no time or cost."


def _seconds_words(seconds):
    m = round(_count(seconds) / 60)
    if not _count(seconds):
        return "–"
    if m < 1:
        return "under 1 min"
    return (f"{m // 60} h" + (f" {m % 60} min" if m % 60 else "")) if m >= 60 else f"{m} min"


def _money(cost):
    """Dollars at list price; "–" when nothing was recorded (never "$0.00", which reads as free)."""
    v = cost if isinstance(cost, int | float) and not isinstance(cost, bool) and cost >= 0 else 0
    return f"${v:,.2f}" if round(v, 2) > 0 else "–"


def _person(owner):
    owner = owner if isinstance(owner, str) else ""
    if not owner:
        return "No owner"
    kind, _, rest = owner.partition(":")
    if kind == "agent":
        return "A helper"
    return rest if kind == "human" and rest else owner


def build_team(answer):
    """ORCH-189 manager view: helper time, money at list price, tickets finished (with the average), stuck now,
    and one row per person. None when the answer carries none of it (an older orch)."""
    if not isinstance(answer, dict) or "seconds" not in answer:
        return None
    seconds, cost, finished = (
        _count(answer.get("seconds")),
        answer.get("cost") or 0,
        _count(answer.get("finished")),
    )
    each = None
    if finished and (seconds or cost):
        each = f"about {_money(cost / finished)} and {_seconds_words(seconds // finished)} each"
    people = []
    for row in answer.get("team") or []:
        if not isinstance(row, dict):
            continue
        people.append(
            {
                "name": _person(row.get("owner")),
                "finished": _count(row.get("finished")),
                "open": _count(row.get("open")),
                "time": _seconds_words(row.get("seconds")),
                "cost": _money(row.get("cost")),
            }
        )
    return {
        "time": _seconds_words(seconds),
        "cost": _money(cost),
        "note": "" if seconds or round(cost, 2) > 0 else NOT_RECORDED,
        "finished": finished,
        "each": each,
        "stuck": _count(answer.get("stuck")),
        "people": people,
    }


def _number(v):
    return v if isinstance(v, int | float) and not isinstance(v, bool) else None


def build_week(answer):
    """ORCH-297: one bar, this week's use against the weekly budget the person set in Usage. The first account
    that is on and has a weekly limit and a reading wins. None (no bar, never a fake zero) when Usage is off,
    has no weekly limit, or has no reading yet. {"label", "percent", "over"}."""
    if not isinstance(answer, dict):
        return None
    for acct in answer.get("accounts") or []:
        if not isinstance(acct, dict) or acct.get("on") is not True:
            continue
        rule = acct.get("rule") if isinstance(acct.get("rule"), dict) else {}
        limit = next(
            (x for x in rule.get("limits") or [] if isinstance(x, dict) and x.get("period") == "week"), None
        )
        use = (acct.get("use") or {}).get("week") if isinstance(acct.get("use"), dict) else None
        budget = _number(limit.get("value")) if limit else None
        if not budget or budget <= 0 or not isinstance(use, dict):
            continue
        name = str(acct.get("label") or "")[:60]
        if limit.get("unit") == "$":
            used = _number(use.get("spent"))
            if used is None:
                continue
            words = f"${used:,.2f} of ${budget:,.2f}" + (" (estimated)" if use.get("estimated") else "")
        else:
            used = _number(use.get("pct"))
            if used is None:
                continue
            words = f"{used:g}% used" + ("" if budget == 100 else f" · budget {budget:g}%")
        return {
            "label": f"{words} this week" + (f" · {name}" if name else ""),
            "percent": max(0, min(100, round(100 * used / budget))),
            "over": used > budget,
        }
    return None


def build_models(answer):
    """Fail closed: an unreadable answer is an error, never a row of zeros."""
    if not isinstance(answer, dict) or answer.get("schema") != "orch.usage/1":
        return {"error": ERROR}
    rows = [row for row in answer.get("tickets") or [] if isinstance(row, dict)]
    totals = _fold(answer.get("totals"))
    models = []
    for name in ORDER:
        if name in totals:
            i, o = _tokens(totals[name])
            if i + o:
                models.append({"name": name, "label": LABELS[name], "tokens": i + o, "in": i, "out": o})
    if not models:
        return {"empty": True, "text": EMPTY, "team": build_team(answer)}
    top = sorted(rows, key=lambda row: -_count(row.get("total")))[:TOP]
    moved, of = _count(answer.get("moved_up")), _count(answer.get("with_model"))
    return {
        "empty": False,
        "team": build_team(answer),
        "models": models,
        "moved_up": moved,
        "of": of,
        "moved_text": f"{moved} of {of} tickets needed the stronger helper",
        "tickets": [
            {
                "key": str(row.get("key") or ""),
                "title": str(row.get("title") or ""),
                "tokens": _count(row.get("total")),
                "parts": _parts(row.get("models")),
            }
            for row in top
        ],
    }
