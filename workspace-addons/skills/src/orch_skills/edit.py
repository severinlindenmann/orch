"""Edit on the Skills page (ORCH-840): this workspace's own skills and instruction files, nothing else.

Read: every editable item gets an opaque edit id (`e_` + 24 hex of a hash over kind, place, name and path), and
`load` gives its text and a revision (sha256 of the file's bytes). Save (`orch skills act save --value=<revision>
-- <edit id>`, the text on stdin, only a person): the id is resolved against a fresh list of editable items (a page
never names a path), the file is re-checked as a regular file inside the workspace reached through real folders,
its bytes must still match the revision the page loaded, a copy goes to the bin first, then the new bytes replace
it through a temporary file next to it. A skill's header is changed line by line (only the fields the person
changed; every other line, unknown metadata too, stays byte for byte) and its body is written as sent.
Design and threat model: ORCH-840 edit-design.md.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

from . import adapters, switches
from .switches import Refused, safe_path

MAX_FILE = 64 * 1024  # a file bigger than this (UTF-8 bytes) is not offered for editing and not written
MAX_INPUT = 160 * 1024  # what a save may send on stdin: the text as JSON (escapes make it longer than the file)
EDIT_ID = re.compile(r"e_[0-9a-f]{24}")
REVISION = re.compile(r"[0-9a-f]{64}")
SKILL_BASES = adapters.SKILL_DIRS
BIN = Path(".orch") / "addons" / "skills" / "bin"
# The ORCH-531 header form: the description and these metadata fields. Anything else in a header is kept as it is.
META_FIELDS = (
    "status",
    "owner",
    "platforms",
    "requires",
    "requires-logins",
    "review-by",
    "version",
    "tags",
    "replaced-by",
)
FIELDS = ("description", *META_FIELDS)
STATUS_WORDS = ("draft", "active", "deprecated", "retired")
PLATFORM_WORDS = ("macos", "windows", "linux")
FIELD_MAX = 300
DESCRIPTION_MAX = 1024
# never in a field: controls (a newline would start a new header line), line separators, bidi and zero-width marks
HIDDEN = re.compile("[\x00-\x1f\x7f-\x9f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]")
_KEY = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.-]*):")


def _skillmeta():
    try:
        from orch import skillmeta
    except ImportError:
        return None
    return skillmeta if hasattr(skillmeta, "parse_header") else None


def edit_id(kind: str, where: str, name: str, rel: str) -> str:
    return "e_" + hashlib.sha256(f"{kind}\0{where}\0{name}\0{rel}".encode()).hexdigest()[:24]


def revision(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ---- which files ------------------------------------------------------------------------------------------


def _regular(root: Path, rel: Path) -> Path | None:
    """root/rel when it is a regular file reached through real folders only (no link on the way), else None."""
    try:
        p = safe_path(root, rel)
        st = os.lstat(p)
    except (Refused, OSError):
        return None
    return p if stat.S_ISREG(st.st_mode) else None


def _readable(path: Path) -> bytes | None:
    """The file's bytes when it can be edited here: at most MAX_FILE, UTF-8, no NUL."""
    try:
        if path.stat().st_size > MAX_FILE:
            return None
        raw = path.read_bytes()
        raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return None if b"\0" in raw or len(raw) > MAX_FILE else raw


def candidates(root: Path) -> list[dict]:
    """Every file this page may edit, as {id, kind, where, name, rel, mode}. A file that is a link, too big,
    not UTF-8, or holds NUL is left out (the panel says why it cannot be edited)."""
    out: list[dict] = []
    seen: set[str] = set()
    for base in SKILL_BASES:
        try:
            if switches._is_link(root / base) or not (root / base).is_dir():
                continue
            kids = sorted((root / base).iterdir())
        except OSError:
            continue
        for folder in kids:
            name = folder.name
            if name.startswith(".") or name in seen or switches._is_link(folder) or not folder.is_dir():
                continue
            if (folder / ".orch-shared").exists():  # shared by the admin: not this workspace's own
                continue
            rel = base / name / "SKILL.md"
            if _regular(root, rel) is None:
                continue
            seen.add(name)
            out.append({"kind": "skill", "where": "workspace", "name": name, "rel": rel})
    for fn in adapters.INSTRUCTION_FILES:
        rel = Path(fn)
        if _regular(root, rel) is not None:
            out.append({"kind": "instructions", "where": "workspace", "name": fn, "rel": rel})
    for c in out:
        c["id"] = edit_id(c["kind"], c["where"], c["name"], c["rel"].as_posix())
    return out


