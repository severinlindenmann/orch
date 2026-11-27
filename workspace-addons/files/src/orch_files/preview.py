"""What the page needs to show one file in the kit's result widget (results.js item): text for documents, notes,
code and data; rows for tables and Excel sheets; plain text for Word and PowerPoint; a file address for pictures,
PDFs, web pages, sound and video; the list of names inside a zip file. Private files show no content.

Computed previews of zip-based files (Excel, Word, PowerPoint, zip) are kept in a small cache next to the index
(`.orch/cache/files/thumbs/`), keyed by path, size and changed time, so a second look is instant. The cache has a
size cap (oldest out first) and may be deleted at any time."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote

from . import extract, index, walk

TEXT_SHOWN = 512 * 1024  # text previews hold at most this much
TABLE_ROWS = 500
SERVE_LIMIT = 4 * 1024 * 1024  # what the dashboard can pass on in one answer (its proxy limit)
CACHE_CAP = 500 * 1024 * 1024


def file_url(path: str, dl: bool = False) -> str:
    return "api/file?p=" + quote(path, safe="") + ("&dl=1" if dl else "")


def thumbs_dir(root: Path) -> Path:
    return index.cache_dir(root) / "thumbs"


def _cache_key(row: dict, mtime_ns: int | None = None) -> str:
    raw = f"{row['path']}\x00{row['size']}\x00{row['changed']}\x00{mtime_ns or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _cache_get(root: Path, key: str) -> dict | None:
    p = thumbs_dir(root) / (key + ".json")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        os.utime(p)  # used now: kept longer
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _cache_put(root: Path, key: str, item: dict, cap: int = CACHE_CAP) -> None:
    d = thumbs_dir(root)
    try:
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / (key + ".tmp")
        tmp.write_text(json.dumps(item), encoding="utf-8")
        os.replace(tmp, d / (key + ".json"))
    except OSError:
        return
    trim(root, cap)


def trim(root: Path, cap: int = CACHE_CAP) -> int:
    """Delete the oldest cached previews until the cache is under `cap` bytes. Returns how many were deleted."""
    d = thumbs_dir(root)
    try:
        files = [
            (e.stat().st_atime, e.stat().st_size, e.path) for e in os.scandir(d) if e.name.endswith(".json")
        ]
    except OSError:
        return 0
    total = sum(s for _, s, _ in files)
    gone = 0
    for _, s, p in sorted(files):
        if total <= cap:
            break
        with contextlib.suppress(OSError):
            os.remove(p)
            total -= s
            gone += 1
    return gone


def build(root: Path, path: str) -> dict | None:
    """The widget item for one indexed file, or None when the path is not in the index."""
    row = index.one(root, path)
    if row is None:
        return None
    kind, name = row["kind"], row["name"]
    ext = extract.ext_of(name)
    item = {
        "type": _widget_type(kind, ext),
        "name": row["title"],
        "size": row["size"],
        "download": None if row["private"] or row["size"] > SERVE_LIMIT else file_url(path, dl=True),
        "href": None if row["private"] or row["size"] > SERVE_LIMIT else file_url(path),
    }
    if row["size"] > SERVE_LIMIT:
        item["too_big"] = True  # the dashboard passes on at most 4 MB: such a file opens from its folder only
    if row["private"]:
        return {**item, "type": "file", "state": "ready", "private": True}
    if row["size"] == 0:
        return {**item, "state": "empty"}
    if kind in ("picture", "video", "audio", "pdf", "page"):
        if row["size"] > SERVE_LIMIT:
            return {**item, "state": "large", "too_big": True}
        return {**item, "src": file_url(path)}
    if ext == "xlsx" or kind in ("doc", "archive"):
        key = _cache_key(row, _mtime_ns(root, path))
        got = _cache_get(root, key)
        if got is not None:
            return {**item, **got}
        extra = _zip_based(root, path, row, ext, kind)
        if extra is not None and extra.get("state") != "error":
            _cache_put(root, key, extra)
        return {**item, **(extra or {"state": "error"})}
    data = walk.read_head(str(root), path, TEXT_SHOWN + 1)
    if data is None:
        return {**item, "state": "error"}
    if not extract.looks_text(data):
        return {**item, "type": "file"}
    text = extract.decode(data[:TEXT_SHOWN])
    if index.secret_in(text, root):  # the same check as the index: such a file shows by name only
        return {**item, **PRIVATE_ITEM}
    out = {**item, "text": text}
    if len(data) > TEXT_SHOWN or row["size"] > TEXT_SHOWN:
        out.update(state="large", shown=text.count("\n") or 1)
    return out


def secret_check(root: Path, row: dict, data: bytes) -> str | None:
    """None when a file may be served; "secret" when its text holds what the orch secret check flags, "unchecked"
    when it could not be read all the way through (it is then not served either). Plain text is checked over
    everything that would be sent; Office files and PDFs over every part of them."""
    ext = extract.ext_of(row["name"])
    if row["kind"] in ("video", "audio") or (row["kind"] == "archive" and ext != "zip"):
        return None
    if row["kind"] == "picture" and ext != "svg":  # a drawing is XML text and can hold a key
        return None
    if row["kind"] in ("doc", "pdf", "archive") or ext == "xlsx":
        text = extract.pdf_scan(data) if row["kind"] == "pdf" else extract.office_scan(data)
        if text is None:
            return "unchecked"
        return "secret" if index.secret_in(text, root) else None
    if not extract.looks_text(data):
        return None
    return "secret" if index.secret_in(extract.decode(data), root) else None


def _mtime_ns(root: Path, path: str) -> int | None:
    try:
        return os.lstat(os.path.join(root, *path.split("/"))).st_mtime_ns
    except OSError:
        return None


PRIVATE_ITEM = {"type": "file", "state": "ready", "private": True, "download": None, "href": None}


def _widget_type(kind: str, ext: str) -> str:
    if kind == "doc":
        return "md"
    if kind == "file":
        return "file"
    return kind


def _zip_based(root: Path, path: str, row: dict, ext: str, kind: str) -> dict | None:
    if row["size"] > extract.NAME_ONLY:
        return {"type": "file", "state": "large"}
    data = walk.read_head(str(root), path, extract.NAME_ONLY)
    if data is None:
        return {"state": "error"}
    if (ext == "xlsx" or kind == "doc") and secret_check(root, row, data):
        return dict(PRIVATE_ITEM)  # a secret in any part, or a part that cannot be read: name only
    if ext == "xlsx":
        rows, sheets = extract.xlsx_rows(data, max_rows=TABLE_ROWS + 1)
        if index.secret_in("\n".join("\t".join(r) for r in rows) + "\n" + "\n".join(sheets), root):
            return dict(PRIVATE_ITEM)
        out: dict = {"type": "table", "rows": rows[: TABLE_ROWS + 1], "sheets": sheets}
        if len(rows) > TABLE_ROWS:
            out.update(state="large", shown=TABLE_ROWS)
        return out
    if kind == "doc":
        text = extract.office_text(data, ext)
        if index.secret_in(text, root):
            return dict(PRIVATE_ITEM)
        return {"type": "text" if ext == "pptx" else "md", "text": _as_plain_md(text)}
    if ext == "zip":
        names = extract.zip_names(data)
        return {"type": "archive", "files": [[n, size_text(s)] for n, s in names]}
    return {"type": "file"}


def _as_plain_md(text: str) -> str:
    """Word text shown as a note: one paragraph per line, nothing in it read as Markdown markup."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line[:1] in "#>-*+|`" or line[:2].rstrip(".").isdigit():
            line = "\\" + line
        out.append(line)
    return "\n\n".join(out)


def size_text(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{max(1, round(n / 1024))} KB"
    return f"{n / 1048576:.1f} MB"
