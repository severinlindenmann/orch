"""orch work-check: one plain line when files changed and no ticket covers them. Pure reading, never blocks.

Changed = a file in the work folder newer than the last ticket event of this workspace. Active = an open
ticket with a live run or claim (an orch-started run, or a hand-started agent that claimed one).

Safety (the folder may be a repo someone else prepared):
- git only LISTS files (`ls-files`, `rev-parse`). It never compares or filters content, so no clean/smudge
  filter, textconv or diff driver of the repo can run (`git status` and `git diff` stat-compare and then
  compare content, which runs those filters). Fixed argv lists, no shell, GIT_* removed, hooks/fsmonitor/
  untracked cache off (same pattern as B8's filesig: dedupe with it after B8 merges).
- orch decides "changed" itself from lstat (mtime), never follows a link and never reads a file.
- Any error, a timeout or a cap (too many files, too slow) means silence.

Once per change set (hook mode only): a marker file `.orch/run/work-check/<hash of the change set>` is created
exclusively; whoever creates it prints, a second fire (the same hook in two settings files, or the next turn)
finds it and stays quiet.

`--hook claude` speaks Claude's hook protocol: the event comes on stdin as JSON, the line goes out as
`{"hookSpecificOutput": {"hookEventName": <event>, "additionalContext": <line>}}`, the exit code is always 0
(exit 2 would block the person's prompt), a watchdog ends the process after HARD_TIMEOUT seconds.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

LINE = (
    'orch: files changed last turn and no ticket is open: record it with orch ticket new "<title>" '
    "or orch run claim <id>."
)
TIMEOUT = 3.0  # seconds for the whole scan
HARD_TIMEOUT = 4.0  # the hook process ends here whatever it is doing
MAX_FILES = 20000
MAX_LIST = 16 * 1024 * 1024
# .agents and .claude hold tool setup (orch init writes skill links and settings there), not the person's work
SKIP_DIRS = (".orch", ".git", ".agents", ".claude", "node_modules", ".venv", "__pycache__", "dist", "build")
SKIP_FILES = ("CLAUDE.local.md", "AGENTS.orch.md")  # orch's own local instruction files
HOOK_EVENTS = ("SessionStart", "UserPromptSubmit")
KEEP_MARKERS = 20
_EXCLUDE = [f":(exclude,glob)**/{d}/**" for d in SKIP_DIRS if d != ".git"]
_GIT = [
    "git",
    "--no-pager",
    "--no-optional-locks",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.untrackedCache=false",
    "-c",
    "core.quotepath=off",
]


class _Stop(Exception):
    """A cap or the deadline: the answer is silence."""


def _git(root: Path, args: list[str], deadline: float) -> subprocess.CompletedProcess | None:
    left = deadline - time.monotonic()
    if left <= 0:
        raise _Stop
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        return subprocess.run(  # fixed argv list, no shell
            _GIT + args, cwd=root, capture_output=True, timeout=left, env=env, check=False
        )
    except subprocess.TimeoutExpired:
        raise _Stop from None
    except OSError:
        return None  # no git program: the folder is walked instead


def _git_names(root: Path, deadline: float) -> list[str] | None:
    """Tracked and untracked-not-ignored paths, as git lists them; None = not a git folder (or no git)."""
    r = _git(root, ["rev-parse", "--is-inside-work-tree"], deadline)
    if r is None or r.returncode != 0:
        return None
    out: list[str] = []
    for extra in ([], ["--others", "--exclude-standard"]):
        r = _git(root, ["ls-files", "-z", *extra, "--", ".", *_EXCLUDE], deadline)
        if r is None or r.returncode != 0 or len(r.stdout) > MAX_LIST:
            raise _Stop
        out += [os.fsdecode(n) for n in r.stdout.split(b"\0") if n]
    return list(dict.fromkeys(out))


def _walk_names(root: Path, deadline: float) -> list[str]:
    """No git: every regular file below root, skipping SKIP_DIRS; links are never followed."""
    out: list[str] = []
    stack = [""]
    while stack:
        if time.monotonic() > deadline:
            raise _Stop
        rel = stack.pop()
        try:
            with os.scandir(root / rel if rel else root) as it:
                for e in it:
                    path = f"{rel}/{e.name}" if rel else e.name
                    if e.is_symlink():
                        continue
                    if e.is_dir(follow_symlinks=False):
                        if e.name not in SKIP_DIRS:
                            stack.append(path)
                    else:
                        out.append(path)
                        if len(out) > MAX_FILES:
                            raise _Stop
        except OSError:
            continue
    return out


def last_event(root: Path) -> float | None:
    """Time (epoch seconds) of the newest ticket event of this workspace; else when orch was set up here."""
    from orch import tickets
    from orch.runs import _parse

    best = 0.0
    for t in tickets.list_all(root, include_general=True):
        stamps = [t.get("created_at"), t.get("updated_at"), *[h.get("at") for h in t.get("history") or []]]
        for s in stamps:
            with contextlib.suppress(Exception):
                best = max(best, _parse(s))
    if best:
        return best
    try:
        return (root / ".orch" / ".gitignore").stat().st_mtime
    except OSError:
        return None


def changed_files(root: Path, since: float) -> list[tuple[str, int, int]] | None:
    """(path, size, mtime_ns) of the files newer than `since`, sorted; None = cannot tell (silent)."""
    deadline = time.monotonic() + TIMEOUT
    try:
        names = _git_names(root, deadline)
        if names is None:
            names = _walk_names(root, deadline)
        if len(names) > MAX_FILES:
            return None
        out = []
        for n, rel in enumerate(names):
            if rel in SKIP_FILES or rel.split("/", 1)[0] in SKIP_DIRS:
                continue
            if n % 256 == 0 and time.monotonic() > deadline:
                return None
            try:
                st = os.lstat(root / rel)
            except OSError:
                continue  # deleted since listed
            if stat.S_ISREG(st.st_mode) and st.st_mtime > since:
                out.append((rel, st.st_size, st.st_mtime_ns))
        return sorted(out)
    except _Stop:
        return None


def covered(root: Path) -> bool:
    """True when an open ticket has an active run or claim (nobody is left out of the record)."""
    from orch import runs, tickets

    for t in tickets.list_all(root):
        if t.get("status") not in tickets.OPEN_STATUSES:
            continue
        try:
            rec = runs.read(root, t["id"])
            if rec and runs.state(rec) in ("alive", "maybe-stale"):
                return True
        except Exception:
            continue
    return False


def own_ticket_open(root: Path) -> bool:
    """The environment of an orch-started run (ORCH_RUN + ORCH_TICKET) names a ticket that is open."""
    from orch import tickets

    if not os.environ.get("ORCH_RUN"):
        return False
    try:
        t = tickets.load(root, os.environ.get("ORCH_TICKET", ""))
    except Exception:
        return False
    return t.get("status") in tickets.OPEN_STATUSES


def check(root: Path) -> dict:
    """{"remind": bool, "files": n, "sig": hash|None, "line": str}. Never raises."""
    quiet = {"remind": False, "files": 0, "sig": None, "line": ""}
    try:
        if not (root / ".orch").is_dir() or (root / ".orch").is_symlink():
            return quiet
        since = last_event(root)
        if since is None:
            return quiet
        files = changed_files(root, since)
        if not files:
            return quiet
        if covered(root):
            return {**quiet, "files": len(files)}
        sig = hashlib.sha256(json.dumps(files).encode()).hexdigest()
        return {"remind": True, "files": len(files), "sig": sig, "line": LINE}
    except Exception:
        return quiet


def first_time(root: Path, sig: str) -> bool:
    """True for exactly one caller per change set (exclusive create of its marker). Error = False (silent)."""
    try:
        d = root / ".orch" / "run" / "work-check"
        if (root / ".orch" / "run").is_symlink() or d.is_symlink():
            return False
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(d / sig[:32], os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
    except OSError:
        return False
    with contextlib.suppress(OSError):  # keep the newest few markers only
        old = sorted(d.iterdir(), key=lambda p: p.stat().st_mtime)[:-KEEP_MARKERS]
        for p in old:
            if p.is_file() and not p.is_symlink():
                p.unlink()
    return True


def _read_event(root_hint: list) -> str | None:
    """The hook's stdin JSON: returns the event name (None = unknown event), sets root_hint[0] to its cwd.
    Reads in a thread: a stdin that never closes must not hang the hook."""
    box: list[str] = []

    def read():
        with contextlib.suppress(Exception):
            box.append(sys.stdin.read(65536))

    t = threading.Thread(target=read, daemon=True)
    t.start()
    t.join(1.0)
    event = "UserPromptSubmit"  # nothing readable: the usual one
    try:
        data = json.loads(box[0]) if box and box[0].strip() else None
    except ValueError:
        data = None
    if isinstance(data, dict):
        if isinstance(data.get("hook_event_name"), str):
            event = data["hook_event_name"]
        cwd = data.get("cwd")
        if isinstance(cwd, str) and os.path.isabs(cwd) and os.path.isdir(cwd):
            root_hint.append(cwd)
    return event if event in HOOK_EVENTS else None


def find_root(start: Path) -> Path:
    for p in (start, *start.parents):
        if (p / ".orch").is_dir():
            return p
    return start


def hook_main() -> int:
    """`orch work-check --hook claude`: always exit 0; stdout is empty or one JSON object."""
    timer = threading.Timer(HARD_TIMEOUT, lambda: os._exit(0))
    timer.daemon = True
    timer.start()
    try:
        hint: list[str] = []
        event = _read_event(hint)
        root = find_root(Path(hint[0] if hint else os.getcwd()))
        if event is None or own_ticket_open(root):
            return 0
        res = check(root)
        if res["remind"] and first_time(root, res["sig"]):
            doc = {"hookSpecificOutput": {"hookEventName": event, "additionalContext": res["line"]}}
            sys.stdout.write(json.dumps(doc) + "\n")
            sys.stdout.flush()
    except BaseException:
        pass
    finally:
        timer.cancel()
    return 0


def run(root: Path, as_json: bool) -> None:
    """`orch work-check [--json]`: the line when there is something to say, else nothing (JSON: always)."""
    res = check(root)
    if as_json:
        print(json.dumps({"remind": res["remind"], "files": res["files"], "line": res["line"] or None}))
    elif res["remind"]:
        print(res["line"])
