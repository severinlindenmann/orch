"""Review stack: the data side (cards, reviewed copies, the stack, decisions kept on the ticket).

A card is a question in questions[] with `card` (what the person is shown) and `shown` (a content-addressed
copy of the files it showed, plus a fingerprint). A swipe is one decision: it is stored on the question
(`decision`, with `answer` = one plain line) and goes through the same tickets functions as today's answers,
Looks good and Send back. Nothing is overwritten: a changed answer appends a new entry that `replaces`
the old one.

Pure data and rules; no server, no UI import.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from orch import history, safefile, tickets
from orch.tickets import Refused

KINDS = ("draft", "check", "link", "choice", "plan")
PREVIEW_TYPES = ("page", "img", "doc", "table", "compare", "options")
VERDICTS = ("ok", "no", "talk")
ACTIONS = ("approve", "use", "use_with_changes", "send_back", "dont", "none_of_these")
FILE_TYPES = {
    ".png": "img", ".jpg": "img", ".jpeg": "img", ".webp": "img", ".gif": "img", ".svg": "img",
    ".html": "page", ".htm": "page", ".md": "doc", ".txt": "doc", ".csv": "doc",
}  # fmt: skip
MAX_FILE = 10 * 1024 * 1024
MAX_TOTAL = 30 * 1024 * 1024
MAX_CARD_JSON = 64 * 1024
MAX_NOTE_BYTES = 8 * 1024
REVIEWED = "reviewed"
_SHA12 = re.compile(r"[0-9a-f]{12}")
_LINK = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//)")  # any scheme (https:, data:, javascript:) or //host
# control characters but newline and tab, DEL, bidi embedding/override/isolate (message.schema.json card_text)
_BAD = re.compile("[\x00-\x08\x0b-\x1f\x7f\u202a-\u202e\u2066-\u2069]")
# a file name is shown to a person: also no direction marks (U+200E, U+200F, U+061C) that spoof a name
_NAME_BAD = re.compile("[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069\u200e\u200f\u061c]")
# a plain http(s) host (no userinfo, no backslash, no %-encoding in the authority): $defs/review_card open
_OPEN = re.compile(r"https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[^\s\\]*)?")
MIMES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".html": "text/html", ".htm": "text/html",
    ".md": "text/markdown", ".txt": "text/plain", ".csv": "text/csv",
}  # fmt: skip
MAX_PHONE_CARD = 20 * 1024 * 1024  # reviewed files one card may put on the phones


class BadVerdict(Refused):
    """A verdict or note that does not fit the card (relay-api.md review_result reason `invalid`)."""


# ---------------------------------------------------------------- card checks


def _text(v, name: str, limit: int, *, required: bool = False) -> str | None:
    if v is None or v == "":
        if required:
            raise Refused(f"A card needs {name}.")
        return None
    if not isinstance(v, str) or not v.strip():
        raise Refused(f"Card {name} must be text.")
    if len(v) > limit:
        raise Refused(f"Card {name} is at most {limit} characters.")
    if _BAD.search(v):
        raise Refused(f"Card {name} has control characters.")
    return v.strip()


def _file_name(v, where: str) -> str:
    if not isinstance(v, str) or not v:
        raise Refused(f"{where}: a file name is needed.")
    if _NAME_BAD.search(v):
        raise Refused(f"{where}: a file name has control or direction characters.")
    if _LINK.match(v):
        raise Refused(f"{where}: links are not allowed in a card, only files ({v[:40]}).")
    if safefile._parts(v) is None:
        raise Refused(f"{where}: '{v[:40]}' is not a plain file path.")
    return v


_PV_KEYS = {
    "page": {"type", "src"},
    "img": {"type", "src", "alt"},
    "doc": {"type", "heading", "paras", "steps"},
    "table": {"type", "cols", "rows"},
    "compare": {"type", "note", "before", "after"},
    "options": {"type", "options"},
}
_OPT_KEYS = {"id", "title", "text", "preview"}


def _only(d: dict, allowed: set, where: str) -> None:
    """No key outside `allowed`: the wire card (message.schema.json $defs/review_card) has none either."""
    extra = [k for k in d if k not in allowed]
    if extra:
        raise Refused(f"{where}: '{str(extra[0])[:40]}' is not part of a card.")


def _drop_empty(d: dict, keys: tuple) -> None:
    for k in keys:  # an optional text given as null or "" is the same as not given
        if k in d and (d[k] is None or d[k] == ""):
            del d[k]


def _walk_preview(pv, where: str, refs: list[tuple[dict, str]], depth: int = 0) -> dict:
    """Check one preview; every file reference found is appended to refs as (dict, key)."""
    if depth > 2 or not isinstance(pv, dict):
        raise Refused(f"{where}: a preview is an object (nested at most twice).")
    t = pv.get("type")
    if t not in PREVIEW_TYPES:
        raise Refused(f"{where}: preview type must be one of {', '.join(PREVIEW_TYPES)}.")
    _only(pv, _PV_KEYS[t], where)
    _drop_empty(pv, ("alt", "heading", "note"))
    if t in ("page", "img"):
        _file_name(pv.get("src"), f"{where}.src")
        refs.append((pv, "src"))
        if t == "img":
            _text(pv.get("alt"), "alt", 200)
    elif t == "doc":
        _text(pv.get("heading"), "heading", 200)
        for key in ("paras", "steps"):
            items = pv.get(key, [])
            if not isinstance(items, list) or len(items) > 50:
                raise Refused(f"{where}.{key} is a list of at most 50 texts.")
            for it in items:
                _text(it, key, 2000, required=True)
    elif t == "table":
        cols, rows = pv.get("cols"), pv.get("rows")
        if (
            not isinstance(cols, list)
            or not cols
            or len(cols) > 12
            or not isinstance(rows, list)
            or len(rows) > 200
        ):
            raise Refused(f"{where}: a table has 1-12 cols and at most 200 rows.")
        for c in cols:
            _text(c, "column", 100, required=True)
        for r in rows:
            if not isinstance(r, list) or len(r) != len(cols):
                raise Refused(f"{where}: every table row has one cell per column.")
            for c in r:
                if not isinstance(c, str) or len(c) > 500 or _BAD.search(c):
                    raise Refused(f"{where}: a table cell is plain text of at most 500 characters.")
    elif t == "compare":
        if depth > 0:
            raise Refused(f"{where}: compare cannot be nested.")
        _text(pv.get("note"), "note", 200)
        for side in ("before", "after"):
            _walk_preview(pv.get(side), f"{where}.{side}", refs, depth + 1)
    elif t == "options":
        if depth > 0:
            raise Refused(f"{where}: options cannot be nested.")
        opts = pv.get("options")
        if not isinstance(opts, list) or not 2 <= len(opts) <= 8:
            raise Refused(f"{where}: options has 2 to 8 entries.")
        ids = set()
        for i, o in enumerate(opts):
            if (
                not isinstance(o, dict)
                or not isinstance(o.get("id"), str)
                or not re.fullmatch(r"[A-Za-z0-9]{1,8}", o["id"])
            ):
                raise Refused(f"{where}.options[{i}] needs a short id (letters/digits).")
            _only(o, _OPT_KEYS, f"{where}.options[{i}]")
            _drop_empty(o, ("text", "preview"))
            if o["id"] in ids:
                raise Refused(f"{where}: option ids must differ.")
            ids.add(o["id"])
            _text(o.get("title"), "option title", 120, required=True)
            _text(o.get("text"), "option text", 500)
            if o.get("preview") is not None:
                _walk_preview(o["preview"], f"{where}.options[{i}].preview", refs, depth + 1)
    return pv


def validate_card(card) -> dict:
    """The card as stored (a copy), or Refused with a plain reason. File references stay sources here
    (prepare_card turns them into reviewed copies)."""
    if not isinstance(card, dict):
        raise Refused("A card is an object.")
    try:
        raw = json.dumps(card, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as e:
        raise Refused("A card must be plain JSON.") from e
    if len(raw.encode("utf-8")) > MAX_CARD_JSON:
        raise Refused(f"A card is at most {MAX_CARD_JSON // 1024} KB.")
    card = json.loads(raw)
    if card.get("kind") not in KINDS:
        raise Refused(f"Card kind must be one of {', '.join(KINDS)}.")
    out: dict = {"kind": card["kind"]}
    out["title"] = _text(card.get("title"), "title", 200, required=True)
    out["why"] = _text(card.get("why"), "why", 500)
    out["need"] = _text(card.get("need"), "need", 200)
    out["then"] = _text(card.get("then"), "then (what happens next)", 500, required=True)
    out["ok_label"] = _text(card.get("ok_label"), "ok_label", 40)
    opn = _text(card.get("open"), "open", 500)
    if opn is not None:
        if not _OPEN.fullmatch(opn):
            raise Refused("Card open is a plain http(s) address (no user name, no backslash, no %).")
        out["open"] = opn
    pv = card.get("preview")
    if pv is not None:
        out["preview"] = _walk_preview(pv, "preview", [])
    elif card["kind"] in ("choice", "link"):
        raise Refused("A choice or link card needs a preview.")
    if card["kind"] == "choice" and (not pv or pv.get("type") != "options"):
        raise Refused("A choice card needs an options preview.")
    return {k: v for k, v in out.items() if v is not None}


# ---------------------------------------------------------------- reviewed copies


def _tid_dir(root: Path, tid: str) -> Path:
    tickets.load(root, tid)  # the ticket exists (and tid is a plain id)
    return root / ".orch" / "tickets" / tid


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_sources(root: Path, tid: str, files: list[str]) -> dict[str, bytes]:
    """name -> bytes. A source is a path inside the workspace, or artifacts/<name> of the ticket. Links,
    .orch/.git paths, odd types and oversize files are refused."""
    blobs: dict[str, bytes] = {}
    total = 0
    for src in files:
        _file_name(src, "file")
        name = src.rsplit("/", 1)[-1]
        ext = os.path.splitext(name)[1].lower()
        if ext not in FILE_TYPES:
            raise Refused(f"'{name}': a card shows {', '.join(sorted(FILE_TYPES))} files only.")
        try:
            if src.startswith("artifacts/"):
                data = safefile.read_ticket_file(root, tid, "artifacts", src[len("artifacts/") :], MAX_FILE)
            else:
                data = safefile.open_file_ref(root, src, MAX_FILE)
        except safefile.TooLarge:
            raise Refused(f"'{name}' is over {MAX_FILE // (1024 * 1024)} MB.") from None
        if data is None:
            raise Refused(f"'{src}' was not found, is a link, or is not allowed.")
        if name in blobs and blobs[name] != data:
            raise Refused(f"Two different files are both named '{name}'. Rename one.")
        total += len(data)
        if total > MAX_TOTAL:
            raise Refused(f"A card holds at most {MAX_TOTAL // (1024 * 1024)} MB of files.")
        blobs[name] = data
    return blobs


def _sha12(blobs: dict[str, bytes]) -> str:
    return _sha(_canon({n: _sha(b) for n, b in sorted(blobs.items())}).encode())[:12]


def _write_copy(root: Path, tid: str, blobs: dict[str, bytes], sha12: str) -> None:
    cur = _tid_dir(root, tid)
    for part in ("", REVIEWED, sha12):
        cur = cur / part if part else cur
        if cur.is_symlink() or (cur.exists() and not cur.is_dir()):
            raise Refused("The reviewed folder of this ticket is blocked by a link or a file.")
        cur.mkdir(exist_ok=True)
    for name, data in blobs.items():
        p = cur / name
        if p.is_symlink():
            raise Refused("A reviewed file is a link. orch will not use it.")
        try:
            if p.is_file() and _sha(p.read_bytes()) == _sha(data):
                continue
        except OSError:
            pass
        p.unlink(missing_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)


def _shown(blobs: dict[str, bytes], sha12: str, card: dict | None) -> dict:
    files = {n: _sha(b) for n, b in sorted(blobs.items())}
    digest = _sha(_canon({"card": card, "files": files}).encode())
    return {"digest": digest, "copy": f"{REVIEWED}/{sha12}/", "files": files}


def copy_reviewed(root: Path, tid: str, files: list[str], card: dict | None = None) -> dict:
    """Copy the source files into .orch/tickets/<tid>/reviewed/<sha12>/ (content addressed: the same files
    give the same folder) and return `shown`: {digest, copy, files{name: sha256}}. `card` (as stored) is
    part of the digest."""
    blobs = _load_sources(root, tid, files)
    sha12 = _sha12(blobs)
    _write_copy(root, tid, blobs, sha12)
    return _shown(blobs, sha12, card)


def prepare_card(root: Path, tid: str, card: dict) -> tuple[dict, dict]:
    """validate_card, copy every file the preview names, rewrite those references to
    reviewed/<sha12>/<name>. Returns (card to store, shown)."""
    card = validate_card(card)
    refs: list[tuple[dict, str]] = []
    if card.get("preview") is not None:
        _walk_preview(card["preview"], "preview", refs)
    sources = sorted({d[k] for d, k in refs})
    blobs = _load_sources(root, tid, sources)
    sha12 = _sha12(blobs)
    for d, k in refs:
        d[k] = f"{REVIEWED}/{sha12}/{d[k].rsplit('/', 1)[-1]}"
    _write_copy(root, tid, blobs, sha12)
    return card, _shown(blobs, sha12, card)


def changed_files(root: Path, tid: str, shown: dict) -> list[str]:
    """Names in shown.files whose copy is missing or no longer has the recorded hash (empty = untouched)."""
    copy = shown.get("copy") if isinstance(shown, dict) else None
    files = shown.get("files") if isinstance(shown, dict) else None
    parts = copy.split("/") if isinstance(copy, str) else []
    if (
        len(parts) < 2
        or parts[0] != REVIEWED
        or not _SHA12.fullmatch(parts[1])
        or not isinstance(files, dict)
    ):
        return ["(shown record unreadable)"]
    sha12 = parts[1]
    bad = []
    for name, want in files.items():
        try:
            data = safefile._read_parts(root, [".orch", "tickets", tid, REVIEWED, sha12], [name], MAX_FILE)
        except safefile.TooLarge:
            data = None
        if data is None or _sha(data) != want:
            bad.append(name)
    return bad


# ---------------------------------------------------------------- the card on the phone (wire shape)

_CARD_TOP = {"kind", "title", "why", "need", "then", "ok_label", "open", "preview"}
_LIMITS = {"title": 200, "why": 500, "need": 200, "then": 500, "ok_label": 40, "open": 500}
_WHY = ("too_large", "held_back")


def card_files_of(card: dict) -> list[str]:
    """The stored file references of a card (reviewed/<sha12>/<name>), each once, in the order they appear."""
    refs: list[tuple[dict, str]] = []
    if isinstance(card.get("preview"), dict):
        _walk_preview(json.loads(json.dumps(card["preview"])), "preview", refs)
    out: list[str] = []
    for d, k in refs:
        if d[k] not in out:
            out.append(d[k])
    return out


def read_reviewed(root: Path, tid: str, shown: dict, src: str) -> bytes | None:
    """The bytes of one reviewed file when they still hash to shown.files[name], else None (not sent)."""
    parts = src.split("/")
    files = shown.get("files") if isinstance(shown, dict) else None
    copy = shown.get("copy") if isinstance(shown, dict) else None
    if (
        len(parts) != 3
        or parts[0] != REVIEWED
        or not _SHA12.fullmatch(parts[1])
        or not isinstance(files, dict)
        or copy != f"{REVIEWED}/{parts[1]}/"
        or not isinstance(files.get(parts[2]), str)
    ):
        return None
    try:
        data = safefile._read_parts(root, [".orch", "tickets", tid, REVIEWED, parts[1]], [parts[2]], MAX_FILE)
    except (safefile.TooLarge, OSError, Refused):
        return None
    return data if data is not None and _sha(data) == files[parts[2]] else None


def wire_card(card: dict, refs: dict) -> dict:
    """The card as it goes to the phones (message.schema.json $defs/review_card): the stored card with every
    file reference replaced by refs[src] = an index into card_files (int), or "too_large" / "held_back"
    ({"file": null, "why": ...}); null and empty optional values left out. Checked by check_wire_card; a card
    that does not pass raises Refused (the question then goes out without `card`)."""

    def src(v):
        r = refs.get(v)
        if isinstance(r, int) and not isinstance(r, bool):
            return {"file": r}
        return {"file": None, "why": r if r in _WHY else "held_back"}

    def pv(p):
        o = {}
        for k, v in p.items():
            if v is None or v == "":
                continue
            if k == "src":
                o[k] = src(v)
            elif k in ("before", "after"):
                o[k] = pv(v)
            elif k == "preview":
                o[k] = pv(v)
            elif k == "options":
                o[k] = [pv(x) for x in v]
            else:
                o[k] = json.loads(json.dumps(v))
        return o

    out = {k: v for k, v in card.items() if k in _CARD_TOP and v is not None and v != "" and k != "preview"}
    if isinstance(card.get("preview"), dict):
        out["preview"] = pv(card["preview"])
    check_wire_card(out, 20)
    return out


def _wtext(v, where: str, limit: int, empty_ok: bool = False) -> None:
    if not isinstance(v, str) or len(v) > limit or _BAD.search(v):
        raise Refused(f"{where}: not plain text of at most {limit} characters.")
    if not v.strip() and not (empty_ok and v == ""):
        raise Refused(f"{where}: blank.")


def _wleaf(p, where: str, nfiles: int) -> None:
    if not isinstance(p, dict) or p.get("type") not in ("page", "img", "doc", "table"):
        raise Refused(f"{where}: not a leaf preview.")
    t = p["type"]
    _only(p, _PV_KEYS[t], where)
    if t in ("page", "img"):
        s = p.get("src")
        ok = isinstance(s, dict) and (
            (set(s) == {"file"} and isinstance(s["file"], int) and not isinstance(s["file"], bool)
             and 0 <= s["file"] < nfiles)
            or (set(s) == {"file", "why"} and s["file"] is None and s["why"] in _WHY)
        )  # fmt: skip
        if not ok:
            raise Refused(f"{where}.src: not a file reference.")
        if "alt" in p:
            _wtext(p["alt"], f"{where}.alt", 200)
    elif t == "doc":
        if "heading" in p:
            _wtext(p["heading"], f"{where}.heading", 200)
        for key in ("paras", "steps"):
            items = p.get(key, [])
            if not isinstance(items, list) or len(items) > 50:
                raise Refused(f"{where}.{key}: a list of at most 50 texts.")
            for it in items:
                _wtext(it, f"{where}.{key}", 2000)
    else:
        cols, rows = p.get("cols"), p.get("rows")
        if not isinstance(cols, list) or not 1 <= len(cols) <= 12 or not isinstance(rows, list):
            raise Refused(f"{where}: a table has 1-12 cols.")
        if len(rows) > 200:
            raise Refused(f"{where}: a table has at most 200 rows.")
        for c in cols:
            _wtext(c, f"{where}.cols", 100)
        for r in rows:
            if not isinstance(r, list) or len(r) != len(cols):
                raise Refused(f"{where}: every table row has one cell per column.")
            for c in r:
                _wtext(c, f"{where}.rows", 500, empty_ok=True)


def check_wire_card(card, nfiles: int) -> None:
    """message.schema.json $defs/review_card, by hand (the schema file is not shipped): Refused when the wire
    card would not pass it. nfiles = how many card_files the question carries."""
    if not isinstance(card, dict):
        raise Refused("A card is an object.")
    _only(card, _CARD_TOP, "card")
    if card.get("kind") not in KINDS:
        raise Refused("card.kind is not a kind.")
    for k in ("title", "then"):
        if k not in card:
            raise Refused(f"card.{k} is needed.")
    for k, n in _LIMITS.items():
        if k in card:
            _wtext(card[k], f"card.{k}", n)
    if "open" in card and not _OPEN.fullmatch(card["open"]):
        raise Refused("card.open is not a plain http(s) address.")
    pv = card.get("preview")
    if card["kind"] in ("choice", "link") and pv is None:
        raise Refused("A choice or link card needs a preview.")
    if card["kind"] == "choice" and not (isinstance(pv, dict) and pv.get("type") == "options"):
        raise Refused("A choice card needs an options preview.")
    if pv is not None:
        t = pv.get("type") if isinstance(pv, dict) else None
        if t == "compare":
            _only(pv, _PV_KEYS["compare"], "preview")
            if "note" in pv:
                _wtext(pv["note"], "preview.note", 200)
            for side in ("before", "after"):
                _wleaf(pv.get(side), f"preview.{side}", nfiles)
        elif t == "options":
            _only(pv, _PV_KEYS["options"], "preview")
            opts = pv.get("options")
            if not isinstance(opts, list) or not 2 <= len(opts) <= 8:
                raise Refused("preview.options has 2 to 8 entries.")
            ids = set()
            for i, o in enumerate(opts):
                w = f"preview.options[{i}]"
                if not isinstance(o, dict) or not re.fullmatch(r"[A-Za-z0-9]{1,8}", str(o.get("id"))):
                    raise Refused(f"{w} needs a short id.")
                _only(o, _OPT_KEYS, w)
                if o["id"] in ids:
                    raise Refused("preview: option ids must differ.")
                ids.add(o["id"])
                _wtext(o.get("title"), f"{w}.title", 120)
                if "text" in o:
                    _wtext(o["text"], f"{w}.text", 500)
                if "preview" in o:
                    _wleaf(o["preview"], f"{w}.preview", nfiles)
        else:
            _wleaf(pv, "preview", nfiles)
    try:
        raw = json.dumps(card, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as e:
        raise Refused("A card must be plain JSON.") from e
    if len(raw.encode("utf-8")) > MAX_CARD_JSON:
        raise Refused(f"A card is at most {MAX_CARD_JSON // 1024} KB.")


# ---------------------------------------------------------------- decisions


def _clip(s: str, n: int) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _note(note) -> dict:
    """The person's own words: {changes:[str], words:{text}, pins:[{n,on,x,y,text}]}; JSON text or a dict."""
    if note in (None, ""):
        return {"changes": [], "words": {"text": "", "voice": []}, "pins": []}
    if isinstance(note, str):
        if len(note.encode("utf-8")) > MAX_NOTE_BYTES:
            raise BadVerdict("A note is at most 8 KB.")
        try:
            note = json.loads(note)
        except ValueError as e:
            raise BadVerdict("A note must be JSON.") from e
    if not isinstance(note, dict):
        raise BadVerdict("A note must be an object.")
    if isinstance(note.get("text"), str) and note["text"].strip():  # the kit page's shape: {text, pins}
        note = dict(note)
        text = note.pop("text")
        words = dict(note.get("words") or {}) if isinstance(note.get("words"), dict) else None
        if words is not None:
            words.setdefault("text", text)
            note["words"] = words
        elif not note.get("words"):
            note["words"] = {"text": text}
        if not note.get("changes"):
            note["changes"] = [text]
    if len(_canon(note).encode("utf-8")) > MAX_NOTE_BYTES:
        raise BadVerdict("A note is at most 8 KB.")
    changes = note.get("changes") or []
    if not isinstance(changes, list) or len(changes) > 20:
        raise BadVerdict("A note has at most 20 changes.")
    changes = [_text(c, "change", 500, required=True) for c in changes]
    words = note.get("words") or {}
    if not isinstance(words, dict):
        raise BadVerdict("Note words must be an object.")
    wtext = _text(words.get("text"), "words", 2000) or ""
    voice = words.get("voice") or []
    if not isinstance(voice, list) or len(voice) > 10 or not all(isinstance(v, dict) for v in voice):
        raise BadVerdict("Note voice is a list of at most 10 recordings.")
    pins = note.get("pins") or []
    if not isinstance(pins, list) or len(pins) > 30:
        raise BadVerdict("A note has at most 30 pins.")
    clean_pins = []
    for p in pins:
        if not isinstance(p, dict) or not isinstance(p.get("n"), int):
            raise BadVerdict("A pin needs a number n.")
        clean_pins.append(
            {
                "n": p["n"],
                "on": _text(p.get("on"), "pin target", 120) or "",
                "x": p.get("x") if isinstance(p.get("x"), (int, float)) else None,
                "y": p.get("y") if isinstance(p.get("y"), (int, float)) else None,
                "text": _text(p.get("text"), "pin text", 500) or "",
            }
        )
    return {"changes": changes, "words": {"text": wtext, "voice": voice}, "pins": clean_pins}


