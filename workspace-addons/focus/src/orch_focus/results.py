"""The newest result of a ticket for the Focus list: {name, kind, preview, at}.

It is the one the ticket's Results tab shows first (web/ticket.js renderProof: the last finished task's file
proof, else its last proof of any kind) and it reads ONLY the ticket document the list already has: no file is
opened here. `preview` is the address the page can ask /api/file for (a picture or a text file), else None.
"""

from __future__ import annotations

import re
from urllib.parse import quote

IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp", "svg"}
PICTURE_PREVIEW = {
    "png",
    "jpg",
    "jpeg",
    "webp",
}  # the tile draws these (web/proof.js); gif and svg stay a badge
PDF_EXT = {"pdf"}
TABLE_EXT = {"csv", "tsv"}
PAGE_EXT = {"html", "htm"}
DOC_EXT = {"txt", "md", "json", "jsonl", "log", "xml", "yml", "yaml", "toml", "ini", "diff", "patch"}
CODE_EXT = {
    "py",
    "js",
    "mjs",
    "ts",
    "tsx",
    "jsx",
    "css",
    "sh",
    "sql",
    "rs",
    "go",
    "java",
    "c",
    "h",
    "cpp",
    "rb",
}
_TID = re.compile(r"t_[a-z0-9]{6,16}")


def _ext(name: str) -> str:
    last = name.rsplit("/", 1)[-1]
    return last.rsplit(".", 1)[-1].lower() if "." in last else ""


def _plain(name: str) -> str:
    stem = re.sub(r"\.[^.]+$", "", name.rsplit("/", 1)[-1])
    stem = re.sub(r"[-_]+", " ", stem).strip()
    return stem[:1].upper() + stem[1:]


def _kind_and_file(tid: str, ev: dict) -> tuple[str, str | None]:
    """(kind, file name inside the ticket's evidence folder or None), like web/proof.js kindOf."""
    t = ev.get("type")
    if t in ("command", "commit"):
        return str(t), None
    if t == "note":
        return "text", None
    if t in ("pr", "url"):
        return "link", None
    prefix = f".orch/tickets/{tid}/evidence/"
    ref = str(ev.get("ref") or "")
    if t != "file" or ev.get("missing") is True or not ref.startswith(prefix) or len(ref) <= len(prefix):
        return "missing", None
    name = ref[len(prefix) :]
    e = _ext(name)
    kind = (
        "image" if e in IMAGE_EXT
        else "pdf" if e in PDF_EXT
        else "table" if e in TABLE_EXT
        else "page" if e in PAGE_EXT
        else "doc" if e in DOC_EXT
        else "code" if e in CODE_EXT
        else "other"
    )  # fmt: skip
    return kind, name


def newest_result(ticket: dict) -> dict | None:
    tid = str(ticket.get("id") or "")
    items = []
    for c in ticket.get("checklist") or []:
        if isinstance(c, dict) and c.get("done") and not c.get("wont_do"):
            items += [e for e in c.get("evidence") or [] if isinstance(e, dict)]
    if not items or not _TID.fullmatch(tid):
        return None
    files = [e for e in items if e.get("type") != "note"]
    ev = (files or items)[-1]
    kind, name = _kind_and_file(tid, ev)
    if ev.get("type") == "file":
        title = _plain(str(ev.get("ref") or "")) or "File"
    elif ev.get("title"):
        title = str(ev["title"])
    else:
        title = str(ev.get("ref") or ev.get("text") or "Result")
    preview = None
    if name is not None and (
        (kind == "image" and _ext(name) in PICTURE_PREVIEW) or (kind in ("doc", "code", "table"))
    ):
        preview = f"/api/file?t={quote(tid)}&n={quote(name)}&m=view"
    at = ev.get("at")
    return {"name": title[:120], "kind": kind, "preview": preview, "at": at if isinstance(at, str) else None}
