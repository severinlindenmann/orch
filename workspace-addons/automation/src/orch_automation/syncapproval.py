"""Local sync provenance is the only authority for incoming automation blocks."""

import hashlib
import json
import os
import tempfile


def allowed(root, ticket):
    try:
        folder = root / ".orch/run/sync"
        path = folder / "local-ext.json"
        if not path.exists():
            return True  # Sync has never received tickets on this machine.
        local = json.loads(path.read_text())
        tid = ticket.get("id")
        if tid not in local:
            return True  # Locally created ticket.
        block = (ticket.get("ext") or {}).get("automation")
        if block is None:
            return True
        hashed = hashlib.sha256(
            json.dumps(block, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        path = folder / "approved.json"
        approved = json.loads(path.read_text()) if path.exists() else {}
        created_path = root / ".orch/addons/automation/local-blocks.json"
        created = json.loads(created_path.read_text()) if created_path.exists() else {}
        return hashed in (
            local[tid].get("automation"),
            approved.get(tid, {}).get("automation"),
            created.get(tid),
        )
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def record_local(root, ticket, block):
    """An automation edit may extend trusted local data, never bless an unapproved incoming block."""
    if not allowed(root, ticket):
        return
    folder = root / ".orch/addons/automation"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "local-blocks.json"
    created = json.loads(path.read_text()) if path.exists() else {}
    created[ticket["id"]] = hashlib.sha256(
        json.dumps(block, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    with tempfile.NamedTemporaryFile(mode="w", dir=folder, delete=False) as f:
        json.dump(created, f)
    os.replace(f.name, path)
