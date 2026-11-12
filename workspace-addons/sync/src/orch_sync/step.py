"""One conservative sync transaction. Only repo.git executes git; live writes are gated."""

import contextlib
import json
import os
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from orch import humanproof, procs, syncgate, tickets
from orch.errors import Refused as CoreRefused

from . import cli, incoming, merge, paths, pause, records, repo

MB = 1_000_000


class Busy(repo.Refused):
    """A writer moved a file during this step: retry next tick (Fable A14: never a substring test)."""


def unstageable(root, path):
    """True when stage keeps this live file out of the commit (so apply must never wait for it)."""
    try:
        p = repo.safe(root, path)
        info = p.lstat()
    except repo.Refused:
        return True
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 25 * MB:
        return True
    if paths.TICKET.fullmatch(path) or path == "ticket-counter.json":
        try:
            data = p.read_bytes()
            if incoming.strict_load(data).get("general") is True:
                return True
            if paths.TICKET.fullmatch(path) and info.st_size > MB:
                return True
            document(path, data)
        except (ValueError, RecursionError, OSError):
            return True
    if paths.ARTIFACT.fullmatch(path):
        owner = "/".join(path.split("/")[:2]) + ".json"
        return unstageable(root, owner) or not repo.safe(root, owner).exists()
    return False


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False) + "\n").encode()


STATE = "run/sync/state.json"


