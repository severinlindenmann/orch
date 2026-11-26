"""One sentence when an account is past 80% of a limit, with the fix. `orch usage list` prints it and the Usage page
shows it as a banner: the same words from this one function (R4.3), so both say the same thing."""

from __future__ import annotations

from pathlib import Path

from . import when

NEAR_PCT = 80.0  # more than this share of a limit used: warn
LIMIT_WORDS = {"5h": "5-hour", "week": "weekly", "month": "monthly"}


def _arg(label: str) -> str:
    return f'"{label}"' if any(c.isspace() for c in label) else label


def _over(row: dict) -> list[tuple[float, str, float, dict | None]]:
    """(share of the limit used, window, the limit, the own limit or None) for each window past NEAR_PCT."""
    own = {lim["period"]: lim for lim in row["rule"]["limits"]}
    out = []
    for name, u in (row.get("use") or {}).items():
        lim = own.get(name)
        if "pct" in u:
            used, cap = u.get("pct"), (lim["value"] if lim and lim["unit"] == "%" else 100.0)
        else:
            used, cap = u.get("spent"), (lim["value"] if lim and lim["unit"] == "$" else None)
        if not isinstance(used, (int, float)) or not isinstance(cap, (int, float)) or cap <= 0:
            continue
        share = used * 100.0 / cap
        if share > NEAR_PCT:
            out.append((share, name, cap, lim))
    return out


def warning(accounts: list[dict], root: Path) -> str | None:
    """The tightest limit past 80% among the accounts that are on, as one line with the fix; None when none is."""
    found = []
    for row in accounts:
        if row.get("removed") or not row.get("on") or row.get("missing"):
            continue
        found += [(share, name, cap, lim, row) for share, name, cap, lim in _over(row)]
    if not found:
        return None
    found.sort(key=lambda x: -x[0])
    share, name, cap, lim, row = found[0]
    label = row["label"]
    word = LIMIT_WORDS.get(name)
    if name == "until" and lim and lim.get("until"):
        what = f"its limit until {str(lim['until'])[:10]}"
    else:
        what = f"its {word} limit" if word else "its limit"
    text = f"{label} is at {min(share, 999):.0f}% of {what}"
    if len(found) > 1:
        text += f" ({len(found) - 1} more past {NEAR_PCT:.0f}%)"
    text += "."
    pct = "pct" in (row.get("use") or {}).get(name, {})
    if lim and not (pct and cap >= 100):
        amount = "100%" if pct else "<dollars>"
        return f"{text} Fix: raise it with orch usage limit {_arg(label)} {amount} --period {name}"
    others = [a for a in accounts if a["type"] == row["type"] and not a.get("on") and not a.get("removed")]
    if others:
        return f"{text} Fix: turn another account on with orch usage on {_arg(others[0]['label'])}"
    resets = (row.get("use") or {}).get(name, {}).get("resets_at")
    if resets:
        try:
            return f"{text} Fix: wait until it resets ({when.words(resets, when.zone(root))}) or add an API credit with orch usage add"
        except (TypeError, ValueError):
            pass
    return f"{text} Fix: wait until it resets or add an API credit with orch usage add"
