"""Local sync provenance is the only authority for incoming automation blocks.

Both records are local1-signed by the core (humanproof.local_sign / local_ok) AND pinned in the guarded home
(humanproof.pin_ok: a monotonic counter and the digest of the one current body, so an older signed copy never
counts again): the sync add-on's .orch/run/sync/local-ext.json (this machine's own add-on values per ticket it
ever received) and this add-on's .orch/addons/automation/local-blocks.json (blocks it wrote here). Once sync is
on, a missing, edited, planted, rolled back or unreadable local-ext.json means no ticket's automation block is
approved (fail closed), and a ticket that shows sync's traces is never "locally created"."""

import hashlib
import json
import os
import tempfile

LOCAL_EXT_KIND = "sync-local-ext"
LOCAL_EXT_SCHEMA = "orch.sync-local-ext/1"
BLOCKS_KIND = "automation-local-blocks"
BLOCKS_SCHEMA = "orch.automation-local-blocks/1"
MAX_BYTES = 16 * 1024 * 1024


def _core():
    try:
        from orch import history, humanproof
    except ImportError:  # standalone use without orch: nothing can be verified
        return None
    return history, humanproof


def sync_on(root):
    """Is sync on (now or ever) for this workspace? Core's rule (history.sync_enabled); without the core, any
    trace of sync counts. An error counts as on (fail closed)."""
    core = _core()
    if core is None:
        return any(os.path.lexists(root / p) for p in (".orch/.git", ".orch/run/sync"))
    try:
        return core[0].sync_enabled(root)
    except Exception:  # noqa: BLE001
        return True


def _digest(block):
    return hashlib.sha256(
        json.dumps(block, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _signed(root, path, kind, schema, humanproof):
    """The record's per-ticket map when this core signed it and it is the current pinned body, else None."""
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            return None
        data = json.loads(path.read_text())
    except (OSError, ValueError, RecursionError):
        return None
    if (
        not isinstance(data, dict)
        or data.get("schema") != schema
        or not isinstance(data.get("tickets"), dict)
    ):
        return None
    body = {k: v for k, v in data.items() if k != "mac"}
    if not humanproof.local_ok(root, kind, body, data.get("mac")) or not humanproof.pin_ok(root, kind, body):
        return None
    return data["tickets"]


def allowed(root, ticket):
    try:
        block = (ticket.get("ext") or {}).get("automation")
        if block is None:
            return True
        if not sync_on(root):
            return True  # Sync was never on here: every block is this machine's.
        core = _core()
        if core is None:
            return False
        history, humanproof = core
        local = _signed(
            root, root / ".orch/run/sync/local-ext.json", LOCAL_EXT_KIND, LOCAL_EXT_SCHEMA, humanproof
        )
        if local is None:
            return False  # missing, rolled back or not this core's record: no synced value counts as approved
        tid = ticket.get("id")
        if tid not in local:
            # Locally created ticket (sync records every ticket it receives first, and the record is the pinned
            # current one), unless the ticket shows sync's own traces: then it came through sync.
            return not history.doc_shows_sync(ticket)
        # approved.json is not read: its entries are the sync add-on's signed records, which only the core can
        # check. A person's approval makes the value this machine's own: sync records it in local-ext.json.
        created = _signed(
            root, root / ".orch/addons/automation/local-blocks.json", BLOCKS_KIND, BLOCKS_SCHEMA, humanproof
        )
        entry = local[tid] if isinstance(local[tid], dict) else {}
        return _digest(block) in (entry.get("automation"), (created or {}).get(tid))
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def record_local(root, ticket, block):
    """An automation edit may extend trusted local data, never bless an unapproved incoming block."""
    if not allowed(root, ticket):
        return
    core = _core()
    if core is None:
        return
    humanproof = core[1]
    folder = root / ".orch/addons/automation"
    path = folder / "local-blocks.json"
    # A record that is not the pinned current one starts empty (it can only lose entries: refuses more).
    created = _signed(root, path, BLOCKS_KIND, BLOCKS_SCHEMA, humanproof) or {}
    created[ticket["id"]] = _digest(block)
    if humanproof.local_key(root) is None:
        return  # no key here: nothing is recorded (a synced ticket's block then stays refused)
    body = humanproof.pin_next(root, BLOCKS_KIND, {"schema": BLOCKS_SCHEMA, "tickets": created})
    mac = humanproof.local_sign(root, BLOCKS_KIND, body) if body else None
    if not mac:
        return  # no key or no usable pin: nothing is recorded
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=folder, delete=False) as f:
        json.dump({**body, "mac": mac}, f)
    os.replace(f.name, path)
