"""The ONE place orch runs git inside a workspace or a separate copy of it.

A repository's own configuration is not trusted. `.git/config` (also through include.path / includeIf),
`.gitattributes` and `.git/hooks` can name programs, and in a copy they are branch content an agent could have
written. When a person clicks Start, orch must not become the one who runs them, outside the agent tool's
sandbox and permission mode. So every call here:

* drops every GIT_* variable of the caller (a hook's GIT_DIR must not aim us at another repository; only what
  this module sets is passed), and sets GIT_TERMINAL_PROMPT=0;
* hooksPath is a fixed device path or a random never-created name; never derived from a file or folder that
  exists (/dev/null; //./NUL on Windows), so repo hooks (reference-transaction, post-checkout, ...) never run;
* turns off `core.fsmonitor` and the untracked cache, `protocol.allow=never` (no network), `core.longpaths`
  (Windows), signing (`commit.gpgSign`, `tag.gpgSign`: no `gpg.program` of the repo runs), `core.sshCommand`,
  `credential.helper`, and `diff.external`; diff-like commands (diff, log, show) get `--no-ext-diff
  --no-textconv`;
* neutralizes every filter driver (clean/smudge/process) and merge driver the repository's configuration
  defines (git has no wildcard: they are enumerated with `git config --includes --get-regexp`, which runs
  nothing), and where git is new enough (2.40) reads no attributes from the branch at all
  (`--attr-source=<empty tree of the repo's hash algorithm>`). That option also means no `text`/`eol`/
  `working-tree-encoding` attribute applies on git >= 2.40: a copy holds the committed bytes (tests check a
  CRLF `text=auto` repo); older git reads the attributes (filters stay neutralized).
  FAIL CLOSED: if the enumeration fails or times out, the operation is refused
  (rc 125), never run with the repository's own drivers. `filters=False` is only for calls that touch no file
  content (rev-parse, config, worktree list);
* adds `--no-optional-locks` to read-only calls, takes an argv list and a timeout, never a shell;
* runs one absolute `git` found on the PATH (no current folder, nothing inside the workspace, the copy or any
  orch worktrees folder), cached per set of such folders.

tests/test_safegit.py has an AST lint: no other module under workspace/src/orch may start git itself, except
LEGACY, which must shrink to zero.
"""

from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from orch import addons

# Modules that still start git themselves. MUST SHRINK TO ZERO: each moves onto safegit. (Empty since B11b.)
LEGACY = ()

IDENTITY = ["-c", "user.name=orch", "-c", "user.email=orch@localhost"]  # for commits orch makes (bring-back)
EMPTY_TREE = {  # by `rev-parse --show-object-format`
    "sha1": "4b825dc642cb6eb9a060e54bf8d69288fbee4904",
    "sha256": "6ef19b41225c5369f1c104d45d8d85efa9b057b53b14b4b9b939dd74decc5321",
}
TIMEOUT = 60
CANNOT_START = 126  # rc: git was found but the operating system could not start it
TOO_LONG = 123  # rc: git's output was longer than the caller's cap
REFUSED = (
    125  # rc: orch refused to run this git call for a safety reason (not allowed, interactive, no drivers)
)
_DRIVER = re.compile(r"^(filter\.(.+)\.(smudge|clean|process)|merge\.(.+)\.driver)$")
_DIFFLIKE = {
    "diff",
    "log",
    "show",
    "format-patch",
    "blame",
    "grep",
    "whatchanged",
    "range-diff",
}  # (`git cherry` takes none of these flags and runs no diff driver)
_GLOBAL_WITH_VALUE = {
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--exec-path",
    "--attr-source",
    "--config-env",
    "--super-prefix",
}

# a value that runs nothing, for the read-only questions orch asks first (no editor is ever involved there)
_NOOP = ""
_exes: dict[frozenset, str | None] = {}
_versions: dict[str, tuple[int, int]] = {}
_trees: dict[str, str] = {}  # the empty tree id per folder
_lock = threading.Lock()


# ---------------------------------------------------------------- which git


_EXACT = "="  # an avoid entry that starts with this means "this folder only", not its subtree
_SYSTEM_BINS = ("/usr/bin", "/bin", "/usr/local/bin", "/opt/homebrew/bin", "/usr/sbin", "/sbin")
_TRUE_HINT = (
    " On Windows: run orch from outside the project's virtual environment folder, or use a virtual "
    "environment located elsewhere."
)