def write(root, relative, data):
    if relative == STATE:  # keeps the pause only as this core signed it, never signs one (pause.seal / pause.sign)
        data = encoded(pause.seal(root, json.loads(data)))
    p = repo.safe(root, relative)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = stat.S_IMODE(p.stat().st_mode)
    except FileNotFoundError:
        mode = 0o600 if relative.startswith("run/") else 0o644
    # Fable A12: a never-synced ".tmp-" name, removed on every failure, with the file's own mode.
    fd, name = tempfile.mkstemp(dir=p.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(name, mode)
        syncgate.replace(name, p)
    finally:
        Path(name).unlink(missing_ok=True)


def oid(root, ref):
    r = repo.git(root, "rev-parse", "--verify", ref, allowed_codes=(0, 128))
    return r.stdout.decode().strip() if r.returncode == 0 else None


def entries(root, ref):
    return {p: (mode, obj) for mode, kind, obj, p in incoming.tree(root, ref)} if ref else {}


def blob(root, entry):
    return repo.git(root, "cat-file", "blob", entry[1]).stdout if entry else None


def put(root, index, path, data):
    obj = repo.git(root, "hash-object", "-w", "--stdin", input=data).stdout.decode().strip()
    repo.git(root, "update-index", "--add", "--cacheinfo", f"100644,{obj},{path}", index=index)


COUNTER_BYTES = 4096
COUNTER_JUMP = 100_000  # a peer's ticket numbers may run at most this far ahead of this machine's


def counter_ok(doc):
    """The core writes {"last": n}; anything else small and plain-int only (Fable A9)."""
    return len(doc) <= 16 and all(
        isinstance(k, str) and len(k) <= 32 and type(v) is int and 0 <= v <= merge.MAX_COUNTER + 1
        for k, v in doc.items()
    )


def top_number(root, ref):
    """The highest ticket number a tree uses: its counter, every key and every old key."""
    rows = entries(root, ref)
    numbers = [0]
    if "ticket-counter.json" in rows:
        last = document("ticket-counter.json", blob(root, rows["ticket-counter.json"])).get("last", 0)
        numbers.append(last if type(last) is int else 0)
    for path, entry in rows.items():
        if paths.TICKET.fullmatch(path):
            doc = document(path, blob(root, entry))
            numbers.extend(merge._key_n(k) for k in [doc.get("key"), *merge.old_keys_of(doc)])
    return max(numbers)


def document(path, data):
    if path == "ticket-counter.json" and len(data) > COUNTER_BYTES:
        raise pause.Pause(f"Document has a problem: {path}", [path])
    try:
        doc = incoming.strict_load(data)
    except (ValueError, RecursionError):
        raise pause.Pause(f"Document has a problem: {path}", [path]) from None
    if path == "ticket-counter.json" and not counter_ok(doc):
        raise pause.Pause(f"Document has a problem: {path}", [path])
    if paths.TICKET.fullmatch(path):
        if not isinstance(doc.get("ext", {}), dict) or len(doc.get("ext", {})) > 64:  # Fable B4: capped
            raise pause.Pause(f"Ticket has a problem: {path}", [path])
        checks = [("ticket", doc)] + [
            (f"addons/{name}/ext", value)
            for name, value in doc.get("ext", {}).items()
            if name in ("automation", "focus", "sync")
        ]
        for name, value in checks:
            schema = Path(__file__).parent / "schemas" / f"{name}.schema.json"
            if not schema.exists():  # the wheel includes these authoritative contracts
                schema = Path(__file__).resolve().parents[4] / "contracts" / f"{name}.schema.json"
            validator = Draft202012Validator(json.loads(schema.read_text()), format_checker=FormatChecker())
            if not validator.is_valid(value) or doc.get("id") != Path(path).stem:
                raise pause.Pause(f"Ticket has a problem: {path}", [path])
    return doc


def validate_tree(root, tree):
    seen, total, folders = {}, 0, {}
    rows = entries(root, tree)
    if len(rows) > 5000:
        raise repo.Refused("Too many files")
    for path, entry in rows.items():
        if not paths.allowed(path) or entry[0] != "100644":
            raise repo.Refused("Tree contains a refused path or file mode")
        for i in range(1, len(path.split("/")) + 1):
            prefix = "/".join(path.split("/")[:i])
            if seen.setdefault(prefix.casefold(), prefix) != prefix:
                raise repo.Refused("Case-fold collision")
        size = int(repo.git(root, "cat-file", "-s", entry[1]).stdout)
        if size > (MB if paths.TICKET.fullmatch(path) else 25 * MB):
            raise repo.Refused(f"File exceeds sync limit: {path}")
        total += size
        if paths.ARTIFACT.fullmatch(path):
            folder = "/".join(path.split("/")[:3])
            count, used = folders.get(folder, (0, 0))
            folders[folder] = count + 1, used + size
        data = blob(root, entry)
        findings = pause.findings(root, path, data)
        if findings:
            raise pause.Pause(f"Not synced: {path}: {findings[0].code}", [path])
        if paths.TICKET.fullmatch(path) or path == "ticket-counter.json":
            doc = document(path, data)
            if doc.get("general") is True:
                raise repo.Refused("General ticket stays local")
    for path in rows:
        if paths.ARTIFACT.fullmatch(path):
            owner = "/".join(path.split("/")[:2]) + ".json"
            if owner not in rows:
                raise repo.Refused(f"Artifact has no ticket: {path}")
            doc = document(owner, blob(root, rows[owner]))
            if doc.get("general") is True:
                raise repo.Refused("General ticket stays local")
    if total > 500 * MB or any(n > 200 or size > 200 * MB for n, size in folders.values()):
        raise repo.Refused("Too much to sync")


def deletions(old, new, root=None):
    gone = [p for p in old.keys() - new.keys() if paths.ARTIFACT.fullmatch(p)]
    if root is not None:
        # Fable A7 (incoming only): an artifact cut to less than half its size counts as removed too.
        size = lambda e: int(repo.git(root, "cat-file", "-s", e[1]).stdout)
        gone += [
            p
            for p in old.keys() & new.keys()
            if paths.ARTIFACT.fullmatch(p) and old[p] != new[p] and size(new[p]) * 2 < size(old[p])
        ]
    count = sum(bool(paths.ARTIFACT.fullmatch(p)) for p in old)
    folders = {p.split("/")[1] for p in gone}
    concentrated = any(
        (n := sum(bool(paths.ARTIFACT.fullmatch(p)) and p.split("/")[1] == tid for p in old)) > 5
        and sum(p.split("/")[1] == tid for p in gone) > n * 0.2
        for tid in folders
    )
    if len(gone) > 5 or len(gone) > count * 0.2 or concentrated:
        raise pause.Pause(f"Many files were removed ({len(gone)}). Apply?", gone)


def stage(root, head, index, state, now):
    old = entries(root, head)
    repo.git(root, "read-tree", head or "--empty")
    repo.git(root, "read-tree", head or "--empty", index=index)
    names = set(old)
    work = repo.safe(root, "")
    for parent, dirs, files in os.walk(repo.safe(root, "tickets"), followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(parent) / d).is_symlink()]
        names.update((Path(parent) / f).relative_to(work).as_posix() for f in files)
    names.add("ticket-counter.json")
    generals, preserved = set(), set()
    left = cli.read(root, "left-out")  # Leave it out (pause.leave_out): checked per path against its bytes
    for path in sorted(names):
        if any(path.startswith(f"tickets/{tid}/") for tid in preserved):
            continue  # The index already contains HEAD's artifacts.
        if not paths.allowed(path) or any(path.startswith(f"tickets/{tid}/") for tid in generals):
            if path in old:
                repo.git(root, "update-index", "--force-remove", "--", path, index=index)
            continue
        tid = path.split("/")[1].removesuffix(".json") if path.startswith("tickets/") else "key"
        with tickets.sync_apply(root, tid):
            try:
                try:
                    p = repo.safe(root, path)
                except repo.Refused:
                    raise ValueError("Link stays local") from None
                info = p.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("Not a regular single-link file")
                if info.st_size > 25 * MB:
                    raise ValueError("File exceeds 25 MB")
                if paths.TICKET.fullmatch(path) or path == "ticket-counter.json":
                    try:
                        data = p.read_bytes()
                        doc = incoming.strict_load(data)
                        if doc.get("general") is not True:
                            if paths.TICKET.fullmatch(path) and info.st_size > MB:
                                raise ValueError("Ticket exceeds 1 MB")
                            doc = document(path, data)
                    except (ValueError, RecursionError):
                        raise ValueError("Ticket has a problem") from None
                    if doc.get("general") is True:
                        (preserved if path in old else generals).add(Path(path).stem)
                        continue
                if path in left and pause.left_out(root, path, p.read_bytes()):
                    continue  # a person left exactly these bytes out: they stay here (the index keeps HEAD's)
                repo.git(root, "add", "-f", "--", ":(literal)" + path, index=index)
            except FileNotFoundError:
                if paths.TICKET.fullmatch(path):
                    (preserved if path in old else generals).add(Path(path).stem)
                    if path not in old:
                        state["skipped"].append(f"Ticket {Path(path).stem} has a problem and was not synced")
                if path in old:
                    if paths.TICKET.fullmatch(path):
                        # Only a person's signed, single-use record lets a missing ticket go (a deletion is
                        # pushed to every machine); a planted or reused one restores the file as usual.
                        # bound to the very copy the person left deleted (its blob in HEAD)
                        allowed = cli.read(root, "allow-delete").get(Path(path).stem)
                        target = f"{Path(path).stem}:{old[path][1]}"
                        if records.ok(root, "delete", target, allowed, single_use=True):
                            records.spend(root, allowed)
                            repo.git(root, "update-index", "--force-remove", "--", path, index=index)
                            continue
                        write(root, path, blob(root, old[path]))
                        state["notices"].append(f"Restored a missing ticket file: {path}")
                        state.setdefault("deleted", {})[Path(path).stem] = (
                            datetime.now(UTC).isoformat().replace("+00:00", "Z")
                        )
                    else:
                        repo.git(root, "update-index", "--force-remove", "--", path, index=index)
            except (ValueError, OSError) as e:
                if paths.TICKET.fullmatch(path):
                    (preserved if path in old else generals).add(Path(path).stem)
                    state["skipped"].append(f"Ticket {Path(path).stem} has a problem and was not synced: {e}")
                elif isinstance(e, repo.Refused):
                    raise
                else:
                    state["skipped"].append(f"{path}: {e}")
    # Purge only excluded folders whose ticket JSON was never tracked in HEAD.
    excluded = {
        p
        for p in names
        if any(p == f"tickets/{tid}.json" or p.startswith(f"tickets/{tid}/") for tid in generals)
    }
    for path in sorted(excluded & old.keys()):
        repo.git(root, "update-index", "--force-remove", "--", path, index=index)
        repo.git(root, "update-index", "--force-remove", "--", path)
    tree = repo.git(root, "write-tree", index=index).stdout.decode().strip()
    rows = entries(root, tree)
    # A person's rename (orch sync resolve --rename-local) is not a removal; the record goes once committed.
    # Only an entry whose new file holds exactly the old bytes counts as moved (nothing is lost); every other
    # entry is a removal, so the deletion gate still sees it.
    renamed = cli.read(root, "renamed")
    moved = {
        p
        for p, new in renamed.items()
        if isinstance(new, str) and p in old and p not in rows and new in rows and new not in old
        and rows[new][1] == old[p][1]
    }
    if any(p not in old for p in renamed):
        write(root, "run/sync/renamed.json", encoded({p: n for p, n in renamed.items() if p in old}))
    deletions({p: e for p, e in old.items() if p not in excluded and p not in moved}, rows)
    validate_tree(root, tree)  # every byte, including unchanged staged blobs
    held = {Path(p).stem for p in entries(root, tree) if paths.TICKET.fullmatch(p)}
    renumber(root, index, now, held=held, live=True)
    return repo.git(root, "write-tree", index=index).stdout.decode().strip()


