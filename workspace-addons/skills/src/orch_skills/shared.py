"""Skills your admin shares over the relay: remove one from this workspace, get it back, and see when the admin
has a newer version (ORCH-842).

Remove puts the name on the core's list `.orch/skills-removed.json` (orch.skills-removed/1, read by
`orch relay refresh`, which then does not bring it back) with the admin's version at that moment, and deletes the
workspace's copy (the admin keeps the original). Get it back takes the name off the list; the skill returns with
the next relay update, which orch starts at once when the relay is reachable.
"""

from __future__ import annotations

import contextlib
import json
import shutil
from pathlib import Path

from . import switches
from .switches import Refused

SCHEMA = "orch.skills-removed/1"
SHARED = Path(".orch") / "secrets" / "shared.json"
INBOX = Path(".orch") / "inbox"
MARK = ".orch-shared"


def _shared_doc(root: Path) -> dict:
    try:
        p = Path(root) / SHARED
        if switches._is_link(p) or not p.is_file() or p.stat().st_size > switches.MAX_BYTES:
            return {}
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def offered(root: Path) -> dict[str, int]:
    """{name: version} the admin offers this workspace (from the last relay update)."""
    got = _shared_doc(root).get("offered")
    if not isinstance(got, dict):
        return {}
    return {k: v for k, v in got.items() if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool)}


def newer_waiting(root: Path) -> bool:
    """The admin sent a "new settings are waiting" notice newer than the last relay update here."""
    have = _shared_doc(root).get("version")
    have = have if isinstance(have, int) else -1
    try:
        files = sorted((Path(root) / INBOX).glob("m_*.json"))[-500:]
    except OSError:
        return False
    for f in files:
        with contextlib.suppress(OSError, ValueError):
            if f.stat().st_size > 64 * 1024:
                continue
            m = json.loads(f.read_text(encoding="utf-8"))
            v = (m.get("body") or {}).get("version") if isinstance(m, dict) else None
            if m.get("type") == "refresh-hint" and isinstance(v, int) and v > have:
                return True
    return False


def removed(root: Path) -> dict[str, int]:
    from orch import skills

    return skills.removed_shared(root)


def _save(root: Path, names: dict[str, int]) -> None:
    from orch import skills

    switches._write(root, skills.REMOVED_FILE, {"schema": SCHEMA, "skills": dict(sorted(names.items()))})


def remove(root: Path, name: str) -> bool:
    """Take a shared skill out of this workspace for good (until Get it back). True when it changed."""
    from orch import skills

    folder = switches.safe_path(root, Path(".agents") / "skills" / name)
    with switches._locked(root):
        names = removed(root)
        if name in names:
            return False
        if not (folder / MARK).is_file():
            raise Refused(f"{name} is not a skill your admin shares here. Nothing was changed.")
        names[name] = offered(root).get(name, 0)
        _save(root, names)  # the list first: a refresh that runs now already skips it
        shutil.rmtree(folder)
    with contextlib.suppress(Refused, OSError):
        skills.unlink_skill(root, name)
    skills.apply_agent_files(root)
    return True


def restore(root: Path, name: str) -> str:
    """Take the name off the list and start a relay update. Returns one plain line of what happened."""
    with switches._locked(root):
        names = removed(root)
        if name not in names:
            return f"{name} was not removed here. Nothing changed."
        del names[name]
        _save(root, names)
    try:
        from orch import relay

        relay.refresh(root)
    except Exception:  # noqa: BLE001  no relay here or not reachable: the next update brings it
        return f"{name} comes back with the next update from your admin."
    if (Path(root) / ".agents" / "skills" / name / MARK).is_file():
        return f"{name} is back in this workspace."
    return f"{name} is no longer shared with this workspace, so it did not come back."