def _note_bv(note) -> dict:
    try:
        return _note(note)
    except BadVerdict:
        raise
    except Refused as e:  # any text the person's note holds that a card text may not
        raise BadVerdict(str(e)) from e


def _bare(action: str, allows, changes: list[str], n: dict) -> dict:
    return {
        "action": action, "picked": None, "allows": allows, "changes": changes, "words": n["words"],
        "pins": n["pins"], "replaces": None, "replaced_by": None,
    }  # fmt: skip


def _what_changes(n: dict) -> list[str]:
    if n["changes"]:
        return list(n["changes"])
    return [n["words"]["text"]] if n["words"]["text"] else []


def summary(decision: dict, card: dict | None = None) -> str:
    """One plain line for a decision, e.g. "Use C with 2 changes: questions on top; month in the heading."."""
    card = card or {}
    act, picked = decision.get("action"), decision.get("picked")
    changes = [_clip(c, 80).rstrip(".") for c in decision.get("changes") or []]
    tail = "; ".join(changes)
    if act == "approve":
        line = card.get("ok_label") or "Approved"
    elif act == "use":
        line = f"Use {picked}"
    elif act == "use_with_changes":
        n = len(changes)
        line = f"Use {picked} with {n} change{'' if n == 1 else 's'}: {tail}"
    elif act == "send_back":
        line = f"Send back for changes: {tail}" if tail else "Send back for changes"
    elif act == "dont":
        line = "Don't do"
    elif act == "none_of_these":
        line = "None of these"
    else:
        raise Refused(f"Unknown decision action {act!r}.")
    line = _clip(line, 400).rstrip(".")
    return line + ("." if act in ("use_with_changes", "send_back") and tail else "")


