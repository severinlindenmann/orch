"""Consent is local, content addressed, and never inferred from ticket text."""

import contextvars
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from orch import addons, config, humanproof, syncgate, tickets

from . import cli, repo

manifest_cache = contextvars.ContextVar("sync_manifests", default=None)
MAX_EXT = 64  # add-on blocks per ticket (Fable B4)


def manifests():
    cached = manifest_cache.get()
    if cached is None:
        return addons.discover()
    if "value" not in cached:
        cached["value"] = addons.discover()
    return cached["value"]


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _block_ok(b):
    return (
        isinstance(b, dict)
        and isinstance(b.get("ticket"), str)
        and isinstance(b.get("addon"), str)
        and "value" in b
        and isinstance(b.get("seen", []), list)
        and all(isinstance(h, str) for h in b.get("seen", []))
        and isinstance(b.get("had", False), bool)
    )


def _load(p):
    try:
        return json.loads(p.read_bytes())
    except (ValueError, RecursionError):
        return None


def held(root, *, waiting=False):
    """Held blocks; waiting=True: only those still waiting for a person (not ignored, not settled). A file of
    any other shape (not JSON, wrong types) counts for nothing: one bad file never breaks a merge or a row."""
    folder = repo.safe(root, "run/sync/held")
    blocks = [(p, _load(p)) for p in sorted(folder.glob("*.json"))] if folder.exists() else []
    return [
        (p, b)
        for p, b in blocks
        if _block_ok(b) and not (waiting and (b.get("ignored") is True or b.get("waiting", True) is not True))
    ]


def holds(local, remote):
    """The add-on names a merge of these sides holds for a person."""
    installed = manifests()
    old, new = local.get("ext", {}), remote.get("ext", {})
    return {
        n
        for n in set(old) | set(new)
        if n != "sync" and installed.get(n, {}).get("ticket_ext_inert") is not True and old.get(n) != new.get(n)
    }


def filter_ticket(root, path, doc, local, remote):
    from .step import encoded, write

    tid = Path(path).stem
    # Fable B12: an approval is used up where it is given: `approve` writes the value into the live ticket.
    # The merge never applies a value from the store, so a later re-send of the same value is held again.
    # approved.json stays as the record the automation add-on checks.
    ignored = cli.read(root, "ignored").get(tid, {})
    installed = manifests()
    old, new = local.get("ext", {}), remote.get("ext", {})
    known = cli.read(root, "local-ext")
    # Record provenance BEFORE publishing any incoming ticket. A crash can only refuse more work.
    if tid not in known:
        known[tid] = {name: digest(value) for name, value in old.items()}
        write(root, "run/sync/local-ext.json", encoded(known))
    ext = dict(doc.get("ext", {}))
    names = set(old) | set(new)
    if len(names) > MAX_EXT:
        from .pause import Pause

        raise Pause(f"Ticket has too many add-on blocks: {path}", [path])
    # Fable B4: read the held blocks once per ticket, not once per name.
    mine = [(p, b) for p, b in held(root) if b["ticket"] == tid]
    # every name the merge produced too (it can synthesise one, e.g. {} for a deletion), so the result never
    # depends on which blocks happen to be on disk (a replay in apply must give the same ticket)
    for name in sorted(names | set(ext) | {b["addon"] for _, b in mine}):
        current = [(p, b) for p, b in mine if b["addon"] == name]
        # Fable B11: the synced bytes keep the merged value (so both machines converge); a block is what keeps
        # this machine's live ticket on its own value for every synced value it held (`seen`).
        seen = {h for _, b in current for h in b.get("seen", []) if isinstance(h, str)}
        prior = next((b for _, b in current if "had" in b), None)
        if (
            name == "sync"
            or installed.get(name, {}).get("ticket_ext_inert") is True
            or old.get(name) == new.get(name)
        ):
            for p, _ in current:
                p.unlink(missing_ok=True)  # the peer no longer proposes a change: nothing left to allow
            if name != "sync" and installed.get(name, {}).get("ticket_ext_inert") is not True:
                # Both sides agree: that value, never one the ext merge synthesised (a deletion gives {}).
                if name in old:
                    ext[name] = old[name]
                else:
                    ext.pop(name, None)
            if prior and seen and name != "sync":
                # Kept, no longer waiting: the committed copy may still hold a held value until applied.
                done = {**prior, "seen": sorted(seen), "waiting": False}
                write(root, f"run/sync/held/{tid}-{digest(done)}.json", encoded(done))
            continue
        value = new.get(name)
        block = {"ticket": tid, "addon": name, "value": value, "hash": digest(value)}
        since = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        # One current candidate per ticket/add-on; an old approval never selects an old candidate.
        for p, previous in current:
            if previous.get("hash") == block["hash"] and previous.get("waiting", True):
                since = previous.get("since", since)
            p.unlink(missing_ok=True)
        block["since"] = since
        block.update(
            had=name in old,
            local=old.get(name),
            seen=sorted(seen | {block["hash"]}),
            waiting=True,
            ignored=ignored.get(name) == block["hash"],
        )
        write(root, f"run/sync/held/{tid}-{digest(block)}.json", encoded(block))
        if name in old:
            ext[name] = old[name]
        else:
            ext.pop(name, None)
    if ext or "ext" in local:
        doc["ext"] = ext
    else:
        doc.pop("ext", None)
    if "sessions" in local:
        doc["sessions"] = local["sessions"]
    else:
        doc.pop("sessions", None)
    return doc


def approve(root, tid, addon, args):
    from .step import document, encoded, step_lock, write

    with step_lock(root), syncgate.hold(root), tickets.sync_apply(root, tid):
        candidates = [(p, b) for p, b in held(root, waiting=True) if b["ticket"] == tid and b["addon"] == addon]
        if len(candidates) != 1:
            raise repo.Refused("No single held change for this ticket and add-on")
        p, block = candidates[0]
        hashed = digest(block["value"])
        # Fable B12: Ignore and Allow are different decisions with different proofs.
        target = f"sync:{'ignore' if getattr(args, 'ignore', False) else 'allow'}:{tid}:{addon}:{hashed}"
        by = humanproof.person_by(
            root, args, "addon.act", target, no_handoff="This approval needs a person's proof over stdin."
        )
        config.require_person(by, "approve this synced change")
        if getattr(args, "ignore", False):
            ignored = cli.read(root, "ignored")
            ignored.setdefault(tid, {})[addon] = hashed
            write(root, "run/sync/ignored.json", encoded(ignored))
            write(root, str(p.relative_to(repo.safe(root, ""))), encoded({**block, "ignored": True}))
            return {"ignored": addon, "ticket": tid}
        path = f"tickets/{tid}.json"
        doc = document(path, repo.safe(root, path).read_bytes())
        ext = doc.setdefault("ext", {})
        if block["value"] is None:
            ext.pop(addon, None)
        else:
            ext[addon] = block["value"]
        document(path, encoded(doc))
        store = cli.read(root, "approved")
        store.setdefault(tid, {})[addon] = hashed
        write(root, "run/sync/approved.json", encoded(store))
        write(root, path, encoded(doc))
        p.unlink()
    return {"approved": addon, "ticket": tid}
