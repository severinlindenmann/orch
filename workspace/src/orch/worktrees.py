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
cleanup.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from orch import adapters, addons, config, harness, runs, safegit, sharedfolder, tickets
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
    """How many copies exist (every path of every ticket counts)."""
    return sum(len(v["paths"]) for v in registry(root).values())


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
        folder.mkdir(parents=True, exist_ok=True)
        if owner.is_symlink():
            return None, "orch cannot use that folder for copies."
        if owner.is_file():
            if owner.read_text(encoding="utf-8").strip() != str(root.resolve()):
                return None, "Another workspace uses the same copy folder."
        else:
            runs._atomic(owner, str(root.resolve()) + "\n")
    except OSError as e:
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
        rc, _, err = _git(argv, dest, GIT_ADD_TIMEOUT, data, filters=argv[0] == "checkout-index")
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

    tickets.apply_op(root, ticket, fn)


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
# Copies are always taken back (they filled the disk before). The ONE invariant for everything below that
# deletes a folder: it is deleted only if it is BOTH
#   (a) exactly path_for(this workspace's id, ticket, orch home): the resolved, ticket-named folder inside
#       <orch home>/worktrees/<ws8>/, spelled without a link or `..` (_want / _same), and
#   (b) owned by this workspace: <ws8>/.owner is a plain file naming this workspace's folder (_owned).
# The path is never taken from the registry, from `.owner`, from a ticket or from an agent: those are only
# compared against path_for (registry lines that disagree are dropped, never followed). Anything that does not
# pass is left alone and logged (fail closed). Deletion never follows a link (rmtree_nofollow). The only
# other thing deleted is a gone workspace's whole <ws8> folder (_sweep_gone), by its own, stricter checks.

REGISTRY_PENDING = Path(".orch") / "run" / "worktrees-pending.json"
CLEAN_LOG = Path(".orch") / "run" / "logs" / "copies-clean.log"
BRANCH_DAYS = 14  # an unmerged orch/<ticket> branch is kept this long after its copy went
GONE_DAYS = 7  # a <ws8> folder of a workspace that is not there (a drive unplugged?) must be idle this long
SWEEP_BUDGET = 25.0  # seconds of git time for one sweep (orch copy clean, Clean up now)
START_SWEEP_BUDGET = 8.0  # the same when a start triggers it: a start never waits longer
SWEEP_WAIT = 2.0  # how long a sweep waits for the copies lock; busy = skip, the next one does it
_DONE = ("done", "dropped")


def _log(root: Path, line: str) -> None:
    with contextlib.suppress(OSError, Refused):
        with runs.open_log(root / CLEAN_LOG) as out:
            out.write(f"{tickets.now()} {line}\n".encode())


def _want(root: Path, ticket: str) -> Path | None:
    """(a): the one path this workspace's copy of `ticket` can have, or None."""
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
    """(b): `<ws8>/.owner` is a plain file (no link) that names this workspace's folder."""
    owner = want.parent / ".owner"
    try:
        if owner.is_symlink() or not owner.is_file() or want.parent.is_symlink():
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


def rmtree_nofollow(top: Path) -> bool:
    """Delete the folder `top` and everything in it; True when it is gone. NEVER follows a link: a link inside
    is removed as a link (its target stays), and a `top` that is itself a link (or not a folder) is refused.
    Read-only files are made writable first (Windows). Callers have already proved `top` is a path they may
    delete (the two checks above); this function only makes sure the deletion stays inside it."""
    if _is_link(top) or not top.is_dir():
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
                continue  # locked: the folder stays, the caller keeps it on its pending list
        try:
            os.rmdir(_long(path))
        except OSError:
            with contextlib.suppress(OSError):
                os.chmod(_long(path), 0o700)
                os.rmdir(_long(path))

    drop(os.path.abspath(top))
    return not top.exists() and not top.is_symlink()


# ---------------------------------------------------------------- the pending list (leftovers, branches)


