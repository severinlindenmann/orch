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

from orch import cardkinds, history, ownerpick, safefile, tickets
from orch.tickets import Refused

KINDS = ("draft", "check", "link", "choice", "plan", "run")
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
    "options": {"type", "options", "before"},
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


# A doc box may carry a little structure (ORCH-183, a merge card): a status line with a tone, rows with a
# short key and a number, and a small footer. The phone gets them as plain paras and steps (wire_card), so
# its schema stays unchanged.
# Glance formats (ORCH-329): headline (one sentence), progress {done, total}, chips [{text, tone}], flow
# (up to 6 short boxes), chart {unit?, bars: [{label, value}]}, diff [{op: + or -, text}], details (long text
# kept behind a click). They are plain data for the card; the phone gets them as paras and steps too.
DOC_EXTRA = {"status", "rows", "foot", "headline", "progress", "chips", "flow", "chart", "diff", "details"}
STATUS_TONES = ("done", "working", "failed")
CHIP_TONES = ("ok", "warn", "bad", "info")


def _glance(pv: dict, where: str) -> None:
    if "headline" in pv:
        _text(pv["headline"], "headline", 200, required=True)
    pr = pv.get("progress")
    if pr is not None and (
        not isinstance(pr, dict)
        or set(pr) != {"done", "total"}
        or not all(isinstance(pr[k], int) and not isinstance(pr[k], bool) and 0 <= pr[k] <= 1000 for k in pr)
        or pr["done"] > pr["total"]
    ):
        raise Refused(f"{where}.progress is {{done, total}} with done at most total.")
    chips = pv.get("chips", [])
    if not isinstance(chips, list) or len(chips) > 8:
        raise Refused(f"{where}.chips is a list of at most 8 chips.")
    for c in chips:
        if not isinstance(c, dict) or set(c) - {"text", "tone"} or c.get("tone", "info") not in CHIP_TONES:
            raise Refused(f"{where}.chips: each chip is {{text, tone: {'|'.join(CHIP_TONES)}}}.")
        _text(c.get("text"), "chips.text", 60, required=True)
    flow = pv.get("flow", [])
    if not isinstance(flow, list) or len(flow) > 6:
        raise Refused(f"{where}.flow is a list of at most 6 short boxes.")
    for f in flow:
        _text(f, "flow", 40, required=True)
    ch = pv.get("chart")
    if ch is not None:
        bars = ch.get("bars") if isinstance(ch, dict) and set(ch) <= {"unit", "bars"} else None
        if not isinstance(bars, list) or not 1 <= len(bars) <= 12:
            raise Refused(f"{where}.chart is {{unit?, bars: 1-12 of {{label, value}}}}.")
        for b in bars:
            ok = isinstance(b, dict) and set(b) == {"label", "value"}
            if not ok or isinstance(b["value"], bool) or not isinstance(b["value"], (int, float)):
                raise Refused(f"{where}.chart: each bar is {{label, value}} with a number.")
            _text(b["label"], "chart.label", 40, required=True)
        if "unit" in ch:
            _text(ch["unit"], "chart.unit", 20, required=True)
    diff = pv.get("diff", [])
    if not isinstance(diff, list) or len(diff) > 30:
        raise Refused(f"{where}.diff is a list of at most 30 lines.")
    for d in diff:  # ORCH-429: file (a name shown above its lines) and risk (why the line is marked red)
        ok = isinstance(d, dict) and {"op", "text"} <= set(d) <= {"op", "text", "file", "risk"}
        if not ok or d["op"] not in ("+", "-"):
            raise Refused(f"{where}.diff: each line is {{op: + or -, text, file?, risk?}}.")
        _text(d["text"], "diff.text", 200, required=True)
        if "file" in d:
            _text(d["file"], "diff.file", 120, required=True)
        if "risk" in d:
            _text(d["risk"], "diff.risk", 60, required=True)
    det = pv.get("details", [])
    if not isinstance(det, list) or len(det) > 50:
        raise Refused(f"{where}.details is a list of at most 50 texts.")
    for t in det:
        _text(t, "details", 2000, required=True)


def _doc_extra(pv: dict, where: str) -> None:
    st = pv.get("status")
    if st is not None:
        if not isinstance(st, dict) or set(st) != {"tone", "text"} or st["tone"] not in STATUS_TONES:
            raise Refused(f"{where}.status is {{tone: {'|'.join(STATUS_TONES)}, text}}.")
        _text(st["text"], "status", 200, required=True)
    _glance(pv, where)
    rows = pv.get("rows", [])
    if not isinstance(rows, list) or len(rows) > 50:
        raise Refused(f"{where}.rows is a list of at most 50 rows.")
    for r in rows:
        if not isinstance(r, dict) or not set(r) <= {"title", "key", "n"} or "title" not in r:
            raise Refused(f"{where}.rows: each row is {{title, key?, n?}}.")
        _text(r["title"], "rows.title", 300, required=True)
        if "key" in r:
            _text(r["key"], "rows.key", 20, required=True)
        if "n" in r and (not isinstance(r["n"], int) or isinstance(r["n"], bool) or not 0 < r["n"] < 10**9):
            raise Refused(f"{where}.rows: n is a positive number.")
    if "foot" in pv:
        _text(pv["foot"], "foot", 200, required=True)


def _plain_doc(p: dict) -> dict:
    """A doc box with status, rows or foot as the phone schema knows it: those become paras and steps."""
    if not DOC_EXTRA & set(p):
        return p
    q = {k: v for k, v in p.items() if k not in DOC_EXTRA}
    paras = [p["status"]["text"]] if isinstance(p.get("status"), dict) else []
    paras += [p["headline"]] if p.get("headline") else []
    pr = p.get("progress")
    paras += [f"{pr['done']} of {pr['total']} steps done"] if isinstance(pr, dict) else []
    paras += [", ".join(c["text"] for c in p.get("chips") or [])] if p.get("chips") else []
    paras += [" → ".join(p["flow"])] if p.get("flow") else []
    paras += list(p.get("paras") or [])
    rows = [
        r["title"] + (f" (#{r['n']}" + (f", {r['key']}" if r.get("key") else "") + ")" if r.get("n") else "")
        for r in p.get("rows") or []
    ]
    rows += [
        f"{b['label']}: {b['value']}{(p['chart'].get('unit') or '')}"
        for b in (p.get("chart") or {}).get("bars", [])
    ]
    last = None
    for d in p.get("diff") or []:  # the phone: a file's name before its lines, a marked line says why
        if d.get("file") and d["file"] != last:
            rows.append(d["file"])
        last = d.get("file") or last
        rows.append(f"{d['op']} {d['text']}" + (f"  (look: {d['risk']})" if d.get("risk") else ""))
    paras += [p["foot"]] if p.get("foot") else []
    paras += list(p.get("details") or [])
    if paras:
        q["paras"] = paras[:50]
    if rows or p.get("steps"):
        q["steps"] = (rows + list(p.get("steps") or []))[:50]
    return q


