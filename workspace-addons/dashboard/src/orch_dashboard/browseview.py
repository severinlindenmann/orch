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
    own = own_ticket(root)
    for r in rows:
        r["title"] = _title(root, r["ticket"])
        if r["ticket"] == own:  # the person's own browser (O-20): the page shows it as "Your browser"
            r["own"] = True
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
                data["final"] = not data.pop("busy", False)  # a full room is tried again later
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


# ---- Allowed sites and the person's own browser (O-20, O-21: owner, 28 Nov) -----------------------------------
# The Browser page shows which sites may open (the workspace's permanent list and each ticket's own), lets a
# person add (also a whole pasted list, read first as it would be stored), search and remove, and opens a browser
# for the person on those same sites. All of it goes through the browse add-on's own files and commands (the
# same ones `orch browse sites` and `orch browse open` use); a helper's session never reaches these routes.
SITES_BODY_MAX = 400 * 1024  # a pasted list of a few thousand addresses
SITES_TICKETS_MAX = 50
OPEN_MAX = 2048
NOT_PERSONS = "Only a person changes the allowed sites."


def _part(name: str):
    """A module of the browse add-on (paths, netcheck, cli), or None when it is not installed."""
    try:
        import importlib

        return importlib.import_module(f"orch_browse.{name}")
    except ImportError:
        return None