def _inside(path: str, folder: str) -> bool:
    """`path` is in `folder` (a subtree), by its name or where it really is (links resolved); commonpath.
    A folder written `=<folder>` matches only a path whose own folder is exactly that one."""
    exact = folder.startswith(_EXACT)
    b = os.path.normcase(os.path.realpath(folder[1:] if exact else folder))
    for a in (os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.abspath(path))):
        if exact:
            if os.path.normcase(os.path.dirname(a)) == b or a == b:
                return True
            continue
        try:
            if os.path.commonpath([a, b]) == b:
                return True
        except ValueError:  # another drive
            pass
    return False


def _is_home(f: Path) -> bool:
    try:
        return f == Path.home().resolve()
    except (OSError, RuntimeError, KeyError):
        return False  # a failing home lookup never makes a folder "home" (and so never relaxes anything)


def _same_as_home(f: Path) -> bool:
    """The same folder as home even when spelled differently (a case-insensitive file system, a link)."""
    try:
        return os.path.samefile(f, Path.home())
    except (OSError, RuntimeError, KeyError, ValueError):
        return False


def _is_anchor(f: Path) -> bool:
    return f.parent == f


def _broad(folder: Path) -> bool:
    """A folder whose whole subtree must not be avoided: a filesystem anchor (`/`, `C:\\`: cron, systemd,
    Docker WORKDIR /), the user's home, or an ancestor of the standard system bin folders. Used ONLY for the
    process cwd. Any failure answers False: full avoidance stays."""
    try:
        f = folder.resolve()
        if _is_anchor(f) or _is_home(f):
            return True
        return any(_inside(b, str(f)) for b in _SYSTEM_BINS if os.path.isdir(b))
    except (OSError, RuntimeError, ValueError):
        return False


def _entry(folder: Path) -> str:
    """The avoid entry for the PROCESS cwd: exact-only when it is broad, else its whole subtree."""
    return _EXACT + str(folder) if _broad(folder) else str(folder)


def unusable_root(root: Path | None) -> str | None:
    """A workspace root that is the user's home or a filesystem anchor cannot be told apart from "everything":
    git is refused there (the caller sees rc 125 and this message)."""
    if root is None:
        return None
    try:
        f = Path(root).resolve()
    except (OSError, RuntimeError):
        return None
    if _is_anchor(f) or _is_home(f) or _same_as_home(f):
        return (
            "orch can't use git when the workspace is your whole home folder or a drive root; "
            "open a project folder instead"
        )
    return None


def _avoid(cwd: Path, root: Path | None) -> frozenset:
    out = {str(cwd)}  # the caller's folder and the root: always the whole subtree
    try:
        out.add(_entry(Path.cwd()))  # always: whatever the caller passes, never a git from our own cwd
    except OSError:
        pass
    if root is not None:
        out.add(str(root))
    homes = list(addons.home_candidates())
    try:
        homes.append(addons.home(root))
    except Exception:  # noqa: BLE001 - no usable orch home: the candidates above are enough
        pass
    out.update(str(h / "worktrees") for h in homes)
    return frozenset(out)


def find_exe(name: str, avoid) -> str | None:
    """A program found on the PATH as an absolute path. The ONE lookup for git and for the person's setup
    command. Not shutil.which (on Windows it also looks in the current folder, so a committed file would run).
    Only absolute PATH entries count, only `<name>.exe` on Windows (never .cmd/.bat: they go through cmd.exe),
    and never one inside any folder in `avoid` (the folder we work in, the workspace root, the copy, any orch
    worktrees folder)."""
    fn = name if os.name != "nt" or name.lower().endswith(".exe") else name + ".exe"
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d or d == "." or not os.path.isabs(d):
            continue
        p = os.path.join(d, fn)
        if os.path.isfile(p) and os.access(p, os.X_OK) and not any(_inside(p, a) for a in avoid):
            return p
    return None


def have_git(cwd: Path, root: Path | None = None) -> bool:
    """A git that orch trusts exists here (found by the avoid rules). A yes/no only, never a path: no other
    module gets the program (the lint in tests/test_safegit.py forbids git_exe(), hardened() and any git
    path outside this module)."""
    return git_exe(cwd, root) is not None