def _card_of(q: dict) -> dict:
    """The card of a question; a plain question gets a plain options card."""
    if isinstance(q.get("card"), dict):
        return q["card"]
    return {
        "kind": "choice" if q.get("options") else "draft",
        "title": q.get("text", ""),
        "preview": {"type": "options", "options": [{"id": o, "title": o} for o in q.get("options") or []]}
        if q.get("options")
        else None,
    }


def _option_ids(q: dict, card: dict) -> list[str]:
    pv = card.get("preview") or {}
    if card.get("kind") == "choice" and pv.get("type") == "options":
        return [o["id"] for o in pv.get("options", [])]
    return list(q.get("options") or [])


def _decision(q: dict, card: dict, verdict: str, picked, note) -> dict:
    if verdict not in VERDICTS:
        raise BadVerdict(f"verdict is one of {', '.join(VERDICTS)}.")
    n = _note_bv(note)
    ids = _option_ids(q, card)
    choose = bool(ids)
    if picked is not None and picked not in ids:
        raise BadVerdict(f"'{picked}' is not one of the options.")
    changes = _what_changes(n)
    if verdict == "ok":
        if choose and picked is None:
            raise BadVerdict("Pick one of the options.")
        action = "use" if choose else "approve"
        changes = []
    elif verdict == "no":
        action, picked, changes = ("none_of_these" if choose else "dont"), None, []
    else:  # talk: words never approve by themselves; a picked option with changes is "use with changes"
        if not changes and not n["pins"]:
            raise BadVerdict("Say what should change.")
        action = "use_with_changes" if picked is not None else "send_back"
    d = {
        "action": action,
        "picked": picked,
        "allows": card.get("ok_label") if action in ("approve", "use") else None,
        "changes": changes,
        "words": n["words"],
        "pins": n["pins"],
        "replaces": None,
        "replaced_by": None,
    }
    d["summary"] = summary(d, card)
    return d