def _ticket_status(root: Path, tid: str) -> str:
    try:
        doc = json.loads((root / ".orch" / "tickets" / f"{tid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "missing"
    return str(doc.get("status") or "") if isinstance(doc, dict) else "missing"


def sites(root: Path) -> dict:
    """GET /api/browse/sites: {"on", "workspace": [site], "tickets": [{ticket, title, sites}], "error"?}. The
    workspace's list holds for every ticket; a ticket's own extra sites are listed while the ticket is open
    (not done or dropped). A site on both lists is shown once, as the workspace's."""
    paths = _part("paths")
    if paths is None or not _on(root):
        return {"on": False, "workspace": [], "tickets": []}
    out: dict = {"on": True, "workspace": [], "tickets": [], "max": paths.MAX_SITES}
    try:
        out["workspace"] = paths.load_workspace_sites(root)
    except (ValueError, OSError):
        out["error"] = "The workspace's site list is damaged, so no page opens until it is fixed."
    held = set(out["workspace"])
    folder = paths.base(root) / "sites"
    try:
        files = (
            [] if folder.is_symlink() else sorted(f for f in folder.glob("t_*.json") if _TID.match(f.stem))
        )
    except OSError:
        files = []
    for f in files:
        if f.is_symlink() or _ticket_status(root, f.stem) in ("missing", "done", "dropped", "superseded"):
            continue
        try:
            own = [s for s in paths.load_ticket_sites(root, f.stem) if s not in held]
        except (ValueError, OSError):
            continue
        if own:
            out["tickets"].append({"ticket": f.stem, "title": _title(root, f.stem), "sites": own})
        if len(out["tickets"]) >= SITES_TICKETS_MAX:
            break
    return out


def sites_change(root: Path, body: dict) -> tuple[int, str]:
    """POST /api/browse/sites {scope: "workspace" | "ticket", ticket, add, remove, check} (the person's session).
    add: a pasted text or a list of entries; remove: stored names. check true only reads the paste: what would be
    stored, what the stored name of an entry is when it differs ("*.20min.ch" is 20min.ch), what cannot be a
    site and why, and how many are on the list already. Without check the same reading is saved, unless an
    entry was refused (nothing is half added)."""
    paths, netcheck = _part("paths"), _part("netcheck")
    if paths is None or netcheck is None or not _on(root):
        return 404, NOT_ON
    scope, ticket, add, remove = body.get("scope"), body.get("ticket"), body.get("add"), body.get("remove")
    ok_add = isinstance(add, str) or (isinstance(add, list) and all(isinstance(x, str) for x in add))
    ok_remove = isinstance(remove, list) and all(isinstance(x, str) and len(x) <= 253 for x in remove)
    if (
        scope not in ("workspace", "ticket")
        or not ok_add
        or not ok_remove
        or not isinstance(body.get("check"), bool)
    ):
        return 400, "That request could not be read."
    tid = None
    if scope == "ticket":
        d = ticket if isinstance(ticket, str) and _TID.match(ticket) else ""
        if not d or _ticket_status(root, d) == "missing":
            return 404, "That ticket is not in this workspace."
        tid = d
    elif ticket is not None:
        return 400, "That request could not be read."
    try:
        current = paths.load_ticket_sites(root, tid) if tid else paths.load_workspace_sites(root)
    except (ValueError, OSError):
        current = []  # a damaged list is replaced by what the person saves now
    read = netcheck.norm_many(add)
    known = [s for s in read["sites"] if s in current]
    new = [s for s in read["sites"] if s not in current]
    doc = {
        "new": new,
        "known": len(known),
        "changed": read["changed"][:200],
        "refused": read["refused"][:200],
        "refused_count": len(read["refused"]),
        "repeats": read["repeats"],
        "saved": False,
    }
    if not body["check"] and not read["refused"]:
        gone = set(remove)
        after = sorted((set(current) | set(new)) - gone)
        if len(after) > paths.MAX_SITES:
            return 409, f"A list holds at most {paths.MAX_SITES} sites. Remove some first."
        if after != sorted(set(current)):
            try:
                paths.save_sites(root, tid, after) if tid else paths.save_workspace_sites(root, after)
            except (ValueError, OSError) as e:
                return 409, f"The list could not be saved ({str(e)[:120]}). Try again."
        doc["saved"] = True
        doc["removed"] = len(gone & set(current))
    return 200, json.dumps(doc)


def own_ticket(root: Path) -> str | None:
    """The ticket that holds the person's own browser: the workspace's Chat ticket (hidden, one per workspace).
    None before the first Chat text and when the core cannot be read."""
    try:
        from orch import tickets

        tid = tickets.general_id(root)
    except Exception:  # noqa: BLE001 - no answer is "none"
        return None
    return tid if isinstance(tid, str) and _TID.match(tid) else None


def open_own(root: Path, address) -> tuple[int, str]:
    """POST /api/browse/open {address} (O-20): a browser for the person, on the allowed sites only. It is the
    browse add-on's own `open` for the workspace's Chat ticket, so the same network filter and the same lists
    hold as for a helper; an address that is not on the list is refused here in plain words, before anything
    starts. Starting may take a moment (the add-on waits until the browser answers)."""
    cli, paths, netcheck = _part("cli"), _part("paths"), _part("netcheck")
    if cli is None or paths is None or netcheck is None or not _on(root):
        return 404, NOT_ON
    if not isinstance(address, str) or not 0 < len(address.strip()) <= OPEN_MAX:
        return 400, "Give the address of a site on the list."
    tid = own_ticket(root)
    if tid is None:
        return 409, "Write one message in Chat first: your browser belongs to this workspace's Chat."
    try:
        site = netcheck.norm_site(address)
        allowed = paths.load_sites(root, tid)
    except (ValueError, OSError) as e:
        return 409, f"That cannot open: {str(e)[:160]}."
    if not allowed:
        return 409, "No site is allowed yet. Add one under Allowed sites first."
    if not netcheck.site_allowed(site, allowed):
        return 409, f"{site} is not on the allowed sites. Add it under Allowed sites first."
    url = address.strip() if re.match(r"^https?://", address.strip(), re.IGNORECASE) else "https://" + site
    try:
        code, out = cli._browser(root, tid, "open", [url])
    except Exception as e:  # noqa: BLE001 - the add-on's own refusal says what to do (not downloaded, still starting)
        return 409, str(e)[:300] or "The browser did not start. Try again."
    if code != 0:
        return 409, str(out)[:300] or "The browser did not start. Try again."
    return 200, json.dumps({"ticket": tid, "site": site})
