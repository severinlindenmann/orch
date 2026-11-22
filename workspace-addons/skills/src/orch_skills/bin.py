"""Delete, the bin and Restore for skills, and New skill (ORCH-841).

Delete never loses a file, even when it is cut off half way:
1. the folder is copied into a bin entry (state "copying"), the copy is checked file by file (sha256),
2. the entry says "removing"; the folder is moved aside in one rename (`.orch-delete-<entry>`), only files the copy
   holds unchanged are removed from it (each compared right before it goes), anything else goes back to the old
   place; then the entry says "in-bin".
A move cut off in step 1 is undone (the half copy goes, the folder was never touched); one cut off in step 2 is
finished the same way. orch does this before every list and every change (`recover`), under the same locks as the
changes (the workspace's and the computer bin's own, shared by every workspace).

Two bins:
- this workspace's skills: `.orch/addons/skills/bin/<entry>/` inside the workspace;
- your computer's skills (the helper tools' own folders, used by every workspace): `<orch home>/skills-bin/<entry>/`,
  outside the workspace, so removing or resetting the workspace keeps them.
Nothing is ever removed from a bin by itself (no automatic purge in this version).

Restore ("restoring" → "restored") copies the entry to `.orch-restore-<entry>` next to the old place (refused when
something is in the way there), claims the name with an empty folder (mkdir fails when it is taken) and renames the
copy onto that claim; anything written into the claim meanwhile makes the rename fail. It never replaces anything.
A restore cut off half way is undone (the temporary folder goes, only when it holds nothing but bin files) or
finished (the folder in place holds exactly the bin copy).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from . import switches
from .switches import Refused, _is_link, safe_path

SCHEMA = "orch.skills-bin/1"
WS_BIN = Path(".orch") / "addons" / "skills" / "bin"
RECORD = "record.json"
ITEM = "item"
LOCK = ".lock"
ENTRY = re.compile(r"[0-9]{8}T[0-9]{6}Z-[A-Za-z0-9_.@-]{1,120}-[0-9a-f]{6}")
BIN_TARGET = re.compile(r"bin:(workspace|mine):(" + ENTRY.pattern + ")")
NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
MAX_BYTES = 200 * 1024 * 1024
MAX_FILES = 5000


# ---- where -------------------------------------------------------------------------------------------------


def mine_bin() -> Path:
    """The bin for your computer's skills: in the person's orch home, outside every workspace."""
    from orch import addons

    return Path(addons.home()) / "skills-bin"


def _bin(root: Path, where: str) -> Path:
    if where == "workspace":
        return safe_path(root, WS_BIN)
    return mine_bin()


def _mine_places(account_home: Path | None) -> list[Path]:
    from orch import inventory

    return [Path(p) for p in inventory.harness_skill_dirs(account_home)]


def _no_links(base: Path, path: Path) -> None:
    """Refuse when base, or any folder from base down to path, is a link."""
    if _is_link(base):
        raise Refused(f"{base.name} is a link; orch will not delete or restore through it. Nothing was changed.")
    p = base
    for part in path.relative_to(base).parts:
        if part in ("", ".", ".."):
            raise Refused("That path is not a skill folder.")
        p = p / part
        if _is_link(p):
            raise Refused(f"{p.name} is a link; orch will not delete or restore through it. Nothing was changed.")


def _place_of(root: Path, where: str, origin: str, account_home: Path | None) -> Path:
    """The folder an entry came from, checked again: a workspace entry only in a skills folder helpers read (switches.skill_places), a
    computer entry only in one of the helper tools' skill folders. A record that names anything else is refused."""
    if where == "workspace":
        rel = Path(origin)
        if rel.is_absolute() or rel.parent not in switches.skill_places() or not rel.name:
            raise Refused("This bin entry does not say where it came from. Nothing was changed.")
        return safe_path(root, rel)
    p = Path(origin)
    for base in _mine_places(account_home):
        if p.parent == base and p.name not in ("", ".", ".."):
            _no_links(base, p)
            return p
    raise Refused("This bin entry came from a skills folder this computer no longer uses. Nothing was changed.")


# ---- one change at a time --------------------------------------------------------------------------------