def _plain_answer(q: dict, d: dict) -> str:
    """A card-less question keeps the plain answer older readers expect: the chosen option itself."""
    if "card" not in q and d["action"] == "use" and not d["changes"]:
        return d["picked"]
    return d["summary"]


def _find(ticket: dict, qid: str) -> dict:
    q = next((x for x in ticket["questions"] if x["id"] == qid), None)
    if q is None:
        raise Refused(f"Ticket {ticket['id']} has no question {qid}.")
    return q


def check_digest(ticket: dict) -> str:
    """What a person is shown of a Check result: exactly check_card(ticket) (title, steps with their done and
    won't-do state), for this ticket id and status. New with Review cards: no stored older value."""
    shown = {"id": ticket["id"], "status": ticket.get("status"), "card": check_card(ticket)}
    return _sha(_canon(shown).encode())


def check_card(ticket: dict) -> dict:
    items = [
        f"{'Done' if c.get('done') or c.get('wont_do') else 'Open'}: {c.get('text', '')}"
        for c in ticket.get("checklist", [])
    ]
    card = {
        "kind": "check",
        "title": ticket.get("title", ticket["id"]),
        "why": "The helper says this is ready for your check.",
        "then": "The ticket is done.",
        "ok_label": "Looks good",
    }
    if items:
        card["preview"] = {"type": "doc", "heading": "Steps", "steps": [_clip(i, 300) for i in items[:50]]}
    return card