def _walk_preview(pv, where: str, refs: list[tuple[dict, str]], depth: int = 0) -> dict:
    """Check one preview; every file reference found is appended to refs as (dict, key)."""
    if depth > 2 or not isinstance(pv, dict):
        raise Refused(f"{where}: a preview is an object (nested at most twice).")
    t = pv.get("type")
    if t not in PREVIEW_TYPES:
        raise Refused(f"{where}: preview type must be one of {', '.join(PREVIEW_TYPES)}.")
    _only(pv, _PV_KEYS[t] | (DOC_EXTRA if t == "doc" else set()), where)
    _drop_empty(pv, ("alt", "heading", "note", "foot"))
    if t in ("page", "img"):
        _file_name(pv.get("src"), f"{where}.src")
        refs.append((pv, "src"))
        if t == "img":
            _text(pv.get("alt"), "alt", 200)
    elif t == "doc":
        _text(pv.get("heading"), "heading", 200)
        _doc_extra(pv, where)
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
        if pv.get("before") is not None:  # how it is today, shown beside the options (not one to pick)
            _walk_preview(pv["before"], f"{where}.before", refs, depth + 1)
    return pv


def is_plain_url(url) -> bool:
    """A plain http(s) address (the same rule as a card's open)."""
    return isinstance(url, str) and len(url) <= 500 and bool(_OPEN.fullmatch(url))


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
    if card["kind"] == "run":  # ORCH-848: the command, as orch parsed it (runcard.check_spec at run time)
        if not isinstance(card.get("run"), dict):
            raise Refused("A run card needs its command (orch ask --run).")
        from orch import runcard

        out["run"] = card["run"]
        no = card.get("no_label", "Not now")
        if no not in runcard.NO_LABELS:  # orch's own words only: never a look-alike of "I ran it"
            raise Refused("A run card's other answer is one of: " + ", ".join(runcard.NO_LABELS) + ".")
        out["no_label"] = no
    elif card.get("run") is not None:
        raise Refused("Only a run card carries a command.")
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
# A run card on the wire (ORCH-860, $defs/card_run): what the phone shows, never what runs (no folder or argv)
_RUN_KEYS = {"command", "class", "changes", "undo", "phone"}
_RUN_CLASSES = ("orch", "other", "login", "copy")
_RUN_NO = (
    "Not now",
    "Leave it off for now",
    "Leave it as it is",
    "Skip it",
    "Do it later",
)  # runcard.NO_LABELS
# printable ASCII only, no shell operator (runcard._SHELL): a search for a bad character, not anchored
_RUN_CMD_BAD = re.compile(r"[^ -~]|[;|&<>`$\\]")
_RUN_OK = "I ran it"  # runcard.OK_LABEL: a run card's yes is orch's own words, never a look-alike of its no
_LIMITS = {"title": 200, "why": 500, "need": 200, "then": 500, "ok_label": 40, "open": 500}
_WHY = ("too_large", "held_back")


def card_files_of(card: dict) -> list[str]:
    """The stored file references of a card (reviewed/<sha12>/<name>), each once, in the order they appear."""
    refs: list[tuple[dict, str]] = []
    if isinstance(card.get("preview"), dict):
        pv = json.loads(json.dumps(card["preview"]))
        if pv.get("type") == "options":
            pv.pop("before", None)  # not on the phone's card (wire_card)
        _walk_preview(pv, "preview", refs)
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
        if p.get("type") == "doc":
            p = _plain_doc(p)
        o = {}
        for k, v in p.items():
            if v is None or v == "" or (k == "before" and p.get("type") == "options"):
                continue  # the phone shows a choice's options only (its card has no Today picture yet)
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
    if card.get("kind") == "run":  # ORCH-860: the command as the phone shows it; runcard decides what runs
        out.update(_wire_run(card))
    if isinstance(card.get("blocked"), str) and card["blocked"]:  # ORCH-548: the phone's card says why, too
        out["then"] = _clip("Looks good is off: " + card["blocked"], _LIMITS["then"])
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


def _wire_run(card: dict) -> dict:
    """A run card's `run` and `no_label` for the phone ($defs/card_run). The spec's folder, argv, program and
    operation stay on this computer. `phone` is True only when runcard says a paired phone may run it."""
    spec = card.get("run") if isinstance(card.get("run"), dict) else {}
    phone = False
    try:
        from orch import runcard

        phone = bool(getattr(runcard, "phone_ok", lambda q: False)({"card": card}))
    except ImportError:
        pass
    run = {
        k: spec[k]
        for k in ("command", "class", "changes", "undo")
        if isinstance(spec.get(k), str) and spec[k]
    }
    run["phone"] = phone and spec.get("class") == "orch"
    return {"run": run, "no_label": card.get("no_label", "Not now")}


def _check_wire_run(card: dict) -> None:
    run = card.get("run")
    if card.get("kind") != "run":
        if "run" in card or "no_label" in card:
            raise Refused("Only a run card carries a command.")
        return
    if not isinstance(run, dict):
        raise Refused("A run card needs its command.")
    _only(run, _RUN_KEYS, "card.run")
    cmd = run.get("command")
    if not isinstance(cmd, str) or not cmd.strip() or len(cmd) > 300 or _RUN_CMD_BAD.search(cmd):
        raise Refused("card.run.command: one line of plain ASCII, at most 300 characters, no shell operator.")
    if run.get("class") not in _RUN_CLASSES:
        raise Refused("card.run.class is not a class.")
    if not isinstance(run.get("phone"), bool):
        raise Refused("card.run.phone is true or false.")
    if run["phone"] and run["class"] != "orch":
        raise Refused("Only orch's own commands run from the phone.")
    for k, n in (("changes", 200), ("undo", 300)):
        if k in run:
            _wtext(run[k], f"card.run.{k}", n)
    if card.get("ok_label", _RUN_OK) != _RUN_OK:
        raise Refused("A run card's yes is I ran it.")
    if card.get("no_label") not in _RUN_NO:
        raise Refused("A run card's other answer is one of orch's own words.")


def check_wire_card(card, nfiles: int) -> None:
    """message.schema.json $defs/review_card, by hand (the schema file is not shipped): Refused when the wire
    card would not pass it. nfiles = how many card_files the question carries."""
    if not isinstance(card, dict):
        raise Refused("A card is an object.")
    _only(card, _CARD_TOP | {"run", "no_label"}, "card")
    if card.get("kind") not in (*KINDS, "run"):
        raise Refused("card.kind is not a kind.")
    _check_wire_run(card)
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
    # the person's own words in full (each change is at most 500 characters): the answer and the run input
    # are what a helper reads, so a cut-off change loses what was asked (#1174, #1775)
    changes = [" ".join(str(c).split()).rstrip(".") for c in decision.get("changes") or []]
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
    line = (line if tail else _clip(line, 400)).rstrip(".")
    return line + ("." if act in ("use_with_changes", "send_back") and tail else "")


def _card_of(q: dict) -> dict:
    """The card of a question; a plain question gets a plain options card."""
    if isinstance(q.get("card"), dict):
        return q["card"]
    if isinstance(q.get("ideas"), list):  # ORCH-2186: a page that cannot sort them shows the ideas as a list
        steps = list(q["ideas"])
        return {"kind": "draft", "title": q.get("text", ""), "preview": {"type": "doc", "steps": steps}}
    return {
        "kind": "choice" if q.get("options") else "draft",
        "title": q.get("text", ""),
        "preview": {"type": "options", "options": [{"id": o, "title": o} for o in q.get("options") or []]}
        if q.get("options")
        else None,
    }


# ORCH-1847: what a one-tap answer never covers. Away mode's own lists (autoreview.AWAY_STAYS), except words
# or names (the person picks those themselves), plus starting; a hit keeps the pick-then-confirm card.
ONE_TAP_KEEPS = ("money", "production", "cannot be undone", "logins or keys", "outside-visible",
                 "a go-ahead without the steps")  # fmt: skip