def git_on_path() -> bool:
    """Is there SOME git program on the PATH (find_exe with nothing avoided)? A yes/no, never a path. Narrower
    than the old per-caller lookup: only ABSOLUTE PATH entries count, so a git planted only in a relative or
    empty entry no longer says "a git exists but is untrusted" (the callers still refuse in a folder that
    has a .git). Lets a caller tell "git is not installed" from "only a git orch does not trust is here"."""
    return find_exe("git", frozenset()) is not None


def avoid_for(cwd: Path, root: Path | None = None) -> frozenset:
    return _avoid(cwd, root)


def git_exe(cwd: Path, root: Path | None = None) -> str | None:
    """The one git program orch runs (see find_exe). Cached per set of avoided folders and the PATH."""
    avoid = _avoid(cwd, root)
    key = avoid | {"PATH=" + os.environ.get("PATH", ""), "CWD=" + os.getcwd()}
    with _lock:
        if key not in _exes:
            _exes[key] = find_exe("git", avoid)
        return _exes[key]


# ---------------------------------------------------------------- arguments


def _python_trivial(name: str, cwd: Path, root: Path | None) -> str | None:
    """Windows has no true/false programs: the python running orch does it, unless that python is inside the
    folder we work in, the workspace root or a copy (a project's own .venv is not a trusted program)."""

    if any(_inside(sys.executable, a) for a in _avoid(cwd, root)):
        return None
    code = "pass" if name == "true" else "raise SystemExit(1)"
    return f'"{sys.executable}" -c "{code}"'


def trivial(name: str, cwd: Path, root: Path | None = None) -> str | None:
    """A command git runs as `true` or `false` (editor, askpass, a merge driver that must fail): an ABSOLUTE
    path found by find_exe, never a bare name that git would resolve through a PATH an agent controls. On
    Windows (no true/false programs) the python running orch, quoted. None = not found: the caller refuses."""
    if os.name == "nt":
        return _python_trivial(name, cwd, root)
    exe = find_exe(name, _avoid(cwd, root))
    return shlex.quote(exe) if exe else None


def safe_path(cwd: Path, root: Path | None = None) -> str:
    """PATH for git and everything it starts: absolute entries only, none inside the folder we work in, the
    workspace root, the copy or an orch worktrees folder (a program an agent committed is never found)."""
    avoid = _avoid(cwd, root)
    keep = [
        d
        for d in os.environ.get("PATH", "").split(os.pathsep)
        if d and os.path.isabs(d) and not any(_inside(d, a) for a in avoid)
    ]
    return os.pathsep.join(keep)


def env(cwd: Path, root: Path | None, true: str, config: list[tuple[str, str]] | None = None):
    """The environment of every git call: ours without any GIT_* variable, a sanitized PATH, and (set AFTER
    the strip, on purpose) nothing may open an editor, ask a password or prompt. `config`: (key, value) pairs
    given through GIT_CONFIG_COUNT/KEY_n/VALUE_n, so a repository-chosen name never has to survive `-c`."""
    e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    e["LC_ALL"] = e["LANG"] = "C"  # harness.py reads git's stderr text
    e["PATH"] = safe_path(cwd, root)
    e["GIT_TERMINAL_PROMPT"] = "0"
    e["GIT_EDITOR"] = e["GIT_SEQUENCE_EDITOR"] = e["GIT_ASKPASS"] = true
    # refs/replace/* and the grafts file live in the shared repository and an agent can write them: with them
    # on, a commit id stays the same while its content or parents change (tip and ancestor checks would lie)
    e["GIT_NO_REPLACE_OBJECTS"] = "1"
    e["GIT_GRAFT_FILE"] = os.devnull
    if config:
        e["GIT_CONFIG_COUNT"] = str(len(config))
        for i, (k, v) in enumerate(config):
            e[f"GIT_CONFIG_KEY_{i}"], e[f"GIT_CONFIG_VALUE_{i}"] = k, v
    return e


def _no_hooks(cwd: Path | None = None, root: Path | None = None) -> str:
    """core.hooksPath for every call. POSIX: /dev/null (a device: it can't be a folder or be redirected).
    Windows: the absolute device path //./NUL (git for Windows is to accept it; the next Windows run
    checks it; if it rejects it, use a random 32-hex name below %LOCALAPPDATA%\\orch, never created).
    Invariant: hooksPath is a fixed device path or a random never-created name; never derived from a file
    or folder that exists. (cwd and root are accepted for the callers' sake and unused.)"""
    if os.name != "nt":
        return "/dev/null"
    return "//./NUL"


