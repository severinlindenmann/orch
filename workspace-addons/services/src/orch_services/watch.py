"""Health check, failing and the one question (`orch services check`).

One pass, no loop and no sleep: the add-on's regular check (service.py, started by `orch start`) runs it every minute.
Per service the pass
- checks its health: the process is alive (driver state) and, with a `port`, the port answers on 127.0.0.1 and the
  program listening there is the service's own process or one it started (another program on the port is no answer);
- counts failures in the last 10 minutes: a failed check, or a start the computer's service tool did by itself
  (launchd `runs`, systemd `NRestarts`); 3 of them = failing;
- raises ONE question (`orch ask`) on the ticket that made the service (or a ticket the add-on keeps for it), never a
  second one while it is open, and takes it back after 10 healthy minutes;
- acts once on the answer: Restart or Stop; Look into it changes nothing and only notes it on the ticket.

The numbers live in `.orch/addons/services/state/<id>.json` under `watch` (atomic write). Questions and state files
carry the service's name, counts and the record's own `depends` lines only, never log text.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from . import drivers, store
from .store import Refused

WINDOW = 600  # seconds: failures counted in the last 10 minutes; healthy this long takes the question back
LIMIT = 3  # failures in the window that make a service failing
MANY = 5  # this many failures in the window: restarting again is not the answer, a person should look into it
PORT_TIMEOUT = 0.5
OWNER_TIMEOUT = 3  # seconds lsof / ps get to say who listens on the port
START_GRACE = (
    90  # seconds after a start or restart through orch in which a silent port is "Starting", not a failure
)
OPTIONS = ("Restart", "Stop", "Look into it")
BY = "agent:services"
QUESTION_KIND = "services:health"
MAX_EVENTS = 20
STALE = 300  # seconds: the regular check runs every minute; a last check older than this is out of date
RECOVERED_SHOWN = 3600  # seconds the page says a failing service runs fine again
AFFECTED_CHARS = 100  # the affected work in one alert sentence, so the count and the suggestion still fit


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


# addresses lsof prints for a listener that takes a connect to 127.0.0.1 (the health probe's address)
LOOPBACK_V4 = ("127.0.0.1", "*", "0.0.0.0", "[::]", "[::ffff:127.0.0.1]")
IPV6_FORMS = ("[::]", "[::ffff:127.0.0.1]")


def _lsof() -> str:
    """lsof by full path: macOS keeps it in /usr/sbin, which a job's or helper's PATH often leaves out."""
    for p in ("/usr/sbin/lsof", "/usr/bin/lsof", "/sbin/lsof", "/bin/lsof"):
        if os.access(p, os.X_OK):
            return p
    return shutil.which("lsof") or "lsof"


def listeners(port: int) -> set[int] | None:
    """The process ids listening on TCP 127.0.0.1:<port> or on every address (lsof), or None when this computer
    cannot say (Windows, no lsof). A listener on ::1 or another address only does not take the probe's connect."""
    if sys.platform == "win32":
        return None
    try:
        cp = subprocess.run(
            [_lsof(), "-nP", "-Fpnt", f"-iTCP:{int(port)}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=OWNER_TIMEOUT,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if cp.returncode not in (0, 1):
        return None
    return parse_lsof(cp.stdout, int(port))


def _tier(host: str, family: str | None) -> int | None:
    """Which listener the computer gives a connect to 127.0.0.1: 0 an exact 127.0.0.1 one, else 1 an IPv4 one on
    every address, else 2 an IPv6 one on every address (it takes IPv4 too unless it is IPv6-only). lsof shows
    both wildcards as `*`; its type line (IPv4 / IPv6) tells them apart. None: it does not take the connect."""
    if host not in LOOPBACK_V4:
        return None
    if host == "127.0.0.1":
        return 0
    if host in IPV6_FORMS or family == "IPv6":
        return 2
    return 1


def parse_lsof(text: str, port: int) -> set[int]:
    """`lsof -Fpnt` lines (p<pid>, then t<type> and n<address>:<port> per socket) -> the pids that take a connect
    to 127.0.0.1:<port>: only those of the most exact kind of listener, so a service listening on IPv6 only does
    not count as answering while another program holds 127.0.0.1 (ORCH-1189 review)."""
    best: dict[int, set[int]] = {}
    pid, family = None, None
    for line in text.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid, family = int(line[1:]), None
        elif line.startswith("f"):
            family = None
        elif line.startswith("t"):
            family = line[1:]
        elif line.startswith("n") and pid is not None:
            host, _, num = line[1:].rpartition(":")
            tier = _tier(host, family) if num == str(port) else None
            if tier is not None:
                best.setdefault(tier, set()).add(pid)
    return best[min(best)] if best else set()


def parents() -> dict[int, int] | None:
    """Every process's parent id (ps), or None when it cannot be read."""
    try:
        cp = subprocess.run(
            ["ps", "-axo", "pid=,ppid="],
            capture_output=True,
            text=True,
            timeout=OWNER_TIMEOUT,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if cp.returncode != 0:
        return None
    out: dict[int, int] = {}
    for line in cp.stdout.splitlines():
        bits = line.split()
        if len(bits) == 2 and bits[0].isdigit() and bits[1].isdigit():
            out[int(bits[0])] = int(bits[1])
    return out


def owns_port(pid: int | None, port: int) -> bool | None:
    """True when the service's process (or one it started, e.g. uv run -> python) listens on the port, False when
    only other programs do, None when this computer cannot tell (then the port answering is taken as before)."""
    if not pid:
        return None
    found = listeners(port)
    if found is None:
        return None
    if pid in found:
        return True
    if not found:  # it answers, but no process of this account listens: someone else's program
        return False
    tree = parents()
    if tree is None:
        return None
    for p in found:
        for _ in range(64):  # walk up to the root; a loop in the table cannot hang
            p = tree.get(p, 0)
            if p == pid:
                return True
            if p <= 1:
                break
    return False


def just_started(root: Path, sid: str) -> bool:
    """True within START_GRACE seconds of the last start or restart through orch."""
    since = store.last_change(root, sid)
    try:
        t = datetime.strptime(since, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp() if since else None
    except ValueError:
        t = None
    return t is not None and 0 <= clock() - t < START_GRACE


def health(rec: dict, st: drivers.Status | None, wanted: bool = True, starting: bool = False) -> dict:
    """{"ok", "how", "text"} in plain words (the mockup's health line). `starting`: just started through orch."""
    port = rec.get("port")
    how = "answers on its address" if port else "process alive"
    alive = bool(st and st.running)
    if not wanted and not alive:
        return {"ok": False, "how": how, "text": "Stopped, so not checked"}
    if not alive:
        return {"ok": False, "how": how, "text": "Not alive"}
    if port and not port_answers(port):
        if starting:
            return {"ok": False, "starting": True, "how": how, "text": "Starting…"}
        return {"ok": False, "how": how, "text": "Alive, but does not answer on its address"}
    if port and owns_port(st.pid, port) is False:
        return {"ok": False, "how": how, "text": "Alive, but another program answers on its address"}
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


def depends_of(rec: dict) -> list[str]:
    """The work known to rely on a service: the record's own `depends` lines (written by hand or by the ticket's
    helper), never guessed from its name, command or ticket. Plain text, at most 6 lines of 80 characters."""
    raw = rec.get("depends")
    if not isinstance(raw, list):
        return []
    out = []
    for d in raw:
        if isinstance(d, str):
            t = " ".join(d.replace("<", "‹").replace(">", "›").split())
            if t:
                out.append(t if len(t) <= 80 else t[:79] + "…")
    return out[:6]


def affected_text(depends: list[str]) -> str:
    """One sentence: the affected work, or that it is not known."""
    if not depends:
        return "What it affects is not known."
    t = ", ".join(depends)
    return f"Affected: {t if len(t) <= AFFECTED_CHARS else t[: AFFECTED_CHARS - 1] + '…'}."


def _stamp_age(stamp: object) -> float | None:
    try:
        t = datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return None
    return clock() - t


def row_extra(root: Path, rec: dict, st: drivers.Status | None) -> dict:
    """What `list --json` adds to a row: health, failing, the open question, when it was last checked (stale when
    that is out of date) and `recovered` while a failing service runs fine again (read-only, no orch calls)."""
    state = read_state(root, rec["id"])
    w = _watch(state)
    wanted = state.get("running") if isinstance(state.get("running"), bool) else bool(st and st.running)
    h = health(rec, st, wanted, just_started(root, rec["id"]))
    failing = w["failing"] and wanted
    age = _stamp_age(w.get("checked_at")) if w.get("checked_at") else None
    stale = age is not None and age > STALE
    n = len([t for t in w["events"] if t > clock() - WINDOW]) if failing and not stale else 0
    if n and not h["ok"]:
        h["text"] += f": it failed {_times(n)} in the last 10 minutes"
    out: dict = {
        "health": h,
        "failing": failing,
        "question": None,
        "checked_at": w.get("checked_at"),
        "stale": stale,
        "recovered": None,
    }
    q = w["question"]
    if failing and q and q.get("open"):
        suggested = q.get("suggested") if q.get("suggested") in OPTIONS else "Restart"
        if stale:
            count = "It was failing at the last check and orch has not checked it since."
        elif n:
            count = f"It failed {_times(n)} in the last 10 minutes."
        else:
            count = ""
        text = " ".join(x for x in (affected_text(depends_of(rec)), count, f"Suggested: {suggested}.") if x)
        out["question"] = {
            "ticket": q.get("ticket"),
            "id": q["id"],
            "title": _title(shown_name(root, rec)),
            "text": text,
            "suggested": suggested,
        }
    back = w.get("recovered")
    back_age = _stamp_age(back.get("at")) if isinstance(back, dict) and back.get("at") else None
    if (
        not failing
        and wanted
        and not stale
        and h["ok"]
        and back_age is not None
        and back_age <= RECOVERED_SHOWN
    ):
        out["recovered"] = {"since": back.get("since") or back["at"]}
    return out


def _times(n: int) -> str:
    return "once" if n == 1 else ("twice" if n == 2 else f"{n} times")


def _title(name: str) -> str:
    return f"{name} keeps stopping"


def shown_name(root: Path, rec: dict) -> str:
    """The service's name in its question; with its id when another service has the same name, so each one gets
    its own question and an answer acts on that one only (ORCH-1683)."""
    recs, _ = store.load_all(root)
    twin = any(r.get("name") == rec["name"] and r.get("id") != rec["id"] for r in recs)
    return f"{rec['name']} ({rec['id']})" if twin else rec["name"]


def question_text(name: str, n: int, depends: list[str] | None = None) -> str:
    return (
        f"{_title(name)}: it failed {_times(n)} in the last 10 minutes. {affected_text(depends or [])}"
        " Restart, Stop or Look into it?"
    )


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


def _open_asked(root: Path, ticket: str, shown: str) -> str | None:
    """The id of an open question this add-on asked on the ticket about this service, else None. A pass that
    stopped between asking and saving the id (killed, sleep) left it there; its count differs from today's, so
    the core's "same open question" check would not catch a second one (#1401)."""
    t = orch(root, "ticket", "show", ticket)
    t = t.get("ticket", t) if isinstance(t, dict) else {}
    head = f"{_title(shown)}: "
    for q in t.get("questions") or []:
        if (
            isinstance(q, dict)
            and isinstance(q.get("id"), str)
            and q.get("kind") == QUESTION_KIND
            and q.get("answer") is None
            and not q.get("taken_back")
            and str(q.get("text") or "").startswith(head)
        ):
            return q["id"]
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
                    f"{shown_name(root, rec)}: could not {word} it. orch asks again.",
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
        f"{shown_name(root, rec)}: the answer was Look into it, so orch left it as it is.",
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
    w["checked_at"] = _iso(now)  # the page tells a fresh check from data that is out of date
    did = _act_on_answer(root, drv, rec, spec, w)

    st = drv.status(spec)
    wanted = wanted_running(root, sid, st)
    h = health(rec, st, wanted, just_started(root, sid))
    if not wanted:  # stopped by the person: nothing to watch; an open question is no longer needed
        if w["question"] and w["question"].get("open"):
            _take_back(root, w, f"{rec['name']} was stopped.")
        w.update(failing=False, events=[], healthy_since=None, question=None, recovered=None)
        w["runs"] = _runs(drv, spec)
        _save_watch(root, sid, w)
        return {"id": sid, "name": rec["name"], "health": h, "failing": False, "did": did}

    events = [t for t in w["events"] if t > now - WINDOW]
    new = 0
    runs = _runs(drv, spec)
    last = w.get("runs")
    if isinstance(runs, int) and isinstance(last, int) and runs > last:
        new = min(runs - last, MAX_EVENTS)  # the computer started it again by itself
    if not h["ok"] and not h.get("starting"):
        new = max(new, 1)  # one stop seen twice (not alive now, and started again) is still one failure
    w["runs"] = runs
    w["events"] = (events + [now] * new)[-MAX_EVENTS:]

    if not new and h["ok"]:  # healthy = alive, answering and not started again; Starting… is not healthy yet
        w["healthy_since"] = w.get("healthy_since") or now
    else:
        w["healthy_since"] = None
    if len(w["events"]) >= LIMIT:
        w["failing"] = True
        w["recovered"] = None
    if w["failing"] and w.get("healthy_since") and now - w["healthy_since"] >= WINDOW:
        if w["question"] and w["question"].get("open"):
            _take_back(root, w, f"{rec['name']} runs fine again for 10 minutes.")
        w["recovered"] = {"at": _iso(now), "since": _iso(w["healthy_since"])}
        w.update(failing=False, events=[], question=None)
        did = did or f"{rec['name']} runs fine again."

    _save_watch(root, sid, w)  # the counts are kept even when asking is refused below
    if w["failing"] and w["question"] is None:
        ticket = _ticket_for(root, rec)
        n = len([t for t in w["events"] if t > now - WINDOW])
        shown = shown_name(root, rec)
        suggested = "Look into it" if n >= MANY else "Restart"
        qid = _open_asked(root, ticket, shown)  # asked before, but that pass ended before it saved the id
        if qid is None:
            q = orch(
                root,
                "ask",
                ticket,
                question_text(shown, max(n, LIMIT), depends_of(rec)),
                *(x for o in OPTIONS for x in ("--option", o)),
                "--recommend",
                suggested,
                "--kind",
                QUESTION_KIND,  # an add-on's own question: Services picks up the answer, no helper is started
                write=True,
            )
            q = q.get("question", q) if isinstance(q, dict) else {}
            if not isinstance(q.get("id"), str):
                raise Refused("orch did not say which question it asked. Try again in a moment.")
            qid = q["id"]
        w["question"] = {
            "ticket": ticket,
            "id": qid,
            "open": True,
            "asked_at": _iso(now),
            "suggested": suggested,
        }
        did = did or f"Asked about {rec['name']} on {ticket}."
    _save_watch(root, sid, w)
    return {
        "id": sid,
        "name": rec["name"],
        "health": h,
        "failing": w["failing"],
        "did": did,
        "unhealthy": not h[
            "ok"
        ],  # `check` says it even before it counts as failing (never "all as expected")
    }


def _take_back(root: Path, w: dict, why: str) -> None:
    q = w["question"]
    try:
        orch(root, "ask", q["ticket"], why, "--take-back", q["id"], write=True)
    except Refused:
        pass  # answered or taken back meanwhile: the episode is over either way, nothing is acted on
    q["open"] = False
