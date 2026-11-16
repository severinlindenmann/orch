"""Factory's files only. Atomic replacement, no symlinks, and serialized writers."""

import errno
import hashlib
import json
import os
import re
import stat
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
    if definition == "proposal":
        for h in value.get("handovers") or []:
            for f in (h.get("sends") or {}).get("files") or []:
                if not handover_file_ok(f):
                    raise Refused(
                        "A hand-over file path may use only letters, digits, spaces, _ . / ( ) - "
                        "(relative, no dot folders, no '..', no extra spaces): rename the file or pick another.",
                        "invalid",
                    )


HANDOVER_FILE_CHARS = set(" _./()-")


def handover_file_ok(f):
    """Strict check of a hand-over file path, on top of the schema pattern (a JSON-schema `$` can match before a
    trailing newline). An allowlist: letters and digits (umlauts too, R1.6), space and _ . / ( ) -; relative; no empty,
    dot or '..' segment; no space at the start or end of the path or of a segment, no double space."""
    if not isinstance(f, str) or not f or len(f) > 120 or "\n" in f or f != f.strip():
        return False
    if not all(c.isalnum() or c in HANDOVER_FILE_CHARS for c in f):
        return False
    if f.startswith("/") or "  " in f or ".." in f:
        return False
    return all(seg and seg == seg.strip() and not seg.startswith(".") for seg in f.split("/"))


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

    # Below the store folder every step is opened relative to the folder before it, without following links (openat):
    # a link swapped in between a check and the open can not redirect a read or a write (#681).
    def _dir_fd(self, parts, create=False):
        if create:
            self.base.mkdir(parents=True, exist_ok=True)
        no_links(self.base)  # the workspace's own folders above the store: checked once
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(self.base, flags)
        try:
            for part in parts:
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                nxt = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = nxt
        except OSError as error:
            os.close(fd)
            if error.errno in (errno.ELOOP, errno.ENOTDIR):  # a link (or a file) where a folder must be
                raise Refused("Factory cannot use symbolic links.", "not_allowed") from None
            raise
        return fd

    def read(self, relative):
        parts = self.path(relative).relative_to(self.base).parts
        dfd = self._dir_fd(parts[:-1])
        try:
            try:  # O_NONBLOCK: a FIFO planted here must not hang Factory (it is refused below as not regular)
                fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
            except OSError as error:
                if error.errno == errno.ELOOP:
                    raise Refused("Factory cannot use symbolic links.", "not_allowed") from None
                raise
        finally:
            os.close(dfd)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise Refused("A Factory file is not a regular file.", "not_allowed")
            os.set_blocking(stream.fileno(), True)
            return stream.read()

    def write(self, relative, data, *, frozen=False):
        parts = self.path(relative).relative_to(self.base).parts
        dfd = self._dir_fd(parts[:-1], create=True)
        name = ".new-" + uuid4().hex
        try:
            if frozen:
                try:
                    if self.read(relative) == data:
                        return
                    raise Refused("This Factory version is already frozen.", "conflict")
                except FileNotFoundError:
                    pass
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, parts[-1], src_dir_fd=dfd, dst_dir_fd=dfd)
            os.fsync(dfd)  # the rename itself is durable too
        finally:
            try:
                os.unlink(name, dir_fd=dfd)
            except FileNotFoundError:
                pass
            os.close(dfd)

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