def base_args(true: str, read_only: bool = False, hooks: str | None = None) -> list[str]:
    out = [
        "-c", f"core.hooksPath={hooks or _no_hooks()}",
        "-c", "core.fsmonitor=false",
        "-c", "core.untrackedCache=false",
        "-c", "protocol.allow=never",
        "-c", "core.longpaths=true",
        "-c", "merge.autoStash=false",
        "-c", "rerere.enabled=false",
        "-c", "commit.gpgSign=false",
        "-c", "tag.gpgSign=false",
        # a repo's own .git/config (an agent can write it) must never make git run a signature program as the
        # person: no verification at all, and every gpg program is the trusted no-op
        "-c", "merge.verifySignatures=false",
        "-c", "core.useReplaceRefs=false",
        "-c", "diff.ignoreSubmodules=none",
        "-c", "status.submoduleSummary=false",
        "-c", f"gpg.program={true}",
        "-c", f"gpg.openpgp.program={true}",
        "-c", f"gpg.x509.program={true}",
        "-c", f"gpg.ssh.program={true}",
        "-c", "gpg.ssh.defaultKeyCommand=",
        "-c", "core.gitProxy=",
        "-c", "core.askPass=",
        "-c", "core.sshCommand=",
        "-c", "credential.helper=",
        "-c", "diff.external=",
        "-c", "log.showSignature=false",
        "-c", f"core.editor={true}",
        "-c", f"sequence.editor={true}",
    ]  # fmt: skip
    return ["--no-optional-locks", *out] if read_only else out


def _spawn(*a, **k):
    """The one process start of the streaming path."""
    return subprocess.Popen(*a, **k)


STDERR_KEEP = 64 * 1024


def _system_directory() -> str | None:
    """Windows' system folder (GetSystemDirectoryW); None elsewhere or on failure."""
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(260)
        n = ctypes.windll.kernel32.GetSystemDirectoryW(buf, 260)
        return buf.value if 0 < n < 260 else None
    except (AttributeError, OSError, ImportError):
        return None


def taskkill_exe() -> str | None:
    """taskkill.exe by its FULL path in the system folder, never by bare name (a bare name is looked up in the
    folder of python.exe (maybe a project .venv\\Scripts) and the current folder first). None = not found."""
    cands = []
    d = _system_directory()
    if d:
        cands.append(os.path.join(d, "taskkill.exe"))
    root = os.environ.get("SystemRoot")
    if root and os.path.isabs(root):
        cands.append(os.path.join(root, "System32", "taskkill.exe"))
    return next((c for c in cands if os.path.isfile(c)), None)


def _kill(p, lock) -> bool:
    """Kill git and everything it started. POSIX: SIGKILL to its process group (git has its own session; its
    children would keep the pipes open), only while git is not yet reaped: an unreaped git (even a zombie)
    keeps its group id reserved, so no reused id is ever hit. Windows: `taskkill /T /F` by full path. True =
    the whole tree was reached (always on POSIX); False = Windows without a findable taskkill (the caller
    fails closed)."""
    ok = True
    with lock:
        if p.returncode is not None:
            return True
        pid = getattr(p, "pid", None)
        try:
            if os.name != "nt":
                if isinstance(pid, int) and pid > 1:
                    os.killpg(pid, signal.SIGKILL)
            else:
                exe = taskkill_exe()
                if exe is None:
                    ok = False
                else:
                    subprocess.run(
                        [exe, "/T", "/F", "/PID", str(pid)], capture_output=True, timeout=5, check=False
                    )
        except (OSError, subprocess.SubprocessError):  # ESRCH: the group is already gone
            pass
        try:
            p.kill()
        except OSError:
            pass
    return ok


