"""Proof files for the Focus preview panel: GET /api/file?t=<ticket>&n=<name>&m=<mode>.

A proof file lives in `.orch/tickets/<ticket>/evidence/`. It is read ONLY through orch.safefile (the one hardened
reader: no links, no hard links, no FIFOs, folders opened one by one). This module adds no path handling of its
own: the name goes to the helper as it came. What it decides is how the bytes are labelled:

- view: at most 2 MB, as a picture, a PDF (checked for its signature) or plain text. A page is shown as text.
- page: an HTML file as a page, but the answer carries `sandbox` (no scripts, no forms, no network) and the
  frame that shows it has an empty `sandbox` too.
- dl: any file up to 25 MB as an attachment.
- info: {name, size} for the file card.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

VIEW_MAX = 2 * 1024 * 1024
DL_MAX = 25 * 1024 * 1024
FOLDER = "evidence"
IMAGES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}
TEXT = {
    "txt", "md", "csv", "tsv", "json", "jsonl", "log", "html", "htm", "xml", "yml", "yaml", "toml", "ini", "svg",
    "py", "js", "mjs", "ts", "tsx", "jsx", "css", "sh", "sql", "rs", "go", "java", "c", "h", "cpp", "rb", "diff", "patch",
}  # fmt: skip
NOPE = (404, b"not found", "text/plain", {})
# sent with every answer of this endpoint; the page and the PDF may be framed by Focus itself
SANDBOX = "default-src 'none'; img-src 'self'; sandbox; frame-ancestors 'self'"
PAGE = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox; frame-ancestors 'self'"
PDF = "default-src 'none'; frame-ancestors 'self'"


def ext_of(name: str) -> str:
    last = name.rsplit("/", 1)[-1]
    return last.rsplit(".", 1)[-1].lower() if "." in last else ""


def read(root: Path, tid, name, mode: str) -> tuple[int, bytes, str, dict]:
    """(status, body, content type, extra headers). Anything the helper refuses is a plain 404."""
    try:
        from orch import safefile
    except ImportError:  # no orch to read with: refuse, never read by hand
        return NOPE
    if not isinstance(name, str) or not name or len(name) > 240 or mode not in ("view", "page", "dl", "info"):
        return NOPE
    ext = ext_of(name)
    if mode == "view" and ext not in IMAGES and ext not in TEXT and ext != "pdf":
        return NOPE
    if mode == "page" and ext not in ("html", "htm"):
        return NOPE
    try:
        data = safefile.read_ticket_file(
            root, tid, FOLDER, name, VIEW_MAX if mode in ("view", "page") else DL_MAX
        )
    except safefile.TooLarge:
        return 413, b"That file is too large to show. Download it instead.", "text/plain", {}
    if data is None:
        return NOPE
    last = name.rsplit("/", 1)[-1]
    if mode == "info":
        return 200, json.dumps({"name": last, "size": len(data)}).encode(), "application/json", {}
    if mode == "dl":
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", last)[:100] or "file"
        return (
            200,
            data,
            "application/octet-stream",
            {"Content-Disposition": f'attachment; filename="{safe}"', "Content-Security-Policy": SANDBOX},
        )
    if mode == "page":
        return 200, data, "text/html; charset=utf-8", {"Content-Security-Policy": PAGE}
    if ext == "pdf":
        if not data.startswith(b"%PDF-"):
            return 415, b"That is not a PDF. Download it instead.", "text/plain", {}
        return 200, data, "application/pdf", {"Content-Security-Policy": PDF}
    return 200, data, IMAGES.get(ext) or "text/plain; charset=utf-8", {"Content-Security-Policy": SANDBOX}