ONE_TAP_STARTS = re.compile(
    r"(start\w*|launch\w*|kick\w*\s?off|begin\w*|run|runs|running)(?![a-z0-9_])", re.I
)
ONE_TAP_OPTIONS = (2, 4)
ONE_TAP_OPTION_MAX = 60


def one_tap(ticket: dict, q: dict) -> bool:
    """A plain, reversible, single-choice question: Review answers it with one tap on the named answer, as
    Home does (ORCH-1847). Only a plain `orch ask --option` question (no card, no add-on kind, no action, no
    phone scope) with two to four short options whose words name no money, sending out, deleting or merging,
    keys or starting. Fails safe: anything else keeps tap an option, then Use it."""
    from orch import autoreview  # autoreview imports runs, which imports review lazily

    if ticket.get("general") is True or "card" in q or q.get("kind") not in (None, "plain"):
        return False
    if q.get("action") is not None or q.get("scope") is not None:
        return False
    opts = q.get("options") or []
    lo, hi = ONE_TAP_OPTIONS
    if not lo <= len(opts) <= hi or len(set(opts)) != len(opts):
        return False
    if any(not isinstance(o, str) or not o.strip() or len(o) > ONE_TAP_OPTION_MAX for o in opts):
        return False
    words = " ".join([str(q.get("text") or ""), str(q.get("because") or ""), *opts])
    if any(k in ONE_TAP_KEEPS for k in autoreview._away_hits(words)):
        return False
    return not ONE_TAP_STARTS.search(autoreview.GAPS.sub(" ", words))


def _with_plan(card: dict, q: dict, ticket: dict, all_tickets: list[dict]) -> dict:
    """The "Plan ready" question of a Show-plan-first ticket is a plain options card; show the plan on it
    (goal, what is not included, the steps) so the person can decide from the card alone. Render only: the
    question and its digest stay as they are."""
    from orch import runs  # runs imports review lazily; no cycle at call time

    if not str(q.get("text", "")).startswith(runs.PLAN_READY):
        return card
    plan = ticket.get("plan") if isinstance(ticket.get("plan"), dict) else {}
    steps = [
        str(k.get("title", "")).strip()
        for k in sorted(
            (k for k in all_tickets if k.get("parent") == ticket.get("id")),
            key=lambda k: (str(k.get("created_at", "")), str(k.get("key", ""))),
        )
    ]
    parts = [f"What this is about: {ticket.get('title', '')}"]
    if plan.get("goal"):
        parts.append(f"Goal: {plan['goal']}")
    if plan.get("not_included"):
        parts.append(f"Not included: {plan['not_included']}")
    if steps:
        parts.append("Steps: " + "; ".join(f"{i}. {x}" for i, x in enumerate(steps, 1) if x))
    return {**card, "why": _clip(" ".join(parts), _LIMITS["why"])}


def _option_ids(q: dict, card: dict) -> list[str]:
    pv = card.get("preview") or {}
    if card.get("kind") == "choice" and pv.get("type") == "options":
        return [o["id"] for o in pv.get("options", [])]
    return list(q.get("options") or [])


IDEAS_SORT = ("keep", "no", "later")


def _ideas_sorted(q: dict, note) -> tuple[dict, object]:
    """ORCH-2186: how the person sorted an ideas question: the note's {"ideas": {"keep": [1, 3], "no": [2],
    "later": [4]}} (numbers from 1, as the list shows them). An idea not named stays for later. No sorting at
    all keeps every idea (a page without the Keep / Later / No rows answers with Looks good).
    Returns ({keep, no, later: [idea text]}, the note without "ideas")."""
    ideas = q["ideas"]
    if isinstance(note, str) and note.strip():
        try:
            note = json.loads(note)
        except ValueError as e:
            raise BadVerdict("A note must be JSON.") from e
    got = note.get("ideas") if isinstance(note, dict) else None
    rest = {k: v for k, v in note.items() if k != "ideas"} if isinstance(note, dict) else note
    if got is None:
        return {"keep": list(ideas), "no": [], "later": []}, rest
    if not isinstance(got, dict) or set(got) - set(IDEAS_SORT):
        raise BadVerdict('Sort ideas as {"keep": [1, 3], "no": [2], "later": [4]}.')
    seen: dict[int, str] = {}
    for word in IDEAS_SORT:
        nums = got.get(word) or []
        if not isinstance(nums, list):
            raise BadVerdict(f'"{word}" is a list of idea numbers.')
        for i in nums:
            if isinstance(i, bool) or not isinstance(i, int) or not 1 <= i <= len(ideas):
                raise BadVerdict(f"Idea numbers go from 1 to {len(ideas)}.")
            if i in seen:
                raise BadVerdict(f"Idea {i} is sorted twice.")
            seen[i] = word
    if not seen:
        raise BadVerdict("Sort at least one idea, then save.")
    word = [seen.get(i, "later") for i in range(1, len(ideas) + 1)]
    return {w: [x for x, got in zip(ideas, word, strict=True) if got == w] for w in IDEAS_SORT}, rest


def ideas_summary(sorted_: dict) -> str:
    """One plain line for the helper: "Keep: A; B. No: C. Later: D." (empty parts left out)."""
    names = {"keep": "Keep", "no": "No", "later": "Later"}
    return " ".join(f"{names[w]}: {'; '.join(sorted_[w])}." for w in IDEAS_SORT if sorted_.get(w))


def _decision(q: dict, card: dict, verdict: str, picked, note) -> dict:
    if verdict not in VERDICTS:
        raise BadVerdict(f"verdict is one of {', '.join(VERDICTS)}.")
    if verdict == "ok" and isinstance(q.get("ideas"), list) and "card" not in q:
        if picked is not None:
            raise BadVerdict("An ideas question has no options to pick: sort the ideas.")
        sorted_, note = _ideas_sorted(q, note)
        d = _bare("approve", None, [], _note_bv(note))
        d["ideas"], d["summary"] = sorted_, ideas_summary(sorted_)
        return d
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
    if action == "send_back" and card.get("kind") == "choice":
        # own words on a question (as on Home's "Write your own"): the words are the answer
        d["summary"] = _clip("; ".join(changes), 400)
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


def check_digest(ticket: dict, root: Path | None = None) -> str:
    """What a person is shown of a Test results card: exactly check_card(ticket) (title, steps with their done
    and won't-do state), for this ticket id and status. New with Review cards: no stored older value."""
    shown = {"id": ticket["id"], "status": ticket.get("status"), "card": check_card(ticket, root)}
    return _sha(_canon(shown).encode())


_PR_NUMBER = re.compile(r"/pull/(\d+)")


def _step_evidence(c: dict) -> str:
    """What a step's evidence says, in one plain line: the completion note, what was run, the pull request."""
    bits: list[str] = []
    for ev in c.get("evidence") or []:
        if not isinstance(ev, dict):
            continue
        kind, ref = ev.get("type") or ev.get("kind"), str(ev.get("ref") or ev.get("text") or "").strip()
        said = [str(ev.get("summary") or "").strip()]
        if kind == "note":
            said.append(ref)
        elif kind == "command" and ref:
            failed = isinstance(ev.get("exit"), int) and ev["exit"] != 0
            said.append(f"Ran: {ref}" + (f" (failed, exit {ev['exit']})" if failed else ""))
        elif kind == "pr":
            m = _PR_NUMBER.search(ref)
            said.append(f"PR #{m.group(1)}" if m else "Pull request")
        bits += [x for x in said if x and x not in bits]
    return " · ".join(bits)


