"""Private, hidden activity records and explicit retention."""

import errno
import json
import os
import re
import stat
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from orch import hider as hiding
from orch.collect_execjson import _hash, detail_name
from orch.errors import Refused
from orch.hider import Hider
from orch.phone_view import redact

_OFF = "Recording is off until key hiding is ready."
_INVALID = "This record entry is not valid."
_RUN = r"r_[a-z0-9_]{6,32}"
_FILE = r"[A-Za-z0-9_-]{1,128}"


class RecordRefused(Refused):
    """Recording cannot proceed safely."""


def record_dir(workspace: Path) -> Path:
    return Path(workspace) / ".orch" / "record"


def registered_writer(workspace: Path) -> "RecordWriter":
    try:
        return RecordWriter(workspace, hider=hiding.current_hider())
    except hiding.NoHiderError:
        raise RecordRefused(_OFF) from None


def _name(value: Any, pattern: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise RecordRefused(_INVALID)
    return value


def _safe(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink():
            raise RecordRefused("The record folder is not safe.")


def _tree(path: Path) -> None:
    _safe(path)
    if path.is_dir():
        for child in path.iterdir():
            _tree(child)


# POSIX: every write walks the folders with directory file descriptors (O_NOFOLLOW at each step), so a symlink
# swapped in between a check and the open is refused instead of followed. Windows has no dir_fd: there the
# symlink check (_safe, which also covers reparse points reported as links) stays the fail-closed fallback.
_FD = os.name == "posix" and {os.open, os.mkdir, os.unlink, os.rmdir, os.replace} <= os.supports_dir_fd
_DIR = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_NOT_SAFE = "The record folder is not safe."


@contextmanager
def _parent(path: Path, create: bool = False):
    """Yield (dir fd, name) of path's parent folder, walked from the root without following any symlink."""
    parts = Path(path).absolute().parts
    fd = os.open(parts[0], _DIR)
    try:
        for part in parts[1:-1]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                    made = True
                except FileExistsError:
                    made = False
            next_fd = os.open(part, _DIR, dir_fd=fd)
            if create and made:
                os.fchmod(next_fd, 0o700)
            os.close(fd)
            fd = next_fd
        yield fd, parts[-1]
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR, errno.EMLINK):
            raise RecordRefused(_NOT_SAFE) from None
        raise
    finally:
        os.close(fd)


def _mkdir(path: Path) -> None:
    _safe(path)
    if _FD:
        with _parent(Path(path) / "x", create=True):
            pass
    elif not path.exists():
        _mkdir(path.parent)
        path.mkdir(mode=0o700, exist_ok=True)
        path.chmod(0o700)


def _open(path: Path, flags: int) -> int:
    _safe(path)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    if _FD:
        with _parent(path) as (pfd, name):
            fd = os.open(name, flags, 0o600, dir_fd=pfd)
    else:
        fd = os.open(path, flags, 0o600)
    if flags & (os.O_WRONLY | os.O_RDWR):
        os.fchmod(fd, 0o600)
    return fd


def _unlink(path: Path) -> None:
    _safe(path)
    if not _FD:
        path.unlink(missing_ok=True)
        return
    try:
        with _parent(path) as (pfd, name):
            os.unlink(name, dir_fd=pfd)
    except FileNotFoundError:
        pass


def _json(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _validate(event: dict, *, detail: bool = False) -> None:
    validator = _DETAIL_VALIDATOR if detail else _VALIDATOR
    if not validator.is_valid(event):
        raise RecordRefused(_INVALID)


def _generic(obj: Any) -> Any:
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, list):
        return [_generic(x) for x in obj]
    if isinstance(obj, dict):
        return {redact(k): _generic(v) for k, v in obj.items()}
    return obj


def _key(event: dict) -> tuple:
    return event["run"], event["id"], event["kind"], event["outcome"] is not None


def _precedence(event: dict) -> int:
    return 1 if event["via"] == "log" else 2


def _lines(path: Path) -> list[dict]:
    _safe(path)
    try:
        fd = _open(path, os.O_RDONLY)
    except FileNotFoundError:
        return []
    result = []
    with os.fdopen(fd, "rb") as stream:
        for line in stream:
            try:
                event = json.loads(line)
                _validate(event)
                result.append(event)
            except (ValueError, UnicodeError, RecordRefused, TypeError):
                continue
    return result


@contextmanager
def _lock(path: Path):
    for _ in range(200):
        try:
            fd = _open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            _safe(path)
            try:
                if time.time() - path.stat().st_mtime > 30:
                    _unlink(path)
                    continue
            except FileNotFoundError:
                continue
            time.sleep(0.005)
    else:
        raise RecordRefused("The record is busy.")
    try:
        yield
    finally:
        os.close(fd)
        _unlink(path)


def _atomic(path: Path, payload: bytes) -> None:
    _safe(path)
    temporary = path.with_name("tmp_" + uuid.uuid4().hex)
    fd = _open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        if _FD:
            with _parent(path) as (pfd, name):
                os.replace(temporary.name, name, src_dir_fd=pfd, dst_dir_fd=pfd)
        else:
            _safe(path)
            os.replace(temporary, path)
    finally:
        _unlink(temporary)


class RecordWriter:
    def __init__(self, workspace: Path, *, hider: Hider):
        if not isinstance(hider, Hider):
            raise RecordRefused(_OFF)
        self.workspace, self.hider = Path(workspace), hider

    def _serialized(self, obj: dict) -> bytes:
        line = _json(obj)
        if self.hider.hide_text(line) != line:
            raise RecordRefused("This record cannot be hidden safely.")
        return line.encode("utf-8")

    def _prepare(self, event: dict, payload: dict | None, hidden: int) -> tuple[bytes, bytes | None]:
        run = event["run"]
        detail_bytes = None
        if payload is not None:
            event["detail"] = f"detail/{run}/{detail_name(event['id'])}.json"
            wrapped = dict(
                v=1,
                id=event["id"],
                run=run,
                input=payload["input"],
                output=payload["output"],
                truncated=False,
                hidden=hidden,
            )
            detail_bytes = self._serialized(wrapped)
            while len(detail_bytes) > 1024 * 1024:
                output = wrapped["output"]
                if not isinstance(output, str):
                    output = _json(output)
                if not output:
                    raise RecordRefused("The record detail is too large.")
                wrapped["output"] = self.hider.hide_cut(output, len(output) // 2)
                wrapped["truncated"] = True
                detail_bytes = self._serialized(wrapped)
            _validate(wrapped, detail=True)
        line = self._serialized(event) + b"\n"
        while len(line) > 8192:
            if event["text"]:
                event["text"] = self.hider.hide_cut(event["text"], len(event["text"]) // 2)
            elif event.get("outcome") and event["outcome"].get("error"):
                error = event["outcome"]["error"]
                event["outcome"]["error"] = self.hider.hide_cut(error, len(error) // 2) or None
            else:
                raise RecordRefused("The record entry is too large.")
            line = self._serialized(event) + b"\n"
        _validate(event)
        return line, detail_bytes

    def append(self, event: dict, *, detail: dict | None = None) -> dict | None:
        try:
            return self._append(event, detail)
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            raise RecordRefused(_INVALID) from None
        except OSError:
            raise RecordRefused("The record could not be written.") from None

    def _append(self, event: dict, detail: dict | None) -> dict | None:
        if not isinstance(event, dict):
            raise RecordRefused(_INVALID)
        run = _name(event.get("run"), _RUN)
        event = dict(event, seq=1, v=1)
        default_id = event.get("id") is None
        eid = event.get("id") if not default_id else f"{run}:1"
        if not isinstance(eid, str):
            raise RecordRefused(_INVALID)
        # Hide key values in the raw id BEFORE it is judged or hashed, so a secret-bearing id can never leave as an
        # unsalted (guessable) hash; the same id still gives the same name for hook and collector (dedupe).
        eid = self.hider.hide_text(eid)
        event["id"] = eid if re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", eid) else _hash(eid)
        # Reject malformed input, including controls, before normalizing display text.
        if not isinstance(event.get("text"), str) or re.search(r"[\x00-\x1f\x7f]", event["text"]):
            raise RecordRefused(_INVALID)
        if event.get("detail") is not None:
            _name(event["detail"], rf"detail/{_RUN}/{_FILE}\.json")
        if detail is not None and (
            not isinstance(detail, dict)
            or not {"input", "output"} <= detail.keys()
            or event.get("kind") in ("key.use", "session.input")
        ):
            raise RecordRefused(_INVALID)
        before = _json([event, detail]).count("[hidden: ")
        event = self.hider.hide_json(event)
        payload = self.hider.hide_json(detail) if detail is not None else None
        hidden = max(0, _json([event, payload]).count("[hidden: ") - before)
        event["text"] = self.hider.hide_cut(" ".join(redact(event["text"]).split()), 500)
        if isinstance(event.get("outcome"), dict) and isinstance(event["outcome"].get("error"), str):
            event["outcome"]["error"] = self.hider.hide_cut(
                " ".join(redact(event["outcome"]["error"]).split()), 300
            )
        if "data" in event:
            event["data"] = _generic(event["data"])
        _validate(event)
        self._prepare(event, payload, hidden)
        root = record_dir(self.workspace)
        _tree(root)
        _mkdir(root / "runs")
        with _lock(root / "runs" / f"{run}.lock"):
            path = root / "runs" / f"{run}.jsonl"
            previous = _lines(path)
            event["seq"] = previous[-1]["seq"] + 1 if previous else 1
            if default_id:
                event["id"] = f"{run}:{event['seq']}"
            if any(_key(old) == _key(event) and _precedence(old) >= _precedence(event) for old in previous):
                return None
            line, detail_bytes = self._prepare(event, payload, hidden)
            if detail_bytes is not None:
                target = root / event["detail"]
                _mkdir(target.parent)
                _atomic(target, detail_bytes)
            meta = self._serialized(
                dict(schema="orch.record/1", since=event["at"], keep_days=90, max_mb=2048)
            )
            try:
                fd = _open(root / "meta.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(meta)
            fd = _open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY)
            try:
                if os.write(fd, line) != len(line):
                    raise RecordRefused("The record could not be written.")
            finally:
                os.close(fd)
            return event


def read_events(workspace: Path, run: str) -> list[dict]:
    run = _name(run, _RUN)
    kept: dict[tuple, dict] = {}
    for event in _lines(record_dir(workspace) / "runs" / f"{run}.jsonl"):
        if event["run"] != run:
            continue
        key = _key(event)
        if key not in kept or _precedence(event) > _precedence(kept[key]):
            kept[key] = event
    return sorted(kept.values(), key=lambda e: e["seq"])


def read_detail(workspace: Path, run: str, file_id: str) -> dict | None:
    run, file_id = _name(run, _RUN), _name(file_id, _FILE)
    path = record_dir(workspace) / "detail" / run / f"{file_id}.json"
    _safe(path)
    try:
        with os.fdopen(_open(path, os.O_RDONLY), "rb") as stream:
            value = json.load(stream)
        _validate(value, detail=True)
        return value if value["run"] == run else None
    except (FileNotFoundError, ValueError, RecordRefused):
        return None


def list_runs(workspace: Path) -> list[str]:
    path = record_dir(workspace) / "runs"
    _tree(path)
    return sorted(p.stem for p in path.glob("*.jsonl") if re.fullmatch(_RUN, p.stem) and p.is_file())


def hook_entry_filter(line: dict) -> dict | None:
    if not isinstance(line, dict) or line.get("kind") not in (
        "step",
        "denial",
        "helper.start",
        "helper.end",
        "usage",
    ):
        raise RecordRefused("This kind of record is not allowed here.")
    return dict(line, via="hook")


def plan_retention(runs: list[dict], now: str, keep_days: int = 90, max_mb: int = 2048) -> dict:
    plan: dict[str, list[str]] = dict(fold_first=[], delete_detail=[], delete_run=[])
    cutoff = datetime.fromisoformat(now) - timedelta(days=keep_days)
    ended = sorted((r for r in runs if r["ended"]), key=lambda r: datetime.fromisoformat(r["ended"]))
    total = sum(r["detail_mb"] + r["file_mb"] for r in runs)
    for run in ended:
        if datetime.fromisoformat(run["ended"]) < cutoff:
            plan["delete_detail"].append(run["run"])
            plan["delete_run"].append(run["run"])
            total -= run["detail_mb"] + run["file_mb"]
    for field, size in (("delete_detail", "detail_mb"), ("delete_run", "file_mb")):
        for run in ended:
            if total <= max_mb:
                break
            if run["run"] not in plan[field] and run[size] > 0:
                plan[field].append(run["run"])
                total -= run[size]
    plan["fold_first"] = plan["delete_run"].copy()
    return plan


def _remove_in(dir_fd: int, name: str) -> None:
    try:
        mode = os.stat(name, dir_fd=dir_fd, follow_symlinks=False).st_mode
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(mode):
        os.unlink(name, dir_fd=dir_fd)  # a link is removed itself, never followed
        return
    child = os.open(name, _DIR, dir_fd=dir_fd)
    try:
        for entry in os.listdir(child):
            _remove_in(child, entry)
    finally:
        os.close(child)
    os.rmdir(name, dir_fd=dir_fd)


def _remove(path: Path) -> None:
    _tree(path)
    if _FD:
        try:
            with _parent(path) as (pfd, name):
                _remove_in(pfd, name)
        except FileNotFoundError:
            pass
    elif path.is_dir():
        for child in path.iterdir():
            _remove(child)
        path.rmdir()
    else:
        path.unlink(missing_ok=True)


def delete_detail(workspace: Path, runs: list[str]) -> None:
    paths = [record_dir(workspace) / "detail" / _name(run, _RUN) for run in runs]
    for path in paths:
        _tree(path)
    for path in paths:
        _remove(path)


def _size(path: Path) -> int:
    _tree(path)
    if path.is_dir():
        return sum(_size(p) for p in path.iterdir())
    return path.stat().st_size if path.exists() else 0


def apply_retention(
    workspace: Path, now: str, keep_days: int, max_mb: int, fold: Callable[[str, list[dict]], Any]
) -> dict:
    root = record_dir(workspace)
    _tree(root)
    runs, events = [], {}
    for run in list_runs(workspace):
        events[run] = read_events(workspace, run)
        states = [e for e in events[run] if e["kind"] == "run.state"]
        last = states[-1] if states else None
        ended = last["at"] if last and last["data"]["state"] in ("done", "failed", "stopped") else None
        runs.append(
            dict(
                run=run,
                ended=ended,
                detail_mb=_size(root / "detail" / run) / 1024**2,
                file_mb=(_size(root / "runs" / f"{run}.jsonl") + _size(root / "jobs" / run)) / 1024**2,
            )
        )
    plan = plan_retention(runs, now, keep_days, max_mb)
    # Detail-only eviction also folds first, although the public plan lists run-file folds only.
    for run in dict.fromkeys(plan["fold_first"] + plan["delete_detail"]):
        fold(run, events[run])
    delete_detail(workspace, plan["delete_detail"])
    for run in plan["delete_run"]:
        _remove(root / "runs" / f"{run}.jsonl")
        _remove(root / "jobs" / run)
    return plan


# Bundled contract: installed packages do not have the repository's contracts directory.
_SCHEMA = {
    "type": "object",
    "required": [
        "v",
        "id",
        "seq",
        "run",
        "session",
        "agent",
        "parent",
        "at",
        "ticket",
        "harness",
        "via",
        "kind",
        "text",
        "used",
        "outcome",
        "detail",
        "coverage",
    ],
    "properties": {
        "v": {"const": 1},
        "id": {"$ref": "#/$defs/event_id"},
        "seq": {"type": "integer", "minimum": 1},
        "run": {"$ref": "#/$defs/run"},
        "session": {
            "oneOf": [
                {"type": "null"},
                {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[A-Za-z0-9_.:-]+$"},
            ]
        },
        "agent": {"$ref": "#/$defs/agent"},
        "parent": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/agent"}]},
        "at": {"$ref": "#/$defs/time"},
        "ticket": {"type": "string", "pattern": "^t_[a-z0-9]{6,16}$"},
        "harness": {"type": "string", "pattern": "^[a-z][a-z0-9-]{0,31}$"},
        "via": {"enum": ["hook", "log", "broker", "job", "core"]},
        "kind": {
            "enum": [
                "step",
                "task.start",
                "task.done",
                "ask",
                "denial",
                "helper.start",
                "helper.end",
                "run.state",
                "usage",
                "key.use",
                "job",
                "session.input",
            ]
        },
        "text": {"type": "string", "maxLength": 500, "pattern": "^[^\\u0000-\\u001f\\u007f]*$"},
        "used": {
            "oneOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "required": ["kind", "name", "action", "source", "version"],
                    "additionalProperties": False,
                    "properties": {
                        "kind": {"enum": ["skill", "tool", "mcp", "key", "helper"]},
                        "name": {"$ref": "#/$defs/name"},
                        "action": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/name"}]},
                        "source": {"enum": ["harness", "admin", "workspace", "builtin", "marketplace"]},
                        "version": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/version"}]},
                    },
                },
            ]
        },
        "outcome": {
            "oneOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "required": ["ok", "error", "ms"],
                    "additionalProperties": False,
                    "properties": {
                        "ok": {"type": ["boolean", "null"]},
                        "error": {
                            "oneOf": [
                                {"type": "null"},
                                {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 300,
                                    "pattern": "^[^\\u0000-\\u001f\\u007f]*$",
                                },
                            ]
                        },
                        "ms": {"oneOf": [{"type": "null"}, {"type": "integer", "minimum": 0}]},
                    },
                },
            ]
        },
        "detail": {
            "oneOf": [
                {"type": "null"},
                {"type": "string", "pattern": "^detail/r_[a-z0-9_]{6,32}/[A-Za-z0-9_-]{1,128}\\.json$"},
            ]
        },
        "coverage": {"enum": ["full", "partial"]},
        "data": {"type": "object"},
    },
    "allOf": [
        {
            "if": {"properties": {"agent": {"const": "main"}}},
            "then": {"properties": {"parent": {"type": "null"}}},
            "else": {"properties": {"parent": {"$ref": "#/$defs/agent"}}},
        },
        {
            "if": {"properties": {"kind": {"const": "step"}}},
            "then": {
                "properties": {
                    "via": {"enum": ["hook", "log"]},
                    "used": {"type": "object", "properties": {"kind": {"enum": ["skill", "tool", "mcp"]}}},
                }
            },
        },
        {
            "if": {"properties": {"kind": {"enum": ["task.start", "task.done"]}}},
            "then": {
                "required": ["data"],
                "properties": {
                    "via": {"const": "core"},
                    "data": {
                        "required": ["check"],
                        "properties": {"check": {"type": "string", "pattern": "^c[0-9]{1,4}$"}},
                    },
                },
            },
        },
        {
            "if": {"properties": {"kind": {"const": "ask"}}},
            "then": {
                "required": ["data"],
                "properties": {
                    "via": {"const": "core"},
                    "data": {
                        "required": ["q"],
                        "properties": {"q": {"type": "string", "pattern": "^q[0-9]{1,4}$"}},
                    },
                },
            },
        },
        {
            "if": {"properties": {"kind": {"const": "denial"}}},
            "then": {"properties": {"outcome": {"type": "object", "properties": {"ok": {"const": False}}}}},
        },
        {
            "if": {"properties": {"kind": {"enum": ["helper.start", "helper.end"]}}},
            "then": {
                "properties": {
                    "agent": {"pattern": "^h_[0-9]{1,4}$"},
                    "used": {"type": "object", "properties": {"kind": {"const": "helper"}}},
                }
            },
        },
        {
            "if": {"properties": {"kind": {"const": "run.state"}}},
            "then": {
                "required": ["data"],
                "properties": {
                    "data": {
                        "required": ["state"],
                        "properties": {
                            "state": {
                                "enum": [
                                    "starting",
                                    "working",
                                    "waiting_you",
                                    "idle",
                                    "done",
                                    "failed",
                                    "stopped",
                                ]
                            }
                        },
                    }
                },
            },
        },
        {
            "if": {"properties": {"kind": {"const": "usage"}}},
            "then": {
                "required": ["data"],
                "properties": {
                    "data": {
                        "anyOf": [{"required": ["used"]}, {"required": ["tokens_in"]}],
                        "properties": {
                            "used": {"type": "number", "minimum": 0, "maximum": 1},
                            "window": {"type": "string", "maxLength": 32},
                            "status": {"enum": ["ok", "warning", "limited"]},
                            "tokens_in": {"type": "integer", "minimum": 0},
                            "tokens_out": {"type": "integer", "minimum": 0},
                        },
                    }
                },
            },
        },
        {
            "if": {"properties": {"kind": {"const": "key.use"}}},
            "then": {
                "required": ["data"],
                "properties": {
                    "via": {"const": "broker"},
                    "detail": {"type": "null"},
                    "used": {
                        "type": "object",
                        "required": ["kind"],
                        "properties": {
                            "kind": {"const": "key"},
                            "action": {"enum": ["env", "file", "exec", "get"]},
                            "source": {"enum": ["workspace", "admin"]},
                        },
                    },
                    "outcome": {"type": "object"},
                    "data": {
                        "required": ["profile", "command"],
                        "additionalProperties": False,
                        "properties": {
                            "profile": {"$ref": "#/$defs/name"},
                            "command": {
                                "oneOf": [
                                    {"type": "null"},
                                    {"type": "string", "pattern": "^[A-Za-z0-9_.+-]{1,64}$"},
                                ]
                            },
                            "skill": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/name"}]},
                            "refused": {
                                "enum": [
                                    "not_in_profile",
                                    "get_off",
                                    "get_to_terminal",
                                    "missing",
                                    "too_short",
                                    "switched_off",
                                ]
                            },
                        },
                    },
                },
            },
        },
        {
            "if": {"properties": {"kind": {"const": "job"}}},
            "then": {
                "required": ["data"],
                "properties": {
                    "via": {"const": "job"},
                    "data": {
                        "required": ["job", "type", "state"],
                        "properties": {
                            "job": {"type": "string", "pattern": "^j_[a-z0-9]{6,32}$"},
                            "type": {
                                "enum": [
                                    "start",
                                    "step",
                                    "progress",
                                    "artifact",
                                    "metric",
                                    "table",
                                    "link",
                                    "log",
                                    "end",
                                    "lost",
                                ]
                            },
                            "state": {"enum": ["running", "ok", "failed", "cancelled", "lost"]},
                        },
                    },
                },
            },
        },
        {
            "if": {"properties": {"kind": {"const": "session.input"}}},
            "then": {
                "required": ["data"],
                "properties": {
                    "via": {"const": "core"},
                    "used": {"type": "null"},
                    "detail": {"type": "null"},
                    "data": {
                        "required": ["by", "from", "since", "ended", "reason", "keys"],
                        "additionalProperties": False,
                        "properties": {
                            "by": {"type": "string", "pattern": "^human:[^\\u0000-\\u001f]{1,58}$"},
                            "from": {"const": "local-page"},
                            "since": {"$ref": "#/$defs/time"},
                            "ended": {"$ref": "#/$defs/time"},
                            "reason": {
                                "enum": ["released", "idle", "run-ended", "switched-off", "locked-by-admin"]
                            },
                            "keys": {"type": "integer", "minimum": 0},
                        },
                    },
                },
            },
        },
    ],
    "$defs": {
        "time": {"type": "string", "format": "date-time", "pattern": "Z$"},
        "run": {"type": "string", "pattern": "^r_[a-z0-9_]{6,32}$"},
        "agent": {"type": "string", "pattern": "^(main|h_[0-9]{1,4})$"},
        "event_id": {"type": "string", "minLength": 1, "maxLength": 160, "pattern": "^[A-Za-z0-9_.:-]+$"},
        "name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
            "pattern": "^[^\\u0000-\\u001f\\u007f<>]+$",
        },
        "version": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
        "detail_file": {
            "type": "object",
            "required": ["v", "id", "run", "input", "output", "truncated", "hidden"],
            "additionalProperties": False,
            "properties": {
                "v": {"const": 1},
                "id": {"$ref": "#/$defs/event_id"},
                "run": {"$ref": "#/$defs/run"},
                "input": {},
                "output": {},
                "truncated": {"type": "boolean"},
                "hidden": {"type": "integer", "minimum": 0},
            },
        },
    },
}
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())
_DETAIL_VALIDATOR = Draft202012Validator(
    {"$ref": "#/$defs/detail_file", "$defs": _SCHEMA["$defs"]}, format_checker=FormatChecker()
)
