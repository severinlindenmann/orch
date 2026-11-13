"""Files of one ticket for the Files tab: the list (from `orch ticket artifacts --json`) and a safe read.

A file is served only from `.orch/tickets/<ticket>/artifacts/` or `.orch/tickets/<ticket>/evidence/`, read through
orch.safefile (the one hardened reader). /api/file shows text, pictures, PDF, sound and video (a page is shown
as text there); a web page is shown by `read_page` only inside a sandboxed frame without this app's privileges.
"""

from __future__ import annotations

import re
from pathlib import Path

from .data import run_orch

TID = re.compile(r"t_[a-z0-9]{6,16}")
KINDS = ("artifacts", "evidence", "files")  # files: what a phone sent to the ticket
MAX_BYTES = 2 * 1024 * 1024
MAX_PHONE = 25 * 1024 * 1024  # a voice note or photo from the phone; also a PDF, sound or video preview
MAX_DOWNLOAD = 64 * 1024 * 1024  # Download is never held to the preview limits
MAX_SHEET = 8 * 1024 * 1024  # a workbook or archive read for its table or listing
PREVIEW_ROWS = 200
MAX_NAME = 240
TEXT = {
    "txt",
    "md",
    "csv",
    "tsv",
    "json",
    "log",
    "html",
    "htm",
    "xml",
    "yml",
    "yaml",
    "toml",
    "py",
    "js",
    "css",
    "ini",
    "markdown",
    "sh",
    "ts",
    "sql",
    "jsonl",
    "cfg",
    "conf",
}
AUDIO = {
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "aac": "audio/aac",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "caf": "audio/x-caf",
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
}
VIDEO = {"webm": "video/webm", "mov": "video/quicktime", "m4v": "video/mp4", "ogv": "video/ogg"}
PDF = "application/pdf"
IMAGES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "svg": "image/svg+xml",
}
# What a page may load next to itself (a stylesheet, a script, a picture, a font, data).
PAGE_ASSETS = {
    "html": "text/html; charset=utf-8",
    "htm": "text/html; charset=utf-8",
    "css": "text/css; charset=utf-8",
    "js": "text/javascript; charset=utf-8",
    "mjs": "text/javascript; charset=utf-8",
    "json": "application/json",
    "txt": "text/plain; charset=utf-8",
    "woff": "font/woff",
    "woff2": "font/woff2",
    "ttf": "font/ttf",
    "otf": "font/otf",
    "ico": "image/x-icon",
    "mp4": "video/mp4",
    **{k: v for k, v in IMAGES.items()},
    **AUDIO,
    **VIDEO,
}
PAGE_SUBRESOURCE_DEST = ("style", "script", "image", "font", "audio", "video")
PAGE_CSP = (
    "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self' data:; media-src 'self'; connect-src 'none'; "
    "form-action 'none'; base-uri 'none'; sandbox allow-scripts"
)


def listing(root: Path, orch_bin: str | None, tid: str) -> dict:
    """{"available": bool, "files": [{name, size, mtime}]}. `available` is False when orch cannot list files."""
    rows = run_orch(orch_bin, ["ticket", "artifacts", tid, "--json"], root)
    if not isinstance(rows, list):
        return {"available": False, "files": []}
    files = []
    for r in rows[:200]:
        if (
            isinstance(r, dict)
            and isinstance(r.get("name"), str)
            and 0 < len(r["name"]) <= MAX_NAME
            and "\x00" not in r["name"]
            and isinstance(r.get("size"), int)
            and not isinstance(r.get("size"), bool)
        ):
            files.append(
                {
                    "name": r["name"],
                    "size": r["size"],
                    "mtime": r["mtime"] if isinstance(r.get("mtime"), str) else "",
                }
            )
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
    media = ext in AUDIO or ext in VIDEO or ext == "pdf"
    if not download and ext not in TEXT and ext not in IMAGES and not media:
        return nope
    big = phone or media or download
    try:
        data = safefile.read_ticket_file(
            root, tid, kind, name, MAX_DOWNLOAD if download else MAX_PHONE if big else MAX_BYTES
        )
    except safefile.TooLarge:
        return 413, b"That file is too large to show.", "text/plain", {}
    if data is None:
        return nope
    if download:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", last)[:100] or "file"
        return (
            200,
            data,
            "application/octet-stream",
            {"Content-Disposition": f'attachment; filename="{safe}"'},
        )
    if ext == "pdf":
        return 200, data, PDF, {}
    if ext in AUDIO:
        return 200, data, AUDIO[ext], {}
    if ext in VIDEO:
        return 200, data, VIDEO[ext], {}
    ctype = (
        IMAGES.get(ext) or "text/plain; charset=utf-8"
    )  # a page or a picture format that can run code is shown as text
    return 200, data, ctype, {}