def _check_open(ticket: dict) -> str | None:
    """The newest pull request in the steps' evidence: the card's Open button."""
    for c in reversed(ticket.get("checklist") or []):
        evs = c.get("evidence") if isinstance(c, dict) else None
        for ev in reversed(evs if isinstance(evs, list) else []):
            if not isinstance(ev, dict):
                continue
            ref = ev.get("ref")
            if ev.get("type") == "pr" and isinstance(ref, str) and len(ref) <= 500 and _OPEN.fullmatch(ref):
                return ref
    return None


_CHECK_FILE_TYPES = {
    ".png": "img", ".jpg": "img", ".jpeg": "img", ".webp": "img", ".gif": "img",
    ".html": "page", ".htm": "page", ".pdf": "file",
}  # fmt: skip
_CHECK_FILE_NAME = re.compile(r"[^/\\\x00-\x1f\x7f]{1,200}(/[^/\\\x00-\x1f\x7f]{1,200}){0,3}")
MAX_CHECK_FILES = 24  # the card shows 5 tiles and a "+N more" tile (ORCH-421)


def _check_files(ticket: dict, root: Path | None) -> list[dict]:
    """The result's own files a person wants to see on the card (ORCH-183): pictures, web pages and PDFs
    from the steps' evidence (with the helper's title), then from the artifacts folder (with `root`). Each is
    {name, type: img|page|file, ref: evidence/<name> | artifacts/<name>, stamp}; the stamp (size, time) puts
    a changed file into check_digest. Files are named, never read here; the page asks for them like the Files
    tab."""
    out: list[dict] = []
    seen: set[str] = set()

    def add(folder: str, name: str, label: str, stamp: str) -> None:
        kind = _CHECK_FILE_TYPES.get(os.path.splitext(name)[1].lower())
        ref = f"{folder}/{name}"
        if not kind or ref in seen or len(out) >= MAX_CHECK_FILES or not _CHECK_FILE_NAME.fullmatch(name):
            return
        if any(p in ("", ".", "..") or p.startswith(".") for p in name.split("/")) or _NAME_BAD.search(label):
            return
        seen.add(ref)
        out.append({"name": _clip(label, 80), "type": kind, "ref": ref, "stamp": _clip(stamp, 60)})

    head = f".orch/tickets/{ticket['id']}/evidence/"
    for c in ticket.get("checklist") or []:
        for ev in (c.get("evidence") if isinstance(c, dict) else None) or []:
            ref = ev.get("ref") if isinstance(ev, dict) else None
            if ev.get("type") == "file" and isinstance(ref, str) and ref.startswith(head):
                name = ref[len(head) :]
                title = ev.get("title") if isinstance(ev.get("title"), str) and ev["title"].strip() else name
                add("evidence", name, title.strip(), str(ev.get("text") or ""))
    if root is not None:
        try:
            rows = tickets.artifacts_list(root, ticket["id"])
        except (Refused, OSError, ValueError):
            rows = []
        for a in rows:
            if a["name"].startswith(tickets.FEEDBACK_DIR + "/"):
                continue  # the person's feedback files are not the result: the card stays the same
            add("artifacts", a["name"], a["name"].rsplit("/", 1)[-1], f"{a['size']} {a['mtime']}")
    return out


def _parent_line(ticket: dict, root: Path | None) -> str:
    """'Part of: ORCH-49 Factory follow-ups' for a sub-ticket (needs `root`); "" without a parent."""
    pid = ticket.get("parent")
    if root is None or not isinstance(pid, str) or not pid:
        return ""
    try:
        parent = tickets.load(root, pid)
    except (Refused, OSError, ValueError):
        return ""
    name = " ".join(x for x in (parent.get("key"), parent.get("title")) if isinstance(x, str) and x.strip())
    return _clip(f"Part of: {name}", 300) if name else ""


def _short(text: str, limit: int) -> str:
    """The first sentence of a text, at most `limit` characters."""
    text = " ".join(text.split())
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return _clip(first, limit)


def _checks_chips(ticket: dict) -> list[dict]:
    """One chip for the commands that passed and one for those that failed (from the steps' evidence)."""
    ok = bad = 0
    for c in ticket.get("checklist") or []:
        for ev in (c.get("evidence") or []) if isinstance(c, dict) else []:
            if isinstance(ev, dict) and (ev.get("type") or ev.get("kind")) == "command":
                if isinstance(ev.get("exit"), int) and ev["exit"] != 0:
                    bad += 1
                else:
                    ok += 1
    out = [{"text": f"{ok} check{'s' if ok != 1 else ''} ran fine", "tone": "ok"}] if ok else []
    return out + ([{"text": f"{bad} check{'s' if bad != 1 else ''} failed", "tone": "bad"}] if bad else [])


def accept_blocked(ticket: dict) -> str:
    """Why Looks good is off on this Test results, with what to press (ORCH-548, owner 18 Nov: open steps and
    an open question stop it, like the ticket page's Looks good since ORCH-250); "" when nothing stops it."""
    steps = sum(
        1
        for c in ticket.get("checklist") or []
        if isinstance(c, dict) and not c.get("done") and not c.get("wont_do")
    )
    asks = sum(
        1
        for q in ticket.get("questions") or []
        if isinstance(q, dict) and q.get("answer") is None and tickets.taken_back_text(q) is None
    )
    out = []
    if steps:
        out.append(
            "1 step is not finished. Send it back to get it done."
            if steps == 1
            else f"{steps} steps are not finished. Send it back to get them done."
        )
    if asks:
        out.append(
            "A question on this ticket still waits for your answer. Answer it first, then press Looks good."
            if asks == 1
            else f"{asks} questions on this ticket still wait for your answer. Answer them first, "
            "then press Looks good."
        )
    return " ".join(out)


# What each button of a Check card does, in the card's own words (ORCH-585: the person could not tell
# whether Looks good also starts follow-up work). Looks good only closes the ticket (tickets.accept_review);
# Send back adds the note as a task and starts a helper on it (tickets.ask_for_changes). The record keeps
# the first part (the line without its Send back ending).
CHECK_DONE = "The ticket is done. Nothing else starts: no new ticket, no more work."
CHECK_DONE_UNCOVERED = (
    "The ticket is done as it is. The missing part is dropped: no new ticket is made for it."
)
_CHECK_SEND_BACK = (
    " To change something, press Send back and say what; a helper then works on it in this ticket."
)
_CHECK_SEND_BACK_UNCOVERED = (
    " To get it done, press Send back and say what is missing; a helper then works on it in this ticket."
)
CHECK_THEN = CHECK_DONE + _CHECK_SEND_BACK
CHECK_THEN_UNCOVERED = CHECK_DONE_UNCOVERED + _CHECK_SEND_BACK_UNCOVERED


