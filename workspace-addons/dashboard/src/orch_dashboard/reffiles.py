"""Preview only the project file named by a stored reference."""

import json
from pathlib import Path


def read(root, tid, number):
    from orch.safefile import TooLarge, open_file_ref

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
