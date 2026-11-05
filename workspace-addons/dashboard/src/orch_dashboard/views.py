"""Pull an add-on view: `orch <name> view --json` (2 s, 256 KB), check it, keep the last good one in memory.
The dashboard never imports add-on code and never shows anything that failed the check."""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

TIMEOUT = 2.0
MAX_BYTES = 256 * 1024
TONES = ("neutral", "good", "warn", "needs-you", "bad")
BLOCKS = ("stat", "list", "calendar", "timeline", "chips", "table")
_LINK = re.compile(r"^(t_[a-z0-9]{6,16}|https://[^\s<>\"'`]+)$")
_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HM = re.compile(r"^[0-2][0-9]:[0-5][0-9]$")
_KEY = re.compile(r"^[a-z_][a-z0-9_]{0,31}$")
COL_TYPES = ("text", "number", "duration", "date", "tone")


def _text(v, n=200):
    return isinstance(v, str) and 1 <= len(v) <= n and "<" not in v and ">" not in v


def _opt(d, k, ok):
    return k not in d or ok(d[k])


def _tone(v):
    return v in TONES


def _link(v):
    return isinstance(v, str) and len(v) <= 500 and bool(_LINK.match(v))


def _chip(c):
    return isinstance(c, dict) and _text(c.get("label"), 40) and _opt(c, "tone", _tone)


def _item_ok(it, required, extra):
    return isinstance(it, dict) and all(k in it for k in required) and _opt(it, "tone", _tone) \
        and _opt(it, "link", _link) and extra(it)


def _block_ok(b) -> bool:
    t = b.get("type") if isinstance(b, dict) else None
    if t == "stat":
        v = b.get("value")
        return _text(b.get("label"), 40) and (_text(v, 24) or (isinstance(v, (int, float)) and not isinstance(v, bool))) \
            and _opt(b, "tone", _tone)
    if t == "list":
        items = b.get("items")
        return _text(b.get("title"), 60) and isinstance(items, list) and len(items) <= 50 and _opt(b, "more", _int) \
            and all(_item_ok(i, ("title",), lambda i: _text(i["title"]) and _opt(i, "subtitle", _text)
                             and _opt(i, "chips", lambda c: isinstance(c, list) and len(c) <= 6 and all(map(_chip, c))))
                    for i in items)
    if t == "calendar":
        days = b.get("days")
        return isinstance(days, list) and len(days) <= 14 and all(
            isinstance(d, dict) and isinstance(d.get("date"), str) and _DATE.match(d["date"])
            and isinstance(d.get("items"), list) and len(d["items"]) <= 20
            and all(_item_ok(i, ("title",), lambda i: _text(i["title"], 80)
                             and _opt(i, "time", lambda v: isinstance(v, str) and bool(_HM.match(v))))
                    for i in d["items"]) for d in days)
    if t == "timeline":
        items = b.get("items")
        return _opt(b, "title", lambda v: _text(v, 60)) and isinstance(items, list) and len(items) <= 50 and all(
            _item_ok(i, ("at", "text"), lambda i: isinstance(i["at"], str) and bool(_TIME.match(i["at"]))
                     and _text(i["text"])) for i in items)
    if t == "chips":
        items = b.get("items")
        return _opt(b, "title", lambda v: _text(v, 60)) and isinstance(items, list) and len(items) <= 30 \
            and all(map(_chip, items))
    if t == "table":
        cols, rows = b.get("columns"), b.get("rows")
        if not (isinstance(cols, list) and 1 <= len(cols) <= 6 and isinstance(rows, list) and len(rows) <= 100):
            return False
        if not (_opt(b, "title", lambda v: _text(v, 60)) and _opt(b, "more", _int)):
            return False
        if not all(isinstance(c, dict) and isinstance(c.get("key"), str) and _KEY.match(c["key"])
                   and _text(c.get("label"), 24) and c.get("type") in COL_TYPES for c in cols):
            return False
        return all(isinstance(r, dict) and isinstance(r.get("cells"), dict) and _opt(r, "link", _link)
                   and all(_KEY.match(str(k)) and (v is None or (isinstance(v, (int, float)) and not isinstance(v, bool))
                                                    or _text(v)) for k, v in r["cells"].items()) for r in rows)
    return False


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def check_view(v) -> dict | None:
    """Return the view with unknown block types dropped, or None when it breaks the contract."""
    if not (isinstance(v, dict) and v.get("schema") == "orch.addon-view/1" and isinstance(v.get("generated_at"), str)
            and _TIME.match(v["generated_at"]) and isinstance(v.get("blocks"), list) and len(v["blocks"]) <= 20
            and _opt(v, "notice", _text) and _opt(v, "notice_tone", _tone)):
        return None
    blocks = []
    for b in v["blocks"]:
        if isinstance(b, dict) and b.get("type") in BLOCKS:
            if not _block_ok(b):
                return None
            blocks.append(b)
        elif not isinstance(b, dict) or not isinstance(b.get("type"), str):
            return None
    return {**{k: v[k] for k in ("schema", "generated_at", "notice", "notice_tone") if k in v}, "blocks": blocks}


class ViewPuller:
    """One per server. `pull(name)` -> {"state": "ok"|"stale"|"error", "view", "as_of", "message"}."""

    def __init__(self, root: Path, orch_bin: str | None, timeout: float = TIMEOUT):
        self.root, self.orch_bin, self.timeout = root, orch_bin, timeout
        self.last: dict[str, dict] = {}
        self.lock = threading.Lock()

    def _run(self, name: str):
        if not self.orch_bin:
            return None, "The orch command was not found."
        try:
            p = subprocess.run([self.orch_bin, name, "view", "--json"], check=False, cwd=self.root, capture_output=True,
                               timeout=self.timeout, env={**os.environ, "ORCH_ROOT": str(self.root),
                                                          "ORCH_BIN": self.orch_bin, "ORCH_ADDON": name})
        except subprocess.TimeoutExpired:
            return None, "It took too long to answer."
        except OSError:
            return None, "The orch command could not be started."
        if len(p.stdout) > MAX_BYTES:
            return None, "The answer was too large."
        if p.returncode != 0:
            return None, "It could not be read right now."
        try:
            view = check_view(json.loads(p.stdout))
        except ValueError:
            view = None
        return (view, "") if view else (None, "The answer was not in the expected form.")

    def pull(self, name: str) -> dict:
        view, why = self._run(name)
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.lock:
            if view:
                self.last[name] = {"view": view, "fetched": time.time()}
                return {"state": "ok", "view": view, "as_of": view["generated_at"], "checked": now}
            old = self.last.get(name)
        if old:
            return {"state": "stale", "view": old["view"], "as_of": old["view"]["generated_at"], "checked": now,
                    "message": why}
        return {"state": "error", "view": None, "as_of": None, "checked": now, "message": why}
