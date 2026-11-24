"""Which files the Files add-on lists, and which of them it may read.

Listed: every plain file under the workspace folder (your folders) and the files helpers made for tickets
(`.orch/tickets/<id>/artifacts|evidence/`). Never followed: links (to files or folders). Left out: orch's own
machinery (the rest of `.orch/`), program folders and leftovers (NOISE), and the person's own leave-out folders.
Until the person turns on the switch in What is included, also left out: system files (a name that starts with a
dot, as Finder and ls hide them, and the agent instruction files of AGENT_FILES, which hold orch's own markup) and
everything a `.gitignore` on the way names. A folder that is its own git repository (it holds a `.git`) is always
listed, as git does: an outer `.gitignore` does not reach into it (a workspace of several repositories ignores them
in its own `.gitignore`), only its own ignore files do. Private files (secret-looking names such as .env, *.pem or
id_rsa, key folders such as .ssh, and files whose text the orch secret check flags) are listed by name only:
their content is never indexed, shown or served.
"""

from __future__ import annotations

import fnmatch
import os
import re
import stat
from collections.abc import Iterator
from dataclasses import dataclass

NOISE = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".tox",
        ".next",
        ".nuxt",
        ".cache",
        ".parcel-cache",
        ".gradle",
        ".idea",
        ".vscode",
        "dist",
        "build",
        "target",
        "DerivedData",
        "Pods",
        ".DS_Store",
        "Thumbs.db",
        ".orch-test",
    }
)
# Names whose content is never read (the name may show). The core's list for safe reads plus a few more.
SECRETISH = (
    "*secret*",
    "*token*",
    "*password*",
    "*passwd*",
    "*credential*",
    "*.pem",
    "*.p8",
    "*.p12",
    "*.pfx",
    "*.key",
    "*.kdbx",
    "*.gpg",
    "*.asc",
    ".netrc",
    ".pgpass",
    ".npmrc",
    ".pypirc",
    ".env",
    ".env.*",
    "*.env",
    "id_rsa*",
    "id_ed25519*",
    "id_ecdsa*",
    "id_dsa*",
    "*_rsa",
    "*apikey*",
    "*api_key*",
    "*api-key*",
)


def _agent_files() -> frozenset[str]:
    """Instruction files agent tools read (lower case): system files, not the person's work (ORCH-1691). The
    tool-specific names come from orch's adapter list, so this add-on names no tool itself (R1.5)."""
    names = {"agents.md", "agents.override.md", "gemini.md"}
    try:
        from orch import adapters
    except Exception:  # noqa: BLE001  no core here: the tool-neutral names only
        return frozenset(names)
    tool = (*getattr(adapters, "AGENT_CONTROL_NAMES", ()), *getattr(adapters, "GUIDE_FILES", ()))
    return frozenset(names | {n.lower() for n in tool if not n.startswith(".")})


AGENT_FILES = _agent_files()
PRIVATE_DIRS = frozenset({".ssh", ".aws", ".gnupg", ".kube", ".docker", ".azure", ".password-store"})
TICKET_DIRS = ("artifacts", "evidence")
TICKET_ID = re.compile(r"t_[a-z0-9]{6,16}")
MAX_FILES = 500_000  # a safety stop for a folder that is far bigger than a workspace


@dataclass(frozen=True)
class Entry:
    path: str  # posix, relative to the workspace
    size: int
    mtime: int  # nanoseconds
    ticket: str | None  # t_... for a ticket file
    private: bool


_SECRET_RX = re.compile("|".join(f"(?:{fnmatch.translate(g)})" for g in SECRETISH), re.DOTALL)


def _reparse(st: os.stat_result) -> bool:
    """A Windows junction or other reparse point (never followed: it can lead outside the workspace)."""
    return bool(getattr(st, "st_file_attributes", 0) & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT


def _junction(e: os.DirEntry) -> bool:
    try:
        return bool(getattr(e, "is_junction", lambda: False)()) or _reparse(e.stat(follow_symlinks=False))
    except OSError:
        return True


def private_part(part: str) -> bool:
    low = part.lower()
    return low in PRIVATE_DIRS or _SECRET_RX.match(low) is not None


def private_name(parts: tuple[str, ...]) -> bool:
    """True when any part of the path looks secret: its content is never read."""
    return any(private_part(p) for p in parts)


class Ignore:
    """A small .gitignore reader: `name`, `*.ext`, `dir/`, `/anchored`, `a/**/b`, `!keep` (last match wins).
    Patterns hold for the folder of the .gitignore file and below."""

    def __init__(self, base: str, lines: list[str]):
        self.base = base  # posix folder of the .gitignore ("" = workspace)
        self.rules: list[tuple[bool, bool, bool, re.Pattern]] = []
        for raw in lines:
            line = raw.rstrip("\n").rstrip()
            if not line or line.startswith("#"):
                continue
            neg = line.startswith("!")
            if neg:
                line = line[1:]
            line = line.removeprefix("\\")
            dir_only = line.endswith("/")
            line = line.strip("/") if dir_only else line
            anchored = line.startswith("/") or "/" in line.rstrip("/")
            line = line.lstrip("/")
            if not line:
                continue
            self.rules.append((neg, dir_only, anchored, re.compile(_glob_re(line))))

    def match(self, rel: str, is_dir: bool) -> bool | None:
        """True ignored, False kept by a `!` rule, None no rule says anything."""
        if self.base:
            if not rel.startswith(self.base + "/"):
                return None
            rel = rel[len(self.base) + 1 :]
        name = rel.rsplit("/", 1)[-1]
        hit = None
        for neg, dir_only, anchored, rx in self.rules:
            if dir_only and not is_dir:
                continue
            if rx.fullmatch(rel if anchored else name):
                hit = not neg
        return hit


def _glob_re(pat: str) -> str:
    out, i = [], 0
    while i < len(pat):
        c = pat[i]
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pat.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = pat.find("]", i + 1)
            if j < 0:
                out.append(re.escape(c))
            else:
                body = pat[i + 1 : j].replace("\\", "\\\\")
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body + "]")
                i = j
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


