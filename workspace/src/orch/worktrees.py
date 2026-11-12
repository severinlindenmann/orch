"""Separate copies of the project folder: one git worktree per ticket, so two agents never change the
same files.

Words for people are "copy"; underneath it is `git worktree add`. What this module decides and guards:

* WHERE: <orch home>/worktrees/<first 8 of .orch/.local-id>/<ticket id>. The ticket id is checked against the
  ticket id pattern and the resolved path must stay inside <orch home>/worktrees/<ws8>/ (path_for). Copies are
  never inside the project, so the project's `git status` never shows them.
* WHAT git is asked: only argv lists, never a shell, always `-c core.longpaths=true` (Windows) and a timeout.
  The branch is `orch/<ticket>`. Nothing here commits or merges (bring-back is a later step; ID_ARGS is the
  identity that step uses when the person has none).
* THE SPLIT STORE: the tracked `.orch/` of the project (tickets, config) is never written into a copy: the
  copy is checked out with `.orch` marked skip-worktree and left out of the working tree, so an agent's
  `git add -A` in the copy can never commit ticket JSON, and `git status` there stays clean. Every orch
  call of
  the agent goes to the workspace's own store (ORCH_ROOT, set by the spawn sites).
* WHO MAY START ONE: routing (route) runs under one workspace lock together with the claim of the run, so two
  starts at the same moment cannot both decide "the folder is free".
* THE SETUP COMMAND (`workflow.copy_setup`) comes only from the person's per-machine config
(config.copy_setup),
  never from a ticket, an agent or the workspace's committed files, and is split into words (no shell).

The registry (.orch/run/worktrees.json, local, gitignored) says which copies orch made: ticket -> {paths:
[{path, branch, base, sub}], created_at}. `sub` is the workspace's folder below the git top folder (""
when the
workspace is the top): the agent starts in <path>/<sub>. `<ws8>/.owner` holds the workspace folder, for
cleanup. The guarded keys/copies/ registry independently records full workspace ids and paths, signed as
a whole with a home-level key and checked against a separately guarded monotonic counter. Neither a
forged .owner nor an unsigned history entry can authorize orphan removal.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from orch import adapters, addons, config, harness, humanproof, runs, safegit, sharedfolder, tickets
from orch.errors import Refused

REGISTRY = Path(".orch") / "run" / "worktrees.json"
LOCK_ID = "_copies"  # runs.locked(root, LOCK_ID): the workspace-level "decide + create + claim" lock
LOCK_WAIT = 150.0  # a worktree of a big repo can take a while; the lock timeout must outlast GIT_ADD_TIMEOUT
GIT_TIMEOUT = 20
GIT_ADD_TIMEOUT = 60
CREATE_BUDGET = 100.0  # all git time of one _create; LOCK_WAIT must stay above it
SETUP_TIMEOUT = 600
ID_ARGS = ["-c", "user.name=orch", "-c", "user.email=orch@localhost"]  # for commits made by orch (bring-back)
_TID = re.compile(r"t_[a-z0-9]{6,16}")
_WS8 = re.compile(r"[0-9a-f]{8}")


# ---------------------------------------------------------------- git, as argv lists only


_ctx = threading.local()  # per thread: .deadline (end of this _create's git budget) and .root


def _git(
    args: list[str],
    cwd: Path,
    timeout: float = GIT_TIMEOUT,
    data: bytes | None = None,
    strip: bool = True,
    **kw,
):
    """safegit.run, the one way orch runs git here (no hooks, no filters, safe env, absolute git, timeout).
    Inside _create the timeout is also capped by what is left of the creation budget."""
    deadline = getattr(_ctx, "deadline", None)
    if deadline is not None:
        timeout = max(1.0, min(timeout, deadline - time.monotonic()))
    return safegit.run(args, cwd, timeout, data=data, strip=strip, root=getattr(_ctx, "root", None), **kw)


# ---------------------------------------------------------------- where copies live


def _ws8(ws_id: str) -> str:
    if not isinstance(ws_id, str) or not addons.ID_RE.match(ws_id):
        raise Refused("This workspace has no usable id. Nothing was made.")
    return ws_id[:8]


def path_for(ws_id: str, ticket: str, home: Path | None = None) -> Path:
    """<orch home>/worktrees/<ws8>/<ticket>. Refuses an odd workspace id or ticket id, and a result that is
    not inside <orch home>/worktrees/<ws8>/ once resolved (a link in the way, a `..` that slipped through)."""
    if not isinstance(ticket, str) or not _TID.fullmatch(ticket):
        raise Refused(f"'{ticket}' is not a ticket id. Nothing was made.")
    ws8 = _ws8(ws_id)
    base = ((home or addons.home()) / "worktrees").resolve()
    folder = (base / ws8).resolve()
    p = folder / ticket
    try:
        p.resolve().relative_to(folder)
        folder.relative_to(base)
    except ValueError:
        raise Refused(f"The copy of {ticket} would be outside {base}. Nothing was made.") from None
    if p.resolve() == folder or ".." in p.parts:
        raise Refused(f"The copy of {ticket} would be outside {base}. Nothing was made.")
    return p


def copies_dir(root: Path) -> Path | None:
    """<orch home>/worktrees/<ws8> of this workspace, or None when it has no id."""
    wid = addons.workspace_id(root)
    if not wid:
        return None
    return ((addons.home(root) / "worktrees").resolve()) / wid[:8]


def _check_copies_home(home: Path) -> None:
    """Reject an unguarded destination before creating any folders or lock files."""
    guarded = humanproof.guarded_home(home)
    if guarded.resolve() != home.resolve():
        raise Refused("The copies record is outside the guarded home.")


def _copies_key(home: Path, *, create: bool = False) -> bytes:
    """Account/home key, independent of workspace ids and path bindings; never in a copy."""
    _check_copies_home(home)
    humanproof.winacl.no_reparse(home)
    if create:
        home.mkdir(parents=True, exist_ok=True)
    humanproof._check_dir(home)
    d = home / "keys" / "copies"
    if create:
        humanproof._private_dir(d, home)
    else:
        humanproof._check_dir(d.parent)
        humanproof._check_dir(d)
    f = d / "identity.key"
    with humanproof._key_lock(d) if create else contextlib.nullcontext():
        try:
            raw = humanproof._read_guarded(f)
        except FileNotFoundError:
            if not create:
                raise
            humanproof._write_private(f, secrets.token_hex(32) + "\n")
            raw = humanproof._read_guarded(f)
    key = bytes.fromhex(raw.decode("ascii").strip())
    if len(key) != 32:
        raise Refused("The copies identity key is damaged.")
    return key


def _copies_mac(key: bytes, data: dict) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hmac.new(key, raw, hashlib.sha256).hexdigest()


def _copies_store(home: Path, key: bytes) -> tuple[int, dict]:
    """Read guarded state strictly. Only a never-created store may start at zero.

    Caller holds the home copies lock. A verified store one step ahead repairs an
    interrupted counter commit; all other mismatches fail closed.
    Callers must never turn invalid state into an empty registry for a write.
    """
    d = home / "keys" / "copies"
    try:
        raw = humanproof._read_guarded(d / "registry.json")
    except FileNotFoundError:
        if os.path.lexists(d / "counter"):
            raise Refused("The copies identity store is missing.") from None
        return 0, {}
    doc = json.loads(raw)
    counter = json.loads(humanproof._read_guarded(d / "counter"))
    if not isinstance(doc, dict):
        raise Refused("The copies identity store is damaged.")
    data = {k: doc.get(k) for k in ("version", "counter", "entries")}
    mac = doc.get("mac")
    if (
        data["version"] != "orch.copies/2"
        or type(counter) is not int
        or counter < 1
        or type(data["counter"]) is not int
        or data["counter"] not in (counter, counter + 1)
        or not isinstance(mac, str)
        or not re.fullmatch(r"[0-9a-f]{64}", mac)
        or not hmac.compare_digest(mac, _copies_mac(key, data))
        or not isinstance(data["entries"], dict)
    ):
        raise Refused("The copies identity store is damaged or out of date.")
    for ws8, entry in data["entries"].items():
        if (
            not _WS8.fullmatch(ws8)
            or not isinstance(entry, dict)
            or not isinstance(entry.get("main"), str)
            or not Path(entry["main"]).is_absolute()
            or not isinstance(entry.get("workspace_id"), str)
            or not addons.ID_RE.fullmatch(entry["workspace_id"])
            or entry["workspace_id"][:8] != ws8
        ):
            raise Refused("The copies identity store has an invalid identity.")
    if data["counter"] == counter + 1:
        humanproof._write_private(d / "counter", str(data["counter"]) + "\n")
    return data["counter"], data["entries"]


def _save_copies_store(home: Path, key: bytes, counter: int, entries: dict) -> None:
    """Caller holds the home copies lock; guarded atomic replacements, counter last."""
    d = home / "keys" / "copies"
    data = {"version": "orch.copies/2", "counter": counter + 1, "entries": entries}
    doc = {**data, "mac": _copies_mac(key, data)}
    humanproof._write_private(d / "registry.json", json.dumps(doc) + "\n")
    humanproof._write_private(d / "counter", str(counter + 1) + "\n")


def _known_copies(base: Path) -> dict:
    """Only the current, whole-store authenticated mapping is deletion authority."""
    try:
        key = _copies_key(base.parent)
        with runs.locked(base.parent / ".copies-state", "_known_copies"):
            return _copies_store(base.parent, key)[1]
    except (OSError, ValueError, Refused):
        return {}


def _known_main(base: Path, ws8: str) -> str | None:
    entry = _known_copies(base).get(ws8)
    return entry["main"] if entry is not None else None


def _legacy_copies_entry(base: Path, ws8: str):
    """Untrusted migration hint only; never used by any deletion/listing reader."""
    path = base / ".known.json"
    if not os.path.lexists(path):
        return None
    try:
        if path.is_symlink():
            raise ValueError
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError
        if ws8 not in doc:
            return None
        if not isinstance(doc[ws8], str):
            raise ValueError
        return doc[ws8]
    except (OSError, ValueError):
        raise Refused("The legacy copies record cannot be migrated.") from None


def _write_copies_owner(folder: Path, main: str) -> None:
    """Anchor replacement to a no-follow directory fd; never write through an owner link."""
    if os.name != "posix":
        if _is_link(folder) or (folder / ".owner").is_symlink():
            raise Refused("orch cannot use that folder for copies.")
        runs._atomic(folder / ".owner", main + "\n")
        return
    directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = ".owner-" + secrets.token_hex(16)
    try:
        # Refuse an existing link. Replacement itself never follows the destination,
        # even if another process swaps it after this open.
        try:
            owner = os.open(".owner", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            pass
        else:
            os.close(owner)
        fd = os.open(temporary, os.O_NOFOLLOW | os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(main + "\n")
            os.replace(temporary, ".owner", src_dir_fd=directory, dst_dir_fd=directory)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=directory)
    finally:
        os.close(directory)


def _remember_copies(root: Path, folder: Path) -> None:
    wid = addons.workspace_id(root)
    if not wid or _ws8(wid) != folder.name:
        raise Refused("The copies folder does not match this workspace's id.")
    home = folder.parent.parent
    _check_copies_home(home)
    with runs.locked(addons.home(root) / ".copies-state", "_known_copies"):
        try:
            key = _copies_key(home, create=True)
            counter, known = _copies_store(home, key)
        except (OSError, ValueError) as e:
            raise Refused("The copies identity store cannot be read.") from e
        main = str(root.resolve())
        entry = known.get(folder.name)
        old = entry["main"] if entry is not None else None
        if entry is not None:
            if entry["workspace_id"] != wid:
                raise Refused("Another workspace uses the same copy folder.")
        else:
            owner = folder / ".owner"
            if os.path.lexists(owner):
                if (
                    owner.is_symlink()
                    or not owner.is_file()
                    or owner.read_text(encoding="utf-8").strip() != main
                ):
                    raise Refused("Another workspace uses the same copy folder.")
            elif folder.exists() and any(folder.iterdir()):
                raise Refused("The existing copies folder has no matching owner.")
            legacy = _legacy_copies_entry(folder.parent, folder.name)
            if legacy is not None and legacy != main:
                raise Refused("Another workspace uses the same copy folder.")
        if old is not None and old != main:
            _write_copies_owner(folder, main)
        known[folder.name] = {"main": main, "workspace_id": wid}
        _save_copies_store(home, key, counter, known)


def _known_gone(d: Path, known: dict | None = None) -> bool:
    """The marker agrees with a signed historical identity, and that workspace is gone. `known`: the store
    already read by a caller that holds the copies-state lock (so this does not take that lock again)."""
    try:
        if known is None:
            main = _known_main(d.parent, d.name)
        else:
            entry = known.get(d.name)
            main = entry["main"] if entry is not None else None
        if main is None:
            return False
        owner = d / ".owner"
        if owner.is_symlink() or owner.read_text(encoding="utf-8").strip() != main:
            return False
        if addons.workspace_id(Path(main)) is not None:
            return False
        return not os.path.lexists(main)
    except (OSError, ValueError, RuntimeError):
        return False


def _safe_sub(sub) -> bool:
    """`sub` (the workspace's folder below the git top): a plain relative path, no anchor, drive or `..`."""
    if sub in (None, ""):
        return True
    if not isinstance(sub, str) or "\0" in sub or len(sub) > 1000:
        return False
    p = PurePosixPath(sub.replace("\\", "/"))
    return not p.is_absolute() and ".." not in p.parts and not re.match(r"^[A-Za-z]:", sub)


def work_dir(entry: dict) -> Path:
    """Where the agent starts for a registry entry: the copy of the git top folder, plus `sub`. Refused if
    `sub`
    is not a plain relative path or the result resolves outside the copy (the registry is a local file other
    processes can write). NOTE for all readers of `ticket.work.folders`: it is a record for people (branch,
    base, sub, host); no code resolves a path from it. Paths come from path_for() and the registry only."""
    top = Path(entry["path"])
    sub = entry.get("sub") or ""
    if not _safe_sub(sub):
        raise Refused("The saved folder of this copy is not usable.")
    out = top / sub if sub else top
    try:
        out.resolve().relative_to(top.resolve())
    except (ValueError, OSError, RuntimeError):
        raise Refused("The saved folder of this copy is not usable.") from None
    return out


# ---------------------------------------------------------------- registry (always under the lock)


def _registry_path(root: Path) -> Path:
    return root / REGISTRY


def registry(root: Path) -> dict:
    """{ticket: {paths: [{path, branch, base, sub}], created_at}}; anything malformed is left out."""
    try:
        doc = json.loads(_registry_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    raw = doc.get("tickets") if isinstance(doc, dict) else None
    out: dict = {}
    for tid, v in (raw or {}).items():
        if not (isinstance(tid, str) and _TID.fullmatch(tid) and isinstance(v, dict)):
            continue
        paths = [
            p
            for p in (v.get("paths") or [])
            if isinstance(p, dict)
            and isinstance(p.get("path"), str)
            and isinstance(p.get("branch"), str)
            and _safe_sub(p.get("sub"))
        ]
        if paths:
            out[tid] = {"paths": paths, "created_at": v.get("created_at")}
    return out


def _save_registry(root: Path, reg: dict) -> None:
    runs._atomic(
        _registry_path(root),
        json.dumps({"schema": "orch.worktrees/1", "tickets": reg}, indent=2, ensure_ascii=False) + "\n",
    )


def count(root: Path) -> int:
    """How many registered copy folders currently exist (not vanished registry paths)."""
    return sum(Path(e["path"]).is_dir() for v in registry(root).values() for e in v["paths"])


@contextlib.contextmanager
def start_lock(root: Path):
    """The workspace-level lock around "decide where this run works, make the copy, claim the run".
    Without it two
    starts at the same moment would both see a free folder. It is the run lock of the pseudo ticket
    `_copies`."""
    with runs.locked(root, LOCK_ID, wait=LOCK_WAIT):
        yield


def is_orch_copy(path: Path) -> bool:
    """True for a folder inside a copy orch made: under <orch home>/worktrees/<ws8>/<ticket>, with `.owner`
    naming a workspace whose id starts with ws8 and whose registry lists that ticket's copy. (The agent
    adapters ask this before they mark such a folder trusted; the person's consent was for the workspace.)"""
    try:
        p = Path(path).resolve()
    except (OSError, RuntimeError):
        return False
    for h in addons.home_candidates():
        base = (h / "worktrees").resolve()
        try:
            parts = p.relative_to(base).parts
        except ValueError:
            continue
        if len(parts) < 2 or not _WS8.fullmatch(parts[0]) or not _TID.fullmatch(parts[1]):
            continue
        try:
            main = Path((base / parts[0] / ".owner").read_text(encoding="utf-8").strip())
            wid = addons.workspace_id(main)
            if not main.is_absolute() or not wid or wid[:8] != parts[0] or not (main / ".orch").is_dir():
                continue
            mine = (base / parts[0] / parts[1]).resolve()
            ent = registry(main).get(parts[1])
            if ent and any(Path(e["path"]).resolve() == mine for e in ent["paths"]):
                return True
        except (OSError, ValueError, RuntimeError):
            continue
    return False


def _mine(root: Path, ticket: str, e: dict) -> bool:
    """This registry entry is THE copy of this ticket: its path is exactly path_for(this workspace, ticket)
    (resolved), it is there, and it is a copy orch made. A forged registry line cannot point ticket A at the
    copy of ticket B or of another workspace."""
    try:
        want = path_for(addons.workspace_id(root) or "", ticket, addons.home(root))
        p = Path(e["path"])
        return p.resolve() == want.resolve() and p.is_dir() and is_orch_copy(p)
    except (Refused, OSError, RuntimeError, KeyError):
        return False


def workdir_for(root: Path, rec: dict | None, ticket: str | None = None) -> Path:
    """The folder a run works in: its record's `folder` when that is exactly THIS ticket's copy
    (path_for(workspace id, ticket), resolved, and a copy orch made), else the root. `ticket`: the run's real
    ticket id when the caller has it (preferred over the record's). A forged or synced record (another
    ticket's copy, another workspace's, an edited path) is ignored."""
    try:
        f = (rec or {}).get("folder")
        if not isinstance(f, str) or not f:
            return root
        p = Path(f).resolve()
        if p == root.resolve():
            return root
        tid = ticket if ticket is not None else (rec or {}).get("ticket")
        wid = addons.workspace_id(root)
        if not (isinstance(tid, str) and tid and wid):
            return root
        want = path_for(wid, tid, addons.home(root))
        if p == want.resolve() and p.is_dir() and is_orch_copy(p):
            return p
    except (OSError, ValueError, RuntimeError, TypeError, AttributeError, Refused):
        pass
    return root


# ---------------------------------------------------------------- make one


def _repo(root: Path) -> tuple[Path, str, str] | None:
    """(git top folder, the workspace's path below it, HEAD commit) or None: no git, no commit, or git
    unhappy."""
    rc, out, _ = _git(["rev-parse", "--show-toplevel"], root, read_only=True, filters=False)
    if rc != 0 or not out:
        return None
    top = Path(out).resolve()  # git prints forward slashes, also on Windows
    try:
        rel = root.resolve().relative_to(top).as_posix()
    except ValueError:
        return None
    rc, head, _ = _git(["rev-parse", "--verify", "HEAD^{commit}"], root, read_only=True, filters=False)
    if rc != 0 or not re.fullmatch(r"[0-9a-f]{40,64}", head):
        return None
    return top, ("" if rel == "." else rel), head


def _drop_partial(top: Path, dest: Path, branch: str, made_branch: bool) -> None:
    """A copy that did not get finished: take back exactly what this call made (this path, this branch)."""
    # filters stay ON here: `remove` looks at file content (is it dirty?) and must not run a driver either
    _git(["worktree", "remove", "--force", str(dest)], top)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)  # dest is the path_for() path we just made, nothing else
    _git(["worktree", "prune"], top, filters=False)
    if made_branch:
        _git(["branch", "-D", branch], top, filters=False)


def _create(root: Path, ticket: str) -> tuple[dict | None, str]:
    """Make the copy of this ticket within CREATE_BUDGET seconds of git time (see _create_inner)."""
    before = getattr(_ctx, "deadline", None)
    _ctx.deadline = time.monotonic() + CREATE_BUDGET
    try:
        with _scoped(root):
            return _create_inner(root, ticket)
    finally:
        _ctx.deadline = before


def _create_inner(root: Path, ticket: str) -> tuple[dict | None, str]:
    """Make the copy of this ticket (lock held by the caller). (registry entry, "") or (None, why)."""
    wid = addons.workspace_id(root, create=True)
    try:
        dest = path_for(wid or "", ticket, addons.home(root))
    except Refused as e:
        return None, str(e)
    repo = _repo(root)
    if repo is None:
        return None, "This folder is not a git project with at least one commit."
    top, rel, head = repo
    try:
        dest.resolve().relative_to(top)
        return None, "The copy would be inside the project."
    except ValueError:
        pass
    folder = dest.parent
    owner = folder / ".owner"
    try:
        _check_copies_home(folder.parent.parent)
        folder.mkdir(parents=True, exist_ok=True)
        _remember_copies(root, folder)
        if owner.is_symlink():
            return None, "orch cannot use that folder for copies."
        if owner.is_file():
            if owner.read_text(encoding="utf-8").strip() != str(root.resolve()):
                return None, "Another workspace uses the same copy folder."
        else:
            _write_copies_owner(folder, str(root.resolve()))
    except (OSError, Refused) as e:
        return None, f"orch cannot make the copy folder: {e}"
    if dest.exists() or dest.is_symlink():
        _git(
            ["worktree", "prune"], top, filters=False
        )  # a copy somebody deleted by hand is still on git's list
        if dest.exists() or dest.is_symlink():
            return None, "That copy folder is already there."
    branch = f"orch/{ticket}"
    rc, _, _ = _git(
        ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], top, read_only=True, filters=False
    )
    made_branch = rc != 0
    add = [
        "worktree",
        "add",
        "--no-checkout",
    ]  # no checkout: the project's tracked .orch must never land in it
    add += ["-b", branch, str(dest), "HEAD"] if made_branch else [str(dest), branch]
    rc, _, err = _git(add, top, GIT_ADD_TIMEOUT, filters=False)
    if rc != 0:
        _drop_partial(top, dest, branch, made_branch)
        return None, f"git could not make the copy: {err.splitlines()[-1] if err else 'unknown error'}"
    steps = [
        (["read-tree", "HEAD"], None),
        # skip-worktree on every tracked file of .orch: git leaves them out of status, add -A and commit -a
        (["update-index", "--skip-worktree", "-z", "--stdin"], "ls"),
        (["checkout-index", "-a", "-f", "-u"], None),  # skipped paths are not written
    ]
    for argv, how in steps:
        data = None
        if how == "ls":
            pathspec = f"{rel}/.orch" if rel else ".orch"
            rc, listed, err = _git(
                ["--literal-pathspecs", "ls-files", "-z", "--", pathspec],
                dest,
                strip=False,
                read_only=True,
                filters=False,
            )
            if rc != 0:
                break
            if not listed:
                continue
            data = listed.encode("utf-8", "surrogateescape")
        # filters stay ON for every step, read-tree and update-index too
        rc, _, err = _git(argv, dest, GIT_ADD_TIMEOUT, data)
        if rc != 0:
            break
    if rc != 0:
        _drop_partial(top, dest, branch, made_branch)
        return None, f"git could not fill the copy: {err.splitlines()[-1] if err else 'unknown error'}"
    start = dest / rel if rel else dest
    start.mkdir(parents=True, exist_ok=True)
    entry = {"path": str(dest), "branch": branch, "base": head, "sub": rel}
    try:
        reg = registry(root)
        mine = reg.setdefault(ticket, {"paths": [], "created_at": tickets.now()})
        mine["paths"] = [p for p in mine["paths"] if p.get("path") != entry["path"]] + [entry]
        _save_registry(root, reg)
    except OSError as e:
        _drop_partial(top, dest, branch, made_branch)
        return None, f"orch cannot write its list of copies: {e}"
    return entry, ""