def _accept_then(ticket: dict, root: Path | None, uncovered: bool) -> str:
    """What Looks good does (the card's "If you approve", ORCH-585), with what does not stop it said in the
    same line (ORCH-548): a pull request not merged yet, the Reviewer's second look still to come. Only the
    pull request's number, never its changing GitHub state, so the card (and its digest) changes only when it
    is merged."""
    prs = []
    for r in ticket.get("refs") or []:
        if (
            isinstance(r, dict)
            and r.get("kind") == "github-pr"
            and r.get("status") not in ("merged", "closed")
        ):
            m = _PR_NUMBER.search(str(r.get("url") or ""))
            if m and f"#{m.group(1)}" not in prs:
                prs.append(f"#{m.group(1)}")
    done = CHECK_DONE_UNCOVERED if uncovered else CHECK_DONE
    if prs:
        head, rest = done.split(". ", 1)
        done = (
            head
            + (
                f", although pull request {prs[0]} is not merged yet"
                if len(prs) == 1
                else f", although pull requests {', '.join(prs[:5])} are not merged yet"
            )
            + ". "
            + rest
        )
    if root is not None:
        from orch import lookreview  # here: it reads the run folder, not needed for every card

        try:
            waits = ticket["id"] in lookreview.read_state(root)["line"]
        except (OSError, ValueError, KeyError):
            waits = False
        if waits:
            done += " The Reviewer's second look is not needed then."
    return done + (_CHECK_SEND_BACK_UNCOVERED if uncovered else _CHECK_SEND_BACK)


def _review_problem(ticket: dict, root: Path | None) -> str:
    """ORCH-826: the problem a review ticket orch made itself found ("" when none or not one): the card says
    it first, so the owner checks what is not good instead of reading what is."""
    if root is None:
        return ""
    from orch import reviewer  # here: it reads run files, not needed for every card

    found = reviewer.review_result(root, ticket)
    if found and not found["ok"]:
        return str(found["line"])
    try:  # ORCH-1741: the Reviewer left it for the person: the one card says why (no second "not sure" row)
        left = (reviewer._read_state(root).get(ticket.get("id")) or {}).get("left")
    except (OSError, ValueError, AttributeError):
        left = None
    return (
        f"the Reviewer was not sure: {' '.join(left.split()).rstrip('.')}."
        if isinstance(left, str) and left.strip()
        else ""
    )


