"""Snapshots of folder add-ons (human-proof.md, `addon.add_local`): what a person allows is the folder's
CONTENT at the moment of the request, not its path. The folder is copied into a private folder of the guarded
orch home (<guarded home>/keys/<ws>/addon-snapshots/<tree hash>/), the proof binds to the tree hash, and the
install and every later reinstall use the snapshot, after checking its hash again."""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import stat
from pathlib import Path

from orch import humanproof, saferead
from orch.errors import Refused

SKIP_TOP = {".git", ".venv", "node_modules", ".pytest_cache", ".ruff_cache", "build", "dist"}
MAX_FILES = 2000
MAX_FILE = 5 * 1024 * 1024
MAX_TOTAL = 25 * 1024 * 1024


def _skip(rel: tuple[str, ...]) -> bool:
    return rel[0] in SKIP_TOP or rel[0].endswith(".egg-info") or "__pycache__" in rel


def read_tree(folder: Path) -> dict[str, bytes]:
    """{relative path: bytes} of the regular files below `folder` (build output and caches left out). A link,
    a FIFO, a device or a hard-linked file, a file over the size cap or too many files: Refused."""
    base = Path(os.path.realpath(folder))
    files: dict[str, bytes] = {}
    total = 0

    def walk(d: Path, rel: tuple[str, ...]) -> None:
        nonlocal total
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name)
        except OSError:
            raise Refused(f"{folder} cannot be read.") from None
        for e in entries:
            r = (*rel, e.name)
            if _skip(r):
                continue
            mode = e.stat(follow_symlinks=False).st_mode
            if stat.S_ISDIR(mode):
                walk(Path(e.path), r)
            elif stat.S_ISREG(mode):
                if len(files) >= MAX_FILES:
                    raise Refused("This add-on folder has too many files to check.")
                data = saferead.read_private(base, "/".join(r), MAX_FILE)
                if data is None:
                    raise Refused(f"{'/'.join(r)} in this add-on folder cannot be read safely.")
                total += len(data)
                if total > MAX_TOTAL:
                    raise Refused("This add-on folder is too big to check.")
                files["/".join(r)] = data
            else:
                raise Refused(f"{'/'.join(r)} in this add-on folder is a link or a special file.")

    walk(base, ())
    return files


def tree_hash(files: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for rel in sorted(files):
        name = rel.encode()
        h.update(len(name).to_bytes(4, "big") + name + len(files[rel]).to_bytes(8, "big") + files[rel])
    return h.hexdigest()


def snapshots_dir(root: Path) -> Path:
    return humanproof.key_dir(root) / "addon-snapshots"


def snapshot(root: Path, folder: Path) -> dict:
    """Copy the folder into the guarded home: {hash, short, path, snapshot}. Same content = same folder."""
    files = read_tree(folder)
    digest = tree_hash(files)
    top = snapshots_dir(root)
    top.mkdir(mode=0o700, exist_ok=True)
    dest = top / digest
    if dest.exists() and verify(dest, digest):
        return _info(folder, digest, dest)
    if dest.exists() or dest.is_symlink():
        shutil.rmtree(dest) if dest.is_dir() and not dest.is_symlink() else dest.unlink()
    tmp = top / f".{digest[:12]}.{secrets.token_hex(4)}"
    tmp.mkdir(mode=0o700)
    try:
        for rel, data in files.items():
            p = tmp / rel
            p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        os.replace(tmp, dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return _info(folder, digest, dest)


def _info(folder: Path, digest: str, dest: Path) -> dict:
    return {
        "hash": digest,
        "short": digest[:8],
        "path": str(Path(folder).expanduser().resolve()),
        "snapshot": str(dest),
    }


def verify(snapshot_dir: Path, digest: str) -> bool:
    """Is this a snapshot folder named `digest`, with exactly that content? (a tampered one: False)"""
    try:
        if Path(snapshot_dir).name != digest or Path(snapshot_dir).parent.name != "addon-snapshots":
            return False
        return tree_hash(read_tree(snapshot_dir)) == digest
    except (Refused, OSError):
        return False
