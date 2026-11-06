"""Files of one ticket for the Artifacts tab: the list (from `orch ticket artifacts --json`) and a safe read.

A file is served only from `.orch/tickets/<ticket>/artifacts/` or `.orch/tickets/<ticket>/evidence/`, read through
orch.safefile (the one hardened reader), and only plain text and pictures are shown (never as a page).
"""
from __future__ import annotations

import re
from pathlib import Path

from .data import run_orch

TID = re.compile(r"t_[a-z0-9]{6,16}")
KINDS = ("artifacts", "evidence", "files")  # files: what a phone sent to the ticket
MAX_BYTES = 2 * 1024 * 1024
MAX_PHONE = 25 * 1024 * 1024  # a voice note or photo from the phone
MAX_NAME = 240
TEXT = {"txt", "md", "csv", "tsv", "json", "log", "html", "htm", "xml", "yml", "yaml", "toml", "py", "js", "css", "ini"}
AUDIO = {"m4a": "audio/mp4", "mp4": "audio/mp4", "aac": "audio/aac", "mp3": "audio/mpeg", "wav": "audio/wav", "caf": "audio/x-caf"}
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


def read_file(root: Path, tid: str, kind: str, name, download: bool = False) -> tuple[int, bytes, str, dict]:
    """(status, body, content type, extra headers). Anything outside the rules is a plain 404. The read itself is
    orch's one hardened reader (orch.safefile: no links, no hard links, no FIFOs, folders opened one by one)."""
    nope = (404, b"not found", "text/plain", {})
    try:
        from orch import safefile
    except ImportError:  # no orch to read with: refuse, never read by hand
        return nope
    if not isinstance(name, str) or not name or len(name) > MAX_NAME:
        return nope
    last = name.rsplit("/", 1)[-1]
    ext = last.rsplit(".", 1)[-1].lower() if "." in last else ""
    phone = kind == "files"
    if not download and ext not in TEXT and ext not in IMAGES and not (phone and ext in AUDIO):
        return nope
    try:
        data = safefile.read_ticket_file(root, tid, kind, name, MAX_PHONE if phone else MAX_BYTES)
    except safefile.TooLarge:
        return 413, b"That file is too large to show.", "text/plain", {}
    if data is None:
        return nope
    if download:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", last)[:100] or "file"
        return 200, data, "application/octet-stream", {"Content-Disposition": f'attachment; filename="{safe}"'}
    if phone and ext in AUDIO:
        return 200, data, AUDIO[ext], {}
    ctype = IMAGES.get(ext) or "text/plain; charset=utf-8"  # a page or a picture format that can run code is shown as text
    return 200, data, ctype, {}
