"""Factory's files only. Atomic replacement, no symlinks, and serialized writers."""

import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker


class Refused(Exception):
    def __init__(self, message, code="refused"):
        super().__init__(message)
        self.code = code


def clock():
    """Current time. FACTORY_NOW (ISO, for tests) can only move time FORWARD: a later clock only shortens
    autopilot grants, so an agent that sets it gains nothing."""
    now = datetime.now(UTC)
    fixed = os.environ.get("FACTORY_NOW")
    try:
        later = datetime.fromisoformat(fixed) if fixed else None
    except ValueError:
        later = None
    if later is not None and later.tzinfo is not None and later > now:
        return later
    return now


def now():
    return clock().isoformat().replace("+00:00", "Z")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def schema_of(definition):
    """The bundled schema for one definition (proposal | autopilot | change | stop), self-contained."""
    schema = json.loads(Path(__file__).with_name("proposal.schema.json").read_bytes())
    if definition not in ("proposal", "autopilot", "change", "stop"):
        raise Refused("Say which one: proposal, autopilot, change or stop.", "invalid")
    schema["$ref"] = "#/$defs/" + definition
    schema.pop("oneOf")
    return schema


def field_list(definition):
    """One short text: the required and the optional fields of a definition."""
    d = schema_of(definition)["$defs"][definition]
    need = list(d.get("required", []))
    more = [k for k in d.get("properties", {}) if k not in need]
    return f"Fields. required: {', '.join(need)}. optional: {', '.join(more) or 'none'}."


def validate(value, definition):
    schema = json.loads(Path(__file__).with_name("proposal.schema.json").read_bytes())
    schema["$ref"] = "#/$defs/" + definition
    schema.pop("oneOf")
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    if errors:
        raise Refused("The Factory data does not match " + definition + ": " + errors[0].message, "invalid")


def no_links(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise Refused("Factory cannot use symbolic links.", "not_allowed")


def read_bytes(path):
    no_links(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        return stream.read()


class Store:
    def __init__(self, root):
        self.base = Path(root).absolute() / ".orch" / "addons" / "factory"

    def path(self, relative):
        p = Path(relative)
        if p.is_absolute() or ".." in p.parts or not p.parts:
            raise Refused("The Factory file path is not valid.", "invalid")
        result = self.base / p
        no_links(result)
        return result

    def read(self, relative):
        return read_bytes(self.path(relative))

    def write(self, relative, data, *, frozen=False):
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        no_links(path)
        if frozen and path.exists():
            if self.read(relative) == data:
                return
            raise Refused("This Factory version is already frozen.", "conflict")
        fd, name = tempfile.mkstemp(prefix=".new-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    @contextmanager
    def locked(self):
        import fcntl

        lock = self.path(".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), "r+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            for folder in ("drafts", "proposals", "changes", "stops"):
                self.path(folder).mkdir(exist_ok=True)
            yield

    def next_version(self, folder, order, prefix, suffix):
        if not re.fullmatch(r"t_[a-z0-9]{6,16}", order):
            raise Refused("The order id is not valid.", "invalid")
        path = self.path(f"{folder}/{order}")
        versions = []
        if path.exists():
            for p in path.iterdir():
                no_links(p)
                match = re.fullmatch(rf"{prefix}([1-9][0-9]*)\.{suffix}", p.name)
                if match:
                    versions.append(int(match[1]))
        return max(versions, default=0) + 1

    def journal_read(self):
        try:
            data = self.read("journal.jsonl")
        except FileNotFoundError:
            return []
        if data and not data.endswith(b"\n"):
            raise Refused("The Factory journal has an incomplete line.", "invalid")
        try:
            rows = [json.loads(line) for line in data.splitlines()]
            for row in rows:
                validate(row, "journal_line")
            return rows
        except (ValueError, UnicodeError):
            raise Refused("The Factory journal cannot be read.", "invalid") from None

    def journal_append(self, line):
        """Caller holds locked(); preserve all previous lines byte for byte."""
        row = {"id": "e_" + uuid4().hex[:20], "at": now(), **line}
        validate(row, "journal_line")
        self.journal_read()
        try:
            previous = self.read("journal.jsonl")
        except FileNotFoundError:
            previous = b""
        self.write("journal.jsonl", previous + json.dumps(row).encode() + b"\n")
        return row
