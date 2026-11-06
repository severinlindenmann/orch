"""Pull an add-on view: `orch <name> view --json` (2 s, 256 KB), check it, keep the last good one in memory.
The dashboard never imports add-on code and never shows anything that failed the check."""
from __future__ import annotations

import json
import os
import re
import signal
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


_OP = re.compile(r"^[a-z][a-z.]{0,31}$")


def _keys_only(d, allowed):
    return isinstance(d, dict) and set(d) <= set(allowed)


def _action(a):
    """{op, args}: flat scalars only; never a command line (extra keys such as `command` break the view)."""
    if not (_keys_only(a, ("op", "args")) and isinstance(a.get("op"), str) and _OP.match(a["op"])):
        return False
    args = a.get("args", {})
    return isinstance(args, dict) and len(args) <= 6 and all(
        _KEY.match(str(k)) and (isinstance(v, (bool, int, float))
                                or (isinstance(v, str) and len(v) <= 200 and "<" not in v and ">" not in v))
        for k, v in args.items())


def _detail_ok(d):
    # Copy copies `value`: a row that shows `lines` instead must not carry a hidden value to copy.
    if isinstance(d, dict) and d.get("copy") and ("lines" in d or "value" not in d):
        return False
    return _keys_only(d, ("label", "value", "lines", "tone", "copy")) and _text(d.get("label"), 30) \
        and _opt(d, "value", _text) and _opt(d, "tone", _tone) and _opt(d, "copy", lambda v: isinstance(v, bool)) \
        and _opt(d, "lines", lambda v: isinstance(v, list) and len(v) <= 5 and all(_text(x) for x in v))


def _ticket_ref_ok(t):
    return _keys_only(t, ("id", "key", "title", "status")) and isinstance(t.get("id"), str) \
        and bool(re.match(r"^t_[a-z0-9]{6,16}$", t["id"])) and _text(t.get("title")) and _opt(t, "key", lambda v: _text(v, 24)) \
        and _opt(t, "status", _chip)


def _toggle_ok(t):
    return _keys_only(t, ("on", "label", "action")) and isinstance(t.get("on"), bool) and _text(t.get("label"), 60) \
        and _action(t.get("action"))


def _row_action_ok(a):
    return _keys_only(a, ("label", "action", "confirm", "tone")) and _text(a.get("label"), 30) and _action(a.get("action")) \
        and _opt(a, "confirm", lambda v: _text(v, 80)) and a.get("tone", "neutral") in ("neutral", "bad")


def _accordion_ok(i):
    return _opt(i, "detail", lambda v: isinstance(v, list) and len(v) <= 12 and all(map(_detail_ok, v))) \
        and _opt(i, "tickets", lambda v: isinstance(v, list) and len(v) <= 10 and all(map(_ticket_ref_ok, v))) \
        and _opt(i, "toggle", _toggle_ok) \
        and _opt(i, "actions", lambda v: isinstance(v, list) and len(v) <= 4 and all(map(_row_action_ok, v)))


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
                             and _opt(i, "chips", lambda c: isinstance(c, list) and len(c) <= 6 and all(map(_chip, c)))
                             and _accordion_ok(i))
                    for i in items)
    if t == "calendar":
        days = b.get("days")
        return isinstance(days, list) and len(days) <= 14 and all(
            isinstance(d, dict) and isinstance(d.get("date"), str) and _DATE.match(d["date"])
            and isinstance(d.get("items"), list) and len(d["items"]) <= 20
            and all(_item_ok(i, ("title",), lambda i: _text(i["title"], 80)
                             and _opt(i, "time", lambda v: isinstance(v, str) and bool(_HM.match(v)))
                             and _opt(i, "every", lambda v: _text(v, 24)) and _opt(i, "note", lambda v: _text(v, 60)))
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
        self.inflight: dict[str, dict] = {}
        self.lock = threading.Lock()

    def _run(self, name: str):
        if not self.orch_bin:
            return None, "The orch command was not found."
        env = {**os.environ, "ORCH_ROOT": str(self.root), "ORCH_BIN": self.orch_bin, "ORCH_ADDON": name}
        try:  # own session: on timeout or too much output the whole process group is killed
            p = subprocess.Popen([self.orch_bin, name, "view", "--json"], cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            return None, "The orch command could not be started."
        chunks: list[bytes] = []
        state = {"n": 0, "big": False}

        def kill():
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

        def read():  # hard cap while reading, not after
            while True:
                data = p.stdout.read1(65536)
                if not data:
                    return
                state["n"] += len(data)
                if state["n"] > MAX_BYTES:
                    state["big"] = True
                    kill()
                    return
                chunks.append(data)

        t = threading.Thread(target=read, daemon=True)
        t.start()
        t.join(self.timeout)
        timed_out = t.is_alive()
        if timed_out:
            kill()
        kill()  # also catches children that outlive the add-on process
        t.join(1)
        p.wait()
        p.stdout.close()
        if state["big"]:
            return None, "The answer was too large."
        if timed_out:
            return None, "It took too long to answer."
        if p.returncode != 0:
            return None, "It could not be read right now."
        try:
            view = check_view(json.loads(b"".join(chunks)))
        except ValueError:
            view = None
        return (view, "") if view else (None, "The answer was not in the expected form.")

    def pull(self, name: str) -> dict:
        """One pull per add-on at a time: concurrent callers wait for the one in flight and share its result."""
        with self.lock:
            flight = self.inflight.get(name)
            mine = flight is None
            if mine:
                flight = self.inflight[name] = {"done": threading.Event(), "result": None}
        if not mine:
            flight["done"].wait(self.timeout + 5)
            return flight["result"] or self._cached(name)
        try:
            flight["result"] = self._pull(name)
        finally:
            with self.lock:
                self.inflight.pop(name, None)
            flight["done"].set()
        return flight["result"]

    def _cached(self, name: str) -> dict:
        with self.lock:
            old = self.last.get(name)
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        if old:
            return {"state": "stale", "view": old["view"], "as_of": old["view"]["generated_at"], "checked": now,
                    "message": "It took too long to answer."}
        return {"state": "error", "view": None, "as_of": None, "checked": now, "message": "It took too long to answer."}

    def _pull(self, name: str) -> dict:
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
