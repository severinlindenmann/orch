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
from pathlib import Path

from orch import addons, config, harness, runs, sharedfolder, tickets
from orch.errors import Refused

REGISTRY = Path(".orch") / "run" / "worktrees.json"
LOCK_ID = "_copies"  # runs.locked(root, LOCK_ID): the workspace-level "decide + create + claim" lock
LOCK_WAIT = 150.0  # a worktree of a big repo can take a while; the lock timeout must outlast GIT_ADD_TIMEOUT
GIT_TIMEOUT = 60
GIT_ADD_TIMEOUT = 120
SETUP_TIMEOUT = 600
ID_ARGS = ["-c", "user.name=orch", "-c", "user.email=orch@localhost"]  # for commits made by orch (bring-back)
_TID = re.compile(r"t_[a-z0-9]{6,16}")
_WS8 = re.compile(r"[0-9a-f]{8}")


# ---------------------------------------------------------------- git, as argv lists only


def _git(
    args: list[str], cwd: Path, timeout: float = GIT_TIMEOUT, data: bytes | None = None, strip: bool = True
):
    """(exit code, stdout, stderr) of `git -c core.longpaths=true <args>`. Never a shell; GIT_* of the caller
    dropped (a hook's GIT_DIR must not point us at the wrong repo). A missing git or a timeout is rc 127
    / 124."""
    argv = ["git", "-c", "core.longpaths=true", *args]
    try:
        p = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            input=data,
            env=harness._git_env(),
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return 127, "", "git is not installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"git {args[0]} took longer than {int(timeout)} s"
    except OSError as e:
        return 127, "", str(e)
    out = p.stdout.decode("utf-8", "surrogateescape")
    return p.returncode, out.strip() if strip else out, p.stderr.decode("utf-8", "replace").strip()


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


def work_dir(entry: dict) -> Path:
    """Where the agent starts for a registry/ticket entry: the copy of the git top folder, plus `sub`."""
    sub = entry.get("sub") or ""
    return Path(entry["path"]) / sub if sub else Path(entry["path"])


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
            if isinstance(p, dict) and isinstance(p.get("path"), str) and isinstance(p.get("branch"), str)
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
        base = h / "worktrees"
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


def workdir_for(root: Path, rec: dict | None) -> Path:
    """The folder a run works in: its record's `folder` when that is a copy of this workspace, else the root.
    A path that is not one of this machine's copies (a synced record, an edited file) is ignored."""
    f = (rec or {}).get("folder")
    if not isinstance(f, str) or not f:
        return root
    try:
        p = Path(f).resolve()
        if p == root.resolve():
            return root
        mine = copies_dir(root)
        if mine is not None and p.is_dir() and p.relative_to(mine) and is_orch_copy(p):
            return p
    except (OSError, ValueError, RuntimeError):
        pass
    return root


# ---------------------------------------------------------------- make one


def _repo(root: Path) -> tuple[Path, str, str] | None:
    """(git top folder, the workspace's path below it, HEAD commit) or None: no git, no commit, or git
    unhappy."""
    rc, out, _ = _git(["rev-parse", "--show-toplevel"], root)
    if rc != 0 or not out:
        return None
    top = Path(out).resolve()  # git prints forward slashes, also on Windows
    try:
        rel = root.resolve().relative_to(top).as_posix()
    except ValueError:
        return None
    rc, head, _ = _git(["rev-parse", "--verify", "HEAD^{commit}"], root)
    if rc != 0 or not re.fullmatch(r"[0-9a-f]{40,64}", head):
        return None
    return top, ("" if rel == "." else rel), head


def _drop_partial(top: Path, dest: Path, branch: str, made_branch: bool) -> None:
    """A copy that did not get finished: take back exactly what this call made (this path, this branch)."""
    _git(["worktree", "remove", "--force", str(dest)], top)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)  # dest is the path_for() path we just made, nothing else
    _git(["worktree", "prune"], top)
    if made_branch:
        _git(["branch", "-D", branch], top)


