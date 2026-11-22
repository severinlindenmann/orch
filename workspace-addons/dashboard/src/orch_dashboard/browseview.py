"""The browser add-on's live view in the dashboard (ORCH-1493, watch only).

The dashboard relays the ticket's broker `watch` stream as server-sent events, the same way as the browser
terminal (ORCH-743): GET /api/browse/stream behind the same-origin check and the sign-in (checked again at every
heartbeat), POST /api/browse/stop behind the action fence and the person's session. The broker is found through
the browse add-on's own files; its key never leaves this computer's processes and never reaches the page.
Frames are relayed, never stored. A signed-in person sees every ticket's browser, as with terminals.

Take over and give back (ORCH-1495): each person's stream gets a page id the broker mints (said in its hello only,
never in a file; an add-on frame's stream gets none). POST
/api/browse/take, /api/browse/give and /api/browse/input (server.py: the action fence, the person's own session, no
add-on frame, JSON only, size caps, exact fields) pass on to the broker with that page id and the owner epoch; the
broker decides (only the page that took over types, the epoch is checked again before each event). When the
stream ends (the page closed, its sign-in ended) the broker's watch ends with it and a take-over pauses. Typed text
is passed on, never logged or kept.
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
EVENTS = frozenset({"hello", "control", "tabs", "frame", "clear", "event", "beat", "end"})
_GEN = re.compile(r"^[0-9a-f]{16}$")
ACTIONS = frozenset({"take", "renew", "cancel"})
MAX_FRAME_SIDE = 4000
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


def _title(root: Path, tid: str) -> str:
    """The ticket's title for the Browser page (the page may not have every ticket loaded)."""
    try:
        doc = json.loads((root / ".orch" / "tickets" / f"{tid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    t = doc.get("title") if isinstance(doc, dict) else None
    return t.strip()[:200] if isinstance(t, str) else ""


def listing(root: Path, now: float | None = None) -> dict:
    """Every ticket's browser for the Browser page and the small previews (ORCH-1494): {"on", "browsers": [{ticket,
    open, title, generation?, started?, ended?, why?}]}, open ones first, then ended in the last day, newest first. Times
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
            ctl = st.get("control") if isinstance(st.get("control"), dict) else {}
            if ctl.get("state") in ("finishing", "person", "paused"):  # who drives (ORCH-1495)
                row["control"] = ctl["state"]
            if isinstance(ctl.get("asking"), str) and ctl["asking"].strip():  # the helper asks for a person
                row["asking"] = ctl["asking"].strip()[:300]
            rows.append(row)
        elif st.get("state") == "ended" and now - at <= RECENT:
            rows.append({"ticket": d.name, "open": False, "ended": at, "why": str(st.get("why", ""))[:200]})
    rows.sort(key=lambda r: (not r["open"], -(r.get("started") or r.get("ended") or 0)))
    rows = rows[:MAX_LIST]
    for r in rows:
        r["title"] = _title(root, r["ticket"])
    return {"on": True, "browsers": rows}


def _event(kind: str, data: dict) -> bytes:
    return f"event: {kind}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


def stream(
    root: Path, ref: str, write: Callable[[bytes], None], gone: Callable[[], bool], person: bool = False
) -> str | None:
    """Relay one watcher. Returns "busy" when too many streams are open (the caller answers 503). person: a
    person's own page (the broker gives it a page id in its hello; a take over names it)."""
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
        for msg in ch.watch(d, stop_after=HEARTBEAT * 2, person=person):
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


def _int(v, lo: int, hi: int) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def person(root: Path, cmd: str, body: dict) -> tuple[int, str]:
    """POST /api/browse/take | give | input (ORCH-1495), the body already read with exactly its fields: check the
    values, then the broker decides. 200 + its JSON answer, 409 + its plain-words refusal, 404 no browser."""
    ch = _channel()
    if ch is None or not hasattr(ch, "person"):
        return 404, NOT_ON
    ticket, gen, page, epoch = body.get("ticket"), body.get("generation"), body.get("page"), body.get("epoch")
    if (
        not isinstance(ticket, str)
        or not isinstance(gen, str)
        or not _GEN.match(gen)
        or not isinstance(page, str)
        or not 0 < len(page) <= 64
        or not _int(epoch, 0, 1 << 40)
    ):
        return 400, "That request could not be read."
    args = [gen, page, str(epoch)]
    if cmd == "take":
        if body.get("action") not in ACTIONS:
            return 400, "That request could not be read."
        args.append(body["action"])
    elif cmd == "send":  # the broker's take command, action send, with the ticked site
        site = body.get("site")
        if not isinstance(site, str) or len(site) > 253 or not re.fullmatch(r"[a-z0-9.-]*", site):
            return 400, "That request could not be read."
        args += ["send", site]
    elif cmd == "input":
        w, h, events = body.get("w"), body.get("h"), body.get("events")
        if not _int(w, 1, MAX_FRAME_SIDE) or not _int(h, 1, MAX_FRAME_SIDE) or not isinstance(events, list):
            return 400, "That request could not be read."
        args.append(json.dumps({"w": w, "h": h, "events": events}, separators=(",", ":")))
    elif cmd != "give":
        return 400, "That request could not be read."
    d = run_dir(root, ticket)
    if d is None:
        return 404, NO_BROWSER
    r = ch.person(d, "take" if cmd == "send" else cmd, args)
    if r is None:
        return 404, NO_BROWSER
    if not r.get("ok"):
        return 409, str(r.get("out", ""))[:300]
    try:
        doc = json.loads(r.get("out") or "{}")
    except ValueError:
        return 409, "That did not work. Try again."
    out = {
        k: doc[k]
        for k in ("state", "epoch", "mine", "since", "asking", "send_site", "sent", "dropped", "text")
        if k in doc
    }
    return 200, json.dumps(out)