def check_card(ticket: dict, root: Path | None = None) -> dict:
    """A Test results card, glance first (ORCH-329): one headline sentence, a progress bar, chips and
    the steps, each once with its evidence (ORCH-1686). Below them the rest of the summary, Done when
    and the parent. No preview when there is nothing to show (an empty box)."""
    rows, done, total = [], 0, 0
    for c in ticket.get("checklist") or []:
        if not isinstance(c, dict):
            continue
        state = "Won't do" if c.get("wont_do") else "Done" if c.get("done") else "Open"
        total, done = total + (state != "Won't do"), done + (state == "Done")
        rows.append((state, _clip(str(c.get("text", "")), 120), _step_evidence(c)))
    # ORCH-1686: each step once, its proof on the same line; the bar already says "N of N steps done", so a
    # list where every step is done drops the "Done:" in front of each.
    all_done = bool(rows) and all(st == "Done" for st, _, _ in rows)
    titles = [
        _clip(("" if all_done else f"{st}: ") + text + (f" — {said}" if said else ""), 1200)
        for st, text, said in rows
    ]
    summary_text = str(ticket.get("summary") or "").strip()
    problem = _review_problem(ticket, root)
    paras = [_clip(f"In short: {summary_text}", 1200)] if summary_text else []
    lead = _short(summary_text, 200) if summary_text else ""
    if lead and not problem and not lead.endswith("…"):
        # the headline is the summary's first sentence: the details carry only the rest of it, not all again
        rest = " ".join(summary_text.split())[len(lead) :].strip()
        paras = [_clip(rest, 1200)] if rest else []
    done_when = str(ticket.get("done_when") or "").strip()
    paras += [_clip(f"Done when: {done_when}", 1200)] if done_when else []
    paras += [x for x in (_parent_line(ticket, root),) if x]
    uncovered = tickets.proof_state(ticket)["uncovered"]
    paras += [_clip(f"No task covers: “{p}”", 600) for p in uncovered[:10]]
    if uncovered:  # what the person can do about it (ORCH-183)
        paras.append(
            "What to do: send it back and say which part is missing,"
            " or approve it if that part does not matter."
        )
    card = {
        "kind": "check",
        "title": ticket.get("title", ticket["id"]),
        "why": f"Check this: {problem}" if problem else "The helper says this is ready for your check.",
        "then": _accept_then(ticket, root, bool(uncovered)),
        "ok_label": "Looks good",
    }
    if uncovered:
        card["need"] = "Done when is not fully covered"
    blocked = accept_blocked(ticket)
    if blocked:  # the page turns Looks good off and shows this line instead of "If you approve"
        card["blocked"] = blocked
        card["need"] = "Looks good is off"
    url = _check_open(ticket)
    if url:
        card["open"] = url
    files = _check_files(ticket, root)
    if files:
        card["files"] = files
    if titles or paras or summary_text or problem:
        pv: dict = {"type": "doc"}
        if problem:  # ORCH-826: the problem first, not the good news
            pv["headline"] = _short(f"Problem found: {problem}", 200)
        elif summary_text:
            pv["headline"] = _short(summary_text, 200)
        if total:
            pv["progress"] = {"done": done, "total": total}
        chips = _checks_chips(ticket)
        if problem:
            chips.insert(0, {"text": "Problem found", "tone": "bad"})
        if uncovered:
            chips.append({"text": "Done when not fully covered", "tone": "warn"})
        if chips:
            pv["chips"] = chips
        if titles:
            pv["steps"] = titles[:50]
        if paras:
            pv["details"] = paras[:50]
        card["preview"] = pv
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
    person: bool = False,
) -> dict:
    """One swipe. key is a question id (q3) or "review" (a ticket in Review). Returns the decision entry
    (the answered question). The person's own checks (human: author, not an agent) stay in tickets.
    person: a signed-in person on the dashboard or a paired phone; a draft card, and the Check of a ticket
    that carries one, take nothing else (ORCH-582, orch/ownerpick.py)."""
    ticket = tickets.load(root, tid)
    if key == "review":
        if picked is not None:
            raise BadVerdict("A Test results card has no options to pick.")
        return _decide_check(root, ticket, verdict, note, by, via, digest, phone, pid, person)
    q = _find(ticket, key)
    tickets.refuse_if_taken_back(q)
    if q.get("answer") is not None:
        raise Refused(f"{key} is already answered. Use change to answer again.")
    ownerpick.refuse_card(q, person)  # before a merge or anything else is tried
    card = _card_of(q)
    if card.get("kind") == "run":  # ORCH-848: only the run itself answers I ran it; nothing while it runs
        from orch import runcard

        if verdict == "ok":
            raise Refused(runcard.OK_REFUSAL)
        if runcard.running(root, tid, key):
            raise Refused("It is running now. Wait for it to finish.")
    d = _decision(q, card, verdict, picked, note)
    if digest is not None and tickets.question_digest(q) != digest:  # before a merge, not only at the write
        raise Refused(f"{key} changed after it was shown. Look at the question again, then answer.")
    try:
        _merge_first(root, tid, q, d, by, via)
    except _merge_failed() as e:  # GitHub said no: the helper gets the reason and fixes it
        d = _send_back_after_failed_merge(card, str(e))
    _, out = tickets.answer(
        root,
        tid,
        key,
        _plain_answer(q, d),
        by,
        via,
        expected_question_digest=digest,
        decision=d,
        person=person,
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


def _merge_failed():
    from orch.ghmerge import MergeFailed

    return MergeFailed


def _send_back_after_failed_merge(card: dict, reason: str) -> dict:
    """The Merge click was refused by GitHub: answer the card as sent back to the helper, with the reason as
    the change to make (the helper then takes develop in, asks for a review or whatever the rule needs)."""
    from orch.ghmerge import OPEN_IT

    reason = _clip(reason.replace(OPEN_IT, "").strip(), 400)
    out = _bare("send_back", None, [f"Merge failed on GitHub, please fix it: {reason}"], _note_bv(None))
    out["summary"] = summary(out, card)
    return out


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

    retry = ghmerge.RETRY_PHONE if via == "phone" else None  # the relay inbox waits for this answer
    try:
        got = ghmerge.merge(url, q["action"].get("head"), retry_for=retry)
    except ghmerge.OwnPullRequest as e:
        _own_pull_request(root, tid, url, e, by, via)
        return
    line = (
        f"The pull request was merged already on GitHub ({got['login']}): {url}"
        if got["already"]
        else f"Merged the pull request on GitHub as {got['login']}: {url}"
    )
    import contextlib

    with contextlib.suppress(Refused, OSError):  # merged; the answer itself is written next
        tickets.note_history(root, tid, by, line, via)


def _own_pull_request(root: Path, tid: str, url: str, e, by: str, via: str) -> None:
    """ORCH-1118: the person clicked Merge on their own pull request and GitHub wants a review it never takes
    from the author. With the merge queue on for its base branch the Merge stands: the answer is saved and the
    queue (another login) approves and merges that commit once its checks are green. Else it is sent back."""
    import contextlib

    from orch import ghmerge
    from orch.cli import _queue_bases

    if not e.base or e.base not in _queue_bases(root):
        raise ghmerge.MergeFailed(
            "GitHub does not let you approve your own pull request, so nothing was merged: "
            "someone else who may approve it approves it on GitHub."
        )
    with contextlib.suppress(Refused, OSError):  # the answer itself is written next
        tickets.note_history(root, tid, by, f"{ghmerge.OWN_PR} {url}", via)


def excused_red(got: dict, known_red: dict | None) -> tuple[list[str], frozenset] | None:
    """The named exceptions that excuse every red check of a finished release pull request (ORCH-178, from
    ORCH-431): (["<check> (<ticket>)", ...], the red checks as (name, conclusion)), or None when a check still
    runs, nothing failed, or one red check has no exception. The roll-up job (ROLLUP_JOBS) is red whenever
    a job it waits for is; it counts as excused only on a plain failure (not cancelled or timed out) next to
    at least one excused job, as every job it waits for shows here too."""
    from orch.releasekeeper import ROLLUP_JOBS, known_name

    failed = got.get("failed")
    if not known_red or not failed:
        return None
    named = []
    for name, word in failed:
        if name in ROLLUP_JOBS:
            if word != "FAILURE":
                return None
            continue
        entry = known_name(name, known_red)
        if entry is None:
            return None
        named.append(f"{name} ({known_red[entry]})")
    return (named, frozenset(failed)) if named else None


def tend_releases(
    root: Path, dry_run: bool = False, checks_of=None, merge_with=None, release_check=None, known_red=None
) -> dict:
    """One pass of the release keeper (`orch review tend-releases`): every unanswered release Merge card
    (`orch ask ... --merge --release`) whose pull request is open, not a draft, still on the card's commit and
    green on every check is merged with the gh login of this computer (the owner's: ghmerge drops helper
    tokens) and recorded as answered by the release keeper. `known_red` ({check: "<ticket>[, until <date>]"},
    the release keeper's named exceptions while their tickets are open, ORCH-456) lets a release whose only
    red checks are named there merge too, as the owner's click on that card would (ORCH-178); without it every
    check must be green. Only while the owner turned it on in Settings
    (`workflow.release_merge`) and automation is not paused. Returns {"off", "paused", "actions": [{ticket,
    key, question, url, verdict, why, done}]}; verdict is merge, wait or stale. dry_run only says it.
    Only a real release merges: from a release/... branch into main, changing nothing that is
    not on develop already (ghmerge.release_problem), so a card a helper marks --release on other work never
    merges by itself. Refused inside a helper (an agent tool in the environment), like the Merge click.
    No AI call: a repeating automation script runs it."""
    from orch import brake, config, ghmerge

    checks_of = checks_of or ghmerge.checks
    merge_with = merge_with or ghmerge.merge
    release_check = release_check or ghmerge.release_problem
    if tickets.agent_tool():
        raise Refused("Releases merge from the automation on this computer, not inside a helper.")
    if not config.release_merge_on(root):
        return {"off": True, "paused": False, "actions": []}
    if brake.paused(root) is not None:
        return {"off": False, "paused": True, "actions": []}
    actions = []
    for t in tickets.list_all(root):
        if t.get("status") in ("done", "dropped"):
            continue
        for q in t.get("questions") or []:
            url = merge_url(q)
            act = q.get("action") if isinstance(q.get("action"), dict) else {}
            if url is None or act.get("release") is not True or q.get("answer") is not None:
                continue
            if tickets.taken_back_text(q):
                continue
            head, excused = act.get("head"), None
            row = {"ticket": t["id"], "key": t.get("key") or t["id"], "question": q["id"], "url": url,
                   "done": False}  # fmt: skip
            got = checks_of(url)
            if got is None:
                row.update(verdict="wait", why="GitHub could not be read")
            elif got["state"] != "OPEN" or got["head"] != head:
                row.update(verdict="stale", why="the pull request changed or closed; a new card is needed")
            elif not got["green"] and (excused := excused_red(got, known_red)) is None:
                row.update(verdict="wait", why="not every check is green yet")
            elif (why := release_check(url, head)) is not None:
                row.update(verdict="wait", why=f"not a release that merges by itself: {why}")
            elif not got["green"]:
                row.update(
                    verdict="merge",
                    why="every check is green except named exceptions: " + ", ".join(excused[0]),
                )
            else:
                row.update(verdict="merge", why="every check is green")
            if row["verdict"] != "merge" or dry_run:
                actions.append(row)
                continue
            try:
                done = merge_with(url, head, excused=excused[1]) if excused else merge_with(url, head)
                d = _bare("approve", "Merge", [], _note(None))
                d["summary"] = f"Merged by itself: {row['why'].replace('is green', 'was green')}."
                line = (f"merged already on GitHub ({done['login']}): {url}" if done.get("already")
                        else f"merged on GitHub as {done['login']}: {url}")  # fmt: skip
                tickets.merged_for_owner(root, t["id"], q["id"], url, head, line, d)
                row["done"] = True
            except Refused as e:  # GitHub said no, or the card changed: the owner's click still works
                row.update(verdict="wait", why=str(e))
            actions.append(row)
    return {"off": False, "paused": False, "actions": actions}


def tend_releases_text(result: dict, dry_run: bool = False) -> str:
    if result.get("off"):
        return (
            "Releases merge only on your click here. "
            "Turn it on: Settings, or orch config set workflow.release_merge on"
        )
    if result.get("paused"):
        return "Automation is paused: no release merges by itself now."
    rows = result.get("actions") or []
    if not rows:
        return "No release waits for a merge."
    out = []
    for r in rows:
        if r["verdict"] == "merge":
            word = "would merge" if dry_run else ("merged" if r["done"] else "not merged")
        else:
            word = "waits" if r["verdict"] == "wait" else "needs a new card"
        out.append(f"{r['key']} {r['question']}: {word} ({r['why']}) {r['url']}")
    return "\n".join(out)


_STATUS_WORDS = {"active": "Working", "ready": "To do", "waiting": "Waiting", "backlog": "Backlog",
                 "dropped": "Dropped", "done": "Done"}  # fmt: skip
# The lines that take a ticket out of Review: an accept or a move ("Status review -> done"), a send back by
# the
# Reviewer or by a person (tickets.ask_for_changes writes no status line, only its own).
_LEFT_REVIEW = re.compile(
    r"Status review -> \w+|" + re.escape(tickets.SENT_BACK_LINE) + r"(?P<back>.+)|Asked for changes: .+", re.S
)


def not_in_review(root: Path, ticket: dict) -> str:
    """Why a Test results card cannot be answered any more (ORCH-548), in one line with what to do: who moved
    the ticket out of Review and when. A Looks good that arrives after the Reviewer, another tab or the phone
    decided
    then says what happened, never only "not waiting for your review"."""
    from orch.net import when

    status = str(ticket.get("status") or "")
    moved, back = None, ""
    for h in reversed(history.lines(root, ticket)):
        m = _LEFT_REVIEW.fullmatch(str(h.get("text", ""))) if isinstance(h, dict) else None
        if m:
            moved, back = h, " ".join((m.group("back") or "").split())
            break
    by = str((moved or {}).get("by") or "")
    at = f" {when(moved['at'])}" if moved and moved.get("at") else ""
    if status == "done":
        if by == tickets.REVIEWER:
            return _clip(f"Already Done: the Reviewer accepted it for you{at}. Nothing more to press.", 300)
        who = "you" if history.is_person_line(moved) else "a helper" if by.startswith("agent:") else "someone"
        return _clip(f"Already Done: {who} accepted it{at}. Nothing more to press.", 300)
    word = _STATUS_WORDS.get(status, status or "changed")
    then = f"It is {word} now and comes back to Check when the helper is done."
    if by == tickets.REVIEWER:
        return _clip(
            f"The Reviewer sent it back{at}" + (f": {back.rstrip('.')}" if back else "") + f". {then}", 300
        )
    if history.is_person_line(moved):
        return _clip(f"You sent it back{at}. {then}", 300)
    return _clip(f"It is not in Check any more: it is {word} now. Open the ticket to see why.", 300)


def answered_elsewhere(root: Path, ticket: dict, q: dict, me: str = "") -> str:
    """Why a shown question card cannot be answered any more (ORCH-921): it was answered in the terminal, on
    the phone or in another tab after the page showed it. One line: what applies now, who answered and when,
    and that nothing was changed. me: the person answering now (their own earlier answer says "you"). The
    ticket is read as shown here (history.shown_ticket: a synced answer nobody verified shows as synced)."""
    from orch.net import when

    ticket = history.shown_ticket(root, ticket)
    by_id = {x.get("id"): x for x in ticket.get("questions") or [] if isinstance(x, dict)}
    q = by_id.get(q.get("id"), q)
    now, seen = q, {q.get("id")}
    while True:  # the answer that applies now: follow replaced_by to the newest one
        nxt = by_id.get((now.get("decision") or {}).get("replaced_by"))
        if not isinstance(nxt, dict) or nxt.get("id") in seen:
            break
        seen.add(nxt.get("id"))
        now = nxt
    by = str(now.get("answered_by") or "")
    if me and by == me:
        who = "you"
    elif by == tickets.REVIEWER:
        who = "the Reviewer"
    elif by.startswith("agent:"):
        who = "a helper"
    else:
        who = by.removeprefix("human:") or "someone"
    at = now.get("answered_at") or now.get("at")
    said = " ".join(str(now.get("answer") or "").split())
    said = said if len(said) <= 120 else said[:119] + "…"
    return _clip(
        f"This was answered already by {who}{' ' + when(at) if at else ''}: {said}. Nothing was changed.", 300
    )


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
    person: bool = False,
) -> dict:
    tid = ticket["id"]
    if not by.startswith("human:"):  # a verdict on a Test results card is a person's (label check)
        raise Refused("Only a person can decide this. Ask the human to do it themselves.")
    ownerpick.refuse_ticket(ticket, person)  # ORCH-582: a ticket with a draft is accepted only by a person
    if verdict not in VERDICTS:
        raise Refused(f"verdict is one of {', '.join(VERDICTS)}.")
    if ticket.get("status") != "review":
        raise Refused(not_in_review(root, ticket))
    if digest is not None and digest != check_digest(ticket, root):
        raise Refused("This result changed after it was shown. Look at it again, then answer.")
    card = check_card(ticket, root)
    n = _note_bv(note)
    if verdict == "ok" and card.get("blocked"):
        raise Refused(card["blocked"])
    if verdict == "ok":
        d = _bare("approve", card["ok_label"], [], n)
        tickets.accept_review(root, tid, by, via, person=person)
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
    return tickets.record_answered(root, tid, entry, by, via, person=person)


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
    person: bool = False,
) -> dict:
    """Answer an answered card again: a NEW entry (same card and shown) with decision.replaces = qid; the old
    entry only gets decision.replaced_by. Nothing is overwritten."""
    ticket = tickets.load(root, tid)
    old = _find(ticket, qid)
    tickets.refuse_if_taken_back(old)
    if old.get("answer") is None:
        raise Refused(f"{qid} is not answered yet. Answer it first.")
    if (old.get("card") or {}).get("kind") == "check":
        raise Refused("A Test results card is final. Reopen the ticket to look at it again.")
    if digest is not None and tickets.question_digest(old) != digest:
        raise Refused(f"{qid} changed after it was shown. Look at the question again, then answer.")
    ownerpick.refuse_card(old, person)
    card = _card_of(old)
    if card.get("kind") == "run" and verdict == "ok":  # ORCH-848: changing an answer never says it ran
        from orch import runcard

        raise Refused(runcard.OK_REFUSAL)
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
    return tickets.record_answered(root, tid, entry, by, via, replaces=qid, person=person)