def _read_ignore(dirpath: str, base: str) -> Ignore | None:
    try:
        fd = os.open(os.path.join(dirpath, ".gitignore"), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > 256 * 1024:
            return None
        data = os.read(fd, 256 * 1024)
    except OSError:
        return None
    finally:
        os.close(fd)
    ig = Ignore(base, data.decode("utf-8", "replace").splitlines())
    return ig if ig.rules else None


def _own_repo(path: str) -> bool:
    """True when the folder is its own git repository: a `.git` folder, or a `.git` file (a worktree or a
    submodule). Never followed when it is a link."""
    try:
        st = os.lstat(os.path.join(path, ".git"))
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)


def system_name(name: str) -> bool:
    """A system file or folder: hidden until the person shows them (a dot name, an agent instruction file)."""
    return name.startswith(".") or name.lower() in AGENT_FILES


def _ignored(stack: list[Ignore], rel: str, is_dir: bool) -> bool:
    hit = None
    for ig in stack:
        m = ig.match(rel, is_dir)
        if m is not None:
            hit = m
    return bool(hit)


def walk(root: str, leave_out: tuple[str, ...] = (), show_ignored: bool = False) -> Iterator[Entry]:
    """Every listed file: your folders first, then the ticket files. Never follows a link. `show_ignored` lists
    system files and what a `.gitignore` names too (program folders and leftovers stay out)."""
    root = os.path.abspath(root)
    count = 0
    left = tuple(p.strip("/") for p in leave_out if p.strip("/"))
    # (absolute dir, posix rel, ignore stack)
    todo: list[tuple[str, str, list[Ignore], bool]] = [(root, "", [], False)]
    while todo:
        d, rel, stack, dir_private = todo.pop()
        ig = None if show_ignored else _read_ignore(d, rel)
        if ig is not None:
            stack = [*stack, ig]
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            subs = []
            for e in it:
                name = e.name
                if name in NOISE or (not show_ignored and system_name(name)):
                    continue
                r = f"{rel}/{name}" if rel else name
                try:
                    if e.is_symlink() or _junction(e):
                        continue
                    if e.is_dir(follow_symlinks=False):
                        if not rel and name == ".orch":
                            continue
                        if r in left:
                            continue
                        if _own_repo(e.path):
                            subs.append((e.path, r, []))  # outer ignore rules stop at a repository
                            continue
                        if _ignored(stack, r, True):
                            continue
                        subs.append((e.path, r, stack))
                        continue
                    if not e.is_file(follow_symlinks=False):
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if _ignored(stack, r, False):
                    continue
                count += 1
                if count > MAX_FILES:
                    return
                yield Entry(r, st.st_size, st.st_mtime_ns, None, dir_private or private_part(name))
            for sp, sr, sst in sorted(subs, key=lambda x: x[1], reverse=True):
                todo.append((sp, sr, sst, dir_private or private_part(sr.rsplit("/", 1)[-1])))
    yield from _ticket_files(root)


def _ticket_files(root: str) -> Iterator[Entry]:
    base = os.path.join(root, ".orch", "tickets")
    try:
        tickets = [
            e for e in os.scandir(base) if TICKET_ID.fullmatch(e.name) and e.is_dir(follow_symlinks=False)
        ]
    except OSError:
        return
    for t in sorted(tickets, key=lambda e: e.name):
        for sub in TICKET_DIRS:
            top = os.path.join(t.path, sub)
            todo = [(top, f".orch/tickets/{t.name}/{sub}")]
            while todo:
                d, rel = todo.pop()
                try:
                    it = os.scandir(d)
                except OSError:
                    continue
                with it:
                    for e in it:
                        try:
                            if e.is_symlink() or e.name in NOISE or _junction(e):
                                continue
                            r = f"{rel}/{e.name}"
                            if e.is_dir(follow_symlinks=False):
                                todo.append((e.path, r))
                                continue
                            if not e.is_file(follow_symlinks=False):
                                continue
                            st = e.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        parts = tuple(r.split("/")[4:])
                        yield Entry(r, st.st_size, st.st_mtime_ns, t.name, private_name(parts))


def read_head(root: str, rel: str, limit: int) -> bytes | None:
    """At most `limit` bytes from the start of a plain file inside root; None for a link, a special file or a
    missing one. Every path part is checked not to be a link (a folder swapped for a link is refused)."""
    parts = rel.split("/")
    if not parts or any(p in ("", ".", "..") for p in parts) or "\\" in rel or "\x00" in rel:
        return None
    cur = os.path.abspath(root)
    for p in parts[:-1]:
        cur = os.path.join(cur, p)
        try:
            st = os.lstat(cur)
            if not stat.S_ISDIR(st.st_mode) or _reparse(st):
                return None
        except OSError:
            return None
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOCTTY", 0)
        | getattr(os, "O_BINARY", 0)
    )
    full = os.path.join(cur, parts[-1])
    try:
        st = os.lstat(full)
        if stat.S_ISLNK(st.st_mode) or _reparse(st):
            return None
        fd = os.open(full, flags)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None
        out = bytearray()
        while len(out) < limit:
            chunk = os.read(fd, min(1024 * 1024, limit - len(out)))
            if not chunk:
                break
            out += chunk
        return bytes(out)
    except OSError:
        return None
    finally:
        os.close(fd)
