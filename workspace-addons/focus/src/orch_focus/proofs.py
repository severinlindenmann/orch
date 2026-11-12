"""Proof files for the Focus preview panel: GET /api/file?t=<ticket>&n=<name>&m=<mode>.

A proof file lives in `.orch/tickets/<ticket>/evidence/`. It is read ONLY through orch.safefile (the one hardened
reader: no links, no hard links, no FIFOs, folders opened one by one). This module adds no path handling of its
own: the name goes to the helper as it came. What it decides is how the bytes are labelled:

- view: at most 2 MB, as a picture, a PDF (checked for its signature) or plain text. A page is shown as text.
- page: GET /page/<ticket>/<name> (read_page below), not an /api/file mode: an HTML file as a page, with its
  relative CSS, scripts, pictures and fonts from the same folder (the URL path is the file path, so a relative
  link resolves to a sibling). Every answer carries `sandbox allow-scripts` (no same-origin: the page cannot
  reach Focus), no network (connect-src none) and no forms; the frame that shows it has the same sandbox.
- dl: any file up to 25 MB as an attachment.
- info: {name, size} for the file card.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
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
# A page and the files it loads: scripts and styles from its own folder or inline, pictures and fonts too, but no
# network calls, no forms, no frames. Not guaranteed: the page can still navigate its own frame (location, link,
# meta refresh) to a web address and put data in the URL; CSP has no navigate-to. Hence the UI wording. `sandbox allow-scripts` has no allow-same-origin: the page
# gets an opaque origin, so it cannot read Focus, its API or its storage, also when opened in a tab of its own.
PAGE = (
    "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self' data:; media-src 'self'; connect-src 'none'; form-action 'none'; frame-src 'none'; "
    "base-uri 'none'; sandbox allow-scripts; frame-ancestors 'self'"
)
# what a page may load from its folder (no JSON/text: nothing to fetch with, and no way to read a stray file)
ASSETS = {
    "html": "text/html; charset=utf-8", "htm": "text/html; charset=utf-8",
    "css": "text/css; charset=utf-8", "js": "text/javascript; charset=utf-8", "mjs": "text/javascript; charset=utf-8",
    "svg": "image/svg+xml", "ico": "image/x-icon", "avif": "image/avif",
    "woff": "font/woff", "woff2": "font/woff2", "ttf": "font/ttf", "otf": "font/otf",
    **IMAGES,
}  # fmt: skip
PDF = "default-src 'none'; frame-ancestors 'self'"


# The key in a page URL (/page/<ticket>/<key>/<file>): HMAC of the ticket id under a secret made at server start.
# Only the fenced /api/t/<ticket> answer carries it, so a foreign website cannot build a URL for <script src> or
# <link href> even when it guesses the ticket id and the file name. It changes with every start of Focus.
_PAGE_SECRET = secrets.token_bytes(32)


def page_key(tid: str) -> str:
    return hmac.new(_PAGE_SECRET, str(tid).encode(), hashlib.sha256).hexdigest()[:16]


def page_key_ok(tid: str, key: str) -> bool:
    return hmac.compare_digest(page_key(tid), str(key))


def ext_of(name: str) -> str:
    last = name.rsplit("/", 1)[-1]
    return last.rsplit(".", 1)[-1].lower() if "." in last else ""


def read(root: Path, tid, name, mode: str) -> tuple[int, bytes, str, dict]:
    """(status, body, content type, extra headers). Anything the helper refuses is a plain 404."""
    try:
        from orch import safefile
    except ImportError:  # no orch to read with: refuse, never read by hand
        return NOPE
    if not isinstance(name, str) or not name or len(name) > 240 or mode not in ("view", "dl", "info"):
        return NOPE
    ext = ext_of(name)
    if mode == "view" and ext not in IMAGES and ext not in TEXT and ext != "pdf":
        return NOPE
    try:
        data = safefile.read_ticket_file(root, tid, FOLDER, name, VIEW_MAX if mode == "view" else DL_MAX)
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
    if ext == "pdf":
        if not data.startswith(b"%PDF-"):
            return 415, b"That is not a PDF. Download it instead.", "text/plain", {}
        return 200, data, "application/pdf", {"Content-Security-Policy": PDF}
    return 200, data, IMAGES.get(ext) or "text/plain; charset=utf-8", {"Content-Security-Policy": SANDBOX}


def read_page(root: Path, tid, key, name) -> tuple[int, bytes, str, dict]:
    """One file of a page (the page itself or something it loads), for GET /page/<ticket>/<key>/<name>. The key must
    be the one of this ticket (page_key), else a plain 404. The same one
    reader as above, so `..`, links, hard links and FIFOs are refused there; the kind comes from the extension and
    only the kinds in ASSETS are served."""
    try:
        from orch import safefile
    except ImportError:
        return NOPE
    if not isinstance(tid, str) or not page_key_ok(tid, key):
        return NOPE
    ctype = ASSETS.get(ext_of(name)) if isinstance(name, str) else None
    if ctype is None:
        return NOPE
    try:
        data = safefile.read_ticket_file(root, tid, FOLDER, name, VIEW_MAX)
    except safefile.TooLarge:
        return 413, b"That file is too large to show.", "text/plain", {}
    if data is None:
        return NOPE
    # CORP cross-origin: the sandboxed page has an opaque origin, so its own CSS and scripts are cross-origin to it
    return 200, data, ctype, {"Content-Security-Policy": PAGE, "Cross-Origin-Resource-Policy": "cross-origin"}
