"""The person's own Files data: starred files and when they last looked (`.orch/addons/files/state.json`,
gitignored, on this computer only)."""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from pathlib import Path

VISIT_GAP = 600  # a page opened again within 10 minutes is the same visit
MAX_STARS = 500
_LOCK = threading.Lock()


def _file(root: Path) -> Path:
    return Path(root) / ".orch" / "addons" / "files" / "state.json"


def load(root: Path) -> dict:
    try:
        d = json.loads(_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    stars = (
        [s for s in d.get("stars", []) if isinstance(s, str)][:MAX_STARS]
        if isinstance(d.get("stars"), list)
        else []
    )
    num = lambda v: float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0
    return {"stars": stars, "seen_at": num(d.get("seen_at")), "prev_seen": num(d.get("prev_seen"))}


def _save(root: Path, d: dict) -> None:
    f = _file(root)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f".state-{os.getpid()}-{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    os.replace(tmp, f)


def page_opened(root: Path, now: float | None = None) -> dict:
    """The page was opened: a new visit moves the last visit's time to prev_seen ("New for you" starts there)."""
    now = now or time.time()
    with _LOCK:
        d = load(root)
        if now - d["seen_at"] > VISIT_GAP:
            d["prev_seen"] = d["seen_at"] or now
        d["seen_at"] = now
        with contextlib.suppress(OSError):
            _save(root, d)
        return d


def star(root: Path, path: str, on: bool) -> list[str]:
    with _LOCK:
        d = load(root)
        stars = [s for s in d["stars"] if s != path]
        if on:
            stars.insert(0, path)
        d["stars"] = stars[:MAX_STARS]
        _save(root, d)
        return d["stars"]