def decide(
    root: Path,
    tid: str,
    key: str,
    verdict: str,
    picked: str | None = None,
    note=None,
    *,
    by: str,
    via: str,
    digest: str | None = None,
    phone: str | None = None,
    pid: str | None = None,
) -> dict:
    """One swipe. key is a question id (q3) or "review" (a ticket in Review). Returns the decision entry
    (the answered question). The person's own checks (human: author, not an agent) stay in tickets."""
    ticket = tickets.load(root, tid)
    if key == "review":
        if picked is not None:
            raise BadVerdict("A Check result has no options to pick.")
        return _decide_check(root, ticket, verdict, note, by, via, digest, phone, pid)
    q = _find(ticket, key)
    tickets.refuse_if_taken_back(q)
    if q.get("answer") is not None:
        raise Refused(f"{key} is already answered. Use change to answer again.")
    card = _card_of(q)
    d = _decision(q, card, verdict, picked, note)
    if digest is not None and tickets.question_digest(q) != digest:  # before a merge, not only at the write
        raise Refused(f"{key} changed after it was shown. Look at the question again, then answer.")
    _merge_first(root, tid, q, d, by, via)
    _, out = tickets.answer(
        root, tid, key, _plain_answer(q, d), by, via, expected_question_digest=digest, decision=d
    )
    return out