def _stream(argv, cwd, env_, timeout, data, max_bytes):
    """(rc, stdout, stderr) reading stdout WHILE git runs: past `max_bytes` the child is killed at once
    (rc TOO_LONG); on timeout it is killed and subprocess.TimeoutExpired is raised. stderr is drained on a
    thread and only its first STDERR_KEEP bytes are kept, so a chatty git cannot fill the pipe or memory.
    Order (portable, nothing platform-specific to wait with): wait for both readers to reach EOF, bounded
    by the timeout; then ALWAYS kill git's whole process group before git is reaped; then reap. If a reader
    is still running after that, the call FAILS (124) with no output: data is only returned once every
    reader is finished. Windows: no Job object; the tree goes with `taskkill /T /F` (full path); without a
    findable taskkill the call fails closed (124)."""
    p = _spawn(
        argv,
        cwd=cwd,
        env=env_,
        stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name != "nt",  # own process group: a kill also reaches git's children
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0,
    )
    lock = threading.Lock()
    out = bytearray()
    err = bytearray()
    over = threading.Event()

    def pump_out():
        while True:
            chunk = p.stdout.read1(65536)
            if not chunk:
                return
            out.extend(chunk)
            if max_bytes is not None and len(out) > max_bytes:
                over.set()
                _kill(p, lock)
                return

    def pump_err():
        while True:
            chunk = p.stderr.read1(65536)
            if not chunk:
                return
            if len(err) < STDERR_KEEP:
                err.extend(chunk[: STDERR_KEEP - len(err)])

    def feed():
        try:
            p.stdin.write(data)
            p.stdin.close()
        except OSError:
            pass

    readers = [threading.Thread(target=f, daemon=True) for f in (pump_out, pump_err)]
    threads = list(readers)
    if data is not None:
        threads.append(threading.Thread(target=feed, daemon=True))
    for t in threads:
        t.start()
    timed_out = False
    killed = True
    try:
        end = time.monotonic() + timeout
        for t in readers:
            t.join(max(0.0, end - time.monotonic()))
            if t.is_alive():
                timed_out = True
                break
    finally:
        killed = _kill(p, lock)  # always: also after a normal end, while git is still unreaped
        with lock:
            p.wait()
        for t in threads:
            t.join(5)
        stuck = any(t.is_alive() for t in threads)
        if not stuck:  # (close would block behind a reader still waiting)
            for f in (p.stdout, p.stderr):
                try:
                    f.close()
                except OSError:
                    pass
    if timed_out:
        raise subprocess.TimeoutExpired(argv, timeout)
    if stuck or not killed:
        return 124, b"", "git's output did not end: orch dropped it"
    if over.is_set():
        return TOO_LONG, b"", f"git printed more than {max_bytes} bytes"
    return p.returncode, bytes(out), bytes(err).decode("utf-8", "replace").strip()


def _raw_bytes(
    argv: list[str],
    cwd: Path,
    timeout: float,
    data: bytes | None = None,
    root: Path | None = None,
    config: list[tuple[str, str]] | None = None,
    max_bytes: int | None = None,
):
    """(rc, stdout bytes, stderr text). The ONE subprocess call. With `max_bytes` stdout is read while git
    runs and git is killed once it passes the cap (rc 123, nothing returned)."""
    true = trivial("true", cwd, root)
    if true is None:
        return (
            REFUSED,
            b"",
            "orch could not find a trusted `true` program, so it did not run git here." + _TRUE_HINT,
        )
    exe = git_exe(cwd, root)
    if exe is None:
        return 127, b"", "git is not installed (or only found inside the project, which orch does not run)"
    argv = [exe, *argv[1:]]
    environ = env(cwd, root, true, config)
    try:
        if max_bytes is not None:
            return _stream(argv, cwd, environ, timeout, data, max_bytes)
        p = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            input=data,
            stdin=None if data is not None else subprocess.DEVNULL,  # never waits for a terminal
            env=environ,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return 127, b"", "git is not installed"
    except subprocess.TimeoutExpired:
        return 124, b"", f"git {argv[-1] if argv else ''} took longer than {int(timeout)} s"
    except OSError as e:  # the program exists but could not be started: not "git is not installed"
        return CANNOT_START, b"", str(e)
    return p.returncode, p.stdout, p.stderr.decode("utf-8", "replace").strip()


def _raw(
    argv: list[str],
    cwd: Path,
    timeout: float,
    data: bytes | None = None,
    root: Path | None = None,
    config: list[tuple[str, str]] | None = None,
):
    rc, out, err = _raw_bytes(argv, cwd, timeout, data, root, config)
    return rc, out.decode("utf-8", "surrogateescape"), err


