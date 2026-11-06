"""Files of one ticket for the Artifacts tab: the list (from `orch ticket artifacts --json`) and a safe read.

A file is served only from `.orch/tickets/<ticket>/artifacts/` or `.orch/tickets/<ticket>/evidence/`. No part of the
path may be a link, the file is opened with O_NOFOLLOW, and only plain text and pictures are shown (never as a page).
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from .data import run_orch

TID = re.compile(r"t_[a-z0-9]{6,16}")
KINDS = ("artifacts", "evidence")
MAX_BYTES = 2 * 1024 * 1024
MAX_NAME = 240
TEXT = {"txt", "md", "csv", "tsv", "json", "log", "html", "htm", "xml", "yml", "yaml", "toml", "py", "js", "css", "ini"}
IMAGES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


def listing(root: Path, orch_bin: str | None, tid: str) -> dict:
    """{"available": bool, "files": [{name, size, mtime}]}. `available` is False when orch cannot list files."""
    rows = run_orch(orch_bin, ["ticket", "artifacts", tid, "--json"], root)
    if not isinstance(rows, list):
        return {"available": False, "files": []}
    files = []
    for r in rows[:200]:
        if (isinstance(r, dict) and isinstance(r.get("name"), str) and 0 < len(r["name"]) <= MAX_NAME
                and "\x00" not in r["name"] and isinstance(r.get("size"), int) and not isinstance(r.get("size"), bool)):
            files.append({"name": r["name"], "size": r["size"], "mtime": r["mtime"] if isinstance(r.get("mtime"), str) else ""})
    return {"available": True, "files": files}


def preview_kind(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return "text" if ext in TEXT else "image" if ext in IMAGES else "none"


def _parts(name) -> list[str] | None:
    if not isinstance(name, str) or not name or len(name) > MAX_NAME or "\x00" in name or "\\" in name or name.startswith("/"):
        return None
    parts = name.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return None
    return parts


def read_file(root: Path, tid: str, kind: str, name, download: bool = False) -> tuple[int, bytes, str, dict]:
    """(status, body, content type, extra headers). Anything outside the rules is a plain 404."""
    nope = (404, b"not found", "text/plain", {})
    parts = _parts(name)
    if not TID.fullmatch(tid or "") or kind not in KINDS or parts is None:
        return nope
    base = str(root.resolve())
    cur = base
    for part in (".orch", "tickets", tid, kind, *parts):
        cur = os.path.join(cur, part)
        try:
            if stat.S_ISLNK(os.lstat(cur).st_mode):
                return nope
        except OSError:
            return nope
    ext = parts[-1].rsplit(".", 1)[-1].lower() if "." in parts[-1] else ""
    if not download and ext not in TEXT and ext not in IMAGES:
        return nope
    try:
        fd = os.open(cur, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return nope
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode):
            return nope
        if st.st_size > MAX_BYTES:
            return 413, b"That file is too large to show.", "text/plain", {}
        data = fh.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        return 413, b"That file is too large to show.", "text/plain", {}
    if download:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", parts[-1])[:100] or "file"
        return 200, data, "application/octet-stream", {"Content-Disposition": f'attachment; filename="{safe}"'}
    ctype = IMAGES.get(ext) or "text/plain; charset=utf-8"  # a page or a picture format that can run code is shown as text
    return 200, data, ctype, {}