def commit(root, tree, parents, now):
    args = [v for parent in parents if parent for v in ("-p", parent)]
    return (
        repo.git(
            root,
            "-c",
            "user.name=orch",
            "-c",
            "user.email=orch@localhost",
            "commit-tree",
            tree,
            *args,
            input=f"orch sync {now}\n".encode(),
            commit_date=now,
        )
        .stdout.decode()
        .strip()
    )


def held_ticket(root, path, doc, local, remote):
    from .approval import filter_ticket

    return filter_ticket(root, path, doc, local, remote)


FUTURE_SKEW = 86_400  # seconds a peer's clock may run ahead


def merge_document(root, path, base, local, remote, now):
    # Direction matters: only remote-only history attribution is demoted.
    stamp, current = merge._utc((remote or {}).get("updated_at")), merge._utc(now)
    if stamp is not None and current is not None and stamp > current + FUTURE_SKEW:
        # Fable A15: a far-future updated_at would win every conflict for good. A person looks first.
        raise pause.Pause(f"A synced ticket is dated in the future: {path}", [path])
    try:
        doc = merge.merge_ticket(
            base or None,
            remote,
            local or {"id": remote["id"]},
            now=now,
            person=humanproof.wont_verifier(root),
            verdict=humanproof.verdict_verifier(root),
        )
    except Exception:  # noqa: BLE001 - an invalid merge always keeps both versions
        raise pause.Pause(f"Ticket cannot be merged: {path}", [path]) from None
    if doc is None:
        raise pause.Pause(f"Ticket cannot be merged: {path}", [path])
    return held_ticket(root, path, doc, local, remote)


def counters_of(root, local_rows, remote_rows):
    return [
        document("ticket-counter.json", blob(root, rows["ticket-counter.json"])).get("last", 0)
        if "ticket-counter.json" in rows
        else 0
        for rows in (local_rows, remote_rows)
    ]