def offer(root: Path, orch_names: set[str]) -> dict[tuple[str, str], dict]:
    """{(kind, name): {"id", "mode"} or {"why"}} for the read model: what the panel's Edit does."""
    out: dict[tuple[str, str], dict] = {}
    for c in candidates(root):
        if c["kind"] == "skill" and c["name"] in orch_names:
            continue  # a copy of orch's own skill: orch writes it
        raw = _readable(root / c["rel"])
        if raw is None:
            out[(c["kind"], c["name"])] = {"why": "Too big, or not plain text: edit it in your editor."}
            continue
        out[(c["kind"], c["name"])] = {"id": c["id"], "mode": _mode(c, raw)}
    return out


def _mode(c: dict, raw: bytes) -> str:
    if c["kind"] != "skill":
        return "text"
    meta = _skillmeta()
    if meta is None:
        return "text"
    try:
        meta.parse_header(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001  a header the reader refuses: edited as one text
        return "text"
    return "skill"


def _resolve(root: Path, target: str, orch_names: set[str]) -> dict:
    if not EDIT_ID.fullmatch(target or ""):
        raise Refused("That is not something Skills can edit. Reload the page and try again.")
    for c in candidates(root):
        if c["id"] == target and not (c["kind"] == "skill" and c["name"] in orch_names):
            return c
    raise Refused("That item cannot be edited here any more. Reload the page and try again.")


# ---- the header -------------------------------------------------------------------------------------------


def _split(text: str) -> tuple[list[str], int, str] | None:
    """(header lines with their line endings, index of the closing --- line, body) or None."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n").strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n").strip() == "---":
            return lines[: i + 1], i, "".join(lines[i + 1 :])
    return None


def _fields_of(head: dict) -> dict:
    meta = head.get("metadata") if isinstance(head.get("metadata"), dict) else {}
    out = {"description": str(head.get("description") or "")}
    for k in META_FIELDS:
        out[k] = str(meta.get(k) or "")
    return out


def load(root: Path, target: str, orch_names: set[str]) -> dict:
    """What the editor shows for one edit id: {id, name, kind, mode, revision, fields+body | text}."""
    c = _resolve(root, target, orch_names)
    path = _regular(root, c["rel"])
    raw = _readable(path) if path else None
    if raw is None:
        raise Refused(f"{c['name']} is too big or not plain text; edit it in your editor.")
    text = raw.decode("utf-8")
    out = {"id": c["id"], "name": c["name"], "kind": c["kind"], "mode": _mode(c, raw), "revision": revision(raw)}
    if out["mode"] == "skill":
        head = _skillmeta().parse_header(text)[0]
        out["fields"] = _fields_of(head)
        out["body"] = _split(text)[2]
    else:
        out["text"] = text
    return out


def _check_field(key: str, value) -> str:
    if not isinstance(value, str):
        raise Refused(f"{key} must be text.")
    v = value.strip()
    if HIDDEN.search(v):
        raise Refused(f"{key}: use plain text on one line.")
    if len(v) > (DESCRIPTION_MAX if key == "description" else FIELD_MAX):
        raise Refused(f"{key} is too long.")
    if key == "description" and not v:
        raise Refused("A skill needs a description: say what it does and when to use it.")
    if key == "status" and v and v not in STATUS_WORDS:
        raise Refused("State is one of: " + ", ".join(STATUS_WORDS) + ".")
    if key == "platforms" and v:
        parts = [p.strip() for p in v.split(",")]
        if not all(p in PLATFORM_WORDS for p in parts):
            raise Refused("Runs on is a list of: " + ", ".join(PLATFORM_WORDS) + ".")
    if key == "review-by" and v:
        try:
            date.fromisoformat(v)
        except ValueError:
            raise Refused("Look again on is a date like 2027-03-31.") from None
        if not re.fullmatch(r"\d{4}-\d\d-\d\d", v):
            raise Refused("Look again on is a date like 2027-03-31.")
    return v


LIST_FIELDS = ("platforms", "requires", "requires-logins", "tags")


def _same(key: str, new: str, old: str) -> bool:
    """A comma list with other spacing ("macos,linux" and "macos, linux") is the same value: its line stays."""
    if key in LIST_FIELDS:
        return [w.strip() for w in new.split(",") if w.strip()] == [w.strip() for w in old.split(",") if w.strip()]
    return new == old


def _quoted(v: str) -> str:
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def rewrite_header(text: str, fields: dict) -> str:
    """The SKILL.md text with the changed form fields written into its header. Unchanged fields, unknown keys,
    comments and the body stay byte for byte. Only a header the one reader (orch.skillmeta) reads is changed, so
    there are no block values, nested maps or lists whose lines could be cut apart. Raises Refused."""
    meta = _skillmeta()
    if meta is None:
        raise Refused("Editing the header needs a newer orch. Nothing was changed.")
    if not isinstance(fields, dict) or set(fields) - set(FIELDS):
        raise Refused("The form sent fields Skills does not know. Reload the page and try again.")
    split = _split(text)
    if split is None:
        raise Refused("SKILL.md has no header to change. Nothing was changed.")
    lines, close, body = split
    try:
        head = meta.parse_header(text)[0]
    except Exception:  # noqa: BLE001
        raise Refused("This header cannot be read as a form. Edit it as text. Nothing was changed.") from None
    old = _fields_of(head)
    for k, v in fields.items():
        if not isinstance(v, str):
            raise Refused(f"{k} must be text.")
    # only what the person changed is checked: a value already in the file (a custom state) may stay as it is
    changed = {k: _check_field(k, v) for k, v in fields.items() if not _same(k, v.strip(), old[k])}
    if not changed:
        return text
    nl = "\r\n" if lines[0].endswith("\r\n") else "\n"
    top: dict[str, int] = {}  # top-level key -> its line
    meta_at: dict[str, int] = {}  # metadata key -> its line
    meta_indent, in_meta = "", False
    for i in range(1, close):
        ln = lines[i].rstrip("\r\n")
        m = _KEY.match(ln.strip()) if ln.strip() and not ln.lstrip().startswith("#") else None
        if not m:
            continue
        if ln[0] in " \t":
            if in_meta:
                meta_at[m.group(1)] = i
                meta_indent = meta_indent or ln[: len(ln) - len(ln.lstrip())]
            continue
        in_meta = m.group(1) == "metadata"
        top[m.group(1)] = i
    out: dict[int, list[str]] = {i: [ln] for i, ln in enumerate(lines[:close])}
    if "description" in changed:
        line = f"description: {_quoted(changed['description'])}{nl}"
        if "description" in top:
            out[top["description"]] = [line]
        else:
            out[0].append(line)  # right after the opening ---
    indent = meta_indent or "  "
    adds = []
    for k in META_FIELDS:
        if k not in changed:
            continue
        line = f"{indent}{k}: {_quoted(changed[k])}{nl}" if changed[k] else None
        if k in meta_at:
            out[meta_at[k]] = [line] if line else []
        elif line:
            adds.append(line)
    if adds:
        if "metadata" not in top:
            out[close - 1].extend([f"metadata:{nl}", *adds])
        elif meta_at or not lines[top["metadata"]].rstrip("\r\n").strip().endswith("{}"):
            out[max([top["metadata"], *meta_at.values()])].extend(adds)
        else:
            raise Refused("The header's metadata is written on one line. Edit it as text. Nothing was changed.")
    result = "".join(x for i in range(close) for x in out[i]) + lines[close] + body
    # the new header must read back as the old one with exactly the asked changes, nothing else
    want = {k: v for k, v in head.items() if k != "metadata"}
    want_meta = dict(head.get("metadata") or {})
    for k, v in changed.items():
        if k == "description":
            want["description"] = v
        elif v:
            want_meta[k] = v
        else:
            want_meta.pop(k, None)
    want["metadata"] = want_meta
    try:
        again = meta.parse_header(result)[0]
    except Exception:  # noqa: BLE001
        again = None
    if again != want or not result.endswith(body):
        raise Refused("That header would not read back correctly. Nothing was changed.")
    return result


def keep_newlines(old: str, new: str) -> str:
    """A browser's text box gives every line ending as LF. When the person changed nothing, the old text comes
    back as it was; when the old text used CRLF throughout, the new one gets CRLF too."""
    if "\r" in new:
        return new
    if old.replace("\r\n", "\n") == new:
        return old
    if "\r\n" in old and "\n" not in old.replace("\r\n", ""):
        return new.replace("\n", "\r\n")
    return new


# ---- save -------------------------------------------------------------------------------------------------


def read_input(stream) -> dict:
    """The save's payload from stdin: at most MAX_INPUT bytes of UTF-8 JSON, no NUL."""
    raw = stream.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        raise Refused("That is too long to save here (at most 64 KB). Nothing was changed.")
    if b"\0" in raw:
        raise Refused("That text holds a character that cannot be saved. Nothing was changed.")

    def once(pairs):
        keys = [k for k, _ in pairs]
        if len(set(keys)) != len(keys):
            raise ValueError("a key twice")
        return dict(pairs)

    try:
        doc = json.loads(raw.decode("utf-8"), object_pairs_hook=once)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise Refused("That could not be read. Reload the page and try again.") from None
    if not isinstance(doc, dict) or not doc or set(doc) - {"fields", "body", "text"}:
        raise Refused("That could not be read. Reload the page and try again.")
    return doc


def _new_bytes(c: dict, current: bytes, doc: dict) -> bytes:
    text = current.decode("utf-8")
    if "text" in doc:
        if set(doc) != {"text"} or not isinstance(doc["text"], str):
            raise Refused("That could not be read. Reload the page and try again.")
        if _mode(c, current) == "skill":
            raise Refused("This skill is edited with its form. Reload the page and try again.")
        new = keep_newlines(text, doc["text"])
        if c["kind"] == "skill" and _split(new) is None:
            raise Refused("A skill starts with its --- header. Nothing was changed.")
    else:
        if _mode(c, current) != "skill" or not isinstance(doc.get("body"), str):
            raise Refused("That could not be read. Reload the page and try again.")
        if not isinstance(doc.get("fields"), dict):
            raise Refused("That could not be read. Reload the page and try again.")
        head = rewrite_header(text, doc["fields"])
        lines, _close, old_body = _split(head)
        new = "".join(lines) + keep_newlines(old_body, doc["body"])
    try:
        raw = new.encode("utf-8")
    except UnicodeEncodeError:  # a lone surrogate from a page
        raise Refused("That text holds a character that cannot be saved. Nothing was changed.") from None
    if "\0" in new:
        raise Refused("That text holds a character that cannot be saved. Nothing was changed.")
    if len(raw) > MAX_FILE:
        raise Refused("That is too long to save here. Nothing was changed.")
    return raw


def _copy_to_bin(root: Path, c: dict, current: bytes, rev: str, who: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    rel = BIN / f"{stamp}-{re.sub(r'[^A-Za-z0-9_.-]', '_', c['name'])[:60]}"
    folder = safe_path(root, rel)
    folder.mkdir(parents=True, exist_ok=False)
    safe_path(root, rel)
    name = c["rel"].name
    fd = os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(current)
        f.flush()
        os.fsync(f.fileno())
    record = {
        "schema": "orch.skills-bin/1",
        "from": c["rel"].as_posix(),
        "why": "edit",
        "revision": rev,
        "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "by": who,
    }
    (folder / "record.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if (folder / name).read_bytes() != current:
        raise Refused("The copy of the old file could not be made. Nothing was changed.")
    return folder


def save(root: Path, target: str, rev: str, doc: dict, who: str, orch_names: set[str]) -> dict:
    """Write one edit. Returns {"item": {id, name, kind}, "revision": new, "changed": bool, "copy": rel}."""
    if not REVISION.fullmatch(rev or ""):
        raise Refused("Open it again before you save.")
    with switches._locked(root):
        c = _resolve(root, target, orch_names)
        path = _regular(root, c["rel"])
        current = _readable(path) if path else None
        if current is None:
            raise Refused(f"{c['name']} cannot be edited here any more. Nothing was changed.")
        now = revision(current)
        if now != rev:
            raise Stale(now)
        new = _new_bytes(c, current, doc)
        item = {"id": c["id"], "name": c["name"], "kind": c["kind"]}
        if new == current:
            return {"item": item, "revision": now, "changed": False}
        try:
            copy = _copy_to_bin(root, c, current, now, who)
        except (OSError, Refused) as e:
            raise Refused("The copy of the old file could not be made. Nothing was changed.") from e
        mode = stat.S_IMODE(os.lstat(path).st_mode)
        fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(new)
                f.flush()
                os.fsync(f.fileno())
            with contextlib.suppress(OSError):
                os.chmod(tmp, mode)
            # an editor may have saved meanwhile (it does not take orch's lock): the newer file wins
            if _regular(root, c["rel"]) is None or path.read_bytes() != current:
                raise Stale(revision(path.read_bytes()) if _regular(root, c["rel"]) else "")
            os.replace(tmp, path)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
        return {"item": item, "revision": revision(new), "changed": True, "copy": copy.relative_to(root).as_posix()}


class Stale(Refused):
    """The file changed since the page loaded it."""

    def __init__(self, now: str):
        super().__init__(
            "This file changed since you opened it. Nothing was saved; your text is still here. "
            "Load the newer version, then make your change again."
        )
        self.now = now
