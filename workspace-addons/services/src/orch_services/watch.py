"""Health check, failing and the one question (`orch services check`).

One pass, no loop and no sleep: the add-on's regular check (service.py, started by `orch start`) runs it every minute.
Per service the pass
- checks its health: the process is alive (driver state) and, with a `port`, the port answers on 127.0.0.1;
- counts failures in the last 10 minutes: a failed check, or a start the computer's service tool did by itself
  (launchd `runs`, systemd `NRestarts`); 3 of them = failing;
- raises ONE question (`orch ask`) on the ticket that made the service (or a ticket the add-on keeps for it), never a
  second one while it is open, and takes it back after 10 healthy minutes;
- acts once on the answer: Restart or Stop; Look into it changes nothing and only notes it on the ticket.

The numbers live in `.orch/addons/services/state/<id>.json` under `watch` (atomic write). Questions and state files
carry the service's name and counts only, never log text.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from . import drivers, store
from .store import Refused

WINDOW = 600  # seconds: failures counted in the last 10 minutes; healthy this long takes the question back
LIMIT = 3  # failures in the window that make a service failing
MANY = 5  # this many failures in the window: restarting again is not the answer, a person should look into it
PORT_TIMEOUT = 0.5
OPTIONS = ("Restart", "Stop", "Look into it")
BY = "agent:services"
QUESTION_KIND = "services:health"
MAX_EVENTS = 20


def clock() -> float:
    """Seconds since the epoch (tests replace it; no sleeping)."""
    return time.time()


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- health


def port_answers(port: int) -> bool:
    """A TCP connect to 127.0.0.1:<port> within half a second."""
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=PORT_TIMEOUT):
            return True
    except (OSError, ValueError):
        return False


def health(rec: dict, st: drivers.Status | None, wanted: bool = True) -> dict:
    """{"ok", "how", "text"} in plain words (the mockup's health line)."""
    port = rec.get("port")
    how = "answers on its address" if port else "process alive"
    alive = bool(st and st.running)
    if not wanted and not alive:
        return {"ok": False, "how": how, "text": "Stopped, so not checked"}
    if not alive:
        return {"ok": False, "how": how, "text": "Not alive"}
    if port and not port_answers(port):
        return {"ok": False, "how": how, "text": "Alive, but does not answer on its address"}
    return {"ok": True, "how": how, "text": "Answers on its address" if port else "Process alive"}


# ---------------------------------------------------------------- state


def read_state(root: Path, sid: str) -> dict:
    return store.read_state(root, sid)


def wanted_running(root: Path, sid: str, st: drivers.Status | None) -> bool:
    """What the person last asked for through orch; without a record, what the computer says now."""
    v = read_state(root, sid).get("running")
    return v if isinstance(v, bool) else bool(st and st.running)


def _watch(state: dict) -> dict:
    w = state.get("watch")
    w = dict(w) if isinstance(w, dict) else {}
    ev = w.get("events")
    w["events"] = [float(x) for x in ev if isinstance(x, (int, float))] if isinstance(ev, list) else []
    q = w.get("question")
    w["question"] = q if isinstance(q, dict) and isinstance(q.get("id"), str) else None
    w["failing"] = w.get("failing") is True
    return w


def _save_watch(root: Path, sid: str, w: dict) -> None:
    store.update_state(root, sid, watch=w)


def row_extra(root: Path, rec: dict, st: drivers.Status | None) -> dict:
    """What `list --json` adds to a row: health, failing and the open question (read-only, no orch calls)."""
    state = read_state(root, rec["id"])
    w = _watch(state)
    wanted = state.get("running") if isinstance(state.get("running"), bool) else bool(st and st.running)
    h = health(rec, st, wanted)
    failing = w["failing"] and wanted
    n = len([t for t in w["events"] if t > clock() - WINDOW]) if failing else 0
    if n and not h["ok"]:
        h["text"] += f": it failed {_times(n)} in the last 10 minutes"
    out: dict = {"health": h, "failing": failing, "question": None}
    q = w["question"]
    if failing and q and q.get("open"):
        ask = "Restart, Stop or Look into it?"
        out["question"] = {
            "ticket": q.get("ticket"),
            "id": q["id"],
            "title": _title(rec["name"]),
            "text": f"It failed {_times(n)} in the last 10 minutes. {ask}" if n else ask,
        }
    return out


def _times(n: int) -> str:
    return "once" if n == 1 else ("twice" if n == 2 else f"{n} times")


def _title(name: str) -> str:
    return f"{name} keeps stopping"


def question_text(name: str, n: int) -> str:
    return f"{_title(name)}: it failed {_times(n)} in the last 10 minutes. Restart, Stop or Look into it?"


# ---------------------------------------------------------------- the core, through its public CLI only


def orch(root: Path, *args: str, write: bool = False):
    """`orch <args> --json` (`$ORCH_BIN`, else `orch`); the answer as JSON, Refused with the core's sentence."""
    import json

    cmd = [os.environ.get("ORCH_BIN") or "orch", *args, "--json"] + (["--by", BY] if write else [])
    try:
        cp = subprocess.run(
            cmd,
            cwd=root,
            env=dict(os.environ, ORCH_ROOT=str(root)),
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise Refused("orch could not be reached. Try again in a moment.") from None
    try:
        value = json.loads(cp.stdout)
    except ValueError:
        raise Refused("orch did not give a readable answer. Try again in a moment.") from None
    if cp.returncode:
        msg = value.get("error") if isinstance(value, dict) else None
        raise Refused(msg or "orch refused the request.")
    return value


def _own_ticket(root: Path, name: str) -> str:
    """The ticket the add-on keeps for a service no ticket made: found by its title, else made."""
    title = f"Services: {name} keeps stopping"
    listing = orch(root, "ticket", "list", "--all")
    rows = listing.get("tickets", []) if isinstance(listing, dict) else listing
    for t in rows if isinstance(rows, list) else []:
        if isinstance(t, dict) and t.get("title") == title and isinstance(t.get("id"), str):
            return t["id"]
    t = orch(root, "ticket", "new", title, write=True)
    t = t.get("ticket", t) if isinstance(t, dict) else {}
    if not isinstance(t.get("id"), str):
        raise Refused("orch did not say which ticket it made. Try again in a moment.")
    return t["id"]


def _ticket_for(root: Path, rec: dict) -> str:
    mb = rec.get("made_by")
    if isinstance(mb, dict) and isinstance(mb.get("ticket"), str) and mb["ticket"]:
        return mb["ticket"]
    return _own_ticket(root, rec["name"])


def _question(root: Path, ticket: str, qid: str) -> dict | None:
    t = orch(root, "ticket", "show", ticket)
    t = t.get("ticket", t) if isinstance(t, dict) else {}
    for q in t.get("questions") or []:
        if isinstance(q, dict) and q.get("id") == qid:
            return q
    return None


# ---------------------------------------------------------------- one pass


def _act_on_answer(root: Path, drv, rec: dict, spec, w: dict) -> str | None:
    """Read the open question; act once on its answer. Returns what happened (plain words) or None."""
    q = w["question"]
    if not q or not q.get("open"):
        return None
    got = _question(root, q["ticket"], q["id"])
    if got is None or got.get("taken_back"):
        q["open"] = False  # gone or taken back by someone: nothing to act on, no new question this time
        _save_watch(root, rec["id"], w)
        return None
    answer = got.get("answer")
    if answer is None:
        return None
    q["open"] = False
    q["answer"] = str(answer)[:40]
    _save_watch(root, rec["id"], w)  # written before acting: an answer is acted on once, never twice
    word = str(answer).strip().lower()
    if word in ("restart", "stop"):
        try:
            getattr(drv, word)(spec)
        except Refused as e:  # the answer is used up: say why on the ticket and ask again on the next pass
            w["question"] = None
            _save_watch(root, rec["id"], w)
            try:  # the tool's own words stay in this output, not on the ticket
                orch(
                    root,
                    "log",
                    q["ticket"],
                    f"{rec['name']}: could not {word} it. orch asks again.",
                    write=True,
                )
            except Refused:
                pass
            return f"Could not {word} {rec['name']} ({e}); orch asks again (answer on {q['ticket']})."
    if word == "restart":
        store.mark(root, rec["id"], True)
        _rebase(drv, spec, w)
        w.update(failing=False, events=[], healthy_since=None, question=None)
        _save_watch(root, rec["id"], w)
        return f"Restarted {rec['name']} (answer on {q['ticket']})."
    if word == "stop":
        store.mark(root, rec["id"], False)
        w.update(failing=False, events=[], healthy_since=None, question=None)
        _save_watch(root, rec["id"], w)
        return f"Stopped {rec['name']} (answer on {q['ticket']})."
    orch(
        root,
        "log",
        q["ticket"],
        f"{rec['name']}: the answer was Look into it, so orch left it as it is.",
        write=True,
    )
    return f"Left {rec['name']} as it is for you to look into (answer on {q['ticket']})."


def _runs(drv, spec) -> int | None:
    f = getattr(drv, "runs", None)
    if f is None:
        return None
    try:
        n = f(spec)
    except Refused:
        return None
    return n if isinstance(n, int) and n >= 0 else None


def _rebase(drv, spec, w: dict) -> None:
    """A start through orch is not a failure: count the computer's own restarts from here."""
    w["runs"] = _runs(drv, spec)


def note_own_start(root: Path, drv, spec) -> None:
    """Called after start / restart through orch."""
    w = _watch(read_state(root, spec.sid))
    _rebase(drv, spec, w)
    _save_watch(root, spec.sid, w)


def check_one(root: Path, drv, rec: dict, spec) -> dict:
    """One service: health, counting, the question and its answer. Returns the row extras plus `did`."""
    sid = rec["id"]
    now = clock()
    w = _watch(read_state(root, sid))
    did = _act_on_answer(root, drv, rec, spec, w)

    st = drv.status(spec)
    wanted = wanted_running(root, sid, st)
    h = health(rec, st, wanted)
    if not wanted:  # stopped by the person: nothing to watch; an open question is no longer needed
        if w["question"] and w["question"].get("open"):
            _take_back(root, w, f"{rec['name']} was stopped.")
        w.update(failing=False, events=[], healthy_since=None, question=None)
        w["runs"] = _runs(drv, spec)
        _save_watch(root, sid, w)
        return {"id": sid, "name": rec["name"], "health": h, "failing": False, "did": did}

    events = [t for t in w["events"] if t > now - WINDOW]
    new = 0
    runs = _runs(drv, spec)
    last = w.get("runs")
    if isinstance(runs, int) and isinstance(last, int) and runs > last:
        new = min(runs - last, MAX_EVENTS)  # the computer started it again by itself
    if not h["ok"]:
        new = max(new, 1)  # one stop seen twice (not alive now, and started again) is still one failure
    w["runs"] = runs
    w["events"] = (events + [now] * new)[-MAX_EVENTS:]

    if not new:  # healthy = alive, answering and not started again since the last pass
        w["healthy_since"] = w.get("healthy_since") or now
    else:
        w["healthy_since"] = None
    if len(w["events"]) >= LIMIT:
        w["failing"] = True
    if w["failing"] and w.get("healthy_since") and now - w["healthy_since"] >= WINDOW:
        if w["question"] and w["question"].get("open"):
            _take_back(root, w, f"{rec['name']} runs fine again for 10 minutes.")
        w.update(failing=False, events=[], question=None)
        did = did or f"{rec['name']} runs fine again."

    _save_watch(root, sid, w)  # the counts are kept even when asking is refused below
    if w["failing"] and w["question"] is None:
        ticket = _ticket_for(root, rec)
        n = len([t for t in w["events"] if t > now - WINDOW])
        q = orch(
            root,
            "ask",
            ticket,
            question_text(rec["name"], max(n, LIMIT)),
            *(x for o in OPTIONS for x in ("--option", o)),
            "--recommend",
            "Look into it" if n >= MANY else "Restart",
            "--kind",
            QUESTION_KIND,  # an add-on's own question: Services picks up the answer, no helper is started
            write=True,
        )
        q = q.get("question", q) if isinstance(q, dict) else {}
        if not isinstance(q.get("id"), str):
            raise Refused("orch did not say which question it asked. Try again in a moment.")
        w["question"] = {"ticket": ticket, "id": q["id"], "open": True, "asked_at": _iso(now)}
        did = did or f"Asked about {rec['name']} on {ticket}."
    _save_watch(root, sid, w)
    return {"id": sid, "name": rec["name"], "health": h, "failing": w["failing"], "did": did}


def _take_back(root: Path, w: dict, why: str) -> None:
    q = w["question"]
    try:
        orch(root, "ask", q["ticket"], why, "--take-back", q["id"], write=True)
    except Refused:
        pass  # answered or taken back meanwhile: the episode is over either way, nothing is acted on
    q["open"] = False
