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
    "Only you can move a workspace's saved keys: run orch workspace move-here yourself in a terminal in the "
    "moved folder (a helper can't)."
)


def _hash_key(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:32]  # = config._perm_key of that real path


def _rewrite(f: Path, change) -> bool:
    """Apply `change(doc) -> bool` to the JSON in `f` and replace it atomically, keeping the file's rights; a
    link, a missing or malformed file, or a file that changed meanwhile (three tries): untouched."""
    if f.is_symlink() or not f.is_file():
        return False
    for _ in range(3):
        try:
            raw = f.read_bytes()
            doc = json.loads(raw)
        except (OSError, ValueError):
            return False
        if not change(doc):
            return False
        tmp = f.with_name(f".{f.name}.orch-move-{os.getpid()}.tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, f.stat().st_mode & 0o777)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
                json.dump(doc, out, indent=2, ensure_ascii=False)
                out.write("\n")
            if f.read_bytes() != raw:
                continue
            os.replace(tmp, f)
            return True
        except OSError:
            return False
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
    return False


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


def move_records(home: Path, old: str, new: str, wid: str) -> list[str]:
    """Move the old path's entries in the orch home to the new path. Returns the files changed."""
    from orch import services

    done = []
    for name, change in (
        ("permissions.json", _rename_key(_hash_key(old), _hash_key(new))),
        ("copies.json", _rename_key(_hash_key(old), _hash_key(new))),
        ("ports.json", _rename_prefix(old, new)),
        ("consent.json", _rename_field(old, new, wid)),
    ):
        if _rewrite(home / name, change):
            done.append(name)
    try:
        with services.locked(timeout=30):  # running.json is written under the services lock
            if _rewrite(home / "running.json", _rename_field(old, new)):
                done.append("running.json")
    except Refused:
        pass  # only a hint for restarts; never blocks the move
    return done


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
    """The whole command: person check, the question with both folders, re-bind, then the records."""
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
    if state != "moved":
        orch_home.key_dir(root, create=False)  # says what is wrong in its own words
        raise Refused(orch_home.TRY_AGAIN)
    try:
        answer = ask(f"Move this workspace's saved keys and settings from {old} to {new}? [y/N] ")
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        raise Refused("Nothing was moved.")
    res = orch_home.move_here(root)
    files = ["binding.json"] if res["moved"] else []
    if res["moved"]:
        files += move_records(addons.home(), res["old"], res["new"], res["id"])
    return {"moved": res["moved"], "old": res["old"], "new": res["new"], "files": files}