def _pending(root: Path) -> dict:
    try:
        doc = json.loads((root / REGISTRY_PENDING).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    doc = doc if isinstance(doc, dict) else {}
    out: dict = {"folders": [], "branches": []}
    for k, keys in (("folders", ("ticket", "path")), ("branches", ("ticket", "branch"))):
        for it in doc.get(k) or []:
            if (
                isinstance(it, dict)
                and all(isinstance(it.get(x), str) for x in keys)
                and _TID.fullmatch(it["ticket"])
            ):
                out[k].append({**it, "removed_at": it.get("removed_at") or tickets.now()})
    return out


def _save_pending(root: Path, doc: dict) -> None:
    runs._atomic(
        root / REGISTRY_PENDING,
        json.dumps({"schema": "orch.worktrees-pending/1", **doc}, indent=2, ensure_ascii=False) + "\n",
    )


def _add_pending(root: Path, kind: str, item: dict) -> None:
    doc = _pending(root)
    key = "path" if kind == "folders" else "branch"
    if not any(i["ticket"] == item["ticket"] and i[key] == item[key] for i in doc[kind]):
        doc[kind].append({**item, "removed_at": tickets.now()})
        _save_pending(root, doc)


def _age_days(stamp: str) -> float:
    try:
        t = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        return (datetime.now(UTC) - t).total_seconds() / 86400
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------- take one copy back


def _is_our_worktree(top: Path, want: Path) -> bool:
    """`want` is a git worktree of THE repository at `top` (its .git is a file, and its common git folder is
    top's): only then is git asked anything inside it. Without this, a folder below an orch home that sits
    inside some other repository would answer git questions (and take a commit) for that other repository."""
    try:
        if not (want / ".git").is_file() or (want / ".git").is_symlink():
            return False
        rc, a, _ = _git(
            ["rev-parse", "--path-format=absolute", "--git-common-dir"], want, read_only=True, filters=False
        )
        rc2, b, _ = _git(
            ["rev-parse", "--path-format=absolute", "--git-common-dir"], top, read_only=True, filters=False
        )
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


def _save_leftovers(top: Path, want: Path, ticket: str) -> bool:
    """Commit what is in the copy to orch/<ticket> (no hooks, no signing, identity orch): True when the copy
    holds nothing uncommitted afterwards. Call only after _is_our_worktree."""
    rc, out, _ = _git(["status", "--porcelain", "-z"], want, read_only=True, strip=False)
    if rc != 0:
        return False
    if not out:
        return True
    rc, _, _ = _git(["add", "-A"], want, GIT_ADD_TIMEOUT)
    if rc != 0:
        return False
    rc, _, _ = _git(
        ["commit", "-q", "--no-verify", "-m", f"orch: {ticket} (saved when the copy was removed)"],
        want,
        GIT_ADD_TIMEOUT,
        identity=True,
    )
    if rc != 0:
        return False
    rc, out, _ = _git(["status", "--porcelain", "-z"], want, read_only=True, strip=False)
    return rc == 0 and not out


def _forget_agent_traces(root: Path, entry: dict, want: Path) -> None:
    """The agent tools' conversation folder and trust entry for this copy (exact paths of THIS copy)."""
    folders = [want]
    with contextlib.suppress(Refused, OSError, RuntimeError, KeyError):
        w = work_dir({**entry, "path": str(want)})
        if w != want:
            folders.append(Path(os.path.abspath(w)))
    for name in adapters_names():
        for f in folders:
            with contextlib.suppress(Exception):
                adapters.forget_folder(name, f, want.parent)


def adapters_names() -> list[str]:
    return adapters.builtin_names()


def _delete_branch(root: Path, top: Path | None, ticket: str, force: bool = False) -> bool:
    """`branch -d orch/<ticket>` (merged into the project's current commit); -D only for the 14-day rule.
    True when the branch is gone (or was never there). The name is built here from the ticket id, never taken
    from a registry or a ticket."""
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


def _remove_copy(root: Path, ticket: str, want: Path, entry: dict, top: Path | None) -> str:
    """Take one verified copy back. Returns "removed", "pending" (a leftover folder could not be deleted yet;
    it is on the pending list) or "kept:<why>" (nothing was deleted). `want` passed _want/_same and _owned in
    the caller (checked again here: this is the only function that deletes a copy)."""
    if not _owned(root, want) or want != _want(root, ticket) or _holds_workspace(root, want):
        return "kept: not this workspace's copy"
    if os.path.lexists(want):
        if _is_link(want) or not want.is_dir():
            return "kept: not a folder"
        ours = top is not None and _is_our_worktree(top, want)
        if ours and not _save_leftovers(top, want, ticket):
            return "kept: its changes could not be saved on branch " + f"orch/{ticket}"
        if ours:
            _git(["worktree", "remove", "--force", str(want)], top)  # THE removal (S3: before `branch -d`)
        if os.path.lexists(want):  # not a worktree of ours, or locked files (Windows): a plain folder now
            rmtree_nofollow(want)  # want: both checks above
    if top is not None:
        _git(["worktree", "prune"], top, filters=False)
    gone = not os.path.lexists(want)
    if not _delete_branch(root, top, ticket):
        _add_pending(root, "branches", {"ticket": ticket, "branch": f"orch/{ticket}"})
    _forget_agent_traces(root, entry, want)
    if not gone:
        _add_pending(root, "folders", {"ticket": ticket, "path": str(want)})
        return "pending"
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


def _remove_locked(root: Path, ticket: str, top: Path | None | bool = False) -> list[str]:
    """remove() with the copies lock already held. Returns one line per thing that was not simply removed."""
    if not isinstance(ticket, str) or not _TID.fullmatch(ticket):
        return [f"'{ticket}' is not a ticket id"]
    if _alive_here(root, ticket):
        return [f"{ticket}: an agent is still working in its copy"]
    if top is False:
        top = _top_of(root)
    want = _want(root, ticket)
    ent = registry(root).get(ticket)
    paths = (ent or {}).get("paths") or []
    keep: list[dict] = []
    notes: list[str] = []
    for e in paths:
        if want is None or not _same(Path(e["path"]), want):
            notes.append(f"{ticket}: dropped a saved copy line that is not this ticket's copy folder")
            continue  # a forged or foreign line: dropped from the list, its path is never touched
        res = _remove_copy(root, ticket, want, e, top)
        if res.startswith("kept"):
            keep.append(e)
            notes.append(f"{ticket}: {res}")
        elif res == "pending":
            notes.append(f"{ticket}: could not delete everything yet, will try again")
    if paths:
        _drop_entry(root, ticket, keep)
    return notes


def remove(root: Path, ticket: str, wait: float = 10.0) -> list[str]:
    """Take back the copy of `ticket`: commit what is in it to orch/<ticket>, remove the worktree, delete the
    folder, drop the registry line and the agent tool's traces, delete the branch when it is merged (else
    the sweep does after BRANCH_DAYS). Returns notes for what stayed; never raises (a copy that cannot be
    removed now is retried by the next sweep). B13 calls this once the changes are added."""
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
    for n in notes:
        _log(root, n)
    return notes


def on_closed(root: Path, ticket: str) -> None:
    """A ticket was closed or cancelled (dropped): its copy goes. Never raises, never waits long."""
    try:
        if ticket not in registry(root):
            return  # no copy: nothing to do, no git call, no lock (the sweep finds odd leftovers)
    except Exception:  # noqa: BLE001
        return
    remove(root, ticket, wait=SWEEP_WAIT)


# ---------------------------------------------------------------- the sweep


def _ticket_closed(root: Path, tid: str) -> bool:
    """The ticket is done, closed (dropped) or not there any more. An unreadable ticket is NOT closed (keep).
    B13: a Done ticket whose changes are still waiting to be added must keep its copy: its check goes here."""
    if not tickets.ticket_path(root, tid).exists():
        return True
    try:
        t = tickets.load(root, tid)
    except Exception:  # noqa: BLE001
        return False
    return isinstance(t, dict) and t.get("status") in _DONE


def _out_of_time(deadline: float) -> bool:
    return time.monotonic() > deadline


def _sweep_registry(root: Path, top, deadline: float, notes: list[str]) -> None:
    """(1) registry entries whose ticket is done, closed or missing."""
    for tid in list(registry(root)):
        if _out_of_time(deadline):
            notes.append("time box reached")
            return
        if _ticket_closed(root, tid):
            notes += _remove_locked(root, tid, top)


def _sweep_orphans(root: Path, top, deadline: float, notes: list[str]) -> None:
    """(2) folders in <home>/worktrees/<ws8>/ that no registry line names: only ticket-named folders, only
    when .owner is this workspace (_remove_copy checks it again), never while a run of that ticket is
    alive."""
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
        if name in known or not _TID.fullmatch(name) or _alive_here(root, name):
            continue
        want = _want(root, name)
        if want is None or not _same(d / name, want) or not os.path.lexists(want):
            continue
        res = _remove_copy(root, name, want, {"path": str(want), "sub": ""}, top)
        notes.append(f"{name}: orphan copy folder: {res}")


def _sweep_pending(root: Path, top, deadline: float, notes: list[str]) -> None:
    """(4) retry the leftovers (locked files) and the branches that were not merged."""
    doc = _pending(root)
    folders = []
    for it in doc["folders"]:
        tid = it["ticket"]
        want = _want(root, tid)
        if want is None or _out_of_time(deadline):
            folders.append(it)
            continue
        if not _same(Path(it["path"]), want) or not _owned(root, want) or _holds_workspace(root, want):
            continue  # not a path we may delete: dropped from the list, untouched
        if os.path.lexists(want) and not (_is_link(want) or not want.is_dir()):
            rmtree_nofollow(want)  # want: both checks above
        if os.path.lexists(want):
            folders.append(it)
        else:
            _git(["worktree", "prune"], top, filters=False) if top else None
    branches = []
    for it in doc["branches"]:
        tid = it["ticket"]
        if top is None or _out_of_time(deadline) or it["branch"] != f"orch/{tid}":
            if it["branch"] == f"orch/{tid}":
                branches.append(it)
            continue
        if _delete_branch(root, top, tid):
            continue
        if _age_days(it["removed_at"]) >= BRANCH_DAYS and not os.path.lexists(
            _want(root, tid) or Path("/nonexistent-orch")
        ):
            if _delete_branch(root, top, tid, force=True):
                notes.append(f"{tid}: deleted its unmerged branch after {BRANCH_DAYS} days")
                continue
        branches.append(it)
    if folders != doc["folders"] or branches != doc["branches"]:
        _save_pending(root, {"folders": folders, "branches": branches})


def _sweep_gone(root: Path, deadline: float, notes: list[str]) -> None:
    """(3) whole <ws8> folders under <home>/worktrees whose .owner workspace is not there (the folder is gone)
    or has another id (the folder was made again). Strict: a real folder named like 8 hex digits (no link),
    `.owner` a plain file with an absolute path, nothing in it but ticket-named folders and `.owner`, and the
    whole thing idle for GONE_DAYS (a disk that is only unplugged must not lose work). Other, living
    workspaces' folders are never touched."""
    base = (addons.home(root) / "worktrees").resolve()
    mine = copies_dir(root)
    if not base.is_dir():
        return
    try:
        folders = sorted(os.scandir(base), key=lambda e: e.name)
    except OSError:
        return
    for ent in folders:
        if _out_of_time(deadline):
            return
        d = base / ent.name
        if not _WS8.fullmatch(ent.name) or _is_link(d) or not d.is_dir() or d == mine:
            continue
        owner = d / ".owner"
        try:
            if owner.is_symlink() or not owner.is_file():
                continue
            main = Path(owner.read_text(encoding="utf-8").strip())
            if not main.is_absolute():
                continue
            wid = addons.workspace_id(main) if main.is_dir() else None
            if wid and wid[:8] == ent.name:
                continue  # its workspace is there: its own sweeps look after it
            kids = [e.name for e in os.scandir(d)]
            if any(k != ".owner" and not _TID.fullmatch(k) for k in kids):
                continue
            newest = max(
                [os.lstat(d).st_mtime, os.lstat(owner).st_mtime]
                + [os.lstat(d / k).st_mtime for k in kids if k != ".owner"]
            )
        except (OSError, ValueError):
            continue
        if time.time() - newest < GONE_DAYS * 86400:
            continue
        ok = True
        for k in kids:
            if k == ".owner":
                continue
            c = d / k
            if _is_link(c) or not c.is_dir():
                ok = False
                continue
            if rmtree_nofollow(c):  # c: a ticket-named folder directly inside a gone workspace's own folder
                for name in adapters_names():
                    with contextlib.suppress(Exception):
                        adapters.forget_folder(name, c, d)
            else:
                ok = False
        if ok:
            with contextlib.suppress(OSError):
                owner.unlink()
                d.rmdir()
            notes.append(f"{ent.name}: removed the copies of a workspace that is gone")


def sweep(root: Path, budget: float = SWEEP_BUDGET) -> list[str]:
    """Take back every copy nobody needs, within `budget` seconds. The notes say what stayed. NEVER raises and
    never waits for the lock more than SWEEP_WAIT: a busy lock means a copy is being made or removed right
    now, and the next sweep does it. Order: (1) done/closed/missing tickets, (2) orphan folders, (3) gone
    workspaces' folders, (4) retries of the pending list. Triggers: orch start, orch run start, orch copy
    clean, the dashboard's "Clean up now"."""
    notes: list[str] = []
    try:
        if not (addons.home(root) / "worktrees").is_dir() and not (root / REGISTRY_PENDING).exists():
            return notes
        deadline = time.monotonic() + budget
        with _scoped(root):
            try:
                with runs.locked(root, LOCK_ID, wait=SWEEP_WAIT):
                    before = getattr(_ctx, "deadline", None)
                    _ctx.deadline = deadline
                    try:
                        top = _top_of(root)
                        for step in (_sweep_registry, _sweep_orphans, _sweep_pending):
                            step(root, top, deadline, notes)
                        _sweep_gone(root, deadline, notes)
                    finally:
                        _ctx.deadline = before
            except Refused:
                notes.append("busy: the next sweep does it")
    except Exception as e:  # noqa: BLE001 - a sweep never stops the person's command
        notes.append(f"the sweep stopped: {e}")
    for n in notes:
        _log(root, n)
    return notes


# ---------------------------------------------------------------- how much room copies take (dashboard)


def usage(root: Path, seconds: float = 3.0, max_entries: int = 200_000) -> dict:
    """{"copies": N, "bytes": X, "partial": bool}: ticket-named folders of this workspace on disk and their
    size (a capped walk, no links followed; `partial` when the cap stopped it). Never on a request path."""
    d = copies_dir(root)
    out = {"copies": 0, "bytes": 0, "partial": False}
    if d is None or not d.is_dir() or _is_link(d):
        return out
    end = time.monotonic() + seconds
    seen = 0
    stack: list[str] = []
    try:
        for e in os.scandir(d):
            if _TID.fullmatch(e.name) and e.is_dir(follow_symlinks=False):
                out["copies"] += 1
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