def version(cwd: Path, root: Path | None = None) -> tuple[int, int]:
    exe = git_exe(cwd, root) or ""
    if exe not in _versions:
        rc, out, _ = _raw(
            ["git", *base_args(_NOOP, True, _no_hooks(cwd, root)), "--version"], cwd, 10, None, root
        )
        m = re.search(r"(\d+)\.(\d+)", out)
        _versions[exe] = (int(m[1]), int(m[2])) if rc == 0 and m else (0, 0)
    return _versions[exe]


def empty_tree(cwd: Path, root: Path | None = None) -> str | None:
    """The empty tree of this repository's hash algorithm; None when that can't be found out."""
    key = str(cwd)
    if key not in _trees:
        rc, out, _ = _raw(
            ["git", *base_args(_NOOP, True, _no_hooks(cwd, root)), "rev-parse", "--show-object-format"],
            cwd,
            10,
            None,
            root,
        )
        if rc != 0 or out.strip() not in EMPTY_TREE:
            return None
        _trees[key] = EMPTY_TREE[out.strip()]
    return _trees[key]


# ALLOWLIST: orch builds every git argv itself, so only these subcommands run; the rest is refused (rc 125).
# worktree/stash/config are further limited below. (B12/B13 need merge, commit, add, rm, reset, worktree
# remove/prune and stash list; they are listed now so those tasks add no new surface.)
ALLOWED = {
    "worktree", "read-tree", "update-index", "checkout-index", "ls-files", "rev-parse", "config", "branch",
    "symbolic-ref", "cat-file", "merge-base", "show-ref", "for-each-ref", "status", "diff", "log", "show",
    "merge", "commit", "add", "rm", "reset", "stash", "check-ignore", "rev-list", "check-attr", "merge-tree",
}  # fmt: skip
# (check-ignore reads ignore rules only: no content, no filters; --stdin is refused below)
# (rev-list and check-attr only read: commit graph / attribute names. B13 uses them for ancestry counts and to
# refuse files that need filters. Neither runs a filter, textconv or external program.)
_CHECK_IGNORE_OK = {"-q", "--quiet", "-v", "--verbose", "-n", "--non-matching", "--no-index"}
_WORKTREE_OK = {"add", "remove", "prune", "list"}
# rev-list and check-attr only read: exact flag sets (no --output=<file>, no abbreviations, no bundles)
_REV_LIST_OK = {
    "--count", "--parents", "--first-parent", "--no-merges", "--merges", "--reverse", "-q", "--quiet", "-n",
}  # fmt: skip
_CHECK_ATTR_OK = {"-z", "--cached"}
_MERGE_TREE_OK = {
    "--write-tree",
    "--name-only",
    "-z",
    "--no-messages",
}  # computes a result tree, touches no work tree
_ATTR_SOURCE = re.compile(r"--source=[0-9a-fA-F]{7,64}")
_CONFIG_READ = {"--get", "--get-all", "--get-regexp", "--list", "-l"}
_NO_MODES = {"add", "commit", "reset", "stash"}  # (checkout/restore/clean/rebase are not allowed at all)
_BAD_GLOBALS = (
    "-c",
    "--config-env",
    "--exec-path",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--super-prefix",
    "--attr-source",
)  # safegit sets its own; a caller passes only the subcommand and its words
_BAD_WORDS = {"--ext-diff", "--textconv", "--show-signature", "--filters"}
_MODE_FLAGS = ("--patch", "--interactive", "--edit")  # and every abbreviation git would accept of them