def reach_gate(root, counters, keys, decisions):
    """Fable A9: numbers only ever go up, so a far jump would be permanent. A person checks it first. The counter
    file's jump is settled by a person's choice of the counter; the incoming TICKET numbers are checked on their
    own: only a counter this person chose (theirs, or a key choice) raises what counts as within reach here, so
    "keep mine" never lets far tickets in. ONE gate for a normal merge and for take-remote. `counters` = [local,
    incoming] counter, `keys` = [local, incoming] ticket numbers (key and old keys)."""
    reach = max([counters[0], *keys[0]])
    counter_choice = decisions.get("ticket-counter.json")
    if counter_choice and counter_choice.get("keep") in ("theirs", "key"):
        chosen = document(
            "ticket-counter.json", pause.selected(root, "ticket-counter.json", counter_choice)
        ).get("last", 0)
        reach = max(reach, chosen if type(chosen) is int else 0)
    if counter_choice and type(counter_choice.get("covers")) is int:
        # A person's proven (signed) counter choice on a jump covers the incoming numbers they reviewed.
        reach = max(reach, counter_choice["covers"])
    if (counters[1] > max([counters[0], *keys[0]]) + COUNTER_JUMP and not counter_choice) or max(
        keys[1], default=0
    ) > reach + COUNTER_JUMP:
        raise pause.Pause(pause.JUMP, ["ticket-counter.json"])


def merged_tree(root, head, remote, index, now, first=False):
    checked_remote = pause.checked_tree(root, remote, index)
    ancestor = repo.git(root, "merge-base", head, remote, allowed_codes=(0, 1)).stdout.decode().strip()
    base_rows = entries(root, ancestor or None)
    local_rows, remote_rows = entries(root, head), entries(root, checked_remote)
    decisions = pause.choices(root, remote)
    known = {}
    changed_keys = set()
    counters = counters_of(root, local_rows, remote_rows)
    keys = [[], []]  # the ticket numbers each side uses (key and old keys)
    for path in sorted(base_rows.keys() | local_rows.keys() | remote_rows.keys()):
        if not paths.TICKET.fullmatch(path):
            continue
        local = document(path, blob(root, local_rows.get(path) or base_rows.get(path))) if path in local_rows or path in base_rows else {}
        incoming_doc = document(path, blob(root, remote_rows[path])) if path in remote_rows else {}
        for side, d in enumerate((local, incoming_doc)):
            keys[side].extend(merge._key_n(k) for k in [d.get("key"), *merge.old_keys_of(d)])
        doc = local or incoming_doc
        if doc.get("key"):
            known.setdefault(doc["key"], []).append({"id": doc["id"], "title": doc["title"]})
        if local and incoming_doc and local.get("key") != incoming_doc.get("key") and path not in decisions:
            clash_key = local.get("key") or incoming_doc.get("key")
            if clash_key not in known:
                known[clash_key] = [{"id": local["id"], "title": local["title"]}]
            changed_keys.add(clash_key)
    reach_gate(root, counters, keys, decisions)
    if changed_keys:
        clashes = {key: known[key] for key in sorted(changed_keys)}
        raise pause.Pause(
            "Ticket numbers need a person's choice",
            [f"tickets/{t['id']}.json" for group in clashes.values() for t in group],
            key_clashes=clashes,
        )
    both_changed = [
        p
        for p in local_rows.keys() | remote_rows.keys()
        if paths.ARTIFACT.fullmatch(p)
        and p not in decisions
        and local_rows.get(p) != remote_rows.get(p)
        and local_rows.get(p) != base_rows.get(p)
        and remote_rows.get(p) != base_rows.get(p)
    ]
    if both_changed:
        raise pause.Pause("Conflicting artifact needs a person", sorted(both_changed))
    bases = repo.git(root, "merge-base", "--all", head, checked_remote, allowed_codes=(0, 1)).stdout.split()
    chosen_all = bool(decisions) and set(entries(root, remote)) <= set(decisions)
    if len(bases) > 1 or (not bases and not first and not chosen_all):
        # Fable A5: several merge bases make git build a virtual base by a text merge of JSON. None at all (a
        # remote that started a new history; not this machine's first join, and not a rewritten history whose
        # every file a person chose) has no base to judge changes by. A file-less pause with its own Needs row:
        # take-remote (a person's proof), or it clears by itself when the remote changes.
        raise pause.Pause("The two histories cannot be combined automatically", [], kind=pause.HISTORY)
    result = repo.git(
        root,
        # Fable A5: paths are stable here; rename detection would move a local file into another folder.
        "-c",
        "merge.renames=false",
        "-c",
        "merge.directoryRenames=false",
        "merge-tree",
        "--write-tree",
        "--no-messages",
        "-z",
        "--allow-unrelated-histories",
        head,
        checked_remote,
        allowed_codes=(0, 1),
    )
    fields = result.stdout.split(b"\0")
    tree = fields[0].decode()
    conflicts = {}
    for field in fields[1:]:
        if not field:
            continue
        meta, path = field.split(b"\t", 1)
        mode, obj, stage_no = meta.decode().split()
        conflicts.setdefault(path.decode(), {})[int(stage_no)] = (mode, obj)
    decisions = pause.choices(root, remote)
    unresolved = [
        p
        for p in conflicts
        if not paths.TICKET.fullmatch(p) and p != "ticket-counter.json" and p not in decisions
    ]
    if unresolved:
        raise pause.Pause("Conflicting artifact needs a person", unresolved)
    repo.git(root, "read-tree", tree, index=index)
    base_result = repo.git(root, "merge-base", head, remote, allowed_codes=(0, 1))
    base = entries(root, base_result.stdout.decode().strip() or None)
    ours, theirs = entries(root, head), entries(root, checked_remote)
    merged_rows = entries(root, tree)
    for path in ours:
        if paths.TICKET.fullmatch(path) and path not in merged_rows:
            put(root, index, path, blob(root, ours[path]))  # Fable A5: a ticket never disappears in a merge
    merges = {}
    for path in sorted(theirs):
        if not (paths.TICKET.fullmatch(path) or path == "ticket-counter.json"):
            continue
        if theirs[path] == base.get(path) or theirs[path] == ours.get(path):
            continue
        versions = conflicts.get(path, {1: base.get(path), 2: ours.get(path), 3: theirs[path]})
        b, a, t = [incoming.strict_load(blob(root, versions.get(n)) or b"{}") for n in (1, 2, 3)]
        if path == "ticket-counter.json":
            doc = merge.merge_counter(b, a, t)
        else:
            # Speculative tree only: apply repeats this merge under the ticket lock.
            doc = merge_document(root, path, b, a, t, now)
            merges[path] = {"base": b, "local": a, "remote": t, "now": now}
        data = encoded(doc)
        # Preserve the selected side's bytes, including its JSON formatting.
        for version, value in ((3, t), (2, a)):
            if doc == value:
                data = blob(root, versions.get(version))
                break
        document(path, data)
        put(root, index, path, data)
    for path in decisions:
        if decisions[path].get("incoming") and paths.TICKET.fullmatch(path):
            continue  # Incoming key choices must retain the verified normal merge.
        if decisions[path].get("keep") == pause.LOCAL_NAME:
            continue  # the checked remote tree already leaves the other computer's case variant out
        data = pause.selected(root, path, decisions[path])
        if paths.TICKET.fullmatch(path):
            # Fable A3: a person's choice is the remote side of a normal merge against this machine's copy,
            # so the verifiers, history demotion and held ext apply; apply replays exactly these inputs. What
            # only this machine decides (key, Done, ext.sync) comes from its own copy, exactly as resolve does.
            original = document(path, data)
            mine = document(path, blob(root, ours[path])) if path in ours else {}
            chosen = original
            if decisions[path].get("keep") in ("mine", "theirs"):
                chosen = pause.local_decisions(original, mine)
            doc = merge_document(root, path, mine, mine, chosen, now)
            merges[path] = {"base": mine, "local": mine, "remote": chosen, "now": now}
            data = data if doc == original else encoded(doc)
            document(path, data)
        put(root, index, path, data)
    renumber(root, index, now, merges, held={Path(p).stem for p in ours if paths.TICKET.fullmatch(p)})
    tree = repo.git(root, "write-tree", index=index).stdout.decode().strip()
    validate_tree(root, tree)
    deletions(ours, entries(root, tree), root)
    return tree, merges