def merge_url(q: dict) -> str | None:
    """The pull request a merge card merges on the Merge click (`orch ask ... --merge`), else None."""
    act, card = q.get("action"), q.get("card")
    url = act.get("merge") if isinstance(act, dict) else None
    if not isinstance(url, str) or not isinstance(card, dict):
        return None
    # only the card --merge built: a link card that shows exactly this address on a Merge button
    if card.get("kind") != "link" or card.get("open") != url or card.get("ok_label") != "Merge":
        return None
    return url


def _merge_first(root: Path, tid: str, q: dict, d: dict, by: str, via: str) -> None:
    """A merge card approved: merge the pull request BEFORE the answer is saved, so a refused merge saves
    nothing and the person can click again. Only a person's click merges: a human actor and no agent tool in
    the environment, or an answer from a paired phone (the relay checked the phone; whoever reads the inbox
    applies it). The merge uses the person's own GitHub login (ghmerge drops helper tokens)."""
    url = merge_url(q)
    if url is None or d.get("action") != "approve":
        return
    if not (by.startswith("human:") and (via == "phone" or not tickets.agent_tool())):
        raise Refused("Only a person merges this. Ask the human to click Merge on the card.")
    from orch import ghmerge

    got = ghmerge.merge(url)
    line = (
        f"The pull request was merged already on GitHub ({got['login']}): {url}"
        if got["already"]
        else f"Merged the pull request on GitHub as {got['login']}: {url}"
    )
    import contextlib

    with contextlib.suppress(Refused, OSError):  # merged; the answer itself is written next
        tickets.note_history(root, tid, by, line, via)


