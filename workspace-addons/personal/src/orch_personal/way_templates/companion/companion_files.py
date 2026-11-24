"""Read what orch Companion writes in its own folder; the only thing written there is this workspace's wanted file.

~/Library/Application Support/orch Companion/now.json        {"v":1,"state":"inactive|idle|call",...}
~/Library/Application Support/orch Companion/wanted/<id>.json  renewed on each look; Companion watches for calls
                                                              only while one is younger than 2 minutes
    {"v": 1, "jobs": ["calls"], "service": {"url", "token"}, "name": "Personal"}
                                                              service: where Companion sends this workspace's
                                                              recordings (our transcription service), when set;
                                                              name: the workspace's name, for "Which workspace gets
                                                              this call?" after each call (ORCH-1269)
~/Library/Application Support/orch Companion/recordings/<id>/pick.json  {"v":1,"for":[<id>..],"at"}: the workspaces
                                                              the person picked after the call
"""

from __future__ import annotations

import contextlib
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
    try:  # the Mac's own python3 (3.9) reads no "Z"
        return (
            time.time()
            - datetime.fromisoformat(iso[:-1] + "+00:00" if iso.endswith("Z") else iso).timestamp()
        )
    except (AttributeError, TypeError, ValueError):
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
        consent = data.get("consent")
        out.update(
            app=app, since=since, consent=consent if consent in ("asked", "agreed", "declined") else "asked"
        )
        out["may_record"] = data.get("may_record") is True and out["consent"] == "agreed"
        out["recording"] = data.get("recording") is True and out["may_record"]
        rec_since = data.get("recording_since")
        if out["recording"] and isinstance(rec_since, str) and _age(rec_since) is not None:
            out["recording_since"] = rec_since[:32]
    tp = data.get("transcript_problem")
    if isinstance(tp, str) and tp.strip():
        out["transcript_problem"] = tp.strip()[:300]
    return out


def _service(svc) -> dict | None:
    if not isinstance(svc, dict):
        return None
    url, token = svc.get("url"), svc.get("token")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")) or len(url) > 300:
        return None
    if not isinstance(token, str) or not token.startswith("ort_") or len(token) != 47:
        return None
    return {"url": url, "token": token}


def me() -> str:
    """This workspace's name in Companion's folder (the same for every look from this way in)."""
    return hashlib.sha256(str(Path(__file__).resolve().parent).encode()).hexdigest()[:16]


def _name(v) -> str | None:
    if not isinstance(v, str):
        return None
    v = " ".join("".join(c for c in v if c.isprintable()).split())[:40]
    return v or None


def want(service=None, name=None) -> None:
    """Tell Companion this workspace wants calls (one small file, renewed on each look), where to upload its
    recordings when a transcription service is set, and the workspace's name (kept from the last look when
    none is given, as in the self-check)."""
    base = home()
    if not base.is_dir() or base.is_symlink():
        return
    folder = base / "wanted"
    if folder.is_symlink():
        return
    folder.mkdir(mode=0o700, exist_ok=True)
    who = me()
    p = folder / f"{who}.json"
    tmp = folder / f".{who}.part"
    data = {"v": 1, "jobs": ["calls"]}
    svc = _service(service)
    if svc:
        data["service"] = svc
    name = _name(name)
    if not name:
        with contextlib.suppress(OSError, ValueError, AttributeError):
            st = os.lstat(p)
            if stat.S_ISREG(st.st_mode) and st.st_size <= MAX_READ:
                name = _name(json.loads(p.read_text()).get("name"))
    if name:
        data["name"] = name
    with contextlib.suppress(FileNotFoundError):
        tmp.unlink()
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # the key is never readable by others
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(data))
    os.replace(tmp, p)
