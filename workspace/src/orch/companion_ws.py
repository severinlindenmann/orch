"""The workspaces on this computer for orch Companion (ORCH-1722): a list, an additive start and the
"Start with my Mac" switch.

orch Companion (the Mac menu bar app) never reads orch's files and never starts or stops anything itself:
it runs `orch workspace companion ... --json` and shows the answer. Everything it may see is in this
module, so what leaves orch is decided here:

- Only workspaces the person set up on THIS computer: a consent record whose workspace id still matches the
  folder's own `.orch/.local-id` (that id is random, gitignored and never synced: a moved, copied or replaced
  folder does not inherit the switch or the listing).
- Per workspace only: id, name, path, state, the dashboard link (127.0.0.1/localhost only), the switch and
  whether the folder sits where macOS may block background jobs. No environment, no pid, no ticket text, no
  add-on error text (errors are fixed codes with orch's own plain line).
- A start is additive: it starts only the background add-ons that are not running and never stops, restarts or
  retires anything (services.start(..., retire=False)).
- The switch lives in ORCH_HOME/start-with-mac.json (this computer only). Off by default. The login start runs
  once per boot of the computer, re-reads the switch right before each workspace and never stops anything.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from orch import addons, config, services
from orch.errors import Refused

V = 1
ID_RE = re.compile(r"^[0-9a-f]{32}$")
# Folders macOS guards with its privacy rules: a background job started there may be refused or ended.
PROTECTED = ("Documents", "Desktop", "Downloads", "Library/Mobile Documents")

MESSAGES = {
    "unknown_workspace": "This workspace is not set up on this computer any more.",
    "moved": "This workspace folder changed. Open it in orch once, then switch it on again.",
    "nothing_to_run": "Nothing in this workspace runs in the background.",
    "did_not_start": "Some parts did not start. Open the workspace folder in Terminal and run: orch start",
    "busy": "orch is busy starting or stopping something. Try again in a minute.",
    "no_boot": "orch could not tell when this computer started, so it started nothing by itself.",
    "failed": "orch could not do this. Open Terminal and run: orch doctor",
}


def _path() -> Path:
    return addons.home() / "start-with-mac.json"


def _load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"v": V, "on": {}}
    if not isinstance(data, dict):
        return {"v": V, "on": {}}
    on = data.get("on")
    out = {
        "v": V,
        "on": {
            k: v
            for k, v in (on.items() if isinstance(on, dict) else [])
            if isinstance(k, str) and ID_RE.match(k) and isinstance(v, str)
        },
    }
    if isinstance(data.get("last_boot"), int):
        out["last_boot"] = data["last_boot"]
    return out


def _save(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, p)


def _known() -> dict[str, Path]:
    """{workspace id: folder} of every workspace set up here whose folder still carries that id."""
    out: dict[str, Path] = {}
    for rec in addons._consents():
        wid, w = rec.get("workspace_id"), rec.get("workspace")
        if not (isinstance(wid, str) and ID_RE.match(wid) and isinstance(w, str)) or wid in out:
            continue
        p = Path(w)
        try:
            if p.is_absolute() and (p / ".orch").is_dir() and addons.read_local_id(p) == wid:
                out[wid] = p.resolve()
        except OSError:
            continue
    return out


def protected(p: Path) -> bool:
    try:
        rel = p.resolve().relative_to(Path.home().resolve())
    except (ValueError, OSError):
        return False
    return any(rel.as_posix() == f or rel.as_posix().startswith(f + "/") for f in PROTECTED)


def _state(root: Path, alive: list[dict]) -> tuple[str, str | None]:
    """(running | partly | stopped | nothing_to_run, dashboard link or None). An add-on that is off on purpose
    (its own idle file) counts as fine."""
    try:
        svc = services._services(root)
    except Exception:  # a broken add-on manifest must not hide the other workspaces
        return "unknown", None
    if not svc:
        return "nothing_to_run", None
    mine = {e["addon"]: e for e in alive if e["workspace"] == str(root)}
    up = [n for n in svc if n in mine]
    fine = [n for n in svc if n in mine or services._idle(root, n)]
    url = services.local_url(mine["dashboard"].get("url")) if "dashboard" in mine else None
    if not up:
        return "stopped", None
    return ("running" if len(fine) == len(svc) else "partly"), url


def listing() -> dict:
    data = _load()
    alive = services.running()
    rows = []
    for wid, p in _known().items():
        state, url = _state(p, alive)
        rows.append(
            {
                "id": wid,
                "name": services._printable(config.workspace_name(p) or p.name)[:80],
                "path": str(p),
                "state": state,
                "dashboard_url": url,
                "start_with_mac": data["on"].get(wid) == str(p),
                "protected_folder": protected(p),
            }
        )
    rows.sort(key=lambda r: (r["name"].lower(), r["path"]))
    return {"v": V, "ok": True, "workspaces": rows}


def _err(code: str, **extra) -> dict:
    return {"v": V, "ok": False, "error": code, "message": MESSAGES[code], **extra}


def _find(wid: str) -> Path | None:
    return _known().get(wid) if ID_RE.match(wid or "") else None


def start(wid: str, switched_on_only: bool = False) -> dict:
    """Start what is not running in one workspace; never stops anything. switched_on_only (the login start):
    the switch is read again inside the lock, so one turned off while this waited starts nothing."""
    root = _find(wid)
    if root is None:
        return _err("unknown_workspace", id=wid)
    try:
        with services.locked(timeout=30):
            if switched_on_only and _load()["on"].get(wid) != str(root):
                return {"v": V, "ok": True, "id": wid, "started": [], "skipped": "switched_off"}
            svc = services._services(root)
            if not svc:
                return _err("nothing_to_run", id=wid)
            running = {e["addon"] for e in services.running() if e["workspace"] == str(root)}
            missing = {n for n in svc if n not in running and not services._idle(root, n)}
            rows = services.start(root, only=missing, retire=False) if missing else []
    except Refused:
        return _err("busy", id=wid)
    failed = sorted(r["addon"] for r in rows if r.get("error") or not (r.get("running") or r.get("idle")))
    started = sorted(r["addon"] for r in rows if r.get("running"))
    if failed:
        return _err("did_not_start", id=wid, started=started, failed=failed)
    return {"v": V, "ok": True, "id": wid, "started": started}


def switch(wid: str, on: bool) -> dict:
    """Turn "Start with my Mac" on or off for one workspace. Off never stops it."""
    root = _find(wid)
    if root is None and on:
        return _err("unknown_workspace", id=wid)
    try:
        with services.locked(timeout=30):  # the same lock as the login start: no lost update either way
            data = _load()
            if on:
                data["on"][wid] = str(root)
            else:
                data["on"].pop(wid, None)
            _save(data)
    except Refused:
        return _err("busy", id=wid)
    return {"v": V, "ok": True, "id": wid, "start_with_mac": on}


def boot_time() -> int | None:
    """When this computer last started (seconds), or None when it cannot be told."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(
                ["/usr/sbin/sysctl", "-n", "kern.boottime"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                stdin=subprocess.DEVNULL,
            ).stdout
            m = re.search(r"sec = (\d+)", out)
            return int(m.group(1)) if m else None
        if sys.platform.startswith("linux"):
            for line in Path("/proc/stat").read_text(encoding="ascii").splitlines():
                if line.startswith("btime "):
                    return int(line.split()[1])
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return None


def at_login() -> dict:
    """Start every switched-on workspace once per boot. A second call in the same boot (orch Companion
    restarted or updated) starts nothing."""
    boot = boot_time()
    if boot is None:  # fail closed: without a boot to compare, every Companion start would start them again
        return _err("no_boot")
    try:
        with services.locked(timeout=30):
            data = _load()
            if data.get("last_boot") == boot:
                return {"v": V, "ok": True, "already": True, "results": []}
            data["last_boot"] = boot
            _save(data)
    except Refused:
        return _err("busy")
    results = []
    for wid in list(_load()["on"]):
        cur = _load()["on"].get(wid)  # read again right before each start: switched off meanwhile = skipped
        if cur is None:
            continue
        root = _find(wid)
        if root is None or str(root) != cur:
            results.append(_err("moved", id=wid))
            continue
        results.append(start(wid, switched_on_only=True))
    return {"v": V, "ok": all(r.get("ok") for r in results), "already": False, "results": results}