def _decide_check(
    root: Path,
    ticket: dict,
    verdict: str,
    note,
    by: str,
    via: str,
    digest: str | None,
    phone: str | None = None,
    pid: str | None = None,
) -> dict:
    tid = ticket["id"]
    if not by.startswith("human:"):  # a verdict on a Check result is a person's (label check)
        raise Refused("Only a person can decide this. Ask the human to do it themselves.")
    if verdict not in VERDICTS:
        raise Refused(f"verdict is one of {', '.join(VERDICTS)}.")
    if ticket.get("status") != "review":
        raise Refused("This ticket is not waiting for your review.")
    if digest is not None and digest != check_digest(ticket):
        raise Refused("This result changed after it was shown. Look at it again, then answer.")
    card = check_card(ticket)
    n = _note_bv(note)
    if verdict == "ok":
        d = _bare("approve", card["ok_label"], [], n)
        tickets.accept_review(root, tid, by, via)
    else:
        changes = _what_changes(n)
        if not changes:
            raise BadVerdict("Say what should change.")
        d = _bare("send_back", None, changes, n)
        tickets.ask_for_changes(root, tid, "; ".join(changes), by, via=via, phone=phone, pid=pid)
    d["summary"] = summary(d, card)
    entry = {
        "text": _clip("Check: " + ticket.get("title", tid), 300),
        "options": [],
        "recommended": None,
        "answer": d["summary"],
        "card": card,
        "decision": d,
    }
    return tickets.record_answered(root, tid, entry, by, via)


def change(
    root: Path,
    tid: str,
    qid: str,
    verdict: str,
    picked: str | None = None,
    note=None,
    *,
    by: str,
    via: str,
    digest: str | None = None,
) -> dict:
    """Answer an answered card again: a NEW entry (same card and shown) with decision.replaces = qid; the old
    entry only gets decision.replaced_by. Nothing is overwritten."""
    ticket = tickets.load(root, tid)
    old = _find(ticket, qid)
    tickets.refuse_if_taken_back(old)
    if old.get("answer") is None:
        raise Refused(f"{qid} is not answered yet. Answer it first.")
    if (old.get("card") or {}).get("kind") == "check":
        raise Refused("A Check result is final. Reopen the ticket to look at it again.")
    if digest is not None and tickets.question_digest(old) != digest:
        raise Refused(f"{qid} changed after it was shown. Look at the question again, then answer.")
    card = _card_of(old)
    d = _decision(old, card, verdict, picked, note)
    if merge_url(old) and (old.get("decision") or {}).get("action") == "approve":
        raise Refused(f"{qid} was merged on GitHub. That cannot be taken back here.")
    _merge_first(root, tid, old, d, by, via)
    d["replaces"] = qid
    entry = {
        k: old[k]
        for k in ("text", "options", "recommended", "kind", "action", "check", "card", "shown")
        if old.get(k) is not None or k in ("options", "recommended")
    }
    entry["answer"] = _plain_answer(old, d)
    entry["decision"] = d
    return tickets.record_answered(root, tid, entry, by, via, replaces=qid)


# ---------------------------------------------------------------- the stack


ABOUT_MAX = 120


