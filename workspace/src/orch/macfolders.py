"""macOS folders a background job may not use (privacy protection, TCC).

A launchd job (orch services) gets no permission for Documents, Desktop, Downloads, iCloud Drive or cloud
storage folders: it dies at once with "getcwd: Operation not permitted". orch services refuses such a folder
up front and orch doctor names it (report r-1119-1255-ws-6).

An external disk (/Volumes/<disk>) is blocked the same way: launchd cannot open a log there (the job ends
with 78 before it starts) and a program started in such a folder hangs in getcwd. A workspace on an external
disk is the person's choice and must keep working, so it is not refused: orch services runs its jobs from a
folder in the home folder and orch doctor says so (report r-1120-0610-services)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# relative to the home folder; the words are what a person sees in Finder
PROTECTED = (
    ("Documents", "Documents"),
    ("Desktop", "Desktop"),
    ("Downloads", "Downloads"),
    ("Library/Mobile Documents", "iCloud Drive"),
    ("Library/CloudStorage", "a cloud storage folder"),
)


def _platform() -> str:
    return sys.platform  # a function, so tests on Linux can pretend to be a Mac


def _resolved(p: Path) -> Path:
    try:
        return Path(p).expanduser().resolve()
    except (OSError, RuntimeError):
        return Path(p).expanduser().absolute()


VOLUMES = Path("/Volumes")


def _device(p: Path) -> int | None:
    try:
        return os.stat(p).st_dev
    except OSError:
        return None


def external_disk(path: Path, home: Path | None = None, platform: str | None = None) -> bool:
    """True when `path` lies on an external disk (/Volumes/<disk>) on macOS. The disk this Mac starts from is
    not external: /Volumes/Macintosh HD is a link to /, and a path on the home folder's own disk does not
    count."""
    if (platform or _platform()) != "darwin":
        return False
    p = _resolved(path)
    vol = _resolved(VOLUMES)
    if vol not in p.parents:
        return False
    own = _device(home or Path.home())
    there = _device(p)
    return there is None or own is None or there != own  # an unmounted disk cannot be read: still external


def protected(path: Path, home: Path | None = None, platform: str | None = None) -> str | None:
    """The Finder name of the protected folder `path` lies in (e.g. "Documents"), or None.
    Only on macOS. Links are followed: a link into Documents counts, a link out of it does not."""
    if (platform or _platform()) != "darwin":
        return None
    h = home or Path.home()
    p = _resolved(path)
    for rel, word in PROTECTED:
        for base in {h / rel, _resolved(h / rel)}:
            if p == base or base in p.parents:
                return word
    return None


def first_protected(paths, home: Path | None = None, platform: str | None = None) -> tuple[Path, str] | None:
    """The first of `paths` that lies in a protected folder, with that folder's name."""
    for p in paths:
        if p is None:
            continue
        word = protected(Path(p), home, platform)
        if word:
            return Path(p), word
    return None


def shown(path: Path, home: Path | None = None) -> str:
    """The path as a person writes it: ~/Documents/x instead of /Users/me/Documents/x."""
    h = home or Path.home()
    try:
        return "~/" + Path(path).relative_to(h).as_posix()
    except ValueError:
        return str(path)


def doctor_row(root: Path, services_on: bool) -> dict | None:
    """orch doctor: a problem row when services is on and the workspace is in a protected folder; a plain note
    (not a problem) when it is on an external disk, where services still run, from the home folder."""
    if not services_on:
        return None
    word = protected(root)
    if not word:
        if external_disk(root):
            return {
                "name": "services folder",
                "ok": True,
                "fact": "This workspace is on an external disk, so its background services run from your "
                "home folder; macOS may keep them off this computer's local network (use the private "
                "network address).",
                "next": "",
            }
        return None
    return {
        "name": "services folder",
        "ok": False,
        "fact": f"This workspace is in {word}; macOS does not let background services run there.",
        "next": "Move the workspace to a folder such as ~/code "
        "(not Documents, Desktop, Downloads or iCloud Drive).",
    }
