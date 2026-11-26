"""Where the browser add-on keeps its files (all under .orch/addons/browse/, kept out of git).

sites/<ticket>.json   the ticket's site list (changed only by a person)
run/<ticket>/         the broker's 0700 folder: channel, state, network log, path of the temp profile
shots/<ticket>/       pictures taken with orch browse shot
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from . import netcheck

SOCK_MAX = 100  # macOS allows 104 bytes for a socket path (bytes, not characters: an umlaut takes two)


def base(root: Path) -> Path:
    return root / ".orch" / "addons" / "browse"


def _private(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, 0o700)
    except OSError:
        pass
    return p


def run_dir(root: Path, tid: str) -> Path:
    return _private(base(root) / "run" / tid)


def shots_dir(root: Path, tid: str) -> Path:
    return _private(base(root) / "shots" / tid)


def socket_path(run: Path) -> Path:
    p = run / "b.sock"
    if len(os.fsencode(p)) <= SOCK_MAX:
        return p
    short = Path(tempfile.gettempdir()) / f"orch-browse-{os.getuid() if hasattr(os, 'getuid') else 0}"
    _private(short)
    return short / (hashlib.sha256(str(run).encode()).hexdigest()[:16] + ".sock")


def sites_file(root: Path, tid: str) -> Path:
    return base(root) / "sites" / f"{tid}.json"


def load_sites(root: Path, tid: str) -> list[str]:
    """The ticket's site list. Missing = empty; damaged = an error (the filter then allows nothing)."""
    f = sites_file(root, tid)
    if not f.exists():
        return []
    doc = json.loads(f.read_text(encoding="utf-8"))
    sites = doc.get("sites", []) if isinstance(doc, dict) else None
    if not isinstance(sites, list) or not all(isinstance(s, str) for s in sites):
        raise ValueError('the file must hold {"sites": ["example.com", ...]}')
    return [netcheck.norm_site(s) for s in sites]


def save_sites(root: Path, tid: str, sites: list[str]) -> None:
    f = sites_file(root, tid)
    _private(f.parent)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"sites": sorted(set(sites))}, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, f)


def write_state(run: Path, doc: dict) -> None:
    tmp = run / "state.tmp"
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    os.replace(tmp, run / "state.json")


def read_state(run: Path) -> dict:
    try:
        return json.loads((run / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def clean_leftovers(run: Path) -> None:
    """A broker that was killed left its temp profile behind: delete it at the next start."""
    f = run / "profile.path"
    try:
        old = Path(f.read_text(encoding="utf-8").strip())
    except OSError:
        return
    if old.name.startswith("orch-browse-") and old.parent == Path(tempfile.gettempdir()):
        shutil.rmtree(old, ignore_errors=True)
    f.unlink(missing_ok=True)


def forget_run(run: Path) -> None:
    for name in ("profile.path", "channel.json"):
        (run / name).unlink(missing_ok=True)
    s = socket_path(run)
    try:
        s.unlink()
    except OSError:
        pass