def refusal(args: list[str]) -> str | None:
    """Why orch will not run this git call at all (None = fine). Only ALLOWED subcommands run (worktree: add,
    remove, prune, list; stash: list, show;
    config: reading only). Never an interactive mode: -p/-i/-e and
    every abbreviation of --patch/--interactive/--edit (git accepts `--patc`, `--inter`)."""
    k = subcommand_index(args)
    for g in args[:k]:
        if g in _BAD_GLOBALS or any(g.startswith(b + "=") for b in _BAD_GLOBALS if b.startswith("--")):
            return f"git option {g} before the command is not allowed: orch sets git's configuration itself"
    if k >= len(args):
        return None
    cmd, rest = args[k], args[k + 1 :]
    allflags = [a.split("=", 1)[0] for a in (rest[: rest.index("--")] if "--" in rest else rest)]
    if any(
        a.startswith("--") and len(a) >= 4 and any(w.startswith(a) for w in _BAD_WORDS) for a in allflags
    ):  # abbreviations too
        return "git: options that run external programs (--ext-diff, --textconv, --filters, ...) are refused"
    if cmd not in ALLOWED:
        return f"git {cmd} is not one of the git commands orch runs"
    flags = rest[: rest.index("--")] if "--" in rest else rest
    if cmd == "worktree" and not (rest and rest[0] in _WORKTREE_OK):
        return "git worktree: only add, remove, prune and list are run"
    if cmd == "stash" and not (rest and rest[0] in ("list", "show")):
        return "git stash: only list and show are run"
    if cmd == "check-ignore" and not (
        set(flags) <= _CHECK_IGNORE_OK
    ):  # exact names: no abbreviations, bundles
        return "git check-ignore: only -q, -v, -n, --no-index and paths from the argument list are run"
    if cmd == "rev-list":
        for a in flags:
            if a.startswith("-") and a not in _REV_LIST_OK and not re.fullmatch(r"--max-count=\d+", a):
                return (
                    "git rev-list: only --count, --parents, --first-parent, -n and similar read flags are run"
                )
    if cmd == "merge-tree":
        for a in flags:
            if a.startswith("-") and a not in _MERGE_TREE_OK:
                return "git merge-tree: only --write-tree, --name-only, -z and --no-messages are run"
    if cmd == "check-attr":
        for a in flags:
            if (
                a.startswith("-")
                and a not in _CHECK_ATTR_OK
                and not re.fullmatch(r"--source=[0-9a-fA-F]{7,64}", a)
            ):
                return "git check-attr: only -z, --cached and --source=<commit> are run"
    if cmd == "config" and not any(a in _CONFIG_READ for a in flags):
        return "git config: orch only reads the configuration"
    if cmd in _NO_MODES or cmd == "add":
        for a in flags:
            f = a.split("=", 1)[0]
            if f.startswith("--") and len(f) >= 3 and any(m.startswith(f) for m in _MODE_FLAGS):
                return f"git {cmd} in an interactive mode is not run by orch"
            if re.fullmatch(r"-[A-Za-z]*[pie][A-Za-z]*", a) and cmd != "commit":
                return f"git {cmd} in an interactive mode is not run by orch"
            if cmd == "commit" and re.fullmatch(r"-[A-Za-z]*[pi][A-Za-z]*", a):
                return "git commit in an interactive mode is not run by orch"
    return None


