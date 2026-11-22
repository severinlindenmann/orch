"""The browser add-on's live view in the dashboard (ORCH-1493, watch only).

The dashboard relays the ticket's broker `watch` stream as server-sent events, the same way as the browser
terminal (ORCH-743): GET /api/browse/stream behind the same-origin check and the sign-in (checked again at every
heartbeat), POST /api/browse/stop behind the action fence and the person's session. The broker is found through
the browse add-on's own files; its key never leaves this computer's processes and never reaches the page.
Frames are relayed, never stored. A signed-in person sees every ticket's browser, as with terminals.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path

MAX_STREAMS = 16
HEARTBEAT = 15
WRITE_TIMEOUT = 20  # seconds a page may take to read one message before its stream ends
_streams = threading.BoundedSemaphore(MAX_STREAMS)
_TID = re.compile(r"^t_[a-z0-9]{4,32}$")
EVENTS = frozenset({"hello", "tabs", "frame", "clear", "event", "beat", "end"})
NOT_ON = "The browser add-on is not turned on in this workspace."
NO_BROWSER = "No browser is open for this ticket."


def _channel():
    try:
        from orch_browse import channel  # the browse add-on, when it is installed
    except ImportError:
        return None
    return channel


def run_dir(root: Path, ref: str) -> Path | None:
    """The ticket's broker folder, or None for an unknown ticket or an odd folder (never follows a link)."""
    tid = (ref or "").strip()
    try:
        from orch import tickets

        tid = tickets.resolve(root, tid)
    except Exception:  # noqa: BLE001 - an unknown ticket is simply no browser
        return None
    if not _TID.match(tid):
        return None
    base = root / ".orch" / "addons" / "browse" / "run"
    d = base / tid
    if base.is_symlink() or d.is_symlink() or not d.is_dir():
        return None
    return d


def state(root: Path, ref: str) -> dict:
    """{"open", "generation"?, "why"?}: what the page shows before it watches. No key, no address."""
    d = run_dir(root, ref)
    if d is None or _channel() is None:
        return {"open": False}
    try:
        st = json.loads((d / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"open": False}
    if st.get("state") == "ready" and (d / "channel.json").exists():
        return {"open": True, "generation": str(st.get("generation", ""))[:32]}
    return {"open": False, "why": str(st.get("why", ""))[:200]}


RECENT = 24 * 3600  # an ended browser stays in the list (and as a quiet line on its ticket) this long
MAX_LIST = 60


def _on(root: Path) -> bool:
    """The browse add-on is installed here and turned on in this workspace."""
    if _channel() is None:
        return False
    try:
        from orch import addons

        return "browse" in addons.active(root)
    except Exception:  # noqa: BLE001 - no answer is "off"
        return False


def _alive(pid) -> bool:
    """The broker's process still runs (a killed broker leaves "ready" behind). No pid: trust the state."""
    if os.name == "nt" or not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return True  # on Windows signal 0 is Ctrl+C, never send it
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:  # alive but not ours to signal (or no signals on this system)
        return True
    return True


def listing(root: Path, now: float | None = None) -> dict:
    """Every ticket's browser for the Browser page and the small previews (ORCH-1494): {"on", "browsers": [{ticket,
    open, generation?, started?, ended?, why?}]}, open ones first, then ended in the last day, newest first. Times
    are epoch seconds; no key, no address, no page. A folder that is a link or not a ticket id is skipped."""
    if not _on(root):
        return {"on": False, "browsers": []}
    base = root / ".orch" / "addons" / "browse" / "run"
    now = time.time() if now is None else now
    rows = []
    try:
        dirs = [] if base.is_symlink() else [d for d in base.iterdir() if _TID.match(d.name)]
    except OSError:
        dirs = []
    for d in dirs:
        if d.is_symlink() or not d.is_dir():
            continue
        f = d / "state.json"
        try:
            st = json.loads(f.read_text(encoding="utf-8"))
            at = f.stat().st_mtime
        except (OSError, ValueError):
            continue
        if not isinstance(st, dict):
            continue
        if st.get("state") == "ready" and (d / "channel.json").exists() and _alive(st.get("pid")):
            started = st.get("started")
            row = {"ticket": d.name, "open": True, "generation": str(st.get("generation", ""))[:32]}
            row["started"] = float(started) if isinstance(started, (int, float)) else at
            rows.append(row)
        elif st.get("state") == "ended" and now - at <= RECENT:
            rows.append({"ticket": d.name, "open": False, "ended": at, "why": str(st.get("why", ""))[:200]})
    rows.sort(key=lambda r: (not r["open"], -(r.get("started") or r.get("ended") or 0)))
    return {"on": True, "browsers": rows[:MAX_LIST]}


def _event(kind: str, data: dict) -> bytes:
    return f"event: {kind}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


def stream(root: Path, ref: str, write: Callable[[bytes], None], gone: Callable[[], bool]) -> str | None:
    """Relay one watcher. Returns "busy" when too many streams are open (the caller answers 503)."""
    ch = _channel()
    if ch is None:
        write(_event("end", {"why": NOT_ON, "final": True}))
        return None
    d = run_dir(root, ref)
    if d is None:
        write(_event("end", {"why": NO_BROWSER, "final": False}))
        return None
    if not _streams.acquire(blocking=False):
        return "busy"
    try:
        got = False
        for msg in ch.watch(d, stop_after=HEARTBEAT * 2):
            got = True
            if gone():
                return None
            kind = msg.get("type")
            if kind not in EVENTS:
                continue
            data = {k: v for k, v in msg.items() if k != "type"}
            if kind == "end":
                data["final"] = True
            write(_event(kind, data))
            if kind == "end":
                return None
        if not got:
            write(_event("end", {"why": NO_BROWSER, "final": False}))
        elif not gone():
            write(_event("end", {"why": "The connection to the browser was lost.", "final": False}))
    finally:
        _streams.release()
    return None


def stop(root: Path, ref: str, generation: str) -> tuple[int, str]:
    ch = _channel()
    if ch is None:
        return 404, NOT_ON
    d = run_dir(root, ref)
    if d is None or not isinstance(generation, str) or not re.fullmatch(r"[0-9a-f]{16}", generation):
        return 404, NO_BROWSER
    r = ch.stop(d, generation)
    if r is None:
        return 404, NO_BROWSER
    return 200, json.dumps({"ok": bool(r.get("ok")), "text": str(r.get("out", ""))[:200]})