def create(root: Path, ticket: str) -> dict | None:
    """Make (or find) the copy of a ticket: the registry entry, or None when copies cannot be made here
    (no git,
    git missing, no commit, a folder in the way). The caller then works in the project folder and shows the
    "also changing this folder" line."""
    with _scoped(root), start_lock(root):
        ent = (registry(root).get(ticket) or {"paths": []})["paths"]
        if ent and _mine(root, ticket, ent[0]):
            return ent[0]
        entry, why = _create(root, ticket)
        if entry is None:
            _note(root, ticket, why)
        return entry


# ---------------------------------------------------------------- files inside the copy, setup command


def _prepare_files(root: Path, entry: dict) -> list[str]:
    """Harness files in the copy: skill links, local instruction files (both point at the workspace's
    harness),
    and the excludes for them. Returns what could not be done, in plain words."""
    from orch import skills

    work = work_dir(entry)
    notes: list[str] = []
    try:
        harness.protect_local(
            root, skills._exclude_lines(root)
        )  # the shared .git/info/exclude covers the copy
        skills.apply_copy_files(root, work)
    except Refused as e:
        notes.append(f"Some orch files could not be put in the copy: {e}")
    return notes


def _setup(root: Path, ticket: str, entry: dict) -> list[str]:
    """The person's own setup command, once per new copy, in the copy. Failure is a warning, the copy
    stays."""
    cmd = config.copy_setup(root)  # per-machine config only: never ticket data, never the workspace's files
    if not cmd:
        return []
    try:
        argv = shlex.split(cmd, posix=os.name != "nt")
    except ValueError:
        return [f"The copy setup command could not be read ({cmd}). The copy is used as it is."]
    work = work_dir(entry)
    exe = None
    if argv:  # `./setup.sh` means the copy's file; a bare name is looked up on the PATH
        if os.sep in argv[0] or "/" in argv[0]:
            c = Path(argv[0]) if os.path.isabs(argv[0]) else work / argv[0]
            exe = str(c) if c.is_file() and os.access(c, os.X_OK) else None
        else:
            exe = safegit.find_exe(argv[0], safegit.avoid_for(work, root))  # same rules as git
    if not exe:
        return [
            f"The copy setup command '{argv[0] if argv else cmd}' was not found."
            " The copy is used as it is (on Windows only .exe programs are run, not .cmd or .bat)."
        ]
    argv[0] = exe
    log = root / ".orch" / "run" / "logs" / f"{ticket}-copy-setup.log"
    try:
        with runs.open_log(log) as out:
            out.write(f"$ {cmd}\n".encode())
            proc = subprocess.Popen(
                argv,
                cwd=work,
                env={k: v for k, v in runs._agent_environ(root).items() if not k.startswith("GIT_")},
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
            )
            try:
                rc = proc.wait(timeout=SETUP_TIMEOUT)
            except subprocess.TimeoutExpired:
                runs.kill_tree(proc.pid)
                proc.wait()
                return [
                    f"Preparing the copy with '{cmd}' took longer than {SETUP_TIMEOUT // 60} minutes and was "
                    "stopped. The copy is used as it is."
                ]
    except OSError as e:
        return [f"Preparing the copy with '{cmd}' could not run: {e}. The copy is used as it is."]
    if rc != 0:
        return [
            f"Preparing the copy with '{cmd}' failed (exit code {rc}); see "
            f"{log.relative_to(root).as_posix()}."
        ]
    return []