def taken_tree(root, head, remote, index, now):
    """take-remote (a HISTORY pause: no usable merge base). The SAME merge authority as a normal merge, with this
    machine's HEAD as the base: every ticket the other computer has is merge_document(head, head, theirs with
    this machine's own decisions: key, Done, ext.sync), so the receiving core's verifiers decide every Won't do
    and verdict, remote-only history is demoted, held add-on values stay held; the counter only goes up; the
    reach gate, key renumbering (this machine's ids keep their keys), the tree checks and the deletion gate run
    as for a merge. Files only this machine has stay; nothing is removed. Returns (tree, merges): the tree is
    exactly what the person's proof covers and what apply writes (apply replays `merges` under the locks)."""
    local_rows, remote_rows = entries(root, head), entries(root, remote)
    keys = [[], []]
    for side, rows in enumerate((local_rows, remote_rows)):
        for path in sorted(rows):
            if paths.TICKET.fullmatch(path):
                d = document(path, blob(root, rows[path]))
                keys[side].extend(merge._key_n(k) for k in [d.get("key"), *merge.old_keys_of(d)])
    reach_gate(root, counters_of(root, local_rows, remote_rows), keys, {})
    repo.git(root, "read-tree", head or "--empty", index=index)
    merges = {}
    for path in sorted(remote_rows):
        if not paths.allowed(path) or remote_rows[path] == local_rows.get(path):
            continue
        data = blob(root, remote_rows[path])
        if paths.TICKET.fullmatch(path):
            theirs = document(path, data)
            mine = document(path, blob(root, local_rows[path])) if path in local_rows else {}
            chosen = pause.local_decisions(theirs, mine) if mine else theirs
            doc = merge_document(root, path, mine, mine, chosen, now)
            merges[path] = {"base": mine, "local": mine, "remote": chosen, "now": now}
            data = data if doc == theirs else encoded(doc)
            document(path, data)
        elif path == "ticket-counter.json":
            mine = document(path, blob(root, local_rows[path])) if path in local_rows else {}
            data = encoded(merge.merge_counter({}, mine, document(path, data)))
            document(path, data)
        put(root, index, path, data)
    renumber(root, index, now, merges, held={Path(p).stem for p in local_rows if paths.TICKET.fullmatch(p)})
    tree = repo.git(root, "write-tree", index=index).stdout.decode().strip()
    validate_tree(root, tree)
    deletions(local_rows, entries(root, tree), root)
    return tree, merges


