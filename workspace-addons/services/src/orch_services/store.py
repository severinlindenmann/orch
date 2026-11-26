"""Service records on disk: one plain JSON file each in .orch/addons/services/services/<id>.json.

Contract: contracts/addons/services/service.schema.json. A file that cannot be read is skipped and counted, never
rewritten. Fields this version does not know are kept when a record is rewritten."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

SCHEMA = "orch.services.service/1"
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MAX_NAME = 80


class Refused(Exception):
    """Plain words for the person; the CLI prints them and exits 2."""


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def base_dir(root: Path) -> Path:
    return root / ".orch" / "addons" / "services"


def records_dir(root: Path) -> Path:
    return base_dir(root) / "services"


def logs_dir(root: Path) -> Path:
    return base_dir(root) / "logs"


def _platform() -> str:
    return sys.platform  # a function, so tests on Linux can pretend to be a Mac


def log_path(root: Path, sid: str, wid: str | None = None) -> Path:
    """Where a job writes its log. macOS (with the workspace id): ~/Library/Logs/orch/<workspace id>/, because
    launchd cannot open a log in a folder macOS protects, such as an external disk (it ends the job with 78 before it
    starts; report r-1120-0610-services). Elsewhere: in the workspace."""
    if wid and _platform() == "darwin":
        return Path.home() / "Library" / "Logs" / "orch" / wid / f"{sid}.log"
    return logs_dir(root) / f"{sid}.log"


def _earlier_log_paths(root: Path, sid: str, wid: str | None) -> tuple[Path, ...]:
    """Every place a job may still write its log: the current one, the workspace (before the logs moved) and, on
    macOS, the per-folder home log an earlier build gave a workspace on /Volumes (<folder name>-<sha1 8>/)."""
    places = [log_path(root, sid, wid), logs_dir(root) / f"{sid}.log"]
    if wid and _platform() == "darwin":
        try:
            r = Path(root).resolve()
        except OSError:
            r = Path(root).absolute()
        tag = hashlib.sha1(str(r).encode()).hexdigest()[:8]
        name = re.sub(r"[^A-Za-z0-9._-]", "-", r.name)
        places.append(Path.home() / "Library" / "Logs" / "orch" / f"{name}-{tag}" / f"{sid}.log")
    return tuple(dict.fromkeys(places))


def read_log_path(root: Path, sid: str, wid: str | None = None) -> Path:
    """The log to read: the newest of the places a job may write it (a job loaded before the logs moved keeps
    writing the old one until it is started again)."""

    def mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return -1.0

    places = _earlier_log_paths(root, sid, wid)
    best = max(places, key=mtime)
    return best if mtime(best) > mtime(places[0]) else places[0]


def home_dir(wid: str) -> Path:
    """macOS: the folder a job of a workspace on an external disk runs from (launchd cannot start it there)."""
    return Path.home() / "Library" / "Application Support" / "orch" / wid


def set_aside_old_log(root: Path, sid: str, wid: str | None = None) -> Path | None:
    """A new service must not show the lines of a removed one with the same id (ORCH-1131): move the old log into
    removed/<sid>-<time>.log next to it (both places on macOS), so the new service starts with an empty log. Returns
    where the log to read went; refused when one could not be moved."""
    shown = read_log_path(root, sid, wid)
    moved: Path | None = None
    for log in _earlier_log_paths(root, sid, wid):
        if not log.is_file():
            continue
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        dest = log.parent / "removed" / f"{sid}-{stamp}.log"
        n = 1
        while dest.exists():
            n += 1
            dest = log.parent / "removed" / f"{sid}-{stamp}-{n}.log"
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(log, dest)
        except OSError as e:
            raise Refused(
                f"The old log of an earlier service {sid} could not be moved aside ({e.strerror or e}). "
                "Close what has it open and try again, or pick another id."
            ) from e
        if log == shown:
            moved = dest
    return moved


def state_path(root: Path, sid: str) -> Path:
    return base_dir(root) / "state" / f"{sid}.json"


def check_id(sid: str) -> str:
    if not isinstance(sid, str) or not ID_RE.fullmatch(sid):
        raise Refused(
            f"'{sid}' is not a valid service id. Use 1-40 lowercase letters, digits and dashes, like web-preview."
        )
    return sid


def clean_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise Refused('Say what the service is called: orch services add "<name>" --id <id> -- <command>')
    if _CONTROL.search(name) or "<" in name or ">" in name:
        raise Refused("A service name is one plain line without < or >. Rephrase it and try again.")
    if len(name) > MAX_NAME:
        raise Refused(f"A service name is at most {MAX_NAME} characters. Shorten it and try again.")
    return name


def clean_command(argv: list[str]) -> list[str]:
    if not argv:
        raise Refused("Say which command the service runs, after --: orch services add ... -- <command>")
    if len(argv) > 64 or any(not a or "\x00" in a or "\n" in a or "\r" in a or len(a) > 4096 for a in argv):
        raise Refused("The command has an empty word or a line break in it. Fix the command and try again.")
    return list(argv)


def clean_cwd(root: Path, cwd: str | None) -> str:
    """A folder inside the workspace, written relative to it with forward slashes ("." = the workspace)."""
    raw = (cwd or ".").strip() or "."
    p = Path(raw)
    if p.is_absolute():
        try:
            p = p.resolve().relative_to(root.resolve())
        except ValueError:
            raise Refused(
                "The folder must be inside this workspace. Give a folder of the workspace."
            ) from None
    # Windows: C:\ws\web or web\app are normal folder names (as_posix turns \ into /); elsewhere a \ that is left
    # is part of a name and is refused, so the record reads the same on every computer.
    posix = p.as_posix()
    rel = PurePosixPath(posix)
    if ".." in rel.parts or "\\" in posix or _CONTROL.search(raw):
        raise Refused("The folder must be inside this workspace. Give a folder of the workspace.")
    text = rel.as_posix() or "."
    full = (root / text).resolve()
    if not full.is_dir():
        raise Refused(f"The folder {text} does not exist in this workspace. Make it first, then try again.")
    try:
        full.relative_to(root.resolve())
    except ValueError:
        raise Refused("The folder must be inside this workspace. Give a folder of the workspace.") from None
    return text


def check_port(port: int | None) -> int | None:
    if port is None:
        return None
    if not 1 <= port <= 65535:
        raise Refused("A port is a number from 1 to 65535. Give the right port and try again.")
    return port


def write_json(path: Path, data: dict) -> None:
    """New file next to the target, then rename (R8.2): a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        with open(tmp, "x", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _valid(d: object, sid: str) -> bool:
    return (
        isinstance(d, dict)
        and d.get("schema") == SCHEMA
        and d.get("id") == sid
        and isinstance(d.get("name"), str)
        and isinstance(d.get("command"), list)
        and bool(d["command"])
        and all(isinstance(a, str) and a for a in d["command"])
        and isinstance(d.get("auto", False), bool)
        and isinstance(d.get("important", False), bool)
    )


def _read(path: Path) -> dict | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return d if _valid(d, path.stem) else None


def load_all(root: Path) -> tuple[list[dict], int]:
    """(records sorted by name, number of files that could not be read)."""
    d = records_dir(root)
    out, bad = [], 0
    if not d.is_dir():
        return out, bad
    for p in sorted(d.glob("*.json")):
        if not ID_RE.fullmatch(p.stem):
            continue
        r = _read(p)
        if r is None:
            bad += 1
        else:
            r.setdefault("cwd", ".")
            r.setdefault("auto", False)
            out.append(r)
    out.sort(key=lambda r: (r["name"].lower(), r["id"]))
    return out, bad


def get(root: Path, sid: str) -> dict:
    check_id(sid)
    p = records_dir(root) / f"{sid}.json"
    if not p.exists():
        raise Refused(f"There is no service {sid}. Run orch services list to see the services.")
    r = _read(p)
    if r is None:
        raise Refused(
            f"The record of service {sid} could not be read. Fix or delete .orch/addons/services/services/{sid}.json."
        )
    r.setdefault("cwd", ".")
    r.setdefault("auto", False)
    return r


def exists(root: Path, sid: str) -> bool:
    return (records_dir(root) / f"{sid}.json").exists()


def save(root: Path, rec: dict) -> None:
    write_json(records_dir(root) / f"{rec['id']}.json", rec)


def delete(root: Path, sid: str) -> None:
    check_id(sid)
    for p in (records_dir(root) / f"{sid}.json", state_path(root, sid)):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def read_state(root: Path, sid: str) -> dict:
    """The state file of a service ({} when there is none or it cannot be read)."""
    p = state_path(root, sid)
    if p.is_symlink():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return d if isinstance(d, dict) else {}


def update_state(root: Path, sid: str, **fields) -> None:
    """Change some fields of the state file and keep the others (new file + rename)."""
    check_id(sid)
    d = read_state(root, sid)
    d.update(fields)
    write_json(state_path(root, sid), d)


def mark(root: Path, sid: str, running: bool) -> None:
    """Remember when the service last changed state (the `since` of a stopped service) and what the person wants."""
    update_state(root, sid, running=running, since=now())


def last_change(root: Path, sid: str) -> str | None:
    d = read_state(root, sid)
    s = d.get("since")
    return s if isinstance(s, str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", s) else None