@contextlib.contextmanager
def _lockfile(lock: Path, wait: float):
    lock.parent.mkdir(parents=True, exist_ok=True)
    end = time.monotonic() + wait
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
            break
        except FileExistsError:
            with contextlib.suppress(OSError):
                if time.time() - lock.stat().st_mtime > 300:  # left by a process that died
                    lock.unlink()
                    continue
            if time.monotonic() > end:
                raise Refused("Another change is being saved. Try again in a moment.") from None
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(fd)
        with contextlib.suppress(OSError):
            lock.unlink()


@contextlib.contextmanager
def locked(root: Path, wait: float = 5.0):
    """The workspace's change lock and the computer bin's own lock (it is shared by every workspace), so a list,
    a delete and a restore never act on the same entry at once."""
    from .switches import _locked

    with _locked(root, wait):
        base = mine_bin()
        if _is_link(base):
            raise Refused("The bin for your computer's skills is a link; orch will not use it.")
        with _lockfile(base / LOCK, wait):
            yield


# ---- the record --------------------------------------------------------------------------------------------


def _read(entry: Path) -> dict | None:
    try:
        if _is_link(entry / RECORD):
            return None
        doc = json.loads((entry / RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("schema") == SCHEMA else None


def _write(entry: Path, doc: dict) -> None:
    fd, tmp = tempfile.mkstemp(prefix=RECORD + ".", suffix=".tmp", dir=entry)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, entry / RECORD)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rmtree(p: Path) -> None:
    def again(func, path, _exc):  # a read-only file (Windows, git objects): make it writable and try once more
        with contextlib.suppress(OSError):
            os.chmod(path, stat.S_IWRITE)
            func(path)

    if _is_link(p):
        p.unlink()
    elif p.exists():
        shutil.rmtree(p, onerror=again)


# ---- comparing folders -------------------------------------------------------------------------------------


def _digest(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tree(folder: Path) -> dict[str, tuple[str, str]]:
    """{relative path: (kind, what)} of everything under folder; kind file (sha256), link (its target) or dir.
    Links are never followed, also not as the starting folder (refused)."""
    _real_dir(folder)
    out: dict[str, tuple[str, str]] = {}
    for dirpath, dirs, files in os.walk(folder, followlinks=False):
        here = Path(dirpath)
        for d in list(dirs):
            p = here / d
            rel = p.relative_to(folder).as_posix()
            if _is_link(p):
                out[rel] = ("link", os.readlink(p))
                dirs.remove(d)
            else:
                out[rel] = ("dir", "")
        for f in files:
            p = here / f
            rel = p.relative_to(folder).as_posix()
            out[rel] = ("link", os.readlink(p)) if _is_link(p) else ("file", _digest(p))
    return out


def _size_ok(folder: Path) -> None:
    total = count = 0
    for dirpath, _dirs, files in os.walk(folder, followlinks=False):
        for f in files:
            count += 1
            with contextlib.suppress(OSError):
                total += os.lstat(Path(dirpath) / f).st_size
    if count > MAX_FILES or total > MAX_BYTES:
        raise Refused("This skill folder is too big for the bin. Nothing was changed.")


def _real_dir(folder: Path) -> None:
    """Refuse a starting folder that is a link or not a folder: orch never walks or removes through a link."""
    try:
        st = os.lstat(folder)
    except OSError:
        raise Refused(f"{folder.name} is missing. Nothing was changed.") from None
    if _is_link(folder) or not stat.S_ISDIR(st.st_mode):
        raise Refused(f"{folder.name} is a link or not a folder; orch will not go through it. Nothing was changed.")


def _same(tree: dict[str, tuple[str, str]], held: dict[str, tuple[str, str]]) -> bool:
    """Everything in tree (files and links) is in held with the same content."""
    return all(v[0] == "dir" or held.get(rel) == v for rel, v in tree.items())


def _clear_held(folder: Path, held: dict[str, tuple[str, str]]) -> bool:
    """Remove from folder only files and links the checked copy holds unchanged (each one compared right before it
    goes), then the folders that became empty. True when folder is gone."""
    _real_dir(folder)
    for dirpath, dirs, files in os.walk(folder, topdown=False, followlinks=False):
        here = Path(dirpath)
        for f in [*files, *(d for d in dirs if _is_link(here / d))]:
            q = here / f
            rel = q.relative_to(folder).as_posix()
            with contextlib.suppress(OSError):
                now = ("link", os.readlink(q)) if _is_link(q) else ("file", _digest(q))
                if held.get(rel) == now:
                    q.unlink()
        with contextlib.suppress(OSError):
            here.rmdir()  # only when empty
    return not os.path.lexists(folder)


def _finish_removal(src: Path, entry: Path, held: dict[str, tuple[str, str]]) -> str | None:
    """Step 2 of Delete, also when it is run again after a cut-off: move the folder aside in one rename (an editor
    that writes to the old place now makes a new folder there, which stays), remove from the aside folder only what
    the bin holds, and put anything else back. Returns a note when files stayed."""
    aside = src.parent / f".orch-delete-{entry.name}"
    if not os.path.lexists(aside):
        if not os.path.lexists(src):
            return None
        os.rename(src, aside)
    if _clear_held(aside, held):
        return None
    if not os.path.lexists(src):
        os.rename(aside, src)
        return "Files changed during the delete stayed in the old place."
    return f"Files changed during the delete are kept in {aside.name} next to the old place."


# ---- recover -----------------------------------------------------------------------------------------------


def _entries(base: Path) -> list[Path]:
    try:
        if not base.is_dir() or _is_link(base):
            return []
        return sorted(p for p in base.iterdir() if ENTRY.fullmatch(p.name) and p.is_dir() and not _is_link(p))
    except OSError:
        return []


def recover(root: Path, account_home: Path | None = None) -> list[str]:
    """Finish or undo every move that was cut off. Returns one plain line per entry it fixed."""
    done = []
    for where in ("workspace", "mine"):
        try:
            base = _bin(root, where)
        except Exception:  # noqa: BLE001, S112  no bin (or a link on its way): nothing to recover there
            continue
        for entry in _entries(base):
            rec = _read(entry)
            if rec is None:
                continue
            with contextlib.suppress(Refused, OSError):
                line = _recover_one(root, where, entry, rec, account_home)
                if line:
                    done.append(line)
    return done


def _recover_one(root: Path, where: str, entry: Path, rec: dict, account_home: Path | None) -> str | None:
    state, name = rec.get("state"), rec.get("name", "?")
    if state == "copying":  # the folder was never touched: drop the half copy
        _rmtree(entry)
        return f"{name}: an unfinished delete was undone; the skill is where it was."
    src = _place_of(root, where, str(rec.get("from", "")), account_home)
    held = _tree(entry / ITEM)  # refused when the bin copy is a link
    if state == "removing":
        note = _finish_removal(src, entry, held)
        rec["state"] = "in-bin"
        if note:
            rec["note"] = note
        _write(entry, rec)
        return f"{name}: an unfinished delete was finished; it is in the bin."
    if state == "restoring":
        tmp = src.parent / f".orch-restore-{entry.name}"
        if os.path.lexists(tmp):  # not in place yet: undo, removing only what is a copy of the bin entry
            if _same(_tree(tmp), held):
                _rmtree(tmp)
                with contextlib.suppress(OSError):
                    src.rmdir()  # orch's empty claim of the name, if it got that far
            else:
                rec["note"] = f"{tmp.name} next to the old place holds other files; orch left it."
            rec["state"] = "in-bin"
            _write(entry, rec)
            return f"{name}: an unfinished restore was undone; it is still in the bin."
        if os.path.lexists(src) and not _is_link(src) and _tree(src) == held:
            rec["state"] = "restored"
            _write(entry, rec)
        else:
            rec["state"] = "in-bin"
            _write(entry, rec)
            return f"{name}: an unfinished restore was undone; it is still in the bin."
    if rec.get("state") == "restored":
        _rmtree(entry)
        return f"{name}: an unfinished restore was finished; it is back."
    return None


# ---- delete ------------------------------------------------------------------------------------------------


def source_folder(root: Path, where: str, name: str, account_home: Path | None = None) -> Path:
    """The real folder of a workspace or computer skill, checked: no link anywhere on the way."""
    if where == "workspace":
        for place in switches.skill_places():
            p = root / place / name
            if (p / "SKILL.md").is_file() or _is_link(p):
                return safe_path(root, place / name)
    elif where == "mine":
        for base in _mine_places(account_home):
            p = base / name
            if (p / "SKILL.md").is_file() or _is_link(p):
                _no_links(base, p)
                return p
    raise Refused("That skill is not here any more. Reload the page and try again.")


def delete(root: Path, where: str, name: str, who: str, account_home: Path | None = None) -> dict:
    """Move one workspace or computer skill into its bin. Returns the bin row."""
    if where not in ("workspace", "mine"):
        raise Refused(f"{name} cannot be deleted here: only this workspace's and your computer's skills can.")
    src = source_folder(root, where, name, account_home)
    if not src.is_dir():
        raise Refused(f"{name} is not a skill folder. Nothing was changed.")
    _size_ok(src)
    if any(p.name.startswith(".orch-delete-") for p in src.parent.iterdir()):
        raise Refused(
            "An earlier delete left a folder next to this skill that needs a look first. Nothing was changed."
        )
    base = _bin(root, where)
    base.mkdir(parents=True, exist_ok=True)
    if where == "workspace":
        safe_path(root, WS_BIN)
        origin = src.relative_to(root).as_posix()
    else:
        origin = str(src)
    safe = re.sub(r"[^A-Za-z0-9_.@-]", "_", name)[:120] or "skill"
    entry = base / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{safe}-{secrets.token_hex(3)}"
    entry.mkdir()
    rec = {
        "schema": SCHEMA,
        "kind": "skill",
        "where": where,
        "name": name,
        "from": origin,
        "at": _now(),
        "by": who,
        "state": "copying",
    }
    _write(entry, rec)
    try:
        shutil.copytree(src, entry / ITEM, symlinks=True)
        held = _tree(entry / ITEM)
        if held != _tree(src):
            raise Refused(f"{name} changed while it was copied. Nothing was deleted; try again.")
    except BaseException:
        _rmtree(entry)
        raise
    rec["state"] = "removing"
    _write(entry, rec)
    note = _finish_removal(src, entry, held)
    if note:
        rec["note"] = note
    rec["state"] = "in-bin"
    _write(entry, rec)
    return _row(root, where, entry, rec, account_home)


# ---- restore -----------------------------------------------------------------------------------------------


def _entry_of(root: Path, target: str) -> tuple[str, Path, dict]:
    m = BIN_TARGET.fullmatch(target or "")
    if not m:
        raise Refused("That is not something in the bin. Reload the page and try again.")
    where, name = m.group(1), m.group(2)
    entry = _bin(root, where) / name
    rec = _read(entry) if entry.is_dir() and not _is_link(entry) else None
    if rec is None or rec.get("where") != where:
        raise Refused("That is not in the bin any more. Reload the page and try again.")
    return where, entry, rec


def restore(root: Path, target: str, who: str, account_home: Path | None = None) -> dict:
    """Put one bin entry back where it was. Never replaces anything there."""
    where, entry, rec = _entry_of(root, target)
    name = rec.get("name", "?")
    if rec.get("state") != "in-bin":
        raise Refused(f"{name} is still being moved. Reload the page in a moment.")
    dest = _place_of(root, where, str(rec.get("from", "")), account_home)
    if os.path.lexists(dest):
        raise Refused(
            f"A skill named {name} is there again. Restore never replaces it: delete or rename that one first."
        )
    if not (entry / ITEM).is_dir() or _is_link(entry / ITEM):
        raise Refused(f"The bin copy of {name} is missing. Nothing was changed.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if where == "workspace":
        _place_of(root, where, str(rec["from"]), account_home)  # the folders just made are real folders too
    tmp = dest.parent / f".orch-restore-{entry.name}"
    if os.path.lexists(tmp):
        raise Refused(f"A folder {tmp.name} is in the way next to the old place. Nothing was changed.")
    rec["state"], rec["restore_by"] = "restoring", who
    _write(entry, rec)
    claimed = False
    try:
        shutil.copytree(entry / ITEM, tmp, symlinks=True)
        if os.name != "nt":  # POSIX rename replaces an empty folder: claim the name first (mkdir fails when taken)
            try:
                os.mkdir(dest)
            except FileExistsError:
                raise Refused(f"A skill named {name} appeared there just now. Restore never replaces it.") from None
            claimed = True
        os.rename(tmp, dest)  # onto orch's own empty claim; anything written into it meanwhile makes this fail
    except BaseException:
        with contextlib.suppress(OSError):
            _rmtree(tmp)
        if claimed:
            with contextlib.suppress(OSError):
                dest.rmdir()
        rec["state"] = "in-bin"
        rec.pop("restore_by", None)
        _write(entry, rec)
        raise
    rec["state"] = "restored"
    _write(entry, rec)
    _rmtree(entry)
    return {"name": name, "where": where, "from": rec["from"]}


# ---- listing -----------------------------------------------------------------------------------------------


def _shown_from(where: str, origin: str, account_home: Path | None) -> str:
    if where == "workspace":
        return origin
    try:
        from orch import addons

        home = Path(account_home) if account_home else Path(addons.real_home())
        return "~/" + Path(origin).relative_to(home).as_posix()
    except (ValueError, Exception):  # noqa: BLE001
        return origin


def _row(root: Path, where: str, entry: Path, rec: dict, account_home: Path | None) -> dict:
    row = {
        "id": f"bin:{where}:{entry.name}",
        "kind": "skill",
        "name": str(rec.get("name", "?")),
        "where": where,
        "from": _shown_from(where, str(rec.get("from", "")), account_home),
        "at": rec.get("at"),
        "by": str(rec.get("by", "")).split(":", 1)[-1],
        "state": rec.get("state"),
    }
    if rec.get("note"):
        row["note"] = rec["note"]
    why = None
    if rec.get("state") != "in-bin":
        why = "Still being moved"
    else:
        try:
            if os.path.lexists(_place_of(root, where, str(rec.get("from", "")), account_home)):
                why = f"A skill named {row['name']} is there again; Restore never replaces it"
        except Refused as e:
            why = str(e).split(". Nothing")[0]
    row["can_restore"] = why is None
    if why:
        row["why"] = why
    return row


def rows(root: Path, account_home: Path | None = None) -> list[dict]:
    """Everything in both bins, newest first (read only)."""
    out = []
    for where in ("workspace", "mine"):
        try:
            base = _bin(root, where)
        except Exception:  # noqa: BLE001, S112  no bin here
            continue
        for entry in _entries(base):
            rec = _read(entry)
            if rec is not None and rec.get("where") == where:
                out.append(_row(root, where, entry, rec, account_home))
    return sorted(out, key=lambda r: str(r.get("at") or ""), reverse=True)


# ---- new skill ---------------------------------------------------------------------------------------------


def skill_text(name: str, owner: str) -> str:
    """The standard header (ORCH-531: top level name and description, orch's fields as strings under metadata),
    state draft, and a short body to fill in."""
    owner = owner.replace('"', "'")
    return (
        "---\n"
        f"name: {name}\n"
        'description: "What this skill does. Use when ... Not for ..."\n'
        "metadata:\n"
        '  version: "0.1.0"\n'
        f'  owner: "{owner}"\n'
        '  status: "draft"\n'
        "---\n"
        f"# {name}\n\n"
        "Write here what a helper should do, step by step.\n"
    )


def new_skill(root: Path, name: str, owner: str, taken: set[str]) -> Path:
    """Make .agents/skills/<name>/SKILL.md with the standard header. Refused when the name is taken anywhere here."""
    if not (NAME.fullmatch(name or "") and len(name) <= 64):
        raise Refused("A skill name uses small letters, digits and single dashes, like weekly-report (at most 64).")
    if name in taken or name.startswith("orch"):
        raise Refused(f"A skill named {name} is already here. Pick another name.")
    for place in switches.skill_places():
        if os.path.lexists(root / place / name):
            raise Refused(f"A skill named {name} is already here. Pick another name.")
    rel = switches.skill_places()[0] / name
    folder = safe_path(root, rel)
    folder.parent.mkdir(parents=True, exist_ok=True)
    safe_path(root, rel)
    try:
        folder.mkdir()
    except FileExistsError:
        raise Refused(f"A skill named {name} is already here. Pick another name.") from None
    fd = os.open(folder / "SKILL.md", os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(skill_text(name, owner))
    return folder