def renumber(root, index, now, merges=None, *, held, live=False):
    tree = repo.git(root, "write-tree", index=index).stdout.decode().strip()
    rows = entries(root, tree)
    docs = {Path(p).stem: document(p, blob(root, e)) for p, e in rows.items() if paths.TICKET.fullmatch(p)}
    counter = incoming.strict_load(blob(root, rows.get("ticket-counter.json")) or b"{}")
    previous_counter = counter
    result = merge.renumber_key_clashes(docs, counter, now, held=held)
    if result is None:
        groups = {}
        for tid, doc in sorted(docs.items()):
            if doc.get("key"):
                groups.setdefault(doc["key"], []).append({"id": tid, "title": doc["title"]})
        clashes = {key: group for key, group in sorted(groups.items()) if len(group) > 1}
        if clashes:
            raise pause.Pause(
                "Ticket numbers need a person's choice",
                [f"tickets/{t['id']}.json" for group in clashes.values() for t in group],
                key_clashes=clashes,
            )
        raise pause.Pause("Ticket keys could not be combined", [f"tickets/{tid}.json" for tid in docs])
    changed, counter = result
    for tid, doc in changed.items():
        path = f"tickets/{tid}.json"
        if live:
            with tickets.sync_apply(root, tid):
                if repo.safe(root, path).read_bytes() != blob(root, rows[path]):
                    raise Busy(f"{path}: busy")
                write(root, path, encoded(doc))
        else:
            merges[path] = {"selected": doc, "now": now}
        put(root, index, path, encoded(doc))
    if changed or counter.get("last", 0) > previous_counter.get("last", 0):
        put(root, index, "ticket-counter.json", encoded(counter))
        if live:
            with tickets.sync_apply(root, "key"):
                write(root, "ticket-counter.json", encoded(counter))


def apply(root, old, new, state, merges=None):
    before, after = entries(root, old), entries(root, new)
    changed = sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
    # Check the whole transaction before writing any path, including on recovery.
    for path in changed:
        if paths.TICKET.fullmatch(path) and path not in (merges or {}):
            raise Busy(f"{path}: busy")
    tids = {path.split("/")[1].removesuffix(".json") for path in changed if path.startswith("tickets/")}
    with contextlib.ExitStack() as locks:
        # Fable A2: hold every lock and check every path before the first write, so a refusal never leaves
        # half a transaction behind that the next stage would commit as local edits.
        for tid in [*sorted(tids), *(["key"] if "ticket-counter.json" in changed else [])]:
            locks.enter_context(tickets.sync_apply(root, tid))
        plan = []
        for path in changed:
            p = repo.safe(root, path)
            previous, data = blob(root, before.get(path)), blob(root, after.get(path))
            current = p.read_bytes() if p.is_file() and not repo.is_link(p) else None
            regular = not p.exists() or (stat.S_ISREG(p.lstat().st_mode) and p.stat().st_nlink == 1)
            if not regular or current not in (previous, data):
                if unstageable(root, path):
                    # A local file stage keeps out (General, broken, too big, a link): it stays as it is and
                    # the merged version stays committed, so nothing is lost and nothing else waits for it.
                    state["skipped"].append(f"{path}: the local file cannot be synced; it was kept as it is")
                    # A Needs row too (needs.py), until the path applies again (_settle_unapplied).
                    unapplied = state.setdefault("unapplied", {})
                    unapplied.setdefault(path, datetime.now(UTC).isoformat().replace("+00:00", "Z"))
                    continue
                state["skipped"].append(f"{path}: busy")
                raise Busy(f"{path}: busy")
            if path in (merges or {}):
                inputs = merges[path]
                # On recovery an already-applied file uses the original local input.
                local = (
                    incoming.strict_load(current or b"{}") if current == previous else inputs.get("local", {})
                )
                if "selected" in inputs:
                    checked = merge_document(
                        root, path, {}, inputs["selected"], inputs["selected"], inputs["now"]
                    )
                else:
                    checked = merge_document(
                        root, path, inputs["base"], local, inputs["remote"], inputs["now"]
                    )
                if checked != incoming.strict_load(data):
                    raise Busy(f"{path}: busy")
            plan.append((path, p, current, data))
        for path, p, current, data in plan:
            if current == data:
                continue  # an interrupted apply already replaced this path
            if (p.read_bytes() if p.is_file() else None) != current:
                raise Busy(f"{path}: busy")  # a plain file writer slipped in since the check
            try:
                if data is None:
                    p.unlink(missing_ok=True)
                else:
                    write(root, path, data)
            except PermissionError:
                raise Busy(f"{path}: busy") from None
    repo.git(root, "update-ref", "refs/heads/orch-state", new, old)
    repo.git(root, "read-tree", new)
    repo.git(root, "update-index", "--refresh", allowed_codes=(0, 1))


@contextlib.contextmanager
def step_lock(root):
    p = repo.safe(root, "run/sync/step.lock")
    with syncgate.hold(root, "step-lock"):
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if not procs.owner_dead(p.read_text()):
                raise repo.Refused("Sync is already running") from None
            p.unlink()
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(procs.own_token())
    from .approval import manifest_cache

    token = manifest_cache.set({})
    try:
        yield
    finally:
        manifest_cache.reset(token)
        p.unlink()


