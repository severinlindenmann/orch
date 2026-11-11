"""Consent is local, content addressed, and never inferred from ticket text."""

import contextvars
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from orch import addons, config, humanproof, syncgate, tickets

from . import cli, records, repo

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


HELD_KIND = "sync-held"
MAX_HELD = 512  # held add-on changes in all tickets together (Opus hard3 #5): more pauses sync
_TID = re.compile(r"t_[a-z0-9]{6,16}")


def _block_ok(root, tid, data):
    """A held block this core wrote (local1 MAC over the whole block) for exactly ticket `tid`."""
    if not isinstance(data, dict) or data.get("ticket") != tid or not isinstance(data.get("addon"), str):
        return False
    body = {k: v for k, v in data.items() if k != "mac"}
    return humanproof.local_ok(root, HELD_KIND, body, data.get("mac"))


def held(root, tid=None):
    """The held add-on changes this core wrote: of one ticket (its files only, never a scan of every block),
    or of all. A planted, edited or unreadable file is no held change (it is removed: it can only be stale)."""
    folder = repo.safe(root, "run/sync/held")
    if not folder.exists():
        return []
    if tid is not None and not _TID.fullmatch(str(tid)):
        return []
    out = []
    for p in sorted(folder.glob(f"{tid}-*.json" if tid else "t_*.json")):
        owner = p.name.split("-", 1)[0]
        try:
            data = json.loads(p.read_text()) if p.stat().st_size <= 1024 * 1024 else None
        except (OSError, ValueError, RecursionError):
            data = None
        if _block_ok(root, owner, data):
            out.append((p, {k: v for k, v in data.items() if k != "mac"}))
        else:
            p.unlink(missing_ok=True)
    return out


def _held_count(root):
    folder = repo.safe(root, "run/sync/held")
    return sum(1 for _ in folder.glob("t_*.json")) if folder.exists() else 0


def filter_ticket(root, path, doc, local, remote):
    from .step import encoded, write

    tid = Path(path).stem
    ignored = cli.read(root, "ignored").get(tid, {})
    ignored = ignored if isinstance(ignored, dict) else {}
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
    current = held(root, tid)  # read once for this ticket
    # a name with a waiting candidate is looked at too: when neither side has it any more, the candidate goes
    for name in sorted(names | {b["addon"] for _, b in current}):
        if name == "sync" or installed.get(name, {}).get("ticket_ext_inert") is True:
            continue
        candidates = [(p, b) for p, b in current if b.get("addon") == name]
        if old.get(name) == new.get(name):
            for p, _ in candidates:  # #540: the peer went back to this machine's value: nothing waits now
                p.unlink(missing_ok=True)
            continue
        value = new.get(name)
        block = {"ticket": tid, "addon": name, "value": value, "hash": digest(value)}
        since = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        # One current candidate per ticket/add-on; an older candidate is gone.
        for p, previous in candidates:
            if previous.get("hash") == block["hash"]:
                since = previous.get("since", since)
            p.unlink(missing_ok=True)
        block["since"] = since
        # Develop's model: a peer's value never enters this machine's ticket without a person (approve writes
        # it); an approval is never replayed by a merge (B12/#540). The ignored row needs a signed record.
        if not records.ok(root, "ignore", f"{tid}:{name}:{block['hash']}", ignored.get(name)):
            if _held_count(root) >= MAX_HELD:
                from .pause import Pause

                raise Pause("Too many synced add-on changes wait for a person", [path])
            mac = humanproof.local_sign(root, HELD_KIND, block)
            if mac:  # unsigned (no key): no row, and the value still stays off this machine
                write(root, f"run/sync/held/{tid}-{digest(block)}.json", encoded({**block, "mac": mac}))
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

    if not _TID.fullmatch(str(tid)):
        raise repo.Refused("No single held change for this ticket and add-on")
    with step_lock(root), syncgate.hold(root), tickets.sync_apply(root, tid):
        candidates = [(p, b) for p, b in held(root, tid) if b["addon"] == addon]
        if len(candidates) != 1:
            raise repo.Refused("No single held change for this ticket and add-on")
        p, block = candidates[0]
        hashed = digest(block["value"])
        # Fable B12: Ignore and Allow are different decisions with different proofs.
        kind = "ignore" if getattr(args, "ignore", False) else "allow"
        target = f"sync:{kind}:{tid}:{addon}:{hashed}"
        by = humanproof.person_by(
            root, args, "addon.act", target, no_handoff="This approval needs a person's proof over stdin."
        )
        config.require_person(by, "approve this synced change")
        entry = records.make(root, kind, f"{tid}:{addon}:{hashed}", {"ticket": tid, "addon": addon, "hash": hashed})
        if kind == "ignore":
            ignored = cli.read(root, "ignored")
            if not isinstance(ignored.get(tid), dict):
                ignored[tid] = {}
            ignored[tid][addon] = entry
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
        # #540: an approval is used once, here (the value is written into this machine's ticket now); its
        # record is a signed log whose id is spent at once, so no later merge or planted copy can replay it.
        records.spend(root, entry)
        store = cli.read(root, "approved")
        if not isinstance(store.get(tid), dict):
            store[tid] = {}
        store[tid][addon] = entry
        write(root, "run/sync/approved.json", encoded(store))
        known = cli.read(root, "local-ext")  # this machine's own value now (the automation add-on reads it)
        if isinstance(known.get(tid), dict):
            known[tid][addon] = hashed
            write(root, "run/sync/local-ext.json", encoded(known))
        write(root, path, encoded(doc))
        p.unlink()
    return {"approved": addon, "ticket": tid}
