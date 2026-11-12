"""Keep both until an explicit resolution; decisions are pinned to one remote commit."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from orch import config, humanproof, syncgate, tickets

from . import cli, incoming, paths, records, repo, scan

HISTORY = "history"  # the pause kind of two histories git cannot combine (no file to choose)
JUMP = "Ticket numbers jumped far ahead on the other computer"  # a person checks the counter (Fable A9)


class Pause(repo.Refused):
    def __init__(self, reason, files=(), *, key_clashes=None, case_names=None, kind=None):
        super().__init__(reason)
        self.files = list(files)
        self.key_clashes = key_clashes
        self.case_names = case_names  # {incoming path: this machine's path that differs only in case}
        self.kind = kind


PAUSED_KIND = "sync-paused"


def sign(root, paused):
    """Sign a pause this core made or changed in this process (its files, reason, kind, remote, clashes) with its
    local1 MAC. Only capture and the person's resolutions call it: an agent can write state.json, but an edited or
    planted pause (a reason that lowers what needs a proof, a remote it never reviewed) is no pause at all."""
    body = {k: v for k, v in paused.items() if k != "mac"}
    mac = humanproof.local_sign(root, PAUSED_KIND, body)
    return {**body, "mac": mac} if mac else None  # unsigned = no pause (sync looks again)


def seal(root, state):
    """Before state.json is written: keep the pause only as this core signed it (verified_pause), else drop it.
    Never signs: a planted pause written back by any core write would otherwise come out signed."""
    state["paused"] = verified_pause(root, state)
    return state


def verified_pause(root, state):
    """The pause in `state` (with its mac, so writing it back unchanged keeps it) when this core signed exactly
    it, else None. A caller that changes it signs it again (sign); a changed pause it forgets is dropped."""
    paused = state.get("paused") if isinstance(state, dict) else None
    if not isinstance(paused, dict):
        return None
    body = {k: v for k, v in paused.items() if k != "mac"}
    if not humanproof.local_ok(root, PAUSED_KIND, body, paused.get("mac")):
        return None
    if not isinstance(body.get("files"), list) or not isinstance(body.get("reason"), str):
        return None
    return paused


def capture(root, state, error, remote, now):
    from . import step

    ours = step.entries(root, step.oid(root, "HEAD"))
    theirs = step.entries(root, remote)
    kind = getattr(error, "kind", None)
    if kind == HISTORY:
        files = []  # nothing to choose per file: its own Needs row; it clears when the remote changes
    else:
        files = error.files or sorted(p for p in ours.keys() | theirs.keys() if ours.get(p) != theirs.get(p))
    files = sorted({p for p in files if paths.allowed(p)})
    paused = {"files": files, "since": now, "remote_sha": remote, "reason": str(error)}
    if kind:
        paused["kind"] = kind
    if error.key_clashes:
        paused["key_clashes"] = error.key_clashes
    if error.case_names:
        paused["case_names"] = {p: v for p, v in error.case_names.items() if p in files}
    state["paused"] = sign(root, paused)  # the one place a new pause is made (Pause raised in this process)
    # Manifest is written last by the step. Saved bytes are never used without matching its sha.
    for path in files:
        data = step.blob(root, theirs.get(path))
        target = repo.safe(root, "run/sync/theirs/" + path)
        if data is not None:
            step.write(root, "run/sync/theirs/" + path, data)
        else:
            target.unlink(missing_ok=True)
    step.write(root, "run/sync/theirs.json", step.encoded({"remote_sha": remote}))


CHOICES = ("mine", "theirs", "key")


def choices(root, remote):
    """The choices for exactly this remote commit: only entries this core signed for exactly that remote and
    path (records "choice"); an entry of any other shape, edited (keep, covers, local, ...) or planted counts
    for nothing."""
    data = cli.read(root, "choices")
    files = data.get("files")
    if data.get("remote_sha") != remote or not isinstance(files, dict):
        return {}
    return {
        p: e
        for p, e in files.items()
        if isinstance(p, str)
        and paths.allowed(p)
        and isinstance(e, dict)
        and (e.get("keep") in CHOICES or (e.get("keep") == LOCAL_NAME and isinstance(e.get("local"), str)))
        and records.ok(root, "choice", f"{remote}:{p}", e)
    }


def record_choice(root, decisions, remote, path, fields, data=None):
    """Put a signed choice for `path` (bound to the reviewed remote, and to the chosen bytes) into `decisions`."""
    if data is not None:
        fields = {**fields, "sha256": hashlib.sha256(data).hexdigest()}
    decisions["files"][path] = records.make(root, "choice", f"{remote}:{path}", fields)


def selected(root, path, entry):
    """The chosen bytes of `path`: only when they are exactly the bytes its signed choice names. `entry` is the
    VERIFIED choice (from choices()); the store is never read again here (no swap between the two reads)."""
    data = repo.safe(root, "run/sync/choices/" + path).read_bytes()
    if not isinstance(entry, dict) or entry.get("sha256") != hashlib.sha256(data).hexdigest():
        drop_choice(root, path)  # the chosen bytes were changed: that choice is gone
        raise Pause(f"{Path(path).name} changed after your choice; choose again", [path])
    return data


def drop_choice(root, path):
    """Forget the choice for `path` (it is asked again). A store of any other shape is reset."""
    from . import step

    store = cli.read(root, "choices")
    files = store.get("files") if isinstance(store.get("files"), dict) else {}
    files.pop(path, None)
    step.write(root, "run/sync/choices.json", step.encoded({**store, "files": files}))


def checked_tree(root, remote, index):
    """Substitute only explicit decisions before checking the whole incoming tree again."""
    from . import step

    decisions = choices(root, remote)
    if not decisions:
        return remote
    repo.git(root, "read-tree", remote, index=index)
    for path in decisions:
        if decisions[path].get("keep") == LOCAL_NAME:
            _keep_local_name(root, remote, index, path, decisions[path])
            continue
        data = selected(root, path, decisions[path])
        live = repo.safe(root, path)
        if decisions[path].get("incoming"):
            changed = paths.TICKET.fullmatch(path) and live.exists()
        else:
            changed = not live.exists() or live.read_bytes() != data
        if changed:
            # Fable B7: the file moved on after the choice. Drop that one choice and ask again, never refuse
            # every later run (the path is no longer paused, so it could not be chosen again).
            drop_choice(root, path)
            raise Pause(f"{Path(path).name} changed after your choice; choose again", [path])
        step.put(root, index, path, data)
    tree = repo.git(root, "write-tree", index=index).stdout.decode().strip()
    at = next((e.get("at") for e in decisions.values() if isinstance(e.get("at"), str)), None)
    return step.commit(root, tree, [remote], at or datetime.now(UTC).isoformat().replace("+00:00", "Z"))


LOCAL_NAME = "local-name"
CASE_PROBLEM = "Same name as a local file in different case"  # incoming.check


def _keep_local_name(root, remote, index, path, decision):
    """A person kept this machine's file name: the remote's case variant `path` is not applied (left out of
    the checked tree), and this machine's file is left as the merge base had it, so the remote side changes
    nothing about it (a remote case-only rename is not a deletion here)."""
    from . import step

    local = decision.get("local")
    if not isinstance(local, str) or not paths.allowed(local) or not repo.safe(root, local).is_file():
        # The local file moved on after the choice: ask again (Fable B7), never refuse every later run.
        drop_choice(root, path)
        raise Pause(f"{Path(path).name} changed after your choice; choose again", [path])
    repo.git(root, "update-index", "--force-remove", "--", path, index=index)
    common = repo.git(root, "merge-base", "HEAD", remote, allowed_codes=(0, 1, 128)).stdout.decode().strip()
    base = step.entries(root, common or None).get(local) if common else None
    if base:
        repo.git(root, "update-index", "--add", "--cacheinfo", f"100644,{base[1]},{local}", index=index)
    else:
        repo.git(root, "update-index", "--force-remove", "--", local, index=index)


ALLOWED_PROBLEMS = ("held-ext", "needs-confirm", "cannot-check")


def blocking(checked, path=None):
    """Fable B6: every incoming problem blocks a choice except an explicit allowlist, and except a content
    problem on the very file being chosen (the choice is what settles it; theirs is rescanned below)."""
    return [
        p
        for p in checked.problems
        if p.code not in ALLOWED_PROBLEMS
        and not (path and p.path == path and p.code not in ("path", "size", "private"))
    ]


def findings(root, path, data):
    """What blocks `data`: a cannot-check finding counts as settled only by this core's signed record that a
    person allowed exactly these bytes at exactly this path (records "file")."""
    approved = cli.read(root, "checked-files")
    hashed = hashlib.sha256(data).hexdigest()
    allowed = records.ok(root, "file", f"{path}:{hashed}", approved.get(path))
    return [f for f in scan.scan_blob(path, data) if f.code != "cannot-check" or not allowed]


def local_decisions(doc, local):
    """A chosen remote ticket with what only this machine decides taken from its own copy: the key and old
    keys (ext.sync) and Done (a peer's Done never becomes Done here by a choice). The peer's Won't do,
    verdict and approval fields stay as they came: the caller merges the chosen copy as the REMOTE side
    (merge_document(local, local, chosen)), so the receiving core's verifiers decide each one and an
    unverified one stays unverified (Fable B2). Nothing in the chosen copy becomes locally trusted."""
    out = {k: v for k, v in doc.items() if k != "key"}
    out.update({k: local[k] for k in ("key",) if k in local})
    if out.get("status") == "done" and local.get("status") != "done":
        out["status"] = local.get("status", "review")
    ext = dict(out["ext"]) if isinstance(out.get("ext"), dict) else {}
    if isinstance(local.get("ext"), dict) and "sync" in local["ext"]:
        ext["sync"] = local["ext"]["sync"]
    else:
        ext.pop("sync", None)
    if ext or "ext" in out:
        out["ext"] = ext
    return out


def resolve(root, path, keep, args=None, *, now=None):
    from . import step

    now = now or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    with step.step_lock(root):
        state = cli.read(root, "state")
        paused = state["paused"] = verified_pause(root, state)
        if not paths.allowed(path) or not paused or path not in paused["files"]:
            raise repo.Refused("This file is not waiting for a choice")
        if any(path == f"tickets/{t['id']}.json" for group in paused.get("key_clashes", {}).values() for t in group):
            raise repo.Refused("Use orch sync keep-key for a ticket number clash")
        if path in (paused.get("case_names") or {}):
            # On a disk that ignores case, either copy would overwrite the other file.
            raise repo.Refused("Use --keep-local-name or --rename-local <new name>: the names differ only in case")
        settings = cli.DEFAULTS | cli.read(root, "settings")
        remote = paused["remote_sha"]
        if settings["mode"] == "remote":
            if not cli.remote_allowed():
                raise repo.Refused("Remote sync is preview-only")
            repo.set_remote(root, cli.confirmed_remote(root, settings))  # checks the repository too
            repo.fetch(root)
            current = step.oid(root, "refs/remotes/origin/orch-state")
            if current != remote:
                state["paused"] = None
                step.write(root, "run/sync/state.json", step.encoded(state))
                result = step._run(root, "remote changed; review again", now, True)
                return result | {"review_again": True}
        if cli.read(root, "theirs").get("remote_sha") != remote:
            raise repo.Refused("Saved copy is no longer current")
        # Check original incoming content even for Keep mine. Unsafe unrelated files still block.
        checked = incoming.check(root, remote, base=None) if remote else None
        if checked and (checked.commit != remote or blocking(checked, path)):
            raise repo.Refused("Incoming files could not be checked")
        with (
            syncgate.hold(root),
            tickets.sync_apply(
                root, Path(path).parts[1].removesuffix(".json") if path.startswith("tickets/") else "key"
            ),
        ):
            live = repo.safe(root, path)
            head = step.blob(root, step.entries(root, "HEAD").get(path))
            mine = live.read_bytes() if live.exists() else head
            saved = repo.safe(root, "run/sync/theirs/" + path)
            theirs = saved.read_bytes() if saved.exists() else None
            if remote and theirs != step.blob(root, step.entries(root, remote).get(path)):
                raise repo.Refused("Saved copy does not match the checked version")
            data = mine if keep == "mine" else theirs
            # Choosing a deletion means keep the surviving copy. Resolve never deletes.
            data = data if data is not None else mine or theirs
            if data is None:
                raise repo.Refused("There is no surviving file to keep")
            issues = findings(root, path, data)
            if issues:
                if any(f.code != "cannot-check" for f in issues):
                    raise repo.Refused("This copy contains a secret or cannot be accepted; edit it first")
                hashed = hashlib.sha256(data).hexdigest()
                by = humanproof.person_by(
                    root,
                    args,
                    "addon.act",
                    "sync:file:" + hashed,
                    no_handoff="Allowing this file needs a person's proof over stdin.",
                )
                config.require_person(by, "allow this unchecked file")
                approved = cli.read(root, "checked-files")
                approved[path] = records.make(root, "file", f"{path}:{hashed}", {"path": path, "sha256": hashed})
                step.write(root, "run/sync/checked-files.json", step.encoded(approved))
            covers = None
            if paths.TICKET.fullmatch(path):
                doc = step.document(path, data)
                try:
                    local = step.document(path, mine) if mine else {}
                except (ValueError, RecursionError):
                    if keep == "mine":
                        raise
                    local = {}  # The raw bytes are retained locally below.
                adopting = keep == "theirs" and data == theirs and mine != data
                if adopting:
                    # Fable B2: adopting a peer's ticket is a person's decision, bound to these exact bytes.
                    by = humanproof.person_by(
                        root,
                        args,
                        "addon.act",
                        "sync:keep-theirs:" + hashlib.sha256(path.encode() + b"\0" + data).hexdigest(),
                        no_handoff="Keeping their copy of a ticket needs a person's proof over stdin.",
                    )
                    config.require_person(by, "keep their copy of this ticket")
                    doc = local_decisions(doc, local)
                # The chosen copy is the remote side of a merge whose base and local side are this machine's
                # copy: its plain fields win, while the receiving core's verifiers decide every Won't do and
                # verdict, its remote-only history lines are demoted (merge.py), and held ext stays held.
                doc = step.merge_document(root, path, local, local, doc, now)
                if adopting:
                    raw = mine or b"{}"
                    backup = "run/sync/mine/" + path + "-" + hashlib.sha256(raw).hexdigest()
                    step.write(root, backup, raw)
                    summary = (
                        "Previous copy kept locally."
                        if scan.scan_blob(path, raw)
                        else raw.decode("utf-8", errors="replace")[:2000]
                    )
                    doc.setdefault("history", []).append(
                        {
                            "at": now,
                            "by": "agent:sync",
                            "text": "sync: my version before sync kept here: "
                            + summary
                            + f" (full copy: {backup})",
                        }
                    )
                data = data if doc == incoming.strict_load(data) else step.encoded(doc)
                step.document(path, data)
            elif path == "ticket-counter.json":
                # Fable B9: a counter only ever goes up and keeps its strict shape, whichever copy is chosen.
                from . import merge

                docs = [step.document(path, d) for d in (mine, theirs) if d is not None]
                jump = paused.get("reason") == JUMP
                if keep == "theirs" and len(docs) == 2:
                    data = step.encoded(merge.merge_counter({}, *docs))
                step.document(path, data)
                # Everything that can refuse runs before the proof, so a refusal never uses it up (LOW-4).
                # The person's proven choice covers the incoming numbers they reviewed (a far key included).
                covers = step.top_number(root, remote) if jump and remote else None
                if keep == "theirs" or jump:
                    # M3: numbers only go up, so their counter (or clearing a jump at all) is a person's
                    # decision, bound to the reviewed remote commit.
                    by = humanproof.person_by(
                        root,
                        args,
                        "addon.act",
                        f"sync:keep-{keep}-counter:{remote}",
                        no_handoff="Choosing the ticket counter needs a person's proof over stdin.",
                    )
                    config.require_person(by, "choose the ticket counter")
            elif paths.ARTIFACT.fullmatch(path) and keep == "theirs" and mine is not None and mine != data:
                # No overwrite even on retries or two choices on the same day.
                suffix = f" (mine {now[:10]})"
                original = Path(path)
                backup = str(original.with_name(original.stem[:60] + suffix + original.suffix[:20]))
                n = 1
                while repo.safe(root, backup).exists() and repo.safe(root, backup).read_bytes() != mine:
                    n += 1
                    backup = str(
                        original.with_name(original.stem[:55] + suffix + f" {n}" + original.suffix[:20])
                    )
                step.write(root, backup, mine)
            decisions = cli.read(root, "choices")
            if not decisions or decisions.get("remote_sha") != remote or not isinstance(decisions.get("files"), dict):
                decisions = {"remote_sha": remote, "files": {}}
            step.write(root, "run/sync/choices/" + path, data)
            fields = {"keep": keep, "at": now, **({"covers": covers} if covers is not None else {})}
            record_choice(root, decisions, remote, path, fields, data)  # covers is inside the signature
            step.write(root, "run/sync/choices.json", step.encoded(decisions))
            step.write(root, path, data)
            paused["files"].remove(path)
            state["paused"] = sign(root, paused) if paused["files"] else None  # changed by core: signed again
            step.write(root, "run/sync/state.json", step.encoded(state))
        if state["paused"]:
            return state
        return step._run(root, "resolved", now, cli.remote_allowed())


def resolve_sides(root, path):
    """(paused, remote, mine, theirs) read as resolve reads them, once, for the proof target AND the sign step's
    review. The saved copy (run/sync/theirs/<path>, agent-writable) counts only when it is exactly the blob of the
    signed pause's remote commit, as resolve checks it (L3): otherwise nothing is offered for signing."""
    from . import step

    state = cli.read(root, "state")
    paused = verified_pause(root, state)
    if not paths.allowed(path) or not paused or path not in paused["files"]:
        raise repo.Refused("This file is not waiting for a choice")
    remote = paused["remote_sha"]
    if remote is not None and (not isinstance(remote, str) or not remote):  # only None means "no remote version"
        raise repo.Refused("Saved copy does not match the checked version")
    live = repo.safe(root, path)
    head = step.blob(root, step.entries(root, "HEAD").get(path))
    mine = live.read_bytes() if live.exists() else head
    saved = repo.safe(root, "run/sync/theirs/" + path)
    theirs = saved.read_bytes() if saved.exists() else None
    if remote is None:  # a pause before any remote version (first push, local mode): no saved copy can be checked (L-3)
        if theirs is not None:
            raise repo.Refused("Saved copy does not match the checked version")
    elif theirs != step.blob(root, step.entries(root, remote).get(path)):
        raise repo.Refused("Saved copy does not match the checked version")
    return paused, remote, mine, theirs


def resolve_target(root, path, keep, sides=None):
    """The proof `resolve(root, path, keep)` will ask for, worked out the same way and without changing anything;
    None when that choice needs no proof. The dashboard mints exactly this target (a stale one simply fails).
    `sides`: resolve_sides() already read for the review the person is shown (the same bytes)."""
    paused, remote, mine, theirs = sides or resolve_sides(root, path)
    data = mine if keep == "mine" else theirs
    data = data if data is not None else mine or theirs
    if data is None:
        return None
    issues = findings(root, path, data)
    if issues and all(f.code == "cannot-check" for f in issues):
        return "sync:file:" + hashlib.sha256(data).hexdigest()
    if paths.TICKET.fullmatch(path) and keep == "theirs" and data == theirs and mine != data:
        return "sync:keep-theirs:" + hashlib.sha256(path.encode() + b"\0" + data).hexdigest()
    if path == "ticket-counter.json" and (keep == "theirs" or paused.get("reason") == JUMP):
        return f"sync:keep-{keep}-counter:{remote}"
    return None


def left_bytes(root, path):
    """The file on this computer a person may leave out: an artifact only (a ticket is edited instead)."""
    if not paths.ARTIFACT.fullmatch(path):
        raise repo.Refused("Only a file of a ticket can be left out; edit the ticket to take out the password or key")
    live = repo.safe(root, path)
    if repo.is_link(live) or not live.is_file():
        raise repo.Refused("Only a file on this computer can be left out")
    return live.read_bytes()


def leave_out_target(root, path, data=None):
    """The proof target of Leave it out: the path and the exact bytes left out (changed content asks again).
    `data`: left_bytes() already read for the review the person is shown."""
    data = left_bytes(root, path) if data is None else data
    return "sync:leave-out:" + hashlib.sha256(path.encode() + b"\0" + data).hexdigest()


def left_out(root, path, data):
    """True when a person left exactly these bytes at this path out of sync (signed record "left-out")."""
    entry = cli.read(root, "left-out").get(path)
    return records.ok(root, "left-out", f"{path}:{hashlib.sha256(data).hexdigest()}", entry)


def left_out_names(root):
    """The paths a person left out (signed records only), for the "not synced" list."""
    out = []
    for path, entry in sorted(cli.read(root, "left-out").items()):
        hashed = entry.get("sha256") if isinstance(entry, dict) else None
        if isinstance(path, str) and isinstance(hashed, str) and records.ok(root, "left-out", f"{path}:{hashed}", entry):
            out.append(path)
    return out


def leave_out(root, path, args, *, now=None):
    """Not synced, by a person's choice: a file of this computer that may contain a password or access key stays
    here only. Bound to its bytes; the pause for it ends and sync looks again."""
    from . import step

    now = now or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    with step.step_lock(root):
        state = cli.read(root, "state")
        paused = state["paused"] = verified_pause(root, state)
        if not paths.allowed(path) or not paused or path not in paused["files"] or "secret" not in paused["reason"]:
            raise repo.Refused("This file is not waiting for a choice")
        data = left_bytes(root, path)
        hashed = hashlib.sha256(data).hexdigest()
        by = humanproof.person_by(
            root,
            args,
            "addon.act",
            "sync:leave-out:" + hashlib.sha256(path.encode() + b"\0" + data).hexdigest(),
            no_handoff="Leaving a file out of sync needs a person's proof over stdin.",
        )
        config.require_person(by, "leave this file out of sync")
        left = cli.read(root, "left-out")
        left[path] = records.make(root, "left-out", f"{path}:{hashed}", {"path": path, "sha256": hashed})
        step.write(root, "run/sync/left-out.json", step.encoded(left))
        paused["files"].remove(path)
        state["paused"] = sign(root, paused) if paused["files"] else None
        step.write(root, "run/sync/state.json", step.encoded(state))
    if state["paused"]:
        return state
    return step.run_once(root, "left a file out", now=now)


def take_target(remote, tree):
    """The proof target of take-remote: the reviewed remote commit AND the exact tree that will be applied."""
    return f"sync:take-remote:{remote}:{tree}"


def take_remote(root, args, *, now=None):
    """A person's way out of a HISTORY pause (several or no merge bases): take the other computer's history as
    the new base. Everything goes through the normal merge authority (step.taken_tree); every check that can
    refuse runs BEFORE the proof, and the proof is bound to the exact tree that is then applied."""
    import tempfile

    from . import step

    now = now or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    with step.step_lock(root):
        state = cli.read(root, "state")
        paused = verified_pause(root, state)
        if not paused or paused.get("kind") != HISTORY:
            raise repo.Refused("Sync is not waiting for this choice")
        remote = paused["remote_sha"]
        settings = cli.DEFAULTS | cli.read(root, "settings")
        if settings["mode"] == "remote":
            if not cli.remote_allowed():
                raise repo.Refused("Remote sync is preview-only")
            repo.check(root)
            repo.set_remote(root, cli.confirmed_remote(root, settings))
            repo.fetch(root)
            if step.oid(root, "refs/remotes/origin/orch-state") != remote:
                state["paused"] = None
                step.write(root, "run/sync/state.json", step.encoded(state))
                result = step._run(root, "remote changed; review again", now, True)
                return result | {"review_again": True}
        checked = incoming.check(root, remote, base=None) if remote else None
        if not checked or checked.commit != remote or blocking(checked):
            raise repo.Refused("Incoming files could not be checked")
        scratch = repo.safe(root, "run/tmp-sync")
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            index = Path(folder) / "index"
            with syncgate.hold(root):
                head = step.oid(root, "HEAD")
                tree = step.stage(root, head, index, state, now)  # this machine's live files are the base
                if not head or tree != step.oid(root, head + "^{tree}"):
                    new = step.commit(root, tree, [head], now)
                    repo.git(root, "update-ref", "refs/heads/orch-state", new, head or "0" * 40)
                    head = new
                repo.git(root, "read-tree", head, index=index)  # the temp index (apply sets the default one)
            tree, merges = step.taken_tree(root, head, remote, index, now)
            by = humanproof.person_by(
                root,
                args,
                "addon.act",
                take_target(remote, tree),
                no_handoff="Taking the other computer's history needs a person's proof over stdin.",
            )
            config.require_person(by, "take the other computer's history")
            new = step.commit(root, tree, [head, remote], now)
            step.write(
                root,
                "run/sync/pending.json",
                step.encoded({"old": head, "new": new, "url": settings.get("remote"), "remote": remote,
                              "merges": merges}),
            )
            with syncgate.hold(root):
                step.apply(root, head, new, state, merges)
            repo.safe(root, "run/sync/pending.json").unlink()
        state["paused"] = None
        step.write(root, "run/sync/state.json", step.encoded(state))
    return step._run(root, "took the other computer's history", now, cli.remote_allowed())


def case_target(path, remote, target=None):
    """The proof target of a name choice: bound to the incoming name, the reviewed remote and the new name."""
    parts = [path, str(remote), target] if target else [path, str(remote)]
    digest = hashlib.sha256("\0".join(parts).encode()).hexdigest()
    return f"sync:case-rename:{digest}" if target else f"sync:case-keep:{digest}"


def resolve_case(root, path, args, *, rename=None, now=None):
    """A person's way out of a name that differs from this machine's only in case (`path` = the incoming name;
    on a disk that ignores case both are one file). Keep this machine's file name: the other computer's variant
    is not applied while the remote stays at the reviewed commit (it is reported each time; a new remote commit
    asks again). Or rename this machine's file (`rename`: a new file name in the same folder): then both
    arrive. Bound to the reviewed remote commit, the path and the new name; agents are refused."""
    import os

    from . import step

    now = now or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    with step.step_lock(root):
        state = cli.read(root, "state")
        paused = state["paused"] = verified_pause(root, state)
        case = (paused or {}).get("case_names") or {}
        if not paused or path not in paused["files"] or path not in case:
            raise repo.Refused("This file has no name clash waiting for a choice")
        local = case[path]
        if not isinstance(local, str) or not paths.allowed(local) or not repo.safe(root, local).is_file():
            raise repo.Refused("Your file is no longer there; run sync again")
        remote = paused["remote_sha"]
        settings = cli.DEFAULTS | cli.read(root, "settings")
        if settings["mode"] == "remote":
            if not cli.remote_allowed():
                raise repo.Refused("Remote sync is preview-only")
            repo.set_remote(root, cli.confirmed_remote(root, settings))  # checks the repository too
            repo.fetch(root)
            if step.oid(root, "refs/remotes/origin/orch-state") != remote:
                state["paused"] = None
                step.write(root, "run/sync/state.json", step.encoded(state))
                result = step._run(root, "remote changed; review again", now, True)
                return result | {"review_again": True}
        target = None
        if rename is not None:
            name = str(rename)
            if not name or name in (".", "..") or name != name.strip() or any(c in name for c in "/\\\0"):
                raise repo.Refused("Give a new file name, without folders")
            if not paths.ARTIFACT.fullmatch(local):
                raise repo.Refused("Only a ticket's files can be renamed")
            folder = local.rsplit("/", 1)[0]
            target = f"{folder}/{name}"
            if not paths.allowed(target) or not paths.ARTIFACT.fullmatch(target):
                raise repo.Refused("This name cannot be synced; choose another")
            taken = {incoming._fold(p) for p in (*step.entries(root, "HEAD"), *step.entries(root, remote))}
            taken |= {incoming._fold(f"{folder}/{f.name}") for f in repo.safe(root, folder).iterdir()}
            if incoming._fold(target) in taken:
                raise repo.Refused("A file with this name (in any case) is already there; choose another")
        by = humanproof.person_by(
            root,
            args,
            "addon.act",
            case_target(path, remote, target),
            no_handoff="Choosing a file name needs a person's proof over stdin.",
        )
        config.require_person(by, "choose a file name")
        with syncgate.hold(root), tickets.sync_apply(root, local.split("/")[1].removesuffix(".json")):
            if target:
                source, dest = repo.safe(root, local), repo.safe(root, target)
                if os.path.lexists(dest):
                    raise repo.Refused("A file with this name is already there; choose another")
                os.rename(source, dest)
                renamed = cli.read(root, "renamed")
                renamed[local] = target
                step.write(root, "run/sync/renamed.json", step.encoded(renamed))
            else:
                decisions = cli.read(root, "choices")
                if decisions.get("remote_sha") != remote or not isinstance(decisions.get("files"), dict):
                    decisions = {"remote_sha": remote, "files": {}}
                record_choice(root, decisions, remote, path, {"keep": LOCAL_NAME, "local": local, "at": now})
                step.write(root, "run/sync/choices.json", step.encoded(decisions))
            paused["files"].remove(path)
            case.pop(path)
            state["paused"] = sign(root, paused) if paused["files"] else None  # changed by core: signed again
            step.write(root, "run/sync/state.json", step.encoded(state))
        if state["paused"]:
            return state
        return step._run(root, "resolved", now, cli.remote_allowed())


def keep_key(root, key, tid, args, *, now=None):
    """A local person's choice, pinned to the reviewed remote and live ticket bytes."""
    # After a hostile rewrite of a known key, each machine keeps its own key until
    # a person runs keep-key on both machines; one machine's choice cannot authorize the other.
    from contextlib import ExitStack

    from . import merge, step

    now = now or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    with step.step_lock(root), syncgate.hold(root), ExitStack() as locks:
        state = cli.read(root, "state")
        paused = state["paused"] = verified_pause(root, state) or {}
        candidates = paused.get("key_clashes", {}).get(key, [])
        if tid not in {t["id"] for t in candidates}:
            raise repo.Refused("No such ticket in this key clash")
        remote = paused["remote_sha"]
        settings = cli.DEFAULTS | cli.read(root, "settings")
        if settings["mode"] == "remote":
            if not cli.remote_allowed():
                raise repo.Refused("Remote sync is preview-only")
            repo.set_remote(root, cli.confirmed_remote(root, settings))  # checks the repository too
            repo.fetch(root)
            if step.oid(root, "refs/remotes/origin/orch-state") != remote:
                raise repo.Refused("Remote changed; review again before choosing a key")
        if cli.read(root, "theirs").get("remote_sha") != remote:
            raise repo.Refused("Saved copy is no longer current")
        checked = incoming.check(root, remote, base=None)
        if any(p.code == "private" for p in checked.problems):
            raise repo.Refused("General ticket stays local")
        if checked.commit != remote or blocking(checked) or any(
            p.path == "ticket-counter.json" for p in checked.problems
        ):
            raise repo.Refused("Incoming files could not be checked")
        by = humanproof.person_by(
            root, args, "addon.act", f"sync:keep-key:{key}:{tid}:{remote}",
            no_handoff="Choosing a ticket number needs a person's proof over stdin.",
        )
        config.require_person(by, "choose a ticket number")
        ours, theirs = step.entries(root, "HEAD"), step.entries(root, remote)
        common = repo.git(root, "merge-base", "HEAD", remote, allowed_codes=(0, 1)).stdout.decode().strip()
        base_rows = step.entries(root, common or None)
        docs, originals = {}, {}
        group = {t["id"] for t in candidates}
        for path in sorted(ours.keys() | theirs.keys()):
            if not paths.TICKET.fullmatch(path):
                continue
            locks.enter_context(tickets.sync_apply(root, Path(path).stem))
            live = repo.safe(root, path)
            raw = live.read_bytes() if live.exists() else None
            originals[path] = raw
            local = step.document(path, raw) if raw else {}
            other = step.document(path, step.blob(root, theirs[path])) if path in theirs else {}
            if local.get("general") is True or other.get("general") is True:
                raise repo.Refused("General ticket stays local")
            doc = local or other
            if local and other and Path(path).stem in group and local != other:
                # Fable B10: keep the peer's edits to a ticket in this group; only the key changes below.
                base = step.document(path, step.blob(root, base_rows[path])) if path in base_rows else {}
                doc = step.merge_document(root, path, base, local, {**other, "key": local.get("key")}, now)
            # Only this person's chosen group may be changed by this decision.
            docs[Path(path).stem] = doc
        locks.enter_context(tickets.sync_apply(root, "key"))
        if any(i not in docs or docs[i].get("key") != key for i in group):
            raise repo.Refused("Ticket numbers changed; review again")
        counter_path = "ticket-counter.json"
        live_counter_path = repo.safe(root, counter_path)
        live_counter = incoming.strict_load(live_counter_path.read_bytes()) if live_counter_path.exists() else {}
        counter = merge.merge_counter(
            {}, live_counter,
            incoming.strict_load(step.blob(root, theirs.get(counter_path)) or b"{}"),
            [k for doc in docs.values() for k in [doc.get("key"), *merge.old_keys_of(doc)]],
        )
        if counter_choice := choices(root, remote).get(counter_path):
            counter = merge.merge_counter(
                {}, counter, incoming.strict_load(selected(root, counter_path, counter_choice))
            )
        selected_docs = {}
        for i in sorted(group):
            doc = docs[i]
            if i != tid:
                path = f"tickets/{i}.json"
                incoming_doc = step.document(path, step.blob(root, theirs[path])) if path in theirs else {}
                incoming_key = incoming_doc.get("key")
                used = {d.get("key") for j, d in docs.items() if j != i}
                if (
                    isinstance(incoming_key, str)
                    and incoming_key != key
                    and key in merge.old_keys_of(incoming_doc)
                    # Fable B9: the peer's number must be this prefix, unused here and within reach of the
                    # counter; otherwise allocate locally.
                    and incoming_key.rsplit("-", 1)[0] == key.rsplit("-", 1)[0]
                    and 0 < merge._key_n(incoming_key) <= counter["last"] + 1
                    and incoming_key not in used
                ):
                    new = incoming_key
                else:
                    counter["last"] += 1
                    if counter["last"] > merge.MAX_COUNTER:
                        raise repo.Refused("Ticket counter exhausted")
                    new = f"{key.rsplit('-', 1)[0]}-{counter['last']}"
                doc.setdefault("ext", {}).setdefault("sync", {})["old_keys"] = sorted(set(merge.old_keys_of(doc)) | {key})
                doc["key"] = new
                line = {"at": now, "by": by, "text": f"sync: key changed from {key} to {new} (person chose {tid})"}
                if line not in doc.setdefault("history", []):
                    doc["history"].append(line)
            path = f"tickets/{i}.json"
            data = step.encoded(doc)
            step.document(path, data)
            if findings(root, path, data):
                raise repo.Refused("Ticket cannot be accepted; edit it first")
            selected_docs[path] = data
        keys = [docs[i].get("key") for i in group]
        other_keys = {doc.get("key") for i, doc in docs.items() if i not in group}
        if len(keys) != len(set(keys)) or any(k in other_keys for k in keys):
            raise repo.Refused("The chosen numbers conflict with another ticket")
        decisions = cli.read(root, "choices")
        if decisions.get("remote_sha") != remote or not isinstance(decisions.get("files"), dict):
            decisions = {"remote_sha": remote, "files": {}}
        selected_docs[counter_path] = step.encoded(counter)
        # Reserve in the live counter too, so offline ticket creation cannot reuse a
        # selected number. Only reserve this decision's keys, never remote counter fields.
        allocated_max = max(int(k.rsplit("-", 1)[1]) for k in keys)
        live_reservation = step.encoded({**live_counter, "last": max(live_counter.get("last", 0), allocated_max)})
        # Save the reservation first and move local losers before resuming the merge.
        # Remote-only tickets stay in sync state until the verified incoming merge.
        order = [counter_path] + [p for p in selected_docs if p not in (counter_path, f"tickets/{tid}.json")] + [f"tickets/{tid}.json"]
        for path in order:
            data = selected_docs[path]
            step.write(root, "run/sync/choices/" + path, data)
            is_incoming = path == counter_path or originals[path] is None
            if path == counter_path or not is_incoming:
                step.write(root, path, live_reservation if path == counter_path else data)
            record_choice(root, decisions, remote, path, {"keep": "key", "at": now, "incoming": is_incoming}, data)
        step.write(root, "run/sync/choices.json", step.encoded(decisions))
        paused["key_clashes"].pop(key)
        paused["files"] = [p for p in paused["files"] if p not in selected_docs]
        state["paused"] = sign(root, paused) if paused["files"] else None  # changed by core: signed again
        step.write(root, "run/sync/state.json", step.encoded(state))
    return state if state["paused"] else step._run(root, "key chosen", now, cli.remote_allowed())