def stack(root: Path) -> list[dict]:
    """Everything waiting for a person's swipe: card questions, plain open questions (as options cards) and
    tickets in Review (as Check cards), grouped by ticket (the round whose oldest card waited longest first),
    then by the task a question belongs to (`orch ask --check`), then oldest first. Each item:
    {id, ticket, ticket_key, ticket_title, key, kind, card, digest, since, options, recommended} and, when the
    question belongs to a task, `about` (its text, one line) and `task` (its id). Neither is part of the card
    or its digest."""
    from orch import needs  # needs imports tickets; no cycle back

    out = []
    order = {}  # ticket id -> {task id: position in its checklist}
    for t in history.shown_json(root, tickets.list_all(root)):
        if t.get("general") is True or not isinstance(t.get("id"), str):
            continue
        base = {"ticket": t["id"], "ticket_key": t.get("key"), "ticket_title": t.get("title", t["id"])}
        tasks = {
            c.get("id"): (i, c.get("text"))
            for i, c in enumerate(t.get("checklist") or [])
            if isinstance(c, dict)
        }
        order[t["id"]] = {k: v[0] for k, v in tasks.items()}
        if t.get("status") not in needs.OPEN:
            for q in t.get("questions") or []:
                if q.get("answer") is not None or q.get("kind") not in (None, "plain"):
                    continue  # an add-on's own question is its business
                card = q["card"] if isinstance(q.get("card"), dict) else _card_of(q)
                task = tasks.get(q.get("check"))
                about = _clip(task[1], ABOUT_MAX) if task and isinstance(task[1], str) else ""
                out.append(
                    {
                        **base,
                        **({"about": about, "task": q["check"]} if about else {}),
                        "id": f"core:q:{t['id']}:{q['id']}",
                        "key": q["id"],
                        "kind": card.get("kind"),
                        "card": card,
                        "digest": tickets.question_digest(q),
                        "since": needs._asked_at(root, t, q["id"]),
                        "options": list(q.get("options") or []),
                        "recommended": q.get("recommended"),
                    }
                )
        if t.get("status") == "review":
            hist = [h for h in history.lines(root, t) if isinstance(h, dict) and h.get("at")]
            out.append(
                {
                    **base,
                    "id": f"core:review:{t['id']}",
                    "key": "review",
                    "kind": "check",
                    "card": check_card(t),
                    "digest": check_digest(t),
                    "since": hist[-1]["at"] if hist else t.get("updated_at") or t.get("created_at"),
                    "options": [],
                    "recommended": None,
                }
            )
    # grouped: the ticket (round) with the longest-waiting card first, then its tasks in checklist order,
    # cards without a task last; inside a group oldest first
    oldest: dict[str, str] = {}
    for r in out:
        oldest[r["ticket"]] = min(oldest.get(r["ticket"], r["since"] or ""), r["since"] or "")
    out.sort(
        key=lambda r: (
            oldest[r["ticket"]],
            r["ticket"],
            order[r["ticket"]].get(r["task"], 1 << 20) if r.get("task") else 1 << 30,
            r["since"] or "",
            r["id"],
        )
    )
    return out


# ---------------------------------------------------------------- what a helper reads


def _when(at: str | None) -> str:
    return re.sub(r":\d\d(?:Z|[+-]\d\d:\d\d)?$", "", (at or "").replace("T", " ")) if at else ""


def _option_title(card: dict, picked: str | None) -> str:
    for o in (card.get("preview") or {}).get("options", []) or []:
        if o.get("id") == picked:
            return o.get("title", "")
    return ""


def applies_now_block(ticket: dict, root: Path | None = None) -> str:
    """Plain text for helpers: what applies now (the current instruction first). The answers themselves are
    listed under the ticket's questions. "" when nothing was decided
    with a card or a decision. With `root` the ticket is read as shown here (history.shown_ticket: a synced
    answer nobody verified shows as synced); without it the caller passes a ticket that is already shown."""
    if root is not None:
        ticket = history.shown_ticket(root, ticket)
    entries = [
        q
        for q in ticket.get("questions", [])
        if isinstance(q.get("decision"), dict) and q.get("answer") is not None
    ]
    if not entries:
        return ""
    label = ticket.get("key") or ticket["id"]
    lines = [f"What applies now ({label})"]
    cur = next((q for q in reversed(entries) if not q["decision"].get("replaced_by")), None)
    if cur is None:
        lines.append("Nothing applies now (every answer was replaced).")
    else:
        d, card = cur["decision"], cur.get("card") or {}
        picked = d.get("picked")
        opt = (
            f"option {picked} ({_option_title(card, picked)})"
            if picked and _option_title(card, picked)
            else f"option {picked}"
        )
        n = len(d.get("changes") or [])
        head = {
            "approve": f"{card.get('ok_label') or 'Approved'}.",
            "use": f"Use {opt}.",
            "use_with_changes": f"Use {opt} WITH {n} CHANGE{'' if n == 1 else 'S'}.",
            "send_back": "Sent back for changes.",
            "dont": "Do not do this.",
            "none_of_these": "None of the options.",
        }.get(d.get("action"), d.get("summary", ""))
        then = card.get("then")
        lines.append(
            f"{head}{' ' + then if then and d.get('action') not in ('dont', 'none_of_these') else ''}"
        )
        for i, c in enumerate(d.get("changes") or [], 1):
            lines.append(f"  {i}. {c}")
        for p in d.get("pins") or []:
            lines.append(f"  pin {p.get('n')} on {p.get('on')}: {p.get('text')}")
        words = (d.get("words") or {}).get("text")
        if words and not d.get("changes"):
            lines.append(f"  In their words: {words}")
        if card.get("kind") == "link" and d.get("action") == "approve":
            lines.append(f"Not allowed by this answer: anything outside {label}.")
        else:
            lines.append(f"Not allowed by this answer: publishing, sending, anything outside {label}.")
    return "\n".join(lines) + "\n"