def _create(root: Path, ticket: str) -> tuple[dict | None, str]:
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
        _git(["worktree", "prune"], top)  # a copy somebody deleted by hand is still on git's list
        if dest.exists() or dest.is_symlink():
            return None, "That copy folder is already there."
    branch = f"orch/{ticket}"
    rc, _, _ = _git(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], top)
    made_branch = rc != 0
    add = [
        "worktree",
        "add",
        "--no-checkout",
    ]  # no checkout: the project's tracked .orch must never land in it
    add += ["-b", branch, str(dest), "HEAD"] if made_branch else [str(dest), branch]
    rc, _, err = _git(add, top, GIT_ADD_TIMEOUT)
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
                ["--literal-pathspecs", "ls-files", "-z", "--", pathspec], dest, strip=False
            )
            if rc != 0:
                break
            if not listed:
                continue
            data = listed.encode("utf-8", "surrogateescape")
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
    with start_lock(root):
        ent = (registry(root).get(ticket) or {"paths": []})["paths"]
        if ent and Path(ent[0]["path"]).is_dir():
            return ent[0]
        return _create(root, ticket)[0]


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
    exe = shutil.which(argv[0]) if argv else None
    if not exe:
        return [
            f"The copy setup command '{argv[0] if argv else cmd}' was not found. The copy is used as it is."
        ]
    argv[0] = exe
    log = root / ".orch" / "run" / "logs" / f"{ticket}-copy-setup.log"
    try:
        with runs.open_log(log) as out:
            out.write(f"$ {cmd}\n".encode())
            proc = subprocess.Popen(
                argv,
                cwd=work_dir(entry),
                env={**os.environ, "ORCH_ROOT": str(root)},
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


def _record_on_ticket(root: Path, ticket: str, entry: dict) -> None:
    def fn(t: dict):
        work = t.setdefault("work", {})
        if not isinstance(work, dict):
            work = t["work"] = {}
        folders = [
            f for f in work.get("folders") or [] if isinstance(f, dict) and f.get("path") != entry["path"]
        ]
        folders.insert(
            0, {k: entry[k] for k in ("path", "branch", "base", "sub") if entry.get(k) is not None}
        )
        work["folders"] = folders

    tickets.apply_op(root, ticket, fn)


# ---------------------------------------------------------------- routing


def _alive_here(root: Path, ticket: str) -> dict | None:
    rec = runs.read(root, ticket)
    return rec if rec and runs.state(rec) in ("alive", "maybe-stale") else None


def route(root: Path, ticket: str) -> tuple[Path, list[str]]:
    """Where does this ticket's agent work: (folder, notes for the person). Call it inside start_lock,
    and claim
    the run inside the same lock. The ticket keeps its copy for life; a new copy is made only when the setting
    asks for one (together: another alive run is in the project folder; always), git can make it, and
    fewer than
    `workflow.copies_max` copies exist. Anything else: the project folder."""
    rec = _alive_here(root, ticket)
    if rec:  # a run is on (or about to take over) this ticket: it stays where it is
        return workdir_for(root, rec), []
    reg = registry(root).get(ticket)
    if reg:
        for e in reg["paths"]:
            if Path(e["path"]).is_dir() and is_orch_copy(Path(e["path"])):
                return work_dir(e), []
        # registered but gone from the disk: make it again below (same path, same branch)
    mode = config.copies_mode(root)
    if mode == "off" and not reg:
        return root, []
    if not reg and mode == "together" and not sharedfolder.alive_in(root, root, ticket):
        return root, []
    if not reg and count(root) >= config.copies_max(root):
        n = config.copies_max(root)
        return root, [
            f"{n} separate copies exist already (the most at once), so this works in your own folder."
        ]
    entry, why = _create(root, ticket)
    if entry is None:
        return root, []  # no git (or not possible here): the "also changing this folder" line says the rest
    notes = _prepare_files(root, entry)
    notes += _setup(root, ticket, entry)
    with contextlib.suppress(Exception):  # the ticket remembers it; a failed write must not stop the start
        _record_on_ticket(root, ticket, entry)
    return work_dir(entry), notes