# ---------------------------------------------------------------- the stack


ABOUT_MAX = 120


def _stack_tickets(root: Path) -> list[dict]:
    """The tickets that can hold a card: an open question on an unfinished ticket, or in Review. With the
    ticket index (ORCH-521) only their files are read (ORCH-522: every ticket was read, 2 s at 10,000);
    without it every ticket."""
    from orch import needs

    try:
        from orch import ticketindex

        rows = ticketindex.rows(root)  # hidden tickets left out, as list_all
    except Exception:  # noqa: BLE001 - no index (or a broken one): every ticket, as before
        return tickets.list_all(root)
    out = []
    for r in rows:
        if r.get("status") == "review" or (r.get("questions_open") and r.get("status") not in needs.OPEN):
            try:
                out.append(tickets.load(root, r["id"]))
            except Exception:  # noqa: BLE001 - a ticket that cannot be read holds no card (as list_all skips it)
                continue
    return out


def _plan_rows(root: Path) -> list[dict]:
    """Every ticket's parent, title, key and creation time for the steps on a "Plan ready" card: the index
    rows (ORCH-1621, ORCH-1622: every ticket file was read); without the index every ticket."""
    try:
        from orch import ticketindex

        return ticketindex.rows(root)
    except Exception:  # noqa: BLE001 - no index (or a broken one): every ticket, as before
        return history.shown_json(root, tickets.list_all(root))


