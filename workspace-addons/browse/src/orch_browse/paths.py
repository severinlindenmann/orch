"""Where the browser add-on keeps its files (all under .orch/addons/browse/, kept out of git).

sites/<ticket>.json   the ticket's own site list (changed only by a person)
sites/_workspace.json the workspace's permanent site list: it holds for every ticket (O-21, owner 28 Nov)
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


WORKSPACE_LIST = "_workspace"  # never a ticket id (those start with t_)
# The run that holds the browser a person opened on the dashboard's Browser page (O-20). Not a ticket id (those have
# 6 to 16 characters after t_), and no `orch browse` command takes it: only the dashboard, for a signed-in person.
OWN_RUN = "t_self"
MAX_SITES = 5000  # one list; far above what a person keeps, and the filter reads it on every connection


def workspace_sites_file(root: Path) -> Path:
    return base(root) / "sites" / f"{WORKSPACE_LIST}.json"


_READ: dict[
    str, tuple[tuple[int, int], list[str]]
] = {}  # file -> ((mtime_ns, size), its sites): see _read_sites


def _read_sites(f: Path) -> list[str]:
    """One stored list. Missing = empty; damaged = an error (the filter then allows nothing). The network filter
    asks on every connection, so a file that did not change is not read and checked again (1,000 sites took
    4 ms each time); a damaged file is never kept."""
    try:
        st = f.stat()
    except OSError:
        return []
    # a saved list is a new file (os.replace), so its file number changes even where times are coarse
    mark, hit = (st.st_mtime_ns, st.st_size, st.st_ino), _READ.get(str(f))
    if hit and hit[0] == mark:
        return list(hit[1])
    doc = json.loads(f.read_text(encoding="utf-8"))
    sites = doc.get("sites", []) if isinstance(doc, dict) else None
    if not isinstance(sites, list) or not all(isinstance(s, str) for s in sites):
        raise ValueError('the file must hold {"sites": ["example.com", ...]}')
    out = [netcheck.norm_site(s) for s in sites]
    if len(_READ) > 256:
        _READ.clear()
    _READ[str(f)] = (mark, out)
    return list(out)


def _write_sites(f: Path, sites: list[str]) -> None:
    if len(set(sites)) > MAX_SITES:
        raise ValueError(f"a site list holds at most {MAX_SITES} sites")
    _private(f.parent)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"sites": sorted(set(sites))}, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, f)


def load_ticket_sites(root: Path, tid: str) -> list[str]:
    """The ticket's own extra sites (without the workspace's list)."""
    return _read_sites(sites_file(root, tid))


def load_workspace_sites(root: Path) -> list[str]:
    """The workspace's permanent list: these sites may open for every ticket."""
    return _read_sites(workspace_sites_file(root))


def load_sites(root: Path, tid: str) -> list[str]:
    """The sites this ticket's browser may open: the workspace's permanent list and the ticket's own, each
    once. This is what the network filter asks on every connection. A damaged list is an error (the filter
    then allows nothing)."""
    return sorted(set(load_workspace_sites(root)) | set(load_ticket_sites(root, tid)))


def sites_by_source(root: Path, tid: str | None = None) -> list[dict]:
    """The allowed sites with where each comes from: [{"site", "source": "workspace" | "ticket"}], by name.
    A site on both lists is the workspace's (it holds for every ticket anyway)."""
    ws = set(load_workspace_sites(root))
    own = set(load_ticket_sites(root, tid)) - ws if tid else set()
    return [{"site": s, "source": "workspace" if s in ws else "ticket"} for s in sorted(ws | own)]


def save_sites(root: Path, tid: str, sites: list[str]) -> None:
    """Write the ticket's own list."""
    _write_sites(sites_file(root, tid), sites)


def save_workspace_sites(root: Path, sites: list[str]) -> None:
    _write_sites(workspace_sites_file(root), sites)


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