def _note(root: Path, ticket: str, why: str, prefix: str = "no separate copy: ") -> None:
    """One line for whoever looks at the copy-setup log (why no copy was made, or what a copy is)."""
    if not why:
        return
    with contextlib.suppress(OSError, Refused):
        with runs.open_log(root / ".orch" / "run" / "logs" / f"{ticket}-copy-setup.log") as out:
            out.write(f"{prefix}{why}\n".encode())


def _record_on_ticket(root: Path, ticket: str, entry: dict) -> None:
    """The ticket remembers THAT it works in a copy: branch, base, sub and the machine (host). Never the local
    path (home folder, user name): that stays in the machine-local registry."""

    def fn(t: dict):
        work = t.setdefault("work", {})
        if not isinstance(work, dict):
            work = t["work"] = {}
        host = runs.host()
        folders = [
            f
            for f in work.get("folders") or []
            if isinstance(f, dict) and (f.get("branch"), f.get("host")) != (entry["branch"], host)
        ]
        folders = [{k: v for k, v in f.items() if k != "path"} for f in folders]  # a legacy local path goes
        rec = {"branch": entry["branch"], "base": entry["base"], "sub": entry.get("sub") or "", "host": host}
        work["folders"] = [rec, *folders]

    tickets.apply_op(root, ticket, fn, by=tickets.SYSTEM)


