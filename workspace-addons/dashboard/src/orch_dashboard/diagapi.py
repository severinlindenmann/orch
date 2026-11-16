"""The dashboard's side of problem reports (contracts/diag.md): the page's action trail (`POST /api/diag`), making a
report (`POST /api/diag/report`), opening its folder (`POST /api/diag/open`) and sending it to the connected relay
(`POST /api/diag/share`, or `share: true` on the report itself).

The trail takes ONLY the fixed `ui.*` events below, with typed, cut values: never a request or response body, a
header, a cookie, or text a person typed. Everything is written through `orch.diag` (same hider, same budgets,
`src` ui); with the debug log off nothing is written and the page is told to stop sending.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    from orch import diag
except ImportError:  # pragma: no cover - the dashboard without orch writes and makes nothing
    diag = None

MAX_TRAIL = 32 * 1024
MAX_EVENTS = 100
MAX_REPORT = 40 * 1024 * 1024  # the page snapshot plus up to 25 MB of added files as base64
TID = re.compile(r"t_[a-z0-9]{6,16}")
ADDON = re.compile(r"[a-z][a-z0-9-]{1,31}")
REF = re.compile(r"r-\d{4}-\d{4}-[A-Za-z0-9_.-]{1,40}")
_ID = re.compile(r"\b(?:ws|t|q|m|ph|wh|b|f|r|j|c)_[A-Za-z0-9]{4,}\b|\b\d{3,}\b")

# event -> {kv key: type}; int = a whole number, str = a short plain string, bool, "ago" = ms since the event
FIELDS: dict[str, dict[str, type]] = {
    "ui.error": {"kind": str, "what": str, "file": str, "line": int, "col": int},
    "ui.console_error": {"what": str, "n": int},
    "ui.fetch": {"route": str, "method": str, "status": int, "ms": int, "outcome": str},
    "ui.action": {"id": str, "route": str},
    "ui.route": {"from": str, "to": str},
    "ui.state": {"client_rev": str, "server_rev": str, "cache_age_ms": int},
    "ui.env": {"w": int, "h": int, "zoom": int, "browser": str, "assets": str, "touch": bool},
}
LEVEL = {"ui.error": "error", "ui.console_error": "warn"}
SHORT = 80


def fold(text) -> str:
    """A route or hash with ids and long numbers folded to `:id`, no query string, cut."""
    s = str(text or "").split("?", 1)[0].split("&", 1)[0]
    return _ID.sub(":id", s)[:SHORT]


def _val(kind: type, v):
    if kind is bool:
        return v if isinstance(v, bool) else None
    if kind is int:
        return v if type(v) is int and -1 <= v <= 10**9 else None
    if isinstance(v, str):
        return re.sub(r"[\x00-\x1f\x7f]+", " ", v).strip()[:SHORT]
    return None


def clean_event(raw) -> tuple[str, dict, int] | None:
    """(name, kv, ago_ms) of one acceptable event, else None. Unknown names and keys are dropped."""
    if not isinstance(raw, dict) or raw.get("ev") not in FIELDS:
        return None
    ev, kv = raw["ev"], {}
    src = raw.get("kv") if isinstance(raw.get("kv"), dict) else {}
    for key, kind in FIELDS[ev].items():
        v = _val(kind, src.get(key))
        if v is None:
            continue
        if key in ("route", "from", "to"):
            v = fold(v)
        elif key == "file":
            v = v.split("?", 1)[0].rsplit("/", 1)[-1][:60]
        kv[key] = v
    ago = raw.get("ago")
    return ev, kv, ago if type(ago) is int and 0 <= ago <= 600_000 else 0


def accept_trail(root: Path, body) -> dict:
    """Write the events of one batch; the answer says whether the log is on (the page stops sending when not)."""
    if diag is None:
        return {"enabled": False}
    diag.forget_settings()  # the setting is changed by another process (the CLI): read it fresh, not from the 5 s cache
    if not diag.enabled(root):
        return {"enabled": False}
    events = body.get("events") if isinstance(body, dict) else None
    if not isinstance(events, list):
        return {"enabled": True, "written": 0}
    n = 0
    for raw in events[:MAX_EVENTS]:
        got = clean_event(raw)
        if got is None:
            continue
        ev, kv, ago = got
        scope = raw.get("ticket") if isinstance(raw, dict) else None
        if isinstance(scope, str) and TID.fullmatch(scope):
            kv["ticket"] = scope
        if ago:
            kv["ago_ms"] = ago
        diag.log_as("ui", ev, LEVEL.get(ev, "debug"), root=root, **kv)
        n += 1
    return {"enabled": True, "written": n}


def make_report(root: Path, body) -> tuple[int, dict | str]:
    """(status, answer): the report folder made by `orch diag report`'s own code, plus the page snapshot."""
    if diag is None:
        return 503, "Reports are not available here."
    if not isinstance(body, dict) or set(body) - {
        "ticket",
        "addon",
        "note",
        "expected",
        "content",
        "page",
        "more",
        "files",
        "share",
    }:
        return 400, "That request could not be read."
    ticket, addon = body.get("ticket"), body.get("addon")
    if ticket is not None and not (isinstance(ticket, str) and TID.fullmatch(ticket)):
        return 400, "That is not a ticket."
    if addon is not None and not (isinstance(addon, str) and ADDON.fullmatch(addon)):
        return 400, "That is not an add-on."
    texts = {}
    for k in ("note", "expected"):
        v = body.get(k)
        if v is not None and not isinstance(v, str):
            return 400, "That request could not be read."
        texts[k] = (v or "").strip()[:600] or None
    more = body.get("more")
    if more is not None and not isinstance(more, str):
        return 400, "That request could not be read."
    files = []
    raw_files = body.get("files") or []
    if not isinstance(raw_files, list) or len(raw_files) > 10:
        return 400, "A report takes at most 10 added files."
    for f in raw_files:
        if not (isinstance(f, dict) and isinstance(f.get("name"), str) and isinstance(f.get("data"), str)):
            return 400, "That request could not be read."
        try:
            files.append((f["name"], base64.b64decode(f["data"], validate=True)))
        except ValueError:
            return 400, "An added file could not be read."
    if body.get("share") not in (None, True, False):
        return 400, "That request could not be read."
    content = body.get("content") is not False
    page = body.get("page")
    if page is not None and not isinstance(page, str):
        return 400, "That request could not be read."
    from orch import diag_report
    from orch.errors import Refused

    try:
        made = diag_report.make(
            root,
            ticket=ticket,
            addon=None if ticket else addon,
            note=texts["note"],
            expected=texts["expected"],
            content=content,
            page=page if page and content else None,
            more=more,
            files=files,
        )
    except Refused as e:
        return 422, str(e)[:300]
    except Exception as e:  # noqa: BLE001 - a plain answer; the cause goes to the debug log
        diag.error("diag.report_failed", e, root=root)
        return 500, "The report could not be made. Please try again."
    diag.log(
        "diag.report_made",
        "info",
        root=root,
        ref=made["ref"],
        scope="ticket" if ticket else "add-on" if addon else "workspace",
        content=content,
        page=bool(page and content),
    )
    rows = [
        {"verdict": c["verdict"], "name": str(c["name"])[:60], "fact": str(c["fact"])[:300]}
        for c in made["checks"]
    ]
    out = {"ref": made["ref"], "path": made["path"], "problems": made["problems"], "checks": rows}
    if body.get("share") is True:  # the person ticked it in the same dialog; the report stays here either way
        code, res = share_report(root, {"ref": made["ref"]})
        out.update(res if code == 200 else {"share_error": res})
    return 200, out


