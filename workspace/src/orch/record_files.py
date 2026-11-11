"""`files` on step events (activity.md, Files): workspace-relative POSIX paths, display only.

`file_ok` is the one shape check (the writer re-checks every entry with it); `workspace_file` is the producer
normalisation shared by the collectors and the hook entry: a path outside the workspace is dropped (None).
"""

import posixpath
import re
import unicodedata
from pathlib import Path
from typing import Any

MAX_FILES = 8
MAX_LEN = 260
_BAD = re.compile(r"[\x00-\x1f\x7f\\]")
_DRIVE = re.compile(r"[A-Za-z]:")


def file_ok(value: Any) -> bool:
    """1..260 chars, NFC, no leading `/`, no `..` segment, no backslash, drive letter or control character."""
    return (
        isinstance(value, str)
        and 1 <= len(value) <= MAX_LEN
        and unicodedata.is_normalized("NFC", value)
        and not value.startswith("/")
        and not _DRIVE.match(value)
        and not _BAD.search(value)
        and ".." not in value.split("/")
    )


def _roots(root: Any) -> list[str]:
    if not isinstance(root, (str, Path)) or not str(root).startswith("/"):
        return []
    found = [posixpath.normpath(str(root))]
    try:
        real = posixpath.normpath(str(Path(root).resolve()))
    except (OSError, RuntimeError, ValueError):
        real = found[0]
    return found + ([real] if real != found[0] else [])


def workspace_file(path: Any, root: Any) -> str | None:
    """`path` as a workspace-relative POSIX path, or None (empty, outside the workspace, the root itself, or
    a shape the record does not take). An absolute path needs `root`; a relative one is relative to it."""
    if not isinstance(path, str) or not path or "\\" in path or "\x00" in path:
        return None
    path = unicodedata.normalize("NFC", path)
    if path.startswith("/"):
        rel = None
        normal = posixpath.normpath(path)
        for base in _roots(root):
            base = unicodedata.normalize("NFC", base)
            prefix = base.rstrip("/") + "/"
            if normal.startswith(prefix):
                rel = normal[len(prefix) :]
                break
        if rel is None:
            return None
    else:
        rel = posixpath.normpath(path)
    if rel in ("", ".") or rel == ".." or rel.startswith("../"):
        return None
    return rel if file_ok(rel) else None


def workspace_files(paths: Any, root: Any) -> list[str]:
    """Normalise a producer's list: drop what is outside or malformed, keep order, no repeats, at most 8."""
    out: list[str] = []
    for path in paths if isinstance(paths, (list, tuple)) else []:
        rel = workspace_file(path, root)
        if rel is not None and rel not in out:
            out.append(rel)
            if len(out) == MAX_FILES:
                break
    return out
