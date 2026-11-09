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

`--hook <tool>` speaks that tool's hook protocol, all of it data in agents/reminder.json
(`reminder_hooks` events, `reminder.output` template, `reminder.skip` names): the event comes on
stdin as JSON, the line goes out as the template says, the exit code is always 0 (exit 2 would block
the person's prompt), a watchdog (started in __main__ before the heavy imports, and again here) ends
the process after HARD_TIMEOUT seconds.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
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
# each tool's own setup names (its settings folder, skill links, local instruction file) come from its
# `reminder.skip` data
SKIP_DIRS = (".orch", ".git", "node_modules", ".venv", "__pycache__", "dist", "build")
SKIP_FILES = ("AGENTS.orch.md",)
KEEP_MARKERS = 20
_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_GIT = [
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


_GIT_EXE: list = []  # git's path, found once per process (the hook has a single root)


def _tool_skips() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(folders, files) every built-in tool's data asks to leave out of the scan, plus the fixed ones."""
    from orch import adapters

    dirs, files = list(SKIP_DIRS), list(SKIP_FILES)
    for n in adapters.builtin_names():
        for name in (adapters.load(n).get("reminder") or {}).get("skip") or []:
            (dirs if not name.endswith(".md") else files).append(name)
    return tuple(dict.fromkeys(dirs)), tuple(dict.fromkeys(files))


def _inside(path: str, folder: str) -> bool:
    """path is folder or below it (commonpath of normalised real paths: right at a drive root too)."""
    p, f = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(folder))
    try:
        return os.path.commonpath([p, f]) == f
    except ValueError:  # another drive
        return False


def _git_exe(root: Path) -> str | None:
    """git as an ABSOLUTE path, found once on PATH. Windows resolves a bare "git" (and shutil.which) in the
    current folder first (the project: a committed git.exe would run on every prompt), so each ABSOLUTE PATH
    entry is checked for exactly `git.exe` (Windows) or `git` (POSIX) by hand: no relative entry, no .cmd,
    no entry at or under the project or the current folder. Migrate to safegit (B11)."""
    if _GIT_EXE:
        return _GIT_EXE[0]
    name = "git.exe" if os.name == "nt" else "git"
    found = None
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d or not os.path.isabs(d) or _inside(d, str(root)) or _inside(d, os.getcwd()):
            continue
        cand = os.path.join(d, name)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            found = cand
            break
    _GIT_EXE.append(found)
    return found


def _git(root: Path, args: list[str], deadline: float) -> subprocess.CompletedProcess | None:
    left = deadline - time.monotonic()
    if left <= 0:
        raise _Stop
    exe = _git_exe(root)
    if exe is None:
        return None  # no (safe) git program: the folder is walked instead
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        return subprocess.run(  # fixed argv list, no shell; the child is killed when the timeout hits
            [exe, *_GIT, *args], cwd=root, capture_output=True, timeout=left, env=env, check=False
        )
    except subprocess.TimeoutExpired:
        raise _Stop from None
    except OSError:
        return None


def _exclude() -> list[str]:
    return [f":(exclude,glob)**/{d}/**" for d in _tool_skips()[0] if d != ".git"]


def _git_names(root: Path, deadline: float) -> list[str] | None:
    """Tracked and untracked-not-ignored paths, as git lists them; None = not a git folder (or no git)."""
    r = _git(root, ["rev-parse", "--is-inside-work-tree"], deadline)
    if r is None or r.returncode != 0:
        return None
    out: list[str] = []
    for extra in ([], ["--others", "--exclude-standard"]):
        r = _git(root, ["ls-files", "-z", *extra, "--", ".", *_exclude()], deadline)
        if r is None or r.returncode != 0 or len(r.stdout) > MAX_LIST:
            raise _Stop
        out += [os.fsdecode(n) for n in r.stdout.split(b"\0") if n]
    return list(dict.fromkeys(out))


def _walk_names(root: Path, deadline: float) -> list[str]:
    """No git: every regular file below root, skipping the skipped folders; links are never followed."""
    skip_dirs = _tool_skips()[0]
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
                        if e.name not in skip_dirs:
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
    skip_dirs, skip_files = _tool_skips()
    try:
        names = _git_names(root, deadline)
        if names is None:
            names = _walk_names(root, deadline)
        if len(names) > MAX_FILES:
            return None
        out = []
        for n, rel in enumerate(names):
            if rel in skip_files or rel.split("/", 1)[0] in skip_dirs:
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
        for x in (root / ".orch", root / ".orch" / "run", d):
            if x.is_symlink() or (hasattr(x, "is_junction") and x.is_junction()):
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


def _read_event(events: tuple[str, ...], root_hint: list, names: dict | None = None) -> str | None:
    """The hook's stdin JSON: returns the event name (None = not one of `events`), adds its cwd to root_hint.
    Reads in a thread: a stdin that never closes must not hang the hook."""
    box: list[str] = []

    def read():
        with contextlib.suppress(Exception):
            box.append(sys.stdin.read(65536))

    t = threading.Thread(target=read, daemon=True)
    t.start()
    t.join(1.0)
    names = names or {}
    event = names.get("default_event") or events[-1]  # nothing readable: the usual one
    try:
        data = json.loads(box[0]) if box and box[0].strip() else None
    except (ValueError, RecursionError):
        data = None
    if isinstance(data, dict):
        ev = data.get(names.get("event", "hook_event_name"))
        if isinstance(ev, str):
            event = ev
        cwd = data.get(names.get("cwd", "cwd"))
        if isinstance(cwd, str) and os.path.isabs(cwd) and os.path.isdir(cwd):
            root_hint.append(cwd)
    return event if event in events else None


def find_root(start: Path) -> Path:
    """The workspace of `start`: its own `.orch`, else the nearest one upwards, but only below a boundary we
    can see (a `.git` folder or the home folder) and owned by us: a `.orch` in a shared ancestor (/tmp,
    a drive root) is nobody's. No boundary found on the way up: only `start` itself counts."""
    home = Path.home()
    chain = []
    for p in (start, *start.parents):
        chain.append(p)
        if p == home or (p / ".git").exists():
            break
    else:
        chain = [start]

    def ours(o: Path) -> bool:
        try:
            if not o.is_dir() or o.is_symlink() or (hasattr(o, "is_junction") and o.is_junction()):
                return False
            return not hasattr(os, "getuid") or o.stat().st_uid == os.getuid()
        except OSError:
            return False

    for p in chain:
        if ours(p / ".orch"):
            return p
    return start


def _fill(node, event: str, line: str):
    if isinstance(node, str):
        return node.replace("{event}", event).replace("{line}", line)
    if isinstance(node, dict):
        return {k: _fill(v, event, line) for k, v in node.items()}
    if isinstance(node, list):
        return [_fill(v, event, line) for v in node]
    return node


def start_watchdog() -> threading.Timer:
    timer = threading.Timer(HARD_TIMEOUT, lambda: os._exit(0))
    timer.daemon = True
    timer.start()
    return timer


def hook_main(argv: list[str] | None = None, watchdog: threading.Timer | None = None) -> int:
    """`orch work-check --hook <tool>`: always exit 0; stdout is empty or the tool's one JSON object."""
    timer = start_watchdog()
    if watchdog is not None:
        watchdog.cancel()  # the one from __main__ is replaced by this one
    try:
        argv = sys.argv[1:] if argv is None else argv
        tool = argv[argv.index("--hook") + 1] if "--hook" in argv[:-1] else ""
        from orch import adapters

        data = adapters.load(tool).get("reminder") if _NAME.match(tool) else None
        hooks = adapters.load(tool).get("reminder_hooks") if data else None
        if not hooks or not data.get("output"):
            return 0
        hint: list[str] = []
        event = _read_event(tuple(hooks), hint, data.get("input"))
        root = find_root(Path(hint[0] if hint else os.getcwd()))
        if event is None or own_ticket_open(root):
            return 0
        res = check(root)
        if res["remind"] and first_time(root, res["sig"]):
            sys.stdout.write(json.dumps(_fill(data["output"], event, res["line"])) + "\n")
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