def share_report(root: Path, body) -> tuple[int, dict | str]:
    """Send one report of this workspace to the connected relay (`orch relay problem share`'s own code)."""
    ref = body.get("ref") if isinstance(body, dict) and set(body) == {"ref"} else None
    if not isinstance(ref, str) or not REF.fullmatch(ref):
        return 400, "That is not a report."
    from orch import relay_problems
    from orch.errors import Refused

    try:
        sent = relay_problems.share(root, ref)
    except Refused as e:
        return 422, str(e)[:300]
    except Exception as e:  # noqa: BLE001 - a plain answer; the cause goes to the debug log
        if diag:
            diag.error("diag.report_failed", e, root=root)
        return 500, "The report could not be sent. Please try again."
    if diag:
        diag.log("diag.report_shared", "info", root=root, ref=ref)
    return 200, {"shared": {"to": str(sent["to"])[:120]}}


def open_folder(root: Path, body) -> tuple[int, dict | str]:
    """Show a report's folder in the computer's file manager (a folder this module's reports made, no links)."""
    ref = body.get("ref") if isinstance(body, dict) and set(body) == {"ref"} else None
    if not isinstance(ref, str) or not REF.fullmatch(ref):
        return 400, "That is not a report."
    folder = root / ".orch" / "diag" / "reports" / ref
    if any(p.is_symlink() for p in (root / ".orch", root / ".orch" / "diag", folder.parent, folder)):
        return 400, "That is not a report."
    if not folder.is_dir():
        return 404, "That report is gone."
    cmd = (
        ["open", str(folder)]
        if sys.platform == "darwin"
        else ["explorer", str(folder)]
        if sys.platform == "win32"
        else ["xdg-open", str(folder)]
    )
    try:
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        return 200, {"opened": True, "path": str(folder)}
    except OSError:
        return 200, {"opened": False, "path": str(folder)}


def parse_json(raw: bytes):
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        return None