def run_last(t: dict, q: dict, card: dict, root: Path | None = None) -> dict:
    """A run card's last failed try (ORCH-848: its error stays on the card), whether a phone may run it
    and, for a sign-in (ORCH-865), whether Run it now opens the Focus terminal (run_terminal) and the
    sign-in under way there (run_login {at, state, terminal})."""
    if card.get("kind") != "run":
        return {}
    from orch import runcard

    rows = t.get("run_attempts") if isinstance(t.get("run_attempts"), dict) else {}
    last = rows.get(q["id"]) if isinstance(rows.get(q["id"]), dict) else None
    out: dict = {"phone_run": runcard.phone_ok(q)}
    if (card.get("run") or {}).get("class") == "login":
        out["run_terminal"] = runcard.terminal_ok(root, q)
        now = runcard.login_now(t, q["id"])
        if now:
            out["run_login"] = now
    if last and last.get("ok") is False:
        out["run_last"] = {
            "at": last.get("at"),
            "exit": last.get("exit") if isinstance(last.get("exit"), int) else None,
            "output": str(last.get("output") or "")[-4000:],
            "error": runcard.error_words(last.get("reason"), last.get("exit"), card.get("run")),
        }
    return out


def stack(root: Path) -> list[dict]:
    """Everything waiting for a person's swipe: card questions, plain open questions (as options cards) and
    tickets in Review (as Check cards), grouped by ticket (the round whose oldest card waited longest first),
    then by the task a question belongs to (`orch ask --check`), then oldest first. Each item:
    {id, ticket, ticket_key, ticket_title, key, kind, card, digest, since, options, recommended} (a question
    also has `one_tap`: answered with one tap on its named answer, ORCH-1847) and, when the
    question belongs to a task, `about` (its text, one line) and `task` (its id). Neither is part of the card
    or its digest."""
    from orch import (
        needs,  # needs imports tickets; no cycle back
        reviewer,  # reviewer reads review's facts; imported here, no cycle at load
    )

    out = []
    order = {}  # ticket id -> {task id: position in its checklist}
    from orch import runs

    every = None  # the parts per ticket, read only when a "Plan ready" card shows them (ORCH-522)
    stored = _stack_tickets(root)
    raw = {t.get("id"): t for t in stored if isinstance(t, dict)}  # cardcontext reads the stored ticket
    shown = history.shown_json(root, stored)
    from orch import (
        cardcontext,  # ORCH-2183: the person's quoted words on a card
        counts,  # ORCH-1741: the Check cards that do not show, as the count leaves them out
    )

    hidden = counts.quiet(root, shown)
    skip = set(hidden["queue"]) | set(hidden["folded"])
    for t in shown:
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
                if q.get("answer") is not None:
                    continue  # every open question is a card, an add-on's own too (Factory's Start?, ORCH-63)
                card = q["card"] if isinstance(q.get("card"), dict) else _card_of(q)
                if "card" not in q:
                    if every is None and str(q.get("text", "")).startswith(runs.PLAN_READY):
                        every = {}  # parent id -> its parts, worked out once for every card
                        for k in _plan_rows(root):
                            every.setdefault(k.get("parent"), []).append(k)
                    card = _with_plan(card, q, t, (every or {}).get(t["id"], []))
                task = tasks.get(q.get("check"))
                about = _clip(task[1], ABOUT_MAX) if task and isinstance(task[1], str) else ""
                # ORCH-2183: the quoted words; out of date asks again (no suggested answer, no one tap)
                said = cardcontext.shown(root, raw.get(t["id"], t), q) if "said" in q else None
                again = bool(said and said.get("stale"))
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
                        "recommended": None if again else q.get("recommended"),
                        "text": q.get("text") or "",
                        "one_tap": False if again else one_tap(t, q),
                        "card_kind": cardkinds.look(
                            card,
                            question_kind=q.get("kind") if isinstance(q.get("kind"), str) else None,
                            merge=isinstance(q.get("action"), dict) and "merge" in q["action"],
                        ),
                        **({"links": q["links"]} if isinstance(q.get("links"), list) else {}),
                        **({"group": q["group"]} if isinstance(q.get("group"), str) else {}),
                        # ORCH-2182: the decision-first card's "If you wait" and "What matters" lines
                        **({"if_wait": q["if_wait"]} if isinstance(q.get("if_wait"), str) else {}),
                        **(
                            {"facts": [f for f in q["facts"] if isinstance(f, str)]}
                            if isinstance(q.get("facts"), list)
                            else {}
                        ),
                        **({"said": said} if said else {}),
                        # ORCH-2184: the deadline the helper gave (orch ask --due), for "Next deadline"
                        **({"due": q["due"]} if isinstance(q.get("due"), str) else {}),
                        # ORCH-2186: the ideas to sort (Keep / Later / No), and the card they were left from
                        **(
                            {"ideas": [i for i in q["ideas"] if isinstance(i, str)]}
                            if isinstance(q.get("ideas"), list)
                            else {}
                        ),
                        **({"left_from": q["left_from"]} if isinstance(q.get("left_from"), str) else {}),
                        **run_last(t, q, card, root),
                    }
                )
        if t.get("status") == "review" and t["id"] not in skip:
            hist = [h for h in history.lines(root, t) if isinstance(h, dict) and h.get("at")]
            card = check_card(t, root)
            proposal = reviewer.proposal(
                hist
            )  # Reviewer mode "propose" (owner, 25 Nov): its verdict, one click
            out.append(
                {
                    **base,
                    "id": f"core:review:{t['id']}",
                    "key": "review",
                    "kind": "check",
                    "card": card,
                    "digest": check_digest(t, root),
                    "since": hist[-1]["at"] if hist else t.get("updated_at") or t.get("created_at"),
                    "options": [],
                    "recommended": {"accept": "ok", "back": "no"}[proposal["verdict"]] if proposal else None,
                    "card_kind": cardkinds.look(card, proposed=proposal is not None),
                    **({"proposal": proposal} if proposal else {}),
                }
            )
    # grouped: the ticket (round) with the longest-waiting card first, then its tasks in checklist order,
    # cards without a task last; inside a group oldest first
    oldest: dict[str, str] = {}
    for r in out:
        oldest[r["ticket"]] = min(oldest.get(r["ticket"], r["since"] or ""), r["since"] or "")
    out.sort(
        key=lambda r: (
            cardkinds.lane_rank(r),  # R2 A (owner, 25 Nov): what holds up work first, then by what you do
            oldest[r["ticket"]],
            r["ticket"],
            order[r["ticket"]].get(r["task"], 1 << 20) if r.get("task") else 1 << 30,
            r["since"] or "",
            r["id"],
        )
    )
    # ORCH-2184: Quick look / Short decision / Take your time (only orders the work)
    from orch import attention

    return attention.tag(out)


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
        if card.get("kind") == "check" and isinstance(then, str):
            # what happened, not the other button
            for tail in (_CHECK_SEND_BACK, _CHECK_SEND_BACK_UNCOVERED):
                if then.endswith(tail):
                    then = then[: -len(tail)]
        if d.get("action") == "send_back" and card.get("kind") == "check":
            then = "The helper makes a new version."  # not the card's "The ticket is done."
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
