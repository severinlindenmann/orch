"""`orch workspace move-here`: after a person moved a workspace folder, its saved keys and the per-folder
records in the orch home still name the old path (ORCH-853). This re-binds the key folder (home.move_here: a
copy is refused) and moves the old path's entries: permissions.json and copies.json (keyed by a hash of the
real path), ports.json ("<path>\\t<add-on>"), consent.json and running.json (a "workspace" field).

Only a person, at a terminal, outside any helper run: a helper that could re-bind a key folder could point a
forged workspace id at another workspace's keys (N17).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from orch.errors import Refused

NOT_A_PERSON = (
    "Only you can do this, a helper can't. Run orch workspace move-here yourself in a terminal in the moved "
    "folder."
)


def _hash_key(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:32]  # = config._perm_key of that real path


MOVED, NONE, FAILED = "moved", "none", "failed"


def _rewrite(f: Path, change) -> str:
    """Apply `change(doc) -> bool` to the JSON in `f` and replace it atomically, keeping the file's rights.
    MOVED; NONE (no file, or nothing of the old path in it); FAILED (a link, a malformed or unreadable file, a
    write error, or a file that kept changing): then it is untouched and the move stops before the keys."""
    if not os.path.lexists(f):
        return NONE
    if f.is_symlink() or not f.is_file():
        return FAILED
    for _ in range(3):
        try:
            raw = f.read_bytes()
            doc = json.loads(raw)
        except (OSError, ValueError):
            return FAILED
        if not change(doc):
            return NONE
        tmp = f.with_name(f".{f.name}.orch-move-{os.getpid()}.tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, f.stat().st_mode & 0o777)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
                json.dump(doc, out, indent=2, ensure_ascii=False)
                out.write("\n")
            if f.read_bytes() != raw:
                continue
            os.replace(tmp, f)
            return MOVED
        except OSError:
            return FAILED
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
    return FAILED


def _rename_key(old_key: str, new_key: str):
    def change(doc) -> bool:
        if not isinstance(doc, dict) or old_key not in doc or new_key in doc:
            return False  # nothing to move, or the new folder has its own entry already: keep that one
        doc[new_key] = doc.pop(old_key)
        return True

    return change


def _rename_prefix(old: str, new: str):
    def change(doc) -> bool:
        if not isinstance(doc, dict):
            return False
        moved = False
        for k in [k for k in doc if isinstance(k, str) and k.startswith(f"{old}\t")]:
            nk = f"{new}\t{k[len(old) + 1 :]}"
            if nk not in doc:
                doc[nk] = doc.pop(k)
                moved = True
        return moved

    return change


def _rename_field(old: str, new: str, wid: str | None = None):
    def change(doc) -> bool:
        if not isinstance(doc, list):
            return False
        moved = False
        for e in doc:
            if (
                isinstance(e, dict)
                and e.get("workspace") == old
                and (wid is None or e.get("workspace_id") == wid)
            ):
                e["workspace"] = new
                moved = True
        return moved

    return change


def move_records(home: Path, old: str, new: str, wid: str) -> tuple[list[str], list[str]]:
    """Move the old path's entries in the orch home to the new path: (files changed, files that failed).
    Safe to run again: what already moved has nothing of the old path left."""
    done, failed = [], []
    for name, change in (
        ("permissions.json", _rename_key(_hash_key(old), _hash_key(new))),
        ("copies.json", _rename_key(_hash_key(old), _hash_key(new))),
        ("ports.json", _rename_prefix(old, new)),
        ("consent.json", _rename_field(old, new, wid)),
    ):
        got = _rewrite(home / name, change)
        (done if got == MOVED else failed if got == FAILED else []).append(name)
    return done, failed


def move_running(home: Path, old: str, new: str) -> bool:
    """running.json is only a hint for restarts (written under the services lock): best effort, after the
    keys moved. False when it could not be updated (then services started in the old folder restart once)."""
    from orch import services

    try:
        with services.locked(timeout=30):
            return _rewrite(home / "running.json", _rename_field(old, new)) != FAILED
    except Refused:
        return False


def is_person(by: str | None) -> bool:
    """A person at a terminal, not inside a helper run (the same marks checkfiles and tickets use)."""
    import sys

    from orch import renew, term, tickets

    if (
        (by or "").startswith("agent:")
        or tickets.agent_tool()
        or any(os.environ.get(k) for k in renew.RUN_MARKS)
    ):
        return False
    return term.is_terminal(sys.stdin) and term.is_terminal(sys.stdout)


def move_here(root: Path, *, by: str | None = None, ask=input) -> dict:
    """The whole command: person check, the question with both folders, then (under the folders lock, once
    the core checked again what the person was asked) the records and the re-bind. A record that cannot be
    moved stops it before the keys, so running it again finishes the job."""
    from orch import addons
    from orch import home as orch_home

    if not is_person(by):
        raise Refused(NOT_A_PERSON)
    new = os.path.realpath(root)
    state, old = orch_home.binding_check(root)
    if state == "here":
        return {"moved": False, "old": new, "new": new, "files": []}
    if state == "none":
        raise Refused("No saved keys belong to this folder, so there is nothing to move.")
    if state == "copy":
        raise Refused(orch_home.COPY_OF.format(old=old))
    wid = addons.read_local_id(root)
    if state != "moved" or old is None or wid is None:
        orch_home.key_dir(root, create=False)  # says what is wrong in its own words
        raise Refused(orch_home.TRY_AGAIN)
    try:
        answer = ask(f"Move this workspace's saved keys and settings from {old} to {new}? [y/N] ")
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        raise Refused("Nothing was moved.")
    home = addons.home()
    files: list[str] = []

    def records() -> None:  # under the folders lock, after the core checked what the person confirmed
        done, failed = move_records(home, old, new, wid)
        if failed:
            raise Refused(
                f"orch could not update {', '.join(failed)} in your orch folder, so the saved keys were not "
                "moved. Close other orch windows and run it again."
            )
        files.extend(done)

    res = orch_home.move_here(root, expect_id=wid, expect_old=old, before_bind=records)
    out = {"moved": res["moved"], "old": res["old"], "new": res["new"], "files": [*files]}
    if res["moved"]:
        out["files"].insert(0, "binding.json")
        if not move_running(home, old, new):
            out["not_moved"] = ["running.json"]
    return out