def subcommand_index(args: list[str]) -> int:
    """Index of the git subcommand in `args`, past leading global options (-C x, -c k=v, --literal-pathspecs,
    --opt=value ...); len(args) when there is none."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in _GLOBAL_WITH_VALUE else 1
    return i


def driver_args(
    cwd: Path, timeout: float = TIMEOUT, root: Path | None = None
) -> list[tuple[str, str]] | None:
    """(key, value) overrides for every filter driver (smudge/clean/process emptied, required off) and merge
    driver (an ABSOLUTE `false`, so a merge conflicts and never silently drops "theirs") the repository's
    configuration defines; None when that could not be found out (the caller refuses). They travel in the
    environment (GIT_CONFIG_*), not as `-c name=value`: the names are repository-chosen."""
    rc, out, _ = _raw(
        ["git", *base_args(_NOOP, True, _no_hooks(cwd, root)), "config", "--includes", "--null",
         "--get-regexp",
         r"^(filter\..*\.(smudge|clean|process)|merge\..*\.driver)$"],
        cwd, timeout, None, root,
    )  # fmt: skip
    if rc == 1:  # git config: no match = nothing defined
        return []
    if rc != 0:
        return None
    false = trivial("false", cwd, root)
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for rec in out.split("\0"):
        if not rec:
            continue
        key = rec.split("\n", 1)[0]
        m = _DRIVER.match(key)
        if not m:
            return None  # a name we cannot parse safely (a newline in it): refuse, never guess
        if key in seen:
            continue
        seen.add(key)
        if m[2]:
            pairs += [(f"filter.{m[2]}.{w}", "") for w in ("smudge", "clean", "process")]
            pairs.append((f"filter.{m[2]}.required", "false"))
        else:
            if false is None:
                return None
            pairs.append((f"merge.{m[4]}.driver", false))
    return pairs


def _prepare(args, cwd, timeout, filters, read_only, root, guard=None):
    """(argv, config) for git `args`, or (None, (rc, reason)) when orch refuses to run it."""
    why = refusal(args) or unusable_root(guard if guard is not None else root)
    if why:
        return None, (REFUSED, why)
    top: list[str] = []  # options before the subcommand
    extra: list[tuple[str, str]] = []
    if filters:
        found = driver_args(cwd, timeout, root)
        if found is None:
            return None, (
                REFUSED,
                "orch could not check this repository's filters, so it did not run git here",
            )
        extra = found
        if version(cwd, root) < (2, 31):  # older git ignores GIT_CONFIG_COUNT: the overrides would not apply
            return None, (
                REFUSED,
                "this git is older than 2.31: orch cannot switch off the repository's drivers",
            )
        if version(cwd, root) >= (2, 40):
            tree = empty_tree(cwd, root)
            if tree is None:
                return None, (
                    REFUSED,
                    "orch could not tell this repository's hash algorithm, so it did not run git",
                )
            top = [f"--attr-source={tree}"]  # the branch's .gitattributes is not read at all
    sub = list(args)
    k = subcommand_index(sub)
    if k + 1 < len(sub) and sub[k] == "stash" and sub[k + 1] == "show":
        k += 1  # the subcommand pair `stash show`
        sub[k + 1 : k + 1] = ["--no-ext-diff", "--no-textconv"]
    elif k < len(sub) and sub[k] in _DIFFLIKE:
        sub[k + 1 : k + 1] = ["--no-ext-diff", "--no-textconv"] if sub[k] != "grep" else ["--no-textconv"]
    true = trivial("true", cwd, root)
    if true is None:
        return None, (
            REFUSED,
            "orch could not find a trusted `true` program, so it did not run git here." + _TRUE_HINT,
        )
    return ["git", *top, *base_args(true, read_only, _no_hooks(cwd, root)), *sub], extra


def run(
    args: list[str],
    cwd: Path,
    timeout: float = TIMEOUT,
    *,
    data: bytes | None = None,
    read_only: bool = False,
    filters: bool = True,
    strip: bool = True,
    root: Path | None = None,
    identity: bool = False,
) -> tuple[int, str, str]:
    """(exit code, stdout, stderr) of git `args` in `cwd`, hardened as the module says. `identity`: commits
    are made as orch <orch@localhost> (user.name/user.email through git's environment configuration, which
    beats the repository's own; needs filters=True, where the git version is checked). rc 127: git missing,
    124: timeout, 125: refused for a safety reason (a subcommand orch does not run, an interactive mode, or
    the repository's drivers could not be listed). `root`: the workspace root (its folder is never searched
    for the git program)."""
    argv, extra = _prepare(args, cwd, timeout, filters, read_only, root)
    if argv is None:
        return extra[0], "", extra[1]
    if identity:
        if not filters:
            return REFUSED, "", "orch commits only with its drivers switched off (filters=True)"
        extra = [*(extra or []), ("user.name", "orch"), ("user.email", "orch@localhost")]
    kw = {"config": extra} if extra else {}
    rc, out, err = _raw(argv, cwd, timeout, data, root, **kw)
    return rc, out.strip() if strip else out, err


def run_bytes(
    args: list[str],
    cwd: Path,
    timeout: float = TIMEOUT,
    *,
    max_bytes: int = 16 * 1024 * 1024,
    read_only: bool = True,
    filters: bool = False,
    root: Path | None = None,
) -> tuple[int, bytes, str]:
    """Like run(), but stdout stays raw bytes (for `-z` listings) and is bounded: rc 123 (TOO_LONG, empty
    stdout) when git printed more than `max_bytes`. Same allowlist, hardening and environment. Defaults are
    for read-only listings (ls-files, rev-parse), which run no filter: pass filters=True for anything that
    reads file content."""
    # the folder git runs in counts as the root when none is given (home / a drive root: refused, rc 125)
    argv, extra = _prepare(args, cwd, timeout, filters, read_only, root, root if root is not None else cwd)
    if argv is None:
        return extra[0], b"", extra[1]
    return _raw_bytes(argv, cwd, timeout, None, root, extra or None, max_bytes)
