"""Tokens per model, how many tickets moved up to Opus, and the tickets with the most tokens (`orch usage`)."""

from .overview import ERROR

LABELS = {"sonnet": "Sonnet", "opus": "Opus", "other": "Other"}
ORDER = ("sonnet", "opus", "other")  # no new model names on the page (owner): any other model counts as Other
EMPTY = "No model use in the last 30 days."
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
        return {"empty": True, "text": EMPTY}
    top = sorted(rows, key=lambda row: -_count(row.get("total")))[:TOP]
    moved, of = _count(answer.get("moved_up")), _count(answer.get("with_model"))
    return {
        "empty": False,
        "models": models,
        "moved_up": moved,
        "of": of,
        "moved_text": f"{moved} of {of} tickets moved up to Opus",
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
