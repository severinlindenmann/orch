"""The workspace look (icon + colour), its description and the workspace switcher.

Everything goes through the `orch` command: `orch look show|set|shared-pages`, `orch status --json` (the workspaces
orch knows on this computer, with their look) and `orch <service> profile` (the description proposal, which the owner
approves in the service's admin page). The caller is always the signed-in session user: actions.py adds
`--by human:<user>`; no request field names a caller. The lines that name a service live here only.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

ID = re.compile(r"[a-z0-9-]{1,32}")
SERVICES = ("relay", "publish")  # the description proposal goes to the first one that is connected
MAX_DESCRIPTION = 280
_CACHE: dict[str, tuple[float, dict | None]] = {}
TTL = 10.0  # `orch look show` asks the services; the 3 s page poll must not


def _actions():
    from . import actions  # late: actions builds its op table from this file

    return actions


def _bad(msg):
    return _actions().BadRequest(msg)


def _pick(v, name):
    if v is None:
        return None
    if not isinstance(v, str) or not ID.fullmatch(v):
        raise _bad(f"That {name} is not available.")
    return v


def _look_set(a):
    """Pick the icon and colour: `orch look set --icon=<id>|none --color=<token>|auto` (the core checks the ids)."""
    _actions()._only(a, ("icon", "color"))
    icon, color = _pick(a.get("icon"), "icon"), _pick(a.get("color"), "colour")
    return ["look", "set"], [f"--icon={icon or 'none'}", f"--color={color or 'auto'}"], []


def _look_shared(a):
    """Show the workspace name and icon on shared file pages: `orch look shared-pages on|off`."""
    _actions()._only(a, ("on",))
    if not isinstance(a.get("on"), bool):
        raise _bad("Say on or off.")
    return ["look", "shared-pages", "on" if a["on"] else "off"], [], []


def _look_description(a):
    """Propose a new description: `orch <service> profile --description=...`. It stays a proposal until the owner
    approves it in the service's admin page."""
    _actions()._only(a, ("service", "text"))
    if a.get("service") not in SERVICES:
        raise _bad("Connect this workspace first.")
    t = a.get("text")
    if not isinstance(t, str) or len(t.strip()) > MAX_DESCRIPTION or "\x00" in t or "\n" in t or "\r" in t:
        raise _bad(f"Write one line of at most {MAX_DESCRIPTION} characters.")
    return [a["service"], "profile"], [f"--description={t.strip()}"], []


LOOK_OPS = {"look.set": _look_set, "look.shared": _look_shared, "look.description": _look_description}


def forget(root: Path) -> None:
    """After a look action: the next state reads the fresh values."""
    _CACHE.pop(str(root), None)


def _s(v, n):
    return v[:n] if isinstance(v, str) else None


def _workspaces(root: Path, orch_bin: str | None) -> list[dict]:
    from .data import run_orch

    rows = run_orch(orch_bin, ["status", "--json"], root)
    here = str(root.resolve())
    out = []
    for w in rows if isinstance(rows, list) else []:
        if not (
            isinstance(w, dict) and isinstance(w.get("workspace"), str) and isinstance(w.get("name"), str)
        ):
            continue
        url = next(
            (
                a.get("url")
                for a in w.get("addons") or []
                if isinstance(a, dict) and a.get("addon") == "dashboard" and isinstance(a.get("url"), str)
            ),
            None,
        )
        if url and not re.fullmatch(r"http://(127\.0\.0\.1|localhost):[0-9]{1,5}(/[!-~]*)?", url[:200]):
            url = None
        needs = None
        path = Path(w["workspace"])
        try:
            if path.is_absolute() and path.is_dir() and (path / ".orch").is_dir():
                items = run_orch(orch_bin, ["needs", "--json"], path, timeout=3.0)
                if isinstance(items, list):
                    needs = len(items)
        except (OSError, ValueError):
            pass
        icon, color = w.get("icon"), w.get("color")
        out.append(
            {
                "name": w["name"][:60],
                "needs": needs,
                "here": w["workspace"] == here,
                "url": url[:200] if url else None,
                "icon": icon if isinstance(icon, str) and ID.fullmatch(icon) else None,
                "color": color if isinstance(color, str) and ID.fullmatch(color) else None,
            }
        )
    return out[:50]


def load_look(root: Path, orch_bin: str | None, fresh: bool = False) -> dict | None:
    """What Settings and the sidebar show about the look. None when `orch look` is not there (older core)."""
    from .data import run_orch

    key = str(root)
    hit = _CACHE.get(key)
    if hit and not fresh and time.monotonic() - hit[0] < TTL:
        return hit[1]
    show = run_orch(orch_bin, ["look", "show", "--json"], root, timeout=15.0)
    if not isinstance(show, dict) or "icon" not in show:
        _CACHE[key] = (time.monotonic(), None)
        return None
    shared = run_orch(orch_bin, ["look", "shared-pages", "--json"], root)
    services = show.get("services") if isinstance(show.get("services"), dict) else {}
    service, description, pending = None, None, None
    for name in SERVICES:
        if name in services and "error" not in (services[name] or {}):
            prof = run_orch(orch_bin, [name, "profile", "--json"], root, timeout=10.0)
            if isinstance(prof, dict):
                service = name
                description = _s(prof.get("description"), MAX_DESCRIPTION)
                p = prof.get("pending")
                pending = _s(p.get("description"), MAX_DESCRIPTION) if isinstance(p, dict) else None
                break
    out = {
        "icon": _s(show.get("icon"), 32),
        "color": _s(show.get("color"), 32),
        "set_by": show.get("set_by") if show.get("set_by") in ("agent", "human") else None,
        "shared_pages": shared.get("on")
        if isinstance(shared, dict) and isinstance(shared.get("on"), bool)
        else True,
        "service": service,
        "description": description,
        "pending": pending,
        "workspaces": _workspaces(root, orch_bin),
    }
    _CACHE[key] = (time.monotonic(), out)
    return out
