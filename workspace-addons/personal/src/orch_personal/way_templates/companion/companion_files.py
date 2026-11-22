"""Read what orch Companion writes in its own folder; the only thing written there is this workspace's wanted file.

~/Library/Application Support/orch Companion/now.json        {"v":1,"state":"inactive|idle|call",...}
~/Library/Application Support/orch Companion/wanted/<id>.json  renewed on each look; Companion watches for calls
                                                              only while one is younger than 2 minutes
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from datetime import datetime
from pathlib import Path

STALE = 45  # seconds: Companion writes at least every 15 s while it runs
MAX_READ = 4096
STATES = ("inactive", "idle", "call")


def home() -> Path:
    return (
        Path(os.environ.get("HOME", str(Path.home()))) / "Library" / "Application Support" / "orch Companion"
    )


def _age(iso: str) -> float | None:
    try:
        return time.time() - datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError):
        return None


def read_now() -> dict:
    """Companion's state, checked: {"state": "missing"|"unavailable"|"inactive"|"idle"|"call", ...}."""
    base = home()
    if not base.is_dir() or base.is_symlink():
        return {"state": "missing"}
    p = base / "now.json"
    try:
        st = os.lstat(p)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_READ:
            return {"state": "unavailable"}
        with open(p, "rb") as f:
            data = json.loads(f.read(MAX_READ).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {"state": "unavailable"}
    if not isinstance(data, dict) or data.get("v") != 1 or data.get("state") not in STATES:
        return {"state": "unavailable"}
    age = _age(data.get("updated"))
    if age is None or age > STALE:
        return {"state": "unavailable"}
    out = {
        "state": data["state"],
        "updated": data["updated"],
        "instance": str(data.get("instance") or "")[:16],
    }
    if data["state"] == "call":
        app, since = data.get("app"), data.get("observed_since")
        if not isinstance(app, str) or not app or len(app) > 40 or _age(since) is None:
            return {"state": "unavailable"}
        out.update(app=app, since=since)
    return out


def want() -> None:
    """Tell Companion this workspace wants calls (one small file, renewed on each look)."""
    base = home()
    if not base.is_dir() or base.is_symlink():
        return
    folder = base / "wanted"
    if folder.is_symlink():
        return
    folder.mkdir(mode=0o700, exist_ok=True)
    who = hashlib.sha256(str(Path(__file__).resolve().parent).encode()).hexdigest()[:16]
    p = folder / f"{who}.json"
    tmp = folder / f".{who}.part"
    tmp.write_text(json.dumps({"v": 1, "jobs": ["calls"]}))
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)