def _remote_moved(root, paused, remote_allowed):
    """A history pause (no files) clears by itself once the remote is no longer the commit it was about."""
    try:
        settings = cli.DEFAULTS | cli.read(root, "settings")
        if settings["mode"] != "remote" or not remote_allowed or not settings.get("remote"):
            return False
        repo.set_remote(root, cli.confirmed_remote(root, settings))
        repo.fetch(root)
        return oid(root, "refs/remotes/origin/orch-state") != paused.get("remote_sha")
    except Exception:  # noqa: BLE001 - offline or refused: the pause stays
        return False


def _run(root, reason, now, remote_allowed):
    previous = cli.read(root, "state")
    paused = pause.verified_pause(root, previous)  # a planted or edited pause is none: look again
    previous = {**previous, "paused": paused}
    if paused:
        if not (paused.get("kind") == pause.HISTORY and _remote_moved(root, paused, remote_allowed)):
            return previous
        previous = {**previous, "paused": None}  # the remote changed: look again
    state = previous | {"last_error": None, "skipped": [], "notices": [], "reason": reason}
    remote = None
    try:
        repo.local_dir(root)
        settings = cli.DEFAULTS | cli.read(root, "settings")
        if settings["kind"] != "private":
            raise repo.Refused("Team sync is not available yet")
        if settings["mode"] == "off":
            return state
        network = settings["mode"] == "remote"
        if network and not remote_allowed:
            raise repo.Refused("Remote sync is preview-only")
        if network:
            cli.confirmed_remote(root, settings)  # settings.json is agent-writable: only the address a person chose
        repo.ensure(root)
        repo.recover(root)
        for attempt in range(2):
            head, remote, offline = oid(root, "HEAD"), None, False
            url = settings.get("remote")
            if network:
                if not url:
                    raise repo.Refused("A remote address is required")
                repo.set_remote(root, url)
                try:
                    repo.fetch(root)
                except repo.RemoteRefused:
                    raise  # a refused remote is reported as it is, never as offline
                except repo.Refused:
                    offline = True
                if not offline:
                    remote = oid(root, "refs/remotes/origin/orch-state")
                    last = state.get("remote_sha") if state.get("remote_url") == url else None
                    if (
                        last
                        and not pause.choices(root, remote)
                        and (
                            not remote
                            or repo.git(
                                root, "merge-base", "--is-ancestor", last, remote, allowed_codes=(0, 1)
                            ).returncode
                        )
                    ):
                        raise pause.Pause("The remote history was rewritten", sorted(entries(root, remote)))
                    if remote:
                        common = (
                            repo.git(root, "merge-base", head, remote, allowed_codes=(0, 1)) if head else None
                        )
                        base = (common.stdout.decode().strip() or None) if common else None
                        checked_ref = remote
                        if pause.choices(root, remote):
                            with tempfile.TemporaryDirectory(dir=repo.local_dir(root)) as folder:
                                checked_ref = pause.checked_tree(root, remote, Path(folder) / "index")
                        result = incoming.check(root, checked_ref, base=base, local=head, gone=_renamed_away(root))
                        problems = [
                            p
                            for p in result.problems
                            if p.code != "held-ext"
                            and not (
                                p.code == "cannot-check"
                                and not pause.findings(
                                    root, p.path, blob(root, entries(root, checked_ref)[p.path])
                                )
                            )
                        ]
                        if problems:
                            files = [p.path for p in problems if p.path]
                            if any(p.code == "needs-confirm" for p in problems):
                                files.extend(p for p in entries(root, base) if p not in entries(root, remote))
                            raise pause.Pause(
                                problems[0].message, files, case_names=_case_names(root, head, problems)
                            )
                        for path, chosen in pause.choices(root, remote).items():
                            if chosen.get("keep") == pause.LOCAL_NAME:
                                state["notices"].append(
                                    f"Kept your file name {Path(str(chosen.get('local'))).name}; the other "
                                    f"computer's {Path(path).name} is not applied."
                                )
                        if not result.commit:
                            raise repo.Refused("Incoming state has no checked commit")
                        if checked_ref == remote:
                            remote = result.commit
                        validate_tree(root, result.commit)
            scratch_root = repo.safe(root, "run/tmp-sync")
            scratch_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=scratch_root) as scratch:
                index = Path(scratch) / "index"
                with syncgate.hold(root):
                    pending = cli.read(root, "pending")
                    if pending and not offline:
                        if (
                            pending["old"] == head
                            and pending.get("url") == url
                            and pending.get("remote") == remote
                        ):
                            validate_tree(root, pending["new"])
                            if "merges" not in pending:
                                raise Busy("Pending merge needs a fresh check: busy")
                            apply(root, head, pending["new"], state, pending["merges"])
                            head = pending["new"]
                        repo.safe(root, "run/sync/pending.json").unlink()
                    tree = stage(root, head, index, state, now)
                    if not head or tree != oid(root, head + "^{tree}"):
                        new = commit(root, tree, [head], now)
                        repo.git(root, "update-ref", "refs/heads/orch-state", new, head or "0" * 40)
                        head = new
                    repo.git(root, "read-tree", head)
                if network and not offline:
                    first = state.get("remote_url") != url
                    parent = commit(root, tree, [], now) if first else head
                    merges = {}
                    new = parent
                    if (
                        remote
                        and repo.git(
                            root, "merge-base", "--is-ancestor", remote, parent, allowed_codes=(0, 1)
                        ).returncode
                    ):
                        tree, merges = merged_tree(root, parent, remote, index, now, first=first)
                        can_forward = (
                            first
                            or not repo.git(
                                root, "merge-base", "--is-ancestor", parent, remote, allowed_codes=(0, 1)
                            ).returncode
                        )
                        if can_forward and tree == oid(root, remote + "^{tree}"):
                            new = remote
                        else:
                            new = commit(root, tree, [parent, remote], now)
                    if new != head:
                        write(
                            root,
                            "run/sync/pending.json",
                            encoded(
                                {
                                    "old": head,
                                    "new": new,
                                    "url": url,
                                    "remote": remote,
                                    "merges": merges,
                                }
                            ),
                        )
                        with syncgate.hold(root):
                            apply(root, head, new, state, merges)
                        repo.safe(root, "run/sync/pending.json").unlink()
                        head = new
                if not network:
                    break
                if offline:
                    raise repo.Refused("offline")
                if head == remote:
                    state.update(remote_sha=head, remote_url=url)
                    break
                # A push transfers history, not just the current tree. Validate every
                # outgoing tree, scanning full blob bytes (including unchanged blobs).
                revisions = [head] + (["--not", remote] if remote else [])
                for outgoing in repo.git(root, "rev-list", *revisions).stdout.decode().splitlines():
                    validate_tree(root, outgoing)
                try:
                    pushed = repo.push(root, head)
                except repo.RemoteRefused:
                    raise
                except repo.Refused:
                    raise repo.Refused("offline") from None
                if pushed:
                    state.update(remote_sha=head, remote_url=url)
                    break
                if attempt:  # rejected twice: someone keeps pushing first; next tick
                    raise repo.Refused("offline")
        state["last_ok"] = now
    except (ValueError, OSError, CoreRefused) as e:
        state["last_error"] = str(e)
        if isinstance(e, pause.Pause):
            pause.capture(root, state, e, remote, now)
        if isinstance(e, Busy):
            repo.safe(root, "run/sync/pending.json").unlink(missing_ok=True)
    except Exception as e:  # noqa: BLE001 - Fable A4/B14: hostile data must never crash every tick unseen
        state["last_error"] = f"Sync stopped: {type(e).__name__}"
    head, remote = oid(root, "HEAD") if repo.safe(root, ".git").is_dir() else None, None
    if head:
        remote = oid(root, "refs/remotes/origin/orch-state")
    _settle_unapplied(root, state, head)
    counts = (
        repo.git(root, "rev-list", "--left-right", "--count", f"{head}...{remote}").stdout.split()
        if head and remote
        else [int(repo.git(root, "rev-list", "--count", head).stdout) if head else 0, 0]
    )
    state.update(ahead=int(counts[0]), behind=int(counts[1]))
    write(root, "run/sync/state.json", encoded(state))
    return state


