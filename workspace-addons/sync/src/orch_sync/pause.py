"""Keep both until an explicit resolution; decisions are pinned to one remote commit."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from orch import config, humanproof, syncgate, tickets

from . import cli, incoming, paths, repo, scan


class Pause(repo.Refused):
    def __init__(self, reason, files=()):
        super().__init__(reason)
        self.files = list(files)


def capture(root, state, error, remote, now):
    from . import step

    ours = step.entries(root, step.oid(root, "HEAD"))
    theirs = step.entries(root, remote)
    files = error.files or sorted(p for p in ours.keys() | theirs.keys() if ours.get(p) != theirs.get(p))
    files = sorted({p for p in files if paths.allowed(p)})
    state["paused"] = {"files": files, "since": now, "remote_sha": remote, "reason": str(error)}
    # Manifest is written last by the step. Saved bytes are never used without matching its sha.
    for path in files:
        data = step.blob(root, theirs.get(path))
        target = repo.safe(root, "run/sync/theirs/" + path)
        if data is not None:
            step.write(root, "run/sync/theirs/" + path, data)
        else:
            target.unlink(missing_ok=True)
    step.write(root, "run/sync/theirs.json", step.encoded({"remote_sha": remote}))


def choices(root, remote):
    data = cli.read(root, "choices")
    return data.get("files", {}) if data.get("remote_sha") == remote else {}


def selected(root, path):
    return repo.safe(root, "run/sync/choices/" + path).read_bytes()


def checked_tree(root, remote, index):
    """Substitute only explicit decisions before checking the whole incoming tree again."""
    from . import step

    decisions = choices(root, remote)
    if not decisions:
        return remote
    repo.git(root, "read-tree", remote, index=index)
    for path in decisions:
        data = selected(root, path)
        live = repo.safe(root, path)
        if not live.exists() or live.read_bytes() != data:
            raise repo.Refused(f"{path}: busy; the selected copy changed")
        step.put(root, index, path, data)
    tree = repo.git(root, "write-tree", index=index).stdout.decode().strip()
    return step.commit(root, tree, [remote], decisions[next(iter(decisions))]["at"])


def findings(root, path, data):
    approved = cli.read(root, "checked-files")
    return [
        f
        for f in scan.scan_blob(path, data)
        if f.code != "cannot-check" or approved.get(path) != hashlib.sha256(data).hexdigest()
    ]


def resolve(root, path, keep, args=None, *, now=None):
    from . import step

    now = now or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    with step.step_lock(root):
        state = cli.read(root, "state")
        paused = state.get("paused")
        if not paths.allowed(path) or not paused or path not in paused["files"]:
            raise repo.Refused("This file is not waiting for a choice")
        settings = cli.DEFAULTS | cli.read(root, "settings")
        remote = paused["remote_sha"]
        if settings["mode"] == "remote":
            if not cli.remote_allowed():
                raise repo.Refused("Remote sync is preview-only")
            repo.check(root)
            repo.git(
                root,
                "fetch",
                "--no-tags",
                "--prune",
                "origin",
                "+refs/heads/*:refs/remotes/origin/*",
                timeout=60,
            )
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
        if checked and (
            checked.commit != remote or any(p.code in ("path", "size") for p in checked.problems)
        ):
            raise repo.Refused("Incoming files could not be checked")
        with (
            syncgate.hold(root),
            tickets.sync_apply(
                root, Path(path).parts[1].removesuffix(".json") if path.startswith("tickets/") else "key"
            ),
        ):
            live = repo.safe(root, path)
            mine = (
                live.read_bytes() if live.exists() else step.blob(root, step.entries(root, "HEAD").get(path))
            )
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
                approved[path] = hashed
                step.write(root, "run/sync/checked-files.json", step.encoded(approved))
            if paths.TICKET.fullmatch(path):
                doc = step.document(path, data)
                try:
                    local = step.document(path, mine) if mine else {}
                except (ValueError, RecursionError):
                    if keep == "mine":
                        raise
                    local = {}  # The raw bytes are retained locally below.
                doc = step.held_ticket(root, path, doc, local, doc)
                # Re-run authority-sensitive merge rules; synced human text is never proof.
                doc = step.merge_document(root, path, {}, doc, doc, now)
                doc = step.held_ticket(root, path, doc, local, doc)
                if keep == "theirs" and mine != data:
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
            if not decisions or decisions.get("remote_sha") != remote:
                decisions = {"remote_sha": remote, "files": {}}
            step.write(root, "run/sync/choices/" + path, data)
            decisions["files"][path] = {"keep": keep, "at": now}
            step.write(root, "run/sync/choices.json", step.encoded(decisions))
            step.write(root, path, data)
            paused["files"].remove(path)
            if not paused["files"]:
                state["paused"] = None
            step.write(root, "run/sync/state.json", step.encoded(state))
        if state["paused"]:
            return state
        return step._run(root, "resolved", now, cli.remote_allowed())
