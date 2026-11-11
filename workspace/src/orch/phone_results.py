"""Phone results: `ticket_view.results` (contracts/blocks.md 'Phone results', message.schema.json).

The sender side only. `prepare` takes the candidate results of a ticket (dicts with id, from, title?, at,
checked?, doc; doc is an orch.blocks/1 document) and returns what may leave the computer: the newest 5, newest
first, each one value-hidden, trimmed for the phone, checked against blocks.schema.json and the phone rules,
at most 2560 bytes each and 8192 bytes together. A result that fails any check is dropped, never sent. Fails
closed: when the value hider can not be built, nothing is sent.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from functools import lru_cache
from pathlib import Path

from orch import hider, keystore

RESULT_BYTES = 2560
RESULTS_BYTES = 8192
MAX_RESULTS = 5
TABLE_ROWS = 20
MORE = "More on the computer"
KNOWN = ("summary", "steps", "progress", "stat", "kv", "table", "file", "link", "chart")  # no log
ID_RE = re.compile(r"(j_[a-z0-9]{6,32}|a_[0-9a-f]{12})")
AT_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z")
LINK_RE = re.compile(r"https://[^/?#@\s<>\"'`]+(/[^?#\s<>\"'`]*)?")
FILE_RE = re.compile(r"[^/\\.\x00-\x1f\x7f][^/\\\x00-\x1f\x7f]*")
LINE_RE = re.compile(r"[^\x00-\x1f\x7f]*")


def cj(o) -> int:
    return len(json.dumps(o, separators=(",", ":"), ensure_ascii=False).encode())


@lru_cache(maxsize=1)
def _validator():
    from jsonschema import Draft202012Validator, FormatChecker

    schema = json.loads((Path(__file__).with_name("blocks.schema.json")).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def doc_valid(doc) -> bool:
    """A whole orch.blocks/1 document (blocks.schema.json, at most 64 KB)."""
    try:
        return not any(_validator().iter_errors(doc)) and cj(doc) <= 65536
    except Exception:
        return False


def trim(r: dict) -> dict:
    """What the sender makes of one result for the phone (reference: validate.py phone_trim)."""
    r = json.loads(json.dumps(r))
    out, cut = [], False
    for b in r["doc"]["blocks"]:
        t = b.get("type")
        if t not in KNOWN:
            cut = True
            continue
        if t == "table" and len(b["rows"]) > TABLE_ROWS:
            b["total_rows"] = b.get("total_rows", len(b["rows"]))
            b["rows"] = b["rows"][:TABLE_ROWS]
            cut = True
        if t == "link":
            u = urllib.parse.urlsplit(b["url"])
            b["url"] = urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "", ""))
        if t == "file":
            b["path"] = b["path"].rsplit("/", 1)[-1]
        out.append(b)
    tail = {"type": "summary", "text": MORE}
    if cut and out[-1:] != [tail]:
        out.append(tail)
    r["doc"]["blocks"] = out
    while cj(r) > RESULT_BYTES or len(out) > 50:
        if out[-1:] != [tail]:
            out.append(tail)
        if len(out) == 1:
            break
        out.pop(-2)
    return r


def phone_ok(r) -> bool:
    """The result as the relay and the phone will check it: envelope, blocks.schema.json, snapshot rules,
    size, and a fixed point of the trim."""
    try:
        if not isinstance(r, dict) or set(r) - {"id", "from", "title", "at", "checked", "doc"}:
            return False
        if not {"id", "from", "at", "doc"} <= set(r) or not isinstance(r["doc"], dict):
            return False
        if not (isinstance(r["id"], str) and ID_RE.fullmatch(r["id"])):
            return False
        if r["from"] not in ("job", "agent", "orch") or r["doc"].get("from") != r["from"]:
            return False
        if not (isinstance(r["at"], str) and AT_RE.fullmatch(r["at"])):
            return False
        if "checked" in r and (r["checked"] is not True or r["from"] != "agent"):
            return False
        if "title" in r and not (
            isinstance(r["title"], str) and 1 <= len(r["title"]) <= 200 and LINE_RE.fullmatch(r["title"])
        ):
            return False
        doc = r["doc"]
        if not doc_valid(doc) or not 1 <= len(doc["blocks"]) <= 50 or cj(r) > RESULT_BYTES:
            return False
        for b in doc["blocks"]:
            t = b.get("type")
            if t not in KNOWN:
                return False
            if t == "table" and len(b["rows"]) > TABLE_ROWS:
                return False
            if t == "link" and not (len(b["url"]) <= 2000 and LINK_RE.fullmatch(b["url"])):
                return False
            if t == "file" and not (len(b["path"]) <= 255 and FILE_RE.fullmatch(b["path"])):
                return False
        return trim(r) == r
    except Exception:
        return False


def value_hider(root: Path):
    """The hider over every stored key value (as secretrun builds it), or None when it can not be built:
    then no result leaves."""
    try:
        return hider.Hider(keystore.all_needles(root))
    except Exception:
        return None


# Known gaps (not covered by the value hider or the pattern scrub): fullwidth/NFKC forms, a value split over
# cells, base32, host case in a URL, a token inside a URL path.
CUT = "[hidden]"


def _hide_labelled(doc: dict) -> None:
    """A secret-looking label hides its value: kv key, stat label, table column key or label (cells)."""
    from orch.phone_view import secret_name as named

    for b in doc.get("blocks", []):
        t = b.get("type")
        if t == "kv":
            for it in b.get("items", []):
                if named(it.get("key", "")):
                    it["value"] = CUT
        elif t == "stat":
            if named(b.get("label", "")):
                b["value"] = CUT
                b.pop("unit", None)
                b.pop("delta", None)
        elif t == "table":
            keys = {
                c.get("key")
                for c in b.get("columns", [])
                if named(c.get("key", "")) or named(c.get("label", ""))
            }
            for row in b.get("rows", []):
                for k in keys:
                    if k in row:
                        row[k] = CUT


def _when(r: dict):
    from datetime import datetime

    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?Z", str(r.get("at")))
    if not m:
        return 0.0
    try:
        return datetime.fromisoformat(m[1] + "+00:00").timestamp() + float(m[2] or 0)
    except ValueError:
        return 0.0


def _scrub(o, redact):
    """Every string leaf and every dict key through the pattern scrub the other phone text gets."""
    if isinstance(o, str):
        return redact(o)
    if isinstance(o, list):
        return [_scrub(x, redact) for x in o]
    if isinstance(o, dict):
        return {redact(k): _scrub(v, redact) for k, v in o.items()}
    return o


def _one(r: dict, h) -> dict | None:
    """One candidate -> the phone form, or None (dropped)."""
    try:
        if not isinstance(r, dict) or not isinstance(r.get("doc"), dict) or not doc_valid(r["doc"]):
            return None
        r = {k: v for k, v in r.items() if k in ("id", "from", "title", "at", "checked", "doc")}
        if r.get("from") != r["doc"].get("from"):
            return None
        from orch.phone_view import redact  # late: phone_view imports this module

        title = r.pop("title", None)
        if isinstance(title, str):  # the whole title is hidden first, then cut: a cut never leaves a prefix
            t = redact(h.hide_text(title)).strip()
            t = t if len(t) <= 200 else t[:199].rstrip() + "…"
            t = "".join(ch for ch in t if ch >= " " and ch != "\x7f")
            if t:
                r["title"] = t  # in place before the trim: it counts against the 2560 bytes
        r = trim(r)  # a trim never cuts a string, and the hider then sees less
        _hide_labelled(r["doc"])
        for _ in range(2):  # hide (exact values), scrub (patterns), trim; twice: the second pass proves it
            r = trim(_scrub(h.hide_json(r), redact))
        return r if phone_ok(r) and h.hide_json(r) == r and _scrub(r, redact) == r else None
    except Exception:
        return None


def prepare(root: Path, candidates: list[dict], h=None) -> list[dict]:
    """The `results` of a full snapshot (newest first, at most 5, ids unique, 8192 bytes together)."""
    h = h or value_hider(root)
    if h is None or not candidates:
        return []
    seen, ordered = set(), []
    for c in sorted(
        (c for c in candidates if isinstance(c, dict)),
        key=lambda c: (_when(c), str(c.get("id"))),
        reverse=True,
    ):
        if c.get("id") in seen:
            continue
        seen.add(c.get("id"))
        ordered.append(c)
    ordered = ordered[:15]  # newest few only: a ticket with a flood of proof files costs no more
    out = []
    for c in ordered:
        if len(out) == MAX_RESULTS:
            break
        r = _one(c, h)
        if r is None:
            continue
        if out and cj(out + [r]) > RESULTS_BYTES:
            break  # the older ones go first: nothing older than a dropped one is kept
        out.append(r)
    return out