# ---------------------------------------------------------------- routing


def _alive_here(root: Path, ticket: str) -> dict | None:
    rec = runs.read(root, ticket)
    return rec if rec and runs.state(rec) in ("alive", "maybe-stale") else None


@contextlib.contextmanager
def _scoped(root: Path):
    """The workspace root for every safegit call of this thread, set and always reset (no stale value)."""
    before = getattr(_ctx, "root", None)
    _ctx.root = root
    try:
        yield
    finally:
        _ctx.root = before


def route(root: Path, ticket: str) -> tuple[Path, list[str], list]:
    """See _route."""
    with _scoped(root):
        return _route(root, ticket)


def _route(root: Path, ticket: str) -> tuple[Path, list[str], list]:
    """Where does this ticket's agent work: (folder, notes, after). Call it inside start_lock, with the claim
    in the same lock. The ticket keeps its copy for life; a new copy is made only when the setting asks for
    one (together: another alive run is in the project folder; always), git can make it, and fewer than
    `workflow.copies_max` copies exist. Anything else: the project folder.
    Under the lock only the quick part happens (decide, git worktree, register). `after` are the slow steps
    (harness files, the setup command, the ticket's record): call them once the lock is released."""
    rec = _alive_here(root, ticket)
    if rec:  # a run is on (or about to take over) this ticket: it stays where it is
        return workdir_for(root, rec), [], []
    reg = registry(root).get(ticket)
    if reg:
        for e in reg["paths"]:
            if _mine(root, ticket, e):
                return work_dir(e), [], []
        # registered but gone from the disk: make it again below (same path, same branch)
    mode = config.copies_mode(root)
    if mode == "off" and not reg:
        return root, [], []
    if not reg and mode == "together" and not sharedfolder.alive_in(root, root, ticket):
        return root, [], []
    if not reg and count(root) >= config.copies_max(root):
        n = config.copies_max(root)
        return (
            root,
            [f"{n} separate copies exist already (the most at once), so this works in your own folder."],
            [],
        )
    entry, why = _create(root, ticket)
    if entry is None:
        _note(root, ticket, why)
        return (
            root,
            [],
            [],
        )  # no git (or not possible here): the "also changing this folder" line says the rest
    notes: list[str] = []

    def after() -> list[str]:
        with _scoped(root):  # the slow steps run outside the lock and outside route(): same root
            _note(
                root,
                ticket,
                "copies hold the committed files as they are (line-ending attributes are not applied)",
                "",
            )
            notes.extend(_prepare_files(root, entry))
            notes.extend(_setup(root, ticket, entry))
            with contextlib.suppress(Exception):  # a failed write must not stop the start
                _record_on_ticket(root, ticket, entry)
            return notes

    return work_dir(entry), [], [after]


# ================================================================ cleanup (B12)
#
# THE INVARIANT: orch takes a copy folder away only in `_delete_copy`, and only when ALL of these hold:
#   (1) the folder is exactly path_for(this workspace's id, ticket, orch home), resolved and spelled
#       without a link or `..`, and <ws8>/.owner is a plain file naming this workspace's folder;
#   (2) the ticket is done, closed or deleted in the MAIN store (this workspace's .orch/tickets), never
#       decided from the registry, the notes file, `.owner` or the folder alone (an agent can write those);
#   (3) no live run uses it;
#   (4) its work is saved: every change, tracked and untracked (not what git ignores), is committed on
#       branch orch/<ticket> through safegit, and HEAD is verified to BE that branch's tip afterwards.
# Any step before the rename that fails keeps the copy (the clean log and "kept" list say why).
# A closed ticket's vanished copy is always removed from the registry, even if later cleanup fails.
# Nothing is ever plain-deleted while it may hold unsaved work: the folder is first RENAMED into
# <ws8>/.trash/ (atomic, same disk); only the trash, which holds saved work only, is deleted, relative to
# open directories (no link is followed), outside the person's command (a detached `orch copy clean --trash`).
# A workspace that is not there any more (project moved or deleted) is NEVER cleaned automatically: its
# copies are only counted ("orphaned"); a person removes them with a click or `orch copy remove-orphaned`.
# Not kept when a copy goes (said on the dashboard card): files git ignores, the inside of nested
# repositories and submodules (only the link is saved). Large untracked files ARE committed to orch/<ticket>.

REGISTRY_PENDING = Path(".orch") / "run" / "worktrees-pending.json"
CLEAN_LOG = Path(".orch") / "run" / "logs" / "copies-clean.log"
BRANCH_DAYS = 14  # unmerged orch/<ticket> branch of a closed ticket: kept this long
SWEEP_BUDGET = 25.0  # seconds of git time for one sweep (orch copy clean, Clean up now)
START_SWEEP_BUDGET = 8.0  # the same when a start triggers it: a start never waits longer
SWEEP_WAIT = 2.0  # how long a sweep waits for the copies lock; busy = skip, the next one does it
TRASH = ".trash"
TRASH_GRACE_HOURS = 24  # a removed copy waits this long in the trash (by orch's own note of the rename)
LOCK_STALE_SECONDS = 600  # an index.lock older than this, in a copy, is a git that was interrupted
_TRASH_NAME = re.compile(r"t_[a-z0-9]{6,16}-[0-9a-f]{8}")
_DONE = ("done", "dropped")


def _log(root: Path, line: str) -> None:
    with contextlib.suppress(OSError, Refused):
        with runs.open_log(root / CLEAN_LOG) as out:
            out.write(f"{tickets.now()} {line}\n".encode())


def _want(root: Path, ticket: str) -> Path | None:
    """(1): the one path this workspace's copy of `ticket` can have, or None."""
    try:
        return path_for(addons.workspace_id(root) or "", ticket, addons.home(root))
    except (Refused, OSError, RuntimeError):
        return None


def _same(p: Path, want: Path) -> bool:
    """`p` IS `want`: the same string (no `..`, no link spelled in) and the same place once resolved."""
    try:
        return os.path.abspath(p) == str(want) and p.resolve() == want
    except (OSError, RuntimeError, ValueError):
        return False


def _owned(root: Path, want: Path) -> bool:
    """(1): `<ws8>/.owner` is a plain file (no link) that names this workspace's folder."""
    owner = want.parent / ".owner"
    try:
        if owner.is_symlink() or not owner.is_file():
            return False
        return owner.read_text(encoding="utf-8").strip() == str(root.resolve())
    except (OSError, RuntimeError):
        return False


def _holds_workspace(root: Path, want: Path) -> bool:
    """The workspace folder itself is `want` or inside it (an odd setup): never delete that."""
    try:
        r = root.resolve()
        return r == want or want in r.parents
    except (OSError, RuntimeError):
        return True