def _case_names(root, head, problems):
    """{incoming path: this machine's path} for each incoming name that differs from a local one only in case."""
    mine = {incoming._fold(p): p for p in entries(root, head)} if head else {}
    out = {}
    for p in problems:
        if p.message == pause.CASE_PROBLEM and mine.get(incoming._fold(p.path)) not in (None, p.path):
            out[p.path] = mine[incoming._fold(p.path)]
    return out or None


def _renamed_away(root):
    """Local files a person renamed (orch sync resolve --rename-local) that are gone from this disk: the next
    stage commits the rename before the merge, so they clash with no incoming name."""
    return {p for p in cli.read(root, "renamed") if paths.allowed(p) and not os.path.lexists(repo.safe(root, p))}


def _settle_unapplied(root, state, head):
    """Drop the paths that apply again: the live file now holds the committed version, e.g. after the local
    file became syncable and was committed. Never raises."""
    pending = state.get("unapplied")
    if not isinstance(pending, dict) or not pending:
        state.pop("unapplied", None)
        return
    try:
        rows = entries(root, head)
    except (ValueError, OSError):
        return
    for path in list(pending):
        try:
            p = repo.safe(root, path)
            live = p.read_bytes() if p.is_file() and not repo.is_link(p) else None
            data = blob(root, rows.get(path))
            if live == data:
                pending.pop(path)
        except (ValueError, OSError):
            continue
    if not pending:
        state.pop("unapplied", None)


def run_once(root, reason, *, now=None):
    remote_allowed = cli.remote_allowed()
    root = Path(root)
    now = now or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    try:
        repo.local_dir(root)
        with step_lock(root):
            return _run(root, reason, now, remote_allowed)
    except (ValueError, OSError, CoreRefused) as e:
        # A competing step owns state.json too; do not overwrite its result.
        return {"last_error": str(e), "skipped": [], "reason": reason}
    except Exception as e:  # noqa: BLE001 - fail closed with a visible error, never a traceback loop
        return {"last_error": f"Sync stopped: {type(e).__name__}", "skipped": [], "reason": reason}
