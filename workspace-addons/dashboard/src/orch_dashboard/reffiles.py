"""Preview only the project file named by a stored reference."""

import json
from pathlib import Path


def read(root, tid, number):
    try:
        from orch.safefile import TooLarge, open_file_ref
    except ImportError:
        return 503, b"The orch tool is not available here, so this file cannot be shown.", "text/plain"

    from .actions import TID

    refused = (404, b"This reference cannot be opened.", "text/plain")
    if not TID.fullmatch(tid) or not number.isdecimal():
        return refused
    try:
        # Safely open the ticket itself, including its parent directories.
        from orch.safefile import _read_parts

        raw = _read_parts(root, [".orch", "tickets"], [tid + ".json"], 2 * 1024 * 1024)
        refs = json.loads(raw)["refs"]
        if not isinstance(refs, list):
            return refused
        n = int(number)
        if not 1 <= n <= len(refs):
            return refused
        ref = refs[n - 1]
        if not isinstance(ref, dict):
            return refused
        if ref.get("kind") != "file" or ref.get("local"):
            return refused
        path = ref["path"]
        body = open_file_ref(root, path, 512 * 1024)
        if body is None:
            return refused
    except (OSError, ValueError, TypeError, KeyError, TooLarge):
        return refused
    return _typed(path, body)


def read_source(root, tid, name):
    """The file a task's copied proof `name` was made from, as it is on disk now (ORCH-1874: "See the current
    file" when it changed since that step). Only a `source` the ticket recorded is ever read."""
    try:
        from orch.safefile import _read_parts
        from orch.tickets import proof_source
    except ImportError:
        return 503, b"The orch tool is not available here, so this file cannot be shown.", "text/plain"

    from .actions import TID

    refused = (404, b"This file is not in the project any more.", "text/plain")
    if not TID.fullmatch(tid) or not isinstance(name, str) or not name or "\x00" in name:
        return refused
    want = f".orch/tickets/{tid}/evidence/{name}"
    try:
        raw = _read_parts(root, [".orch", "tickets"], [tid + ".json"], 2 * 1024 * 1024)
        checklist = json.loads(raw).get("checklist")
        evs = [
            e
            for c in (checklist if isinstance(checklist, list) else [])
            if isinstance(c, dict) and isinstance(c.get("evidence"), list)
            for e in c["evidence"]
            if isinstance(e, dict) and e.get("ref") == want and isinstance(e.get("source"), str)
        ]
        body = proof_source(Path(root), tid, evs[0]) if evs else None
    except Exception:  # noqa: BLE001 - any trouble reading: the plain "not there" answer
        return refused
    if body is None or len(body) > 512 * 1024:
        return refused
    return _typed(evs[0]["source"], body)


def _typed(path, body):
    ext = Path(path).suffix.lower()
    types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    if ext in types:
        return 200, body, types[ext]
    if ext in (".txt", ".md", ".markdown"):
        try:
            body.decode("utf-8")
            return 200, body, "text/plain; charset=utf-8"
        except UnicodeDecodeError:
            pass
    return 415, b"This file type can't be shown here.", "text/plain"
