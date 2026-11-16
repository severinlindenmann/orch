"""When an agent tool's login on this computer runs out, and which tickets stop then.

orch asks the tool itself (agents/login.json: the tool's own status command) and keeps exactly two facts
from the answer: logged in or not, and the end time, re-written as a UTC time. Nothing else the tool prints
is kept, shown or logged, so no key and no account detail can leave through here (R5.2). A tool that tells
no end time gets no early warning: it shows as run out only once it says it is logged out.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from orch import adapters, runs, runs_live, tickets

WARN_DAYS = 3  # the warning starts this many days before the end
TIMEOUT = 10  # seconds for the tool's status command
_MAX = 65536  # status answers are small; a longer one is not read


def _end(value) -> str | None:
    """The end time as 'YYYY-MM-DDTHH:MM:SSZ', or None. Only a real time passes: the tool's text is parsed
    and written anew, never copied."""
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, int | float):
            t = datetime.fromtimestamp(value / 1000 if value > 1e11 else value, UTC)
        elif isinstance(value, str) and len(value) <= 40:
            t = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=UTC)
        else:
            return None
        return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OverflowError, OSError):
        return None


def ask(binary: str, spec: dict) -> tuple[bool | None, str | None]:
    """(logged in, end time) from the tool's own status command; (None, None) when it cannot be read."""
    try:
        r = subprocess.run(
            [binary, *spec["status"]],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
        doc = json.loads((r.stdout or "")[:_MAX])
    except (OSError, subprocess.SubprocessError, ValueError):
        return None, None
    if not isinstance(doc, dict):
        return None, None
    logged_in = doc.get(spec["logged_in"])
    return (logged_in if isinstance(logged_in, bool) else None), _end(doc.get(spec.get("ends") or ""))


def state(logged_in: bool | None, ends_at: str | None, now: datetime | None = None) -> str:
    """out | soon | ok | unknown."""
    now = now or datetime.now(UTC)
    if logged_in is False:
        return "out"
    if ends_at:
        end = datetime.strptime(ends_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        if end <= now:
            return "out"
        if end - now <= timedelta(days=WARN_DAYS):
            return "soon"
    return "unknown" if logged_in is None else "ok"


def stops(root: Path, adapter: str) -> list[dict]:
    """Tickets a helper works on right now with this tool: [{id, key, title}]."""
    out = []
    for rec in runs_live.records(root):
        tid = rec.get("ticket")
        try:
            if runs.state(rec) != "alive" or tickets.is_general(root, tid):
                continue
            if adapters.load(str(rec.get("agent") or ""), root)["adapter"] != adapter:
                continue
            t = tickets.load(root, tid)
        except Exception:  # noqa: BLE001  a broken record or ticket never hides the warning
            continue
        out.append({"id": tid, "key": t.get("key") or tid, "title": t.get("title") or ""})
    return out


def overview(root: Path, now: datetime | None = None) -> list[dict]:
    """One row per installed tool that can tell about its login:
    {tool, label, state, logged_in, ends_at, chosen, stops}."""
    try:
        chosen = adapters.load(adapters.chosen(root), root)["adapter"]
    except Exception:  # noqa: BLE001  no agent chosen or found: nothing is "the helper here"
        chosen = None
    rows = []
    for name in adapters.builtin_names():
        a = adapters.load(name)
        spec = a.get("login")
        binary = shutil.which((a.get("detect") or {}).get("binary") or "")
        if not spec or not binary:
            continue
        logged_in, ends_at = ask(binary, spec)
        rows.append(
            {
                "tool": name,
                "label": a["label"],
                "state": state(logged_in, ends_at, now),
                "logged_in": logged_in,
                "ends_at": ends_at,
                "chosen": name == chosen,
                "stops": stops(root, name),
            }
        )
    return rows
