"""`orch services needs --json`: rows for `orch needs` (needs.schema.json).

W-054 A (owner, 28 Nov): Home mentions a failing service only when work depends on it. One row per service that
keeps failing AND that something relies on: its record names the work (`depends`, written by hand or by the
ticket's helper, never guessed), or the person marked it important. A failing service nothing depends on gives no row: it is on the Services page alone, with
Restart and Remove. The row's one button restarts it (`orch services act restart -- <id>`, the page's own verb).

Read-only and cheap: it takes the rows `orch services list` already builds; a computer that cannot list its jobs
gives no rows."""

from __future__ import annotations

from datetime import UTC, datetime


def _plain(text: object, n: int) -> str:
    t = " ".join(str(text).replace("<", "‹").replace(">", "›").split())
    return t if len(t) <= n else t[: n - 1] + "…"


def _since(row: dict) -> str:
    for key in ("since", "checked_at"):
        v = row.get(key)
        if isinstance(v, str) and v.endswith("Z"):
            return v
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def rows(listing: list[dict]) -> list[dict]:
    """The needs rows of `listing` (the rows of `orch services list --json`)."""
    out = []
    for r in listing:
        depends = [d for d in r.get("depends") or [] if isinstance(d, str) and d.strip()]
        important = bool(r.get("important"))
        if r.get("state") != "failing" or not (depends or important):
            continue
        name = _plain(r.get("name") or r["id"], 80)
        why = f"It is needed for: {', '.join(depends)}." if depends else "It is marked important."
        out.append(
            {
                "id": f"services:failing-{r['id']}",
                "source": "services",
                "kind": "services:failing",
                "ticket": None,
                "title": name,
                "text": _plain(f"{name} keeps stopping. {why}", 500),
                "tone": "bad",
                "since": _since(r),
                "actions": [{"label": "Restart", "verb": "restart", "target": r["id"]}],
                "cli": f"orch services restart {r['id']}",
            }
        )
    return out
