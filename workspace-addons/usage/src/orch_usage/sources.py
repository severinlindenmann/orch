"""From what Usage keeps to one helper start's pick (ORCH-661): the accounts with their use become the picker's
sources, the owner's share (share.json, ORCH-657) becomes the picker's share, and `pick()` answers one start.

    pick(root, request)        -> picker.Pick    (gathers the accounts, reads the share, picks, holds the money)
    from_rows(rows)            -> [source]       (one per account, labels and numbers only)
    picker_share(share, rows)  -> {...}          (the share in the picker's words)

A source is at its limit exactly when the Usage page says it is skipped (spread.skipped): the page and the pick
never disagree. Only labels, numbers and times: never a key or login.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import page, picker, spread
from . import share as share_mod


def _tools() -> list[tuple[str, str, tuple[str, ...]]]:
    """The built-in helper tools from orch's agent registry (agents.json), in its order: (registry name, label,
    the API key variables it takes or drops). No tool name is written in this add-on (the adapter rule)."""
    try:
        from orch import agentsdata

        reg = agentsdata.load()["adapters"]
    except Exception:  # noqa: BLE001 - outside an orch install: no tools known
        return []
    out = []
    for name, doc in reg.items():
        detect = doc.get("detect") if isinstance(doc, dict) else None
        if not detect:  # the generic entry: not a tool of its own
            continue
        key = doc.get("api_key") or {}
        names = [key.get("env"), *(key.get("drop") or [])]
        out.append((name, str(doc.get("label") or name), tuple(str(v) for v in names if v)))
    return out


def lead_tool() -> str | None:
    """The tool orch starts by default: the registry's first."""
    t = _tools()
    return t[0][0] if t else None


def helper_tool() -> str | None:
    """The helper tool a share means when Usage has no helper tool account: the registry's second, else its first."""
    t = _tools()
    return t[1][0] if len(t) > 1 else (t[0][0] if t else None)


def tool_of(row: dict) -> str | None:
    """An account's tool by its registry name: its own `tool`, else the tool that takes its provider's API key
    (provider openai -> the tool with an OPENAI_ key variable), else a tool label in its label, else the lead tool."""
    tools = _tools()
    tool = str(row.get("tool") or "").lower()
    if any(tool == name for name, _, _ in tools):
        return tool
    provider = str(row.get("provider") or "").lower().split("-")[0]
    if provider:
        prefix = provider.upper() + "_"
        for name, _, keys in tools:
            if any(k.startswith(prefix) for k in keys):
                return name
    label = str(row.get("label", "")).lower()
    for name, tool_label, _ in tools:
        if tool_label.lower() in label:
            return name
    return lead_tool()


def tool_label(name: str | None) -> str:
    """A tool's name for people, from the registry."""
    return next((label for n, label, _ in _tools() if n == name), name or "")


def _time(text) -> datetime | None:
    """A reader's time in any ISO form (the switcher says 2026-11-16T19:29:59.99+00:00), as UTC."""
    if not isinstance(text, str) or not text:
        return None
    try:
        t = datetime.fromisoformat(text)
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=UTC)).astimezone(UTC)


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def source(row: dict) -> dict:
    """One account (a row of cli.gather) as a picker source."""
    bars = page._bars(row)
    missing = bool(row.get("missing"))
    on = bool(row.get("on")) and not missing
    acc = {"on": on, "state": "missing" if missing else "", "bars": bars}
    why = spread.skipped(acc) if on else None
    tool = tool_of(row)
    out = {
        "id": row["id"],
        "label": row.get("label") or row["id"],
        "tool": tool,
        "tool_label": tool_label(tool),
        "type": row.get("type"),
        "on": on,
        "at_limit": why is not None,
        "resets": None,
        "week_used": None,
        "week_start": None,
        "left": None,
        "day_limit": None,
        "spent_today": None,
    }
    if row.get("type") == "subscription":
        week = (row.get("use") or {}).get("week") or {}
        out["week_used"] = _num(week.get("pct"))
        reset = _time(week.get("resets_at"))
        if reset:
            out["week_start"] = picker._iso(reset - timedelta(days=7))
        if why:
            full = [b for b in bars if b.get("unit") == "%" and _num(b.get("used")) is not None]
            full = [
                _time(b.get("resets_at")) for b in full if _num(b["used"]) >= (_num(b.get("limit")) or 100.0)
            ]
            full = sorted(t for t in full if t)
            out["resets"] = picker._iso(full[-1]) if full else None  # room again once every full window reset
        return out
    lefts = []
    for b in bars:
        used, limit = _num(b.get("used")), _num(b.get("limit"))
        if b.get("limit_unit") != "$" or limit is None:
            continue
        if b.get("period") == "day":
            out["day_limit"], out["spent_today"] = limit, used
        elif used is not None:
            since = ((row.get("use") or {}).get(b.get("period")) or {}).get("since")
            lefts.append((max(limit - used, 0.0), since))
    if lefts:
        out["left"], since = min(lefts, key=lambda x: x[0])
        # The readers today count the credit skills' calls, not helper starts: every start that finished since the
        # limit's period began comes off what is left too (never overspend). A reader that counts helper starts
        # itself must set left_at to the time it read the number instead.
        out["left_at"] = picker._iso(_time(since)) if _time(since) else "0000-00-00T00:00:00Z"
    return out


def from_rows(rows: list[dict]) -> list[dict]:
    return [source(r) for r in sorted(rows, key=lambda r: r.get("order", 0))]


def _share_tool(rows: list[dict]) -> str:
    """The helper tool the share means: the first helper tool account that is on, in Usage's order (as the share's
    words name it, share.tool_name), as the picker knows it (its registry name)."""
    for r in sorted(rows, key=lambda r: r.get("order", 0)):
        if r.get("type") == "helper-tool" and r.get("on", True):
            return tool_of(r)
    return helper_tool()


def picker_share(s: dict | None, rows: list[dict]) -> dict:
    """The owner's share in the picker's words. No share: the accounts in their order, one after the other."""
    order = [r["id"] for r in sorted(rows, key=lambda r: r.get("order", 0))]
    if s is None:
        return {"order": order}
    tool = _share_tool(rows)
    out = {"order": order, "credit_kinds": list(s.get("api_for") or [])}
    if int(s.get("tool_one_in") or 0) > 0:
        out["one_in"] = {"tool": tool, "every": int(s["tool_one_in"])}
    pct, day = s.get("week_pct"), s.get("by_day")
    if isinstance(pct, int) and pct < share_mod.MAX_PCT and day in share_mod.DAYS:
        out["week"] = {picker.DAYS[share_mod.DAYS.index(day)]: pct}
        ahead = s.get("when_ahead")
        if ahead in ("api", "both", "tool"):
            out["ahead_to"] = ahead
            out["ahead_dollars_day"] = s.get("day_dollars") if ahead != "tool" else None
            if ahead != "api":
                out["ahead_tool"] = tool
    return out


def pick(root: Path, request: dict, at: datetime | None = None) -> picker.Pick:
    """One helper start: the accounts as Usage sees them now, the owner's share, the pick (money held)."""
    from .cli import gather  # cli imports this module

    rows = gather(root)["accounts"]
    return picker.pick(
        root, request, picker_share(share_mod.load(root), rows), from_rows(rows), at or datetime.now(UTC)
    )