def _is_link(p: Path) -> bool:
    """A link, or on Windows a junction (a folder that is another folder)."""
    try:
        if p.is_symlink():
            return True
        st = os.lstat(p)
        return bool(getattr(st, "st_file_attributes", 0) & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return True  # cannot tell: treat as a link, i.e. do not delete


def _long(p: str) -> str:
    """Windows: the extended-length form, so paths over 260 characters can be deleted."""
    if os.name == "nt" and not p.startswith("\\\\?\\"):
        return "\\\\?\\" + os.path.abspath(p)
    return p


def _chmod_nofollow(path: str, is_dir: bool) -> None:
    """chmod 0700 of `path` itself through an open descriptor; refuses (OSError) when it is a link."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | (getattr(os, "O_DIRECTORY", 0) if is_dir else 0)
    fd = os.open(path, flags)
    try:
        os.fchmod(fd, 0o700)
    finally:
        os.close(fd)


def rmtree_nofollow(top: Path) -> bool:
    """Delete the folder `top` and everything in it; True when it is gone. NEVER follows a link: a link
    inside
    is removed as a link (its target stays), and a `top` that is itself a link (or not a folder) is refused.
    POSIX: relative to open directories (shutil.rmtree's fd walk, which also refuses a top that was swapped
    for a link after any check); Windows: a walk that checks every entry for a reparse point. Callers only
    pass the trash (saved work) or, in tests, a plain folder."""
    if _is_link(top) or not top.is_dir():
        return not top.exists() and not top.is_symlink()
    if os.name != "nt" and shutil.rmtree.avoids_symlink_attacks:

        def fix(func, path, exc):
            # a read-only file or folder: make exactly it (and the folder it is in) writable and try again.
            # chmod through an open descriptor of a thing that is NOT a link (O_NOFOLLOW): a link inside a
            # copy can never make orch change the mode of its target
            if isinstance(exc, PermissionError):
                parent = os.path.dirname(path) or "."
                if os.path.realpath(parent) == os.path.abspath(parent):  # no link anywhere in the path
                    with contextlib.suppress(OSError):
                        _chmod_nofollow(parent, True)
                with contextlib.suppress(OSError):  # a link refuses here: it is removed without any chmod
                    _chmod_nofollow(path, os.path.isdir(path) and not os.path.islink(path))
                with contextlib.suppress(OSError):
                    func(path)

        with contextlib.suppress(OSError):
            if sys.version_info >= (3, 12):
                shutil.rmtree(top, onexc=fix)
            else:
                shutil.rmtree(top, onerror=lambda f, p, ei: fix(f, p, ei[1]))
        return not top.exists() and not top.is_symlink()

    def drop(path: str) -> None:
        try:
            entries = list(os.scandir(_long(path)))
        except OSError:
            return
        for e in entries:
            full = os.path.join(path, e.name)
            try:
                if _is_link(Path(full)):
                    try:
                        os.unlink(_long(full))  # the link itself
                    except OSError:
                        os.rmdir(_long(full))  # a Windows junction: the junction, not what it points at
                elif e.is_dir(follow_symlinks=False):
                    drop(full)
                else:
                    try:
                        os.unlink(_long(full))
                    except PermissionError:
                        os.chmod(_long(full), 0o700)
                        os.unlink(_long(full))
            except OSError:
                continue  # locked: the folder stays, a later sweep tries again
        try:
            os.rmdir(_long(path))
        except OSError:
            with contextlib.suppress(OSError):
                os.chmod(_long(path), 0o700)
                os.rmdir(_long(path))

    drop(os.path.abspath(top))
    return not top.exists() and not top.is_symlink()


# ---------------------------------------------------------------- notes: when a copy was kept, branch ages


def _pending(root: Path) -> dict:
    """Local notes only. They NEVER authorize anything: `kept` says why a copy stayed (for people),
    `branches`
    when orch removed a copy (it can only make a branch live longer, never shorter)."""
    try:
        doc = json.loads((root / REGISTRY_PENDING).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    doc = doc if isinstance(doc, dict) else {}
    out: dict = {"kept": [], "branches": [], "trash": []}
    for k, key in (("kept", "reason"), ("branches", "branch"), ("trash", "name")):
        for it in doc.get(k) or []:
            if (
                isinstance(it, dict)
                and isinstance(it.get("ticket"), str)
                and _TID.fullmatch(it["ticket"])
                and isinstance(it.get(key), str)
            ):
                out[k].append({**it, "at": it.get("at") if isinstance(it.get("at"), str) else tickets.now()})
    return out


def _save_pending(root: Path, doc: dict) -> None:
    runs._atomic(
        root / REGISTRY_PENDING,
        json.dumps(
            {
                "schema": "orch.worktrees-pending/3",
                "kept": doc["kept"],
                "branches": doc["branches"],
                "trash": doc["trash"],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
    )


def _mark(root: Path, kind: str, ticket: str, **fields) -> None:
    """Record (kept: why a copy stayed; branches: this ticket's copy was removed now); one line per ticket."""
    with contextlib.suppress(OSError, Refused):
        doc = _pending(root)
        doc[kind] = [i for i in doc[kind] if i["ticket"] != ticket]
        if fields:
            doc[kind].append({"ticket": ticket, "at": tickets.now(), **fields})
        _save_pending(root, doc)


def _trash_note(root: Path, ticket: str, name: str) -> None:
    """orch's own record of WHEN a copy went into the trash (the grace period counts from it, never from
    mtimes an agent can set)."""
    with contextlib.suppress(OSError, Refused):
        doc = _pending(root)
        doc["trash"] = [i for i in doc["trash"] if i["name"] != name]
        doc["trash"].append({"ticket": ticket, "name": name, "at": tickets.now()})
        _save_pending(root, doc)


def _age_days(stamp: str) -> float:
    try:
        t = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        return (datetime.now(UTC) - t).total_seconds() / 86400
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------- the checks and the one deletion


def _ticket_closed(root: Path, tid: str) -> bool:
    """(2): the ticket is done, closed (dropped) or not there any more, in THIS workspace's own store. An
    unreadable ticket is NOT closed (keep)."""
    if not tickets.ticket_path(root, tid).exists():
        return True
    try:
        t = tickets.load(root, tid)
    except Exception:  # noqa: BLE001
        return False
    return isinstance(t, dict) and t.get("status") in _DONE


def _is_our_worktree(top: Path, want: Path) -> bool:
    """`want` is a git worktree of THE repository at `top` (its .git is a file, and its common git folder is
    top's): only then is git asked anything inside it. Without this, a folder below an orch home that sits
    inside some other repository would answer git questions (and take a commit) for that other repository."""
    try:
        if not (want / ".git").is_file() or (want / ".git").is_symlink():
            return False
        args = ["rev-parse", "--path-format=absolute", "--git-common-dir"]
        rc, a, _ = _git(args, want, read_only=True, filters=False)
        rc2, b, _ = _git(args, top, read_only=True, filters=False)
        rc3, tl, _ = _git(["rev-parse", "--show-toplevel"], want, read_only=True, filters=False)
        return (
            rc == 0
            and rc2 == 0
            and rc3 == 0
            and bool(a)
            and Path(a).resolve() == Path(b).resolve()
            and Path(tl).resolve() == want
        )
    except (OSError, RuntimeError):
        return False


def _gitdir_of(want: Path) -> Path | None:
    """The copy's own git folder, from its `.git` file ("gitdir: <path>")."""
    try:
        f = want / ".git"
        if f.is_symlink() or not f.is_file():
            return None
        line = f.read_text(encoding="utf-8").strip()
        if not line.startswith("gitdir:"):
            return None
        g = Path(line.split(":", 1)[1].strip())
        return Path(os.path.abspath(g if g.is_absolute() else want / g))
    except (OSError, ValueError, RuntimeError):
        return None


def _stale_index_lock(want: Path) -> Path | None:
    """<copy's git folder>/index.lock when it is a plain file older than LOCK_STALE_SECONDS: a git that was
    killed in the middle (no git runs that long)."""
    g = _gitdir_of(want)
    if g is None:
        return None
    lock = g / "index.lock"
    try:
        st = os.lstat(lock)
        if not stat_is_file(st) or time.time() - st.st_mtime < LOCK_STALE_SECONDS:
            return None
        return lock
    except OSError:
        return None


def stat_is_file(st) -> bool:
    import stat

    return stat.S_ISREG(st.st_mode)


INTERRUPTED = "git was interrupted"


def _clean_status(want: Path) -> bool | None:
    rc, out, _ = _git(["status", "--porcelain", "-z"], want, read_only=True, strip=False)
    return None if rc != 0 else not out


def _save_leftovers(want: Path, ticket: str) -> tuple[bool, str]:
    """(4): commit what is in the copy to orch/<ticket> (no hooks, no signing, identity orch) and verify
    that
    HEAD is that branch's tip and nothing is left uncommitted. Never commits onto another branch or a
    detached
    HEAD (a detached HEAD sitting exactly on the tip is put back on the branch first). Call only after
    _is_our_worktree. Returns (saved, why not)."""
    ref = f"refs/heads/orch/{ticket}"
    rc, cur, _ = _git(["symbolic-ref", "-q", "HEAD"], want, read_only=True, filters=False)
    if cur != ref:
        if rc == 0:
            return False, f"the copy is on branch {cur.removeprefix('refs/heads/')}, not orch/{ticket}"
        rc1, head, _ = _git(["rev-parse", "--verify", "-q", "HEAD"], want, read_only=True, filters=False)
        rc2, tip, _ = _git(["rev-parse", "--verify", "-q", ref], want, read_only=True, filters=False)
        if not (rc1 == 0 and rc2 == 0 and head and head == tip):
            return False, f"the copy is not on branch orch/{ticket} (detached somewhere else)"
        rc, _, _ = _git(["symbolic-ref", "HEAD", ref], want, filters=False)
        if rc != 0:
            return False, "the copy could not be put back on its branch"
    interrupted = f"{INTERRUPTED} (a stale index.lock): use Try again"
    clean = _clean_status(want)
    if clean is None:
        return False, interrupted if _stale_index_lock(want) else "git could not read the copy's state"
    if not clean:
        rc, _, err = _git(["add", "-A"], want, GIT_ADD_TIMEOUT)
        if rc != 0:
            if _stale_index_lock(want):
                return False, interrupted
            return False, f"git could not add the copy's files ({err.splitlines()[-1] if err else rc})"
        msg = f"orch: {ticket} (saved when the copy was removed)"
        rc, _, err = _git(["commit", "-q", "--no-verify", "-m", msg], want, GIT_ADD_TIMEOUT, identity=True)
        if rc != 0:
            if _stale_index_lock(want):
                return False, interrupted
            return False, f"git could not save the copy's changes ({err.splitlines()[-1] if err else rc})"
    rc1, head, _ = _git(["rev-parse", "--verify", "-q", "HEAD"], want, read_only=True, filters=False)
    rc2, tip, _ = _git(["rev-parse", "--verify", "-q", ref], want, read_only=True, filters=False)
    if not (rc1 == 0 and rc2 == 0 and head and head == tip) or _clean_status(want) is not True:
        return False, f"the saved changes are not on branch orch/{ticket}"
    return True, ""


def _forget_agent_traces(entry: dict, want: Path) -> None:
    """The agent tools' conversation folder and trust entry for this copy (exact paths of THIS copy)."""
    folders = [want]
    with contextlib.suppress(Refused, OSError, RuntimeError, KeyError):
        w = work_dir({**entry, "path": str(want)})
        if w != want:
            folders.append(Path(os.path.abspath(w)))
    for name in adapters.builtin_names():
        for f in folders:
            with contextlib.suppress(Exception):
                adapters.forget_folder(name, f, want.parent)


def _delete_branch(top: Path | None, ticket: str, force: bool = False) -> bool:
    """`branch -d orch/<ticket>` (merged into the project's current commit); -D only for the 14-day rule.
    True when the branch is gone (or was never there). The name is built here from the ticket id."""
    if top is None:
        return False
    branch = f"orch/{ticket}"
    rc, _, _ = _git(
        ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], top, read_only=True, filters=False
    )
    if rc != 0:
        return True
    rc, _, _ = _git(["branch", "-D" if force else "-d", "--", branch], top, filters=False)
    return rc == 0


def _to_trash(want: Path, ticket: str) -> Path | None:
    """Move the verified folder into <ws8>/.trash/<ticket>-<random> (a rename: atomic, same disk, nothing is
    deleted). None when it cannot be moved (Windows: a locked file): the copy then stays where it is."""
    trash = want.parent / TRASH
    try:
        if trash.is_symlink():
            return None
        trash.mkdir(exist_ok=True)
        dest = trash / f"{ticket}-{secrets.token_hex(4)}"
        os.rename(want, dest)
        return dest
    except OSError:
        return None


def _delete_copy(root: Path, ticket: str, reason: str, top: Path | None, entry: dict | None = None) -> str:
    """THE function every removal goes through (see the invariant above). Returns "removed" or "kept:
    <why>".
    `reason` (done, closed, sweep, orphan) is only for the log. Never raises."""
    try:
        res = _delete_copy_inner(root, ticket, top, entry or {})
    except Exception as e:  # noqa: BLE001 - fail closed
        res = f"kept: {e}"
    # The rename is the removal boundary. Later git/trace cleanup can fail, but
    # cannot turn a vanished closed copy back into a kept registry entry.
    want = _want(root, ticket)
    if want is not None and _ticket_closed(root, ticket):
        try:
            want.lstat()
        except FileNotFoundError:
            res = "removed"
        except OSError:
            pass  # unreadable is not missing
    if res == "removed":
        _mark(root, "kept", ticket)
        _log(root, f"{ticket}: removed ({reason})")
    else:
        _mark(root, "kept", ticket, reason=res.removeprefix("kept: "), stale_lock=INTERRUPTED in res)
        _log(root, f"{ticket}: {res} ({reason})")
    return res


def _delete_copy_inner(root: Path, ticket: str, top: Path | None, entry: dict) -> str:
    want = _want(root, ticket)
    if want is None or not _owned(root, want) or _holds_workspace(root, want):
        return "kept: not this workspace's copy"
    if not _ticket_closed(root, ticket):  # (2) the main store decides
        return "kept: its ticket is not done or closed"
    if _alive_here(root, ticket):  # (3)
        return "kept: an agent is still working in it"
    if os.path.lexists(want):
        if _is_link(want) or not want.is_dir():
            return "kept: not a folder"
        if top is None:
            return "kept: git is not available right now"
        if not _is_our_worktree(top, want):
            return "kept: git could not confirm it is a copy of this project"
        ok, why = _save_leftovers(want, ticket)  # (4)
        if not ok:
            return f"kept: {why}"
        moved = _to_trash(want, ticket)
        if moved is None:
            return "kept: it could not be moved away (a file is in use?)"
        _trash_note(root, ticket, moved.name)
        _mark(root, "branches", ticket, branch=f"orch/{ticket}")
    if top is not None:
        _git(["worktree", "prune"], top, filters=False)  # its folder is gone from where git knew it
    if not _delete_branch(top, ticket):
        _mark(root, "branches", ticket, branch=f"orch/{ticket}")
    else:
        _mark(root, "branches", ticket)
    _forget_agent_traces(entry or {"path": str(want), "sub": ""}, want)
    return "removed"


def _top_of(root: Path) -> Path | None:
    repo = _repo(root)
    return repo[0] if repo else None


def _drop_entry(root: Path, ticket: str, keep: list[dict]) -> None:
    reg = registry(root)
    if ticket in reg:
        if keep:
            reg[ticket]["paths"] = keep
        else:
            del reg[ticket]
        _save_registry(root, reg)


def _remove_locked(
    root: Path, ticket: str, top: Path | None | bool = False, reason: str = "closed"
) -> list[str]:
    """remove() with the copies lock already held. Returns one line per thing that was kept."""
    if not isinstance(ticket, str) or not _TID.fullmatch(ticket):
        return [f"'{ticket}' is not a ticket id"]
    ent = registry(root).get(ticket)
    paths = (ent or {}).get("paths") or []
    if not paths:
        return []
    if top is False:
        top = _top_of(root)
    want = _want(root, ticket)
    keep: list[dict] = []
    notes: list[str] = []
    for e in paths:
        if want is None or not _same(Path(e["path"]), want):
            notes.append(f"{ticket}: dropped a saved copy line that is not this ticket's copy folder")
            continue  # a forged or foreign line: dropped from the list, its path is never touched
        res = _delete_copy(root, ticket, reason, top, e)
        if res != "removed":
            keep.append(e)
            notes.append(f"{ticket}: {res}")
    _drop_entry(root, ticket, keep)
    return notes


def remove(root: Path, ticket: str, wait: float = 10.0) -> list[str]:
    """Take back the copy of `ticket` (B13 calls this once the changes are added): only when the
    invariant holds,
    else the copy stays and the notes say why. Never raises. The folder is moved to the trash; a detached
    `orch copy clean --trash` empties it."""
    try:
        with _scoped(root), runs.locked(root, LOCK_ID, wait=wait):
            before = getattr(_ctx, "deadline", None)
            _ctx.deadline = time.monotonic() + SWEEP_BUDGET
            try:
                notes = _remove_locked(root, ticket)
            finally:
                _ctx.deadline = before
    except Exception as e:  # noqa: BLE001
        notes = [f"{ticket}: the copy was not removed now ({e})"]
    spawn_trash_clean(root)
    return notes


def on_closed(root: Path, ticket: str) -> None:
    """A ticket was done, closed or cancelled: its copy goes. Never raises, never waits long."""
    try:
        if ticket not in registry(root):
            return  # no copy: nothing to do, no git call, no lock (the sweep finds odd leftovers)
    except Exception:  # noqa: BLE001
        return
    remove(root, ticket, wait=SWEEP_WAIT)


def on_run_ended(root: Path, tid: str) -> None:
    """A run of `tid` ended: when its ticket is already closed, its copy goes now (it waited for the run)."""
    try:
        if tid in registry(root) and _ticket_closed(root, tid):
            remove(root, tid, wait=SWEEP_WAIT)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- the trash (saved work only)


def _parse_at(stamp: str) -> float | None:
    try:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    except (ValueError, TypeError):
        return None


def _changed_since(top: Path, since: float, cap: int = 100_000) -> bool:
    """Some file or folder below `top` was modified after `since` (a capped walk of lstat times, no links
    followed). Too big to tell counts as changed: nothing is deleted on a guess."""
    seen = 0
    stack = [str(top)]
    while stack:
        cur = stack.pop()
        try:
            for e in os.scandir(cur):
                seen += 1
                if seen > cap:
                    return True
                if e.stat(follow_symlinks=False).st_mtime > since + 2:
                    return True
                if e.is_dir(follow_symlinks=False):
                    stack.append(e.path)
        except OSError:
            return True
    return False


def _empty_trash_in(root: Path, wsdir: Path, deadline: float, grace: bool = True) -> bool:
    """Delete what is in <wsdir>/.trash (renamed copies whose work is saved on its branch). Only direct
    children named <ticket>-<8 hex>, never a link. With `grace` (every automatic run): an entry is
    deleted only TRASH_GRACE_HOURS after the rename recorded in orch's own note (an entry without a
    note starts its grace now), and never when anything in it changed after the rename (a process orch
    did not know, such as a dev server, wrote into it): that one stays, flagged for a person. Without
    `grace` (a person chose to remove copies of a project that is gone) it is deleted at once. True
    when the trash is empty."""
    trash = wsdir / TRASH
    if not trash.exists():
        return True
    if _is_link(trash) or not trash.is_dir():
        return False
    left = False
    try:
        names = sorted(e.name for e in os.scandir(trash))
    except OSError:
        return False
    doc = _pending(root) if grace else None
    notes = {i["name"]: i for i in doc["trash"]} if doc else {}
    dirty = False
    for name in names:
        c = trash / name
        if not _TRASH_NAME.fullmatch(name) or _is_link(c) or not c.is_dir():
            left = True
            continue
        if grace:
            n = notes.get(name)
            at = _parse_at(n["at"]) if n else None
            if n is None or at is None:
                doc["trash"] = [i for i in doc["trash"] if i["name"] != name] + [
                    {"ticket": name.split("-")[0], "name": name, "at": tickets.now()}
                ]
                dirty = left = True
                continue
            if time.time() - at < TRASH_GRACE_HOURS * 3600:
                left = True
                continue
            if _changed_since(c, at):
                if not n.get("changed"):
                    n["changed"] = True
                    dirty = True
                left = True
                continue
        if time.monotonic() > deadline or not rmtree_nofollow(c):
            left = True
        elif grace:
            doc["trash"] = [i for i in doc["trash"] if i["name"] != name]
            dirty = True
    if dirty:
        with contextlib.suppress(OSError, Refused):
            _save_pending(root, doc)
    return not left


def empty_trash(root: Path, budget: float = 300.0) -> bool:
    """Empty this workspace's trash (explicit `orch copy clean --trash`, run detached). Never raises."""
    try:
        d = copies_dir(root)
        if d is None or not d.is_dir() or _is_link(d) or not _owned(root, d / "t_x000000"):
            return False
        return _empty_trash_in(root, d, time.monotonic() + budget)
    except Exception:  # noqa: BLE001
        return False


def _spawn_clean(root: Path, flag: str) -> None:
    """Run `orch copy clean <flag>` detached, from a neutral folder, with -I -P (nothing planted in the
    workspace is imported) and the workspace named by ORCH_ROOT."""
    if os.environ.get("ORCH_NO_DETACHED_CLEAN"):
        return
    from orch import procs

    # a neutral folder that holds neither the workspace nor ORCH_HOME (orch distrusts an ORCH_HOME inside the
    # current folder, so the home itself is no place to run from)
    neutral = Path(os.path.realpath(tempfile.gettempdir()))
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["ORCH_ROOT"] = str(root)
    subprocess.Popen(
        procs.orch_python_argv("copy", "clean", flag),
        cwd=neutral,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=os.name != "nt",
    )


def spawn_trash_clean(root: Path) -> None:
    """Empty the trash in a detached process, so a big folder never delays the person's command."""
    try:
        d = copies_dir(root)
        if d is not None and (d / TRASH).is_dir():
            _spawn_clean(root, "--trash")
    except Exception:  # noqa: BLE001
        pass


def schedule_sweep(root: Path) -> None:
    """What a START does: never the sweep itself (its saves must not run under a start's patience), only a
    detached `orch copy clean --background`, and only when there is anything that could need cleaning."""
    try:
        d = copies_dir(root)
        if (d is not None and d.is_dir() and any(True for _ in os.scandir(d))) or (
            root / REGISTRY_PENDING
        ).exists():
            _spawn_clean(root, "--background")
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- the sweep


def _out_of_time(deadline: float) -> bool:
    return time.monotonic() > deadline


def _sweep_registry(root: Path, top, deadline: float, notes: list[str]) -> None:
    """(1) registry entries whose ticket is done, closed or missing."""
    for tid in list(registry(root)):
        if _out_of_time(deadline):
            notes.append("time box reached")
            return
        if _ticket_closed(root, tid):
            notes += _remove_locked(root, tid, top, "sweep")


def _sweep_orphans(root: Path, top, deadline: float, notes: list[str]) -> None:
    """(2) folders in <home>/worktrees/<ws8>/ that no registry line names. Through the same single function:
    its ticket must be done/closed in the main store (an orphan of an open ticket is kept and only logged)."""
    d = copies_dir(root)
    if d is None or not d.is_dir() or _is_link(d):
        return
    known = set(registry(root))
    try:
        names = sorted(n.name for n in os.scandir(d))
    except OSError:
        return
    for name in names:
        if _out_of_time(deadline):
            notes.append("time box reached")
            return
        if name in known or not _TID.fullmatch(name):
            continue
        want = _want(root, name)
        if want is None or not _same(d / name, want) or not os.path.lexists(want):
            continue
        res = _delete_copy(root, name, "orphan", top, {"path": str(want), "sub": ""})
        if res != "removed":
            notes.append(f"{name}: orphan copy folder: {res}")


def _tip_age_days(top: Path, ticket: str) -> float | None:
    rc, out, _ = _git(["log", "-1", "--format=%ct", f"refs/heads/orch/{ticket}", "--"], top, read_only=True)
    try:
        return (time.time() - int(out)) / 86400 if rc == 0 else None
    except ValueError:
        return None


def _sweep_branches(root: Path, top, deadline: float, notes: list[str]) -> None:
    """(3) orch/<ticket> branches left behind by removed copies: merged ones go at once (`-d`); an
    unmerged one
    only when its ticket is done/closed in the main store, no copy or live run exists, and BRANCH_DAYS
    passed
    since its last commit (the commit's own time) and since orch removed the copy (orch's note, which
    can only
    make it longer)."""
    if top is None:
        return
    rc, out, _ = _git(["for-each-ref", "--format=%(refname:short)", "refs/heads/orch/"], top, read_only=True)
    if rc != 0:
        return
    removed_at = {i["ticket"]: i["at"] for i in _pending(root)["branches"]}
    reg = registry(root)
    for name in out.splitlines():
        if _out_of_time(deadline):
            return
        tid = name.removeprefix("orch/")
        if not _TID.fullmatch(tid) or name != f"orch/{tid}":
            continue
        if tid in reg or not _ticket_closed(root, tid) or _alive_here(root, tid):
            continue
        want = _want(root, tid)
        if want is not None and os.path.lexists(want):
            continue
        if _delete_branch(top, tid):
            _mark(root, "branches", tid)
            continue
        age = _tip_age_days(top, tid)
        if age is None:
            continue
        if tid in removed_at:
            age = min(age, _age_days(removed_at[tid]))
        if age >= BRANCH_DAYS and _delete_branch(top, tid, force=True):
            _mark(root, "branches", tid)
            notes.append(f"{tid}: deleted its unmerged branch after {BRANCH_DAYS} days")


def _owner_workspace_here(d: Path) -> bool | None:
    """True: `<ws8>/.owner` names a workspace that is there with this id; False: not there or another id;
    None: not an orch copies folder."""
    owner = d / ".owner"
    try:
        if owner.is_symlink() or not owner.is_file():
            return None
        main = Path(owner.read_text(encoding="utf-8").strip())
        if not main.is_absolute():
            return None
        wid = addons.workspace_id(main) if main.is_dir() else None
        return bool(wid and wid[:8] == d.name)
    except (OSError, ValueError, RuntimeError):
        return None


def orphaned(root: Path) -> list[dict]:
    """Copy folders of workspaces that are not there any more (project moved or deleted, or its id changed):
    [{ws8, copies}]. Only reported, never deleted by a sweep: a moved project looks the same."""
    base = (addons.home(root) / "worktrees").resolve()
    mine = copies_dir(root)
    out: list[dict] = []
    try:
        entries = sorted(os.scandir(base), key=lambda e: e.name)
    except OSError:
        return out
    for ent in entries:
        d = base / ent.name
        if not _WS8.fullmatch(ent.name) or _is_link(d) or not d.is_dir() or d == mine:
            continue
        if not _known_gone(d):
            continue
        try:
            n = sum(1 for e in os.scandir(d) if _TID.fullmatch(e.name) and e.is_dir(follow_symlinks=False))
        except OSError:
            continue
        if n:
            out.append({"ws8": ent.name, "copies": n})
    return out


def remove_orphaned(root: Path, ws8: str, discard: bool = False) -> list[str]:
    """A PERSON's explicit decision (CLI, or the dashboard's Remove): take back the copies of a
    workspace that
    is not here. Each copy's changes are saved on its branch first when git can do it (the project's
    repository
    is still reachable); one that cannot be saved stays, unless `discard` (CLI only: "throw the changes
    away").
    Refused for an agent. Never touches a workspace that is there."""
    if tickets.agent_tool():
        raise Refused("Only a person can remove copies of a project that is gone.")
    if not isinstance(ws8, str) or not _WS8.fullmatch(ws8):
        raise Refused("That is not a copies folder.")
    base = (addons.home(root) / "worktrees").resolve()
    d = base / ws8
    notes: list[str] = []
    if _is_link(d) or not d.is_dir() or not _known_gone(d) or d == copies_dir(root):
        raise Refused("That project is still here (or is not a copies folder). Nothing was removed.")
    with _scoped(root):
        for name in sorted(e.name for e in os.scandir(d)):
            c = d / name
            if not _TID.fullmatch(name) or _is_link(c) or not c.is_dir():
                continue
            saved = False
            try:
                rc, common, _ = _git(
                    ["rev-parse", "--path-format=absolute", "--git-common-dir"],
                    c,
                    read_only=True,
                    filters=False,
                )
                top = Path(common).parent if rc == 0 and Path(common).name == ".git" else None
                if top is not None and _is_our_worktree(top, c):
                    saved, why = _save_leftovers(c, name)
                else:
                    why = "git cannot reach the project of this copy"
            except Exception as e:  # noqa: BLE001
                why = str(e)
            if saved or discard:
                if _to_trash(c, name) is None:
                    notes.append(f"{name}: could not be moved away (a file is in use?)")
                else:
                    _log(root, f"{ws8}/{name}: removed by a person ({'saved' if saved else 'discarded'})")
            else:
                notes.append(f"{name}: kept: {why}")
        if _empty_trash_in(root, d, time.monotonic() + 300, grace=False) and not any(
            _TID.fullmatch(e.name) for e in os.scandir(d)
        ):
            with runs.locked(addons.home(root) / ".copies-state", "_known_copies"):
                key = _copies_key(base.parent)
                counter, known = _copies_store(base.parent, key)
                if ws8 not in known or not _known_gone(d, known):
                    raise Refused("The copies identity changed. Nothing more was removed.")
                try:
                    with contextlib.suppress(FileNotFoundError):
                        (d / TRASH).rmdir()
                    (d / ".owner").unlink()
                    try:
                        d.rmdir()
                    except OSError:
                        _write_copies_owner(d, known[ws8]["main"])
                        raise
                except OSError as e:
                    notes.append(f"{ws8}: kept: could not remove the copies folder: {e}")
                else:
                    known.pop(ws8)
                    try:
                        _save_copies_store(base.parent, key, counter, known)
                    except OSError as e:
                        notes.append(
                            f"{ws8}: copies folder removed, but could not update the identity store: {e}"
                        )
    return notes


def retry(root: Path, ticket: str) -> list[str]:
    """A PERSON's "Try again" for a copy kept because git was interrupted: remove the stale index.lock of THIS
    copy (exactly <the project's .git>/worktrees/<name>/index.lock, a plain file older than
    LOCK_STALE_SECONDS;
    safegit runs no such operation, so it is a plain unlink with these checks), then remove the copy through
    the normal path. Refused for an agent."""
    if tickets.agent_tool():
        raise Refused("Only a person can do this.")
    if not isinstance(ticket, str) or not _TID.fullmatch(ticket):
        raise Refused(f"'{ticket}' is not a ticket id.")
    with _scoped(root), start_lock(root):
        if _alive_here(root, ticket):
            raise Refused(f"{INTERRUPTED}: an agent is still working in the copy. Try again when it ends.")
        want = _want(root, ticket)
        ent = registry(root).get(ticket)
        if want is None or not ent or not any(_same(Path(e["path"]), want) for e in ent["paths"]):
            raise Refused("That copy is not in the list.")
        if _owned(root, want) and os.path.lexists(want) and not _is_link(want):
            lock = _stale_index_lock(want)
            top = _top_of(root)
            if lock is not None and top is not None:
                try:
                    common = top / ".git"
                    wt = lock.parent
                    expected = common / "worktrees" / wt.name
                    backlink = wt / "gitdir"
                    if (
                        not _is_link(wt)
                        and not _is_link(common / "worktrees")
                        and wt == expected
                        and lock.resolve() == expected.resolve() / "index.lock"
                        and not lock.is_symlink()
                        and not backlink.is_symlink()
                        and Path(backlink.read_text(encoding="utf-8").strip()).resolve()
                        == (want / ".git").resolve()
                    ):
                        lock.unlink()
                        _log(root, f"{ticket}: removed a stale index.lock at a person's request")
                except OSError as e:
                    raise Refused(f"The old lock file could not be removed: {e}") from None
        before = getattr(_ctx, "deadline", None)
        _ctx.deadline = time.monotonic() + SWEEP_BUDGET
        try:
            notes = _remove_locked(root, ticket)
        finally:
            _ctx.deadline = before
    spawn_trash_clean(root)
    return notes


def sweep(root: Path, budget: float = SWEEP_BUDGET) -> list[str]:
    """Take back every copy nobody needs, within `budget` seconds. The notes say what stayed. NEVER
    raises and
    never waits for the lock more than SWEEP_WAIT: a busy lock means a copy is being made or removed right
    now, and the next sweep does it. Order: (1) done/closed/missing tickets, (2) orphan folders of closed
    tickets, (3) leftover branches. The trash is emptied by a detached process. Triggers: orch start,
    orch run
    start, orch copy clean, the dashboard's "Clean up now"."""
    notes: list[str] = []
    try:
        deadline = time.monotonic() + budget
        with _scoped(root):
            try:
                with runs.locked(root, LOCK_ID, wait=SWEEP_WAIT):
                    before = getattr(_ctx, "deadline", None)
                    _ctx.deadline = deadline
                    try:
                        top = _top_of(root)
                        for step in (_sweep_registry, _sweep_orphans, _sweep_branches):
                            step(root, top, deadline, notes)
                    finally:
                        _ctx.deadline = before
            except Refused:
                notes.append("busy: the next sweep does it")
        spawn_trash_clean(root)
    except Exception as e:  # noqa: BLE001 - a sweep never stops the person's command
        notes.append(f"the sweep stopped: {e}")
    for n in notes:
        _log(root, n)
    return notes


# ---------------------------------------------------------------- how much room copies take (dashboard)


def usage(root: Path, seconds: float = 3.0, max_entries: int = 200_000) -> dict:
    """{"copies": N, "bytes": X, "partial": bool, "orphaned": [{ws8, copies}]}: live registered copies
    and ticket-named folders' size (a capped walk, no links followed; `partial` when the cap stopped it),
    and the copies of projects that are gone. Never on a request path."""
    d = copies_dir(root)
    out = {"copies": count(root), "bytes": 0, "partial": False, "orphaned": [], "changed": 0, "stuck": []}
    with contextlib.suppress(Exception):
        out["orphaned"] = orphaned(root)
        doc = _pending(root)
        out["changed"] = sum(1 for i in doc["trash"] if i.get("changed"))
        out["stuck"] = [
            {"ticket": i["ticket"], "reason": i["reason"]} for i in doc["kept"] if i.get("stale_lock")
        ]
    if d is None or not d.is_dir() or _is_link(d):
        return out
    end = time.monotonic() + seconds
    seen = 0
    stack: list[str] = []
    try:
        for e in os.scandir(d):
            if _TID.fullmatch(e.name) and e.is_dir(follow_symlinks=False):
                stack.append(e.path)
    except OSError:
        return out
    while stack:
        cur = stack.pop()
        try:
            for e in os.scandir(cur):
                seen += 1
                if seen > max_entries or time.monotonic() > end:
                    out["partial"] = True
                    return out
                if e.is_dir(follow_symlinks=False):
                    stack.append(e.path)
                elif e.is_file(follow_symlinks=False):
                    out["bytes"] += e.stat(follow_symlinks=False).st_size
        except OSError:
            continue
    return out