def read_page(root: Path, tid: str, kind: str, name) -> tuple[int, bytes, str, dict]:
    """One file of a ticket's web page (the page and what sits next to it), served with its real type so its own
    stylesheet and script work. Always sandboxed (see PAGE_CSP): the frame cannot reach this app."""
    nope = (404, b"not found", "text/plain", {})
    try:
        from orch import safefile
    except ImportError:
        return nope
    if kind not in KINDS or not isinstance(name, str) or not name or len(name) > MAX_NAME:
        return nope
    ext = name.rsplit("/", 1)[-1].rsplit(".", 1)[-1].lower() if "." in name.rsplit("/", 1)[-1] else ""
    ctype = PAGE_ASSETS.get(ext)
    if ctype is None:
        return nope
    try:
        data = safefile.read_ticket_file(root, tid, kind, name, MAX_PHONE)
    except safefile.TooLarge:
        return 413, b"That file is too large to show.", "text/plain", {}
    if data is None:
        return nope
    # A page is only for this app's own frame. What it loads next to itself comes from the frame's opaque origin,
    # which can only be allowed by "cross-origin"; those files are inert (style, script, picture, font, media).
    return (
        200,
        data,
        ctype,
        {"Cross-Origin-Resource-Policy": "same-origin" if ext in ("html", "htm") else "cross-origin"},
    )


PREVIEW_COLS = 200
MAX_CELL_TEXT = 500


def _col(ref: str) -> int:
    """Zero-based column of a cell reference like "C7"; never loops past the preview width."""
    n = 0
    for ch in ref:
        if not ("A" <= ch <= "Z"):
            break
        n = n * 26 + ord(ch) - 64
        if n > 100_000:
            return 100_000
    return max(n - 1, 0)


def _xlsx(zf, sheet: int) -> dict:
    import xml.etree.ElementTree as ET

    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

    def read(member: str) -> bytes:
        info = zf.getinfo(member)
        if info.file_size > MAX_SHEET:
            raise ValueError("too large")
        return zf.read(member)

    wb = ET.fromstring(read("xl/workbook.xml"))
    sheets = [(s.get("name") or "Sheet", s.get(rel_ns + "id")) for s in wb.iter(ns + "sheet")]
    rels = {}
    if "xl/_rels/workbook.xml.rels" in zf.namelist():
        for r in ET.fromstring(read("xl/_rels/workbook.xml.rels")):
            rels[r.get("Id")] = r.get("Target") or ""
    strings: list[str] = []
    if "xl/sharedStrings.xml" in zf.namelist():
        for si in ET.fromstring(read("xl/sharedStrings.xml")).iter(ns + "si"):
            if len(strings) >= 100_000:
                break
            strings.append("".join(t.text or "" for t in si.iter(ns + "t"))[:MAX_CELL_TEXT])
    sheet = sheet if 0 <= sheet < len(sheets) else 0
    target = rels.get(sheets[sheet][1], f"worksheets/sheet{sheet + 1}.xml").lstrip("/")
    member = target if target.startswith("xl/") else "xl/" + target
    rows, total, width = [], 0, 0
    for row in ET.fromstring(read(member)).iter(ns + "row"):
        total += 1
        if len(rows) > PREVIEW_ROWS:  # counted, not read: the preview holds the first rows only
            continue
        cells: list[str] = []
        for c in row.iter(ns + "c"):
            idx = _col(c.get("r") or "A1")
            if idx >= PREVIEW_COLS:  # a crafted reference (XFD1, ZZZZZZ1) must not grow anything
                width = PREVIEW_COLS
                continue
            while len(cells) < idx:
                cells.append("")
            v = c.find(ns + "v")
            t = c.get("t")
            if t == "s" and v is not None and (v.text or "").isdigit() and int(v.text) < len(strings):
                val = strings[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(ns + "t"))
            else:
                val = v.text if v is not None and v.text is not None else ""
            if len(cells) == idx:
                cells.append(val[:MAX_CELL_TEXT])
        width = max(width, len(cells))
        rows.append(cells)
    columns = rows[0] if rows else []
    return {
        "sheets": [n for n, _ in sheets],
        "sheet": sheet,
        "columns": columns,
        "rows": rows[1:],
        "rowCount": max(total - 1, 0),
        "colCount": width,
    }


def info(root: Path, tid: str, kind: str, name, sheet: int = 0) -> tuple[int, dict]:
    """Facts a viewer needs that the browser cannot read itself: PDF page count, archive listing, workbook cells."""
    try:
        from orch import safefile
    except ImportError:
        return 404, {}
    if kind not in KINDS or not isinstance(name, str) or not name or len(name) > MAX_NAME:
        return 404, {}
    ext = name.rsplit(".", 1)[-1].lower() if "." in name.rsplit("/", 1)[-1] else ""
    if ext not in ("pdf", "zip", "xlsx"):
        return 404, {}
    try:
        data = safefile.read_ticket_file(root, tid, kind, name, MAX_PHONE if ext == "pdf" else MAX_SHEET)
    except safefile.TooLarge:
        return 413, {"error": "too large"}
    if data is None:
        return 404, {}
    if ext == "pdf":
        return 200, {"pages": len(re.findall(rb"/Type\s*/Page(?![s\w])", data))}
    import io
    import zipfile

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        if ext == "zip":
            infos = [i for i in zf.infolist() if not i.is_dir()]
            return 200, {
                "entries": [{"name": i.filename[:200], "size": i.file_size} for i in infos[:200]],
                "count": len(infos),
            }
        return 200, _xlsx(zf, sheet)
    except Exception:  # noqa: BLE001  a broken archive or workbook (zip, XML) is a plain "cannot be shown", never a crash
        return 422, {"error": "unreadable"}
