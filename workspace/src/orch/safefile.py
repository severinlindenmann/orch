"""The ONE reader for a file inside a ticket's folder (.orch/tickets/<id>/<folder>/<name>).

Used wherever a file a person or an agent could have tampered with is read and shown or sent (the phone view
of proof files, the dashboard's Artifacts tab). The rules are enforced here and nowhere else:

- the path has exactly that shape: a ticket id, a folder in FOLDERS, a name of plain parts (no `..`, no drive,
  no `:`, no backslash, no NUL);
- the folders are opened one by one from the workspace with dir_fd, each with O_NOFOLLOW|O_DIRECTORY, so a
  folder swapped for a link while we look is refused, never followed (Windows: every part is checked for
  links, the real path is contained, the file is re-checked after open);
- the file is opened O_NOFOLLOW|O_NONBLOCK (a FIFO never hangs the reader), must be a regular file with
  exactly one name (a hard link to .orch/secrets/... is refused), and is read from that handle up to
  `max_bytes`.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path, PureWindowsPath

FOLDERS = ("artifacts", "evidence")
_ID_RE = re.compile(r"^t_[a-z0-9]{6,16}$")
_DIR_FD = True  # tests turn it off to run the Windows path on POSIX


class TooLarge(Exception):
    """The file is bigger than the cap."""


def _parts(name) -> list[str] | None:
    if not isinstance(name, str) or not name or len(name) > 240:
        return None
    if ":" in name or "\\" in name or "\0" in name or name.startswith("/"):
        return None
    parts = name.split("/")
    for p in parts:
        if p in ("", ".", "..") or PureWindowsPath(p).drive or PureWindowsPath(p).anchor:
            return None
    return parts


def read_ticket_file(root: Path, tid: str, folder: str, name, max_bytes: int) -> bytes | None:
    """The bytes of .orch/tickets/<tid>/<folder>/<name>, or None when the rules above refuse it.
    Raises TooLarge when it is a fine file over `max_bytes`."""
    parts = _parts(name)
    if parts is None or folder not in FOLDERS or not isinstance(tid, str) or not _ID_RE.fullmatch(tid):
        return None
    head = [".orch", "tickets", tid, folder]
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    dir_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_DIRECTORY", 0)
    fds: list[int] = []
    try:
        if _DIR_FD and os.open in os.supports_dir_fd and hasattr(os, "O_DIRECTORY"):
            fds.append(os.open(os.path.realpath(root), os.O_RDONLY | os.O_DIRECTORY))
            for part in [*head, *parts[:-1]]:
                fds.append(os.open(part, dir_flags, dir_fd=fds[-1]))
            fd = os.open(parts[-1], flags, dir_fd=fds[-1])
        else:  # Windows: no dir_fd. Check every part for links, contain the real path, re-check after open
            base = Path(os.path.realpath(root))
            cur = base
            for part in [*head, *parts]:
                cur = cur / part
                if cur.is_symlink():
                    return None
            real = Path(os.path.realpath(cur))
            allowed = base.joinpath(*head)
            if allowed not in real.parents or (base / ".orch" / "secrets") in (real, *real.parents):
                return None
            before = os.lstat(real)
            if not stat.S_ISREG(before.st_mode):
                return None
            fd = os.open(real, flags)
            try:
                st = os.fstat(fd)
            except OSError:
                os.close(fd)
                raise
            if (st.st_dev, st.st_ino) != (before.st_dev, before.st_ino):
                os.close(fd)
                return None
    except OSError:
        return None
    finally:
        for d in fds:
            os.close(d)
    try:
        st = os.fstat(fd)
    except OSError:
        os.close(fd)
        return None
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:  # a folder, a FIFO, a device, a hard link: refused
        os.close(fd)
        return None
    with os.fdopen(fd, "rb") as f:
        if st.st_size > max_bytes:
            raise TooLarge
        data = f.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise TooLarge
    return data
