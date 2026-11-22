"""Local sync provenance is the only authority for incoming automation blocks.

Two plain records: the sync add-on's .orch/run/sync/local-ext.json (this machine's own add-on values per ticket it
ever received) and this add-on's .orch/addons/automation/local-blocks.json (blocks it wrote here). Old files that
still carry mac or counter fields load as before (those fields are ignored). Once sync is on, a missing or
unreadable local-ext.json means no ticket's automation block is approved (fail closed), and a ticket that shows
sync's traces is never "locally created"."""

import hashlib
import json
import os
import tempfile

LOCAL_EXT_SCHEMA = "orch.sync-local-ext/1"
BLOCKS_SCHEMA = "orch.automation-local-blocks/1"
MAX_BYTES = 16 * 1024 * 1024


def _core():
    try:
        from orch import history
    except ImportError:  # standalone use without orch: nothing can be checked
        return None
    return history


def sync_on(root):
    """Is sync on (now or ever) for this workspace? Core's rule (history.sync_enabled); without the core, any
    trace of sync counts. An error counts as on (fail closed)."""
    core = _core()
    if core is None:
        return any(os.path.lexists(root / p) for p in (".orch/.git", ".orch/run/sync"))
    try:
        return core.sync_enabled(root)
    except Exception:  # noqa: BLE001
        return True


def _digest(block):
    return hashlib.sha256(
        json.dumps(block, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _record(path, schema):
    """The record's per-ticket map when the file is a record of this schema, else None."""
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
        history = core
        tid = ticket.get("id")
        # This machine's own record: a block this machine wrote (a schedule made here, or one a person
        # allowed) is allowed by that record alone. It only ever names exact blocks written here; the sync
        # folder merely existing says nothing against it.
        created = _record(root / ".orch/addons/automation/local-blocks.json", BLOCKS_SCHEMA)
        if created and isinstance(tid, str) and created.get(tid) == _digest(block):
            return True
        local = _record(root / ".orch/run/sync/local-ext.json", LOCAL_EXT_SCHEMA)
        if local is None:
            return False  # missing or unreadable: no synced value counts as allowed
        if tid not in local:
            # Locally created ticket (sync records every ticket it receives first), unless the ticket shows sync's own traces: then it came through sync.
            return not history.doc_shows_sync(ticket)
        # approved.json is not read: a person's choice makes the value this machine's own, and sync records it
        # in local-ext.json.
        entry = local[tid] if isinstance(local[tid], dict) else {}
        return _digest(block) == entry.get("automation")
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def allow_key(ticket):
    """A short key for exactly this ticket's current automation block: what a person confirms with
    `orch automation allow <ticket> --key <key>`. Any change to the block gives a new key."""
    block = (ticket.get("ext") or {}).get("automation")
    return hashlib.sha256(f"{ticket.get('id')}:{_digest(block)}".encode()).hexdigest()[:12]


def allow_here(root, ticket, given_key):
    """A person's yes on this computer for exactly the block they were shown (the key still matches): the block is
    recorded as this machine's own, as if it had been made here. Works whether or not sync holds it."""
    block = (ticket.get("ext") or {}).get("automation")
    if block is None:
        raise ValueError("This ticket has no repeat or wake-up to allow.")
    if not isinstance(given_key, str) or given_key.strip().lower() != allow_key(ticket):
        name = ticket.get("key") or ticket.get("id")
        raise ValueError(
            "The repeat changed since that key was made. Look at it on the ticket again; to allow what it is now, "
            f"run: orch automation allow {name} --key {allow_key(ticket)}"
        )
    _write_blocks(root, ticket["id"], block)


def _write_blocks(root, tid, block):
    folder = root / ".orch/addons/automation"
    path = folder / "local-blocks.json"
    created = _record(path, BLOCKS_SCHEMA) or {}
    created[tid] = _digest(block)
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=folder, delete=False) as f:
        json.dump({"schema": BLOCKS_SCHEMA, "tickets": created}, f)
    os.replace(f.name, path)


def record_local(root, ticket, block):
    """An automation edit may extend trusted local data, never bless an unapproved incoming block."""
    if not allowed(root, ticket):
        return
    _write_blocks(root, ticket["id"], block)
