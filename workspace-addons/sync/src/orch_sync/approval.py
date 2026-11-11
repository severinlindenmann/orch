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


def held(root):
    folder = repo.safe(root, "run/sync/held")
    return [(p, json.loads(p.read_text())) for p in sorted(folder.glob("*.json"))] if folder.exists() else []


def filter_ticket(root, path, doc, local, remote):
    from .step import encoded, write

    tid = Path(path).stem
    approved = cli.read(root, "approved").get(tid, {})
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
    for name in names:
        if name == "sync" or installed.get(name, {}).get("ticket_ext_inert") is True:
            continue
        if old.get(name) == new.get(name):
            continue
        value = new.get(name)
        block = {"ticket": tid, "addon": name, "value": value, "hash": digest(value)}
        since = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        # One current candidate per ticket/add-on; an old approval never selects an old candidate.
        for p, previous in held(root):
            if previous.get("ticket") == tid and previous.get("addon") == name:
                if previous.get("hash") == block["hash"]:
                    since = previous.get("since", since)
                p.unlink()
        block["since"] = since
        if approved.get(name) == block["hash"]:
            if value is None:
                ext.pop(name, None)
            else:
                ext[name] = value
        else:
            if ignored.get(name) != block["hash"]:
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
        candidates = [(p, b) for p, b in held(root) if b["ticket"] == tid and b["addon"] == addon]
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
            p.unlink()
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
