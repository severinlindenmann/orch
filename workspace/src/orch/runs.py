"""One agent run per ticket on this machine: the claim, pending input, argv, start and wrap.

Files (all under .orch/run/, gitignored, per machine; contracts/run.schema.json, run-pending.schema.json):
  tickets/<tid>.json    the claim of the one run working on the ticket (missing = nobody)
  tickets/<tid>.lock    O_EXCL lock; every claim, renew, release, takeover and pending write holds it
  pending/<tid>.jsonl   input for a busy ticket, one line each, delivered once (deduped by id)
  logs/<tid>-<run>.log  output of a oneshot run

Rules: a claim with a pid is stale only when the pid is gone or alive with another start time. A claim
without a pid is "maybe stale" after the lease (30 min) with no orch write and is taken over only on request
(`--take-over`). A lease running out never starts an agent. Sessions live in the ticket (ticket.sessions[]).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from orch import adapters, services, tickets
from orch.errors import Refused

LEASE_SECONDS = 30 * 60
LOCK_STALE_SECONDS = 30
MAX_DRAIN_TURNS = 10
PENDING_KINDS = ("answer", "message", "event", "text")
_ALPHA = "abcdefghijklmnopqrstuvwxyz0123456789"


def lease_seconds() -> float:
    """The lease; ORCH_RUN_LEASE_SECONDS shortens it for tests."""
    try:
        return float(os.environ.get("ORCH_RUN_LEASE_SECONDS", LEASE_SECONDS))
    except ValueError:
        return LEASE_SECONDS


class Busy(Refused):
    """Somebody already works on the ticket. Exit 2, with pending: true when the event was queued."""

    def __init__(self, message: str, extra: dict):
        super().__init__(message)
        self.extra = extra


# ---------------------------------------------------------------- paths, time, processes


def run_dir(root: Path) -> Path:
    return root / ".orch" / "run"


def record_path(root: Path, tid: str) -> Path:
    tickets.ticket_path(root, tid)  # id shape check
    return run_dir(root) / "tickets" / f"{tid}.json"


def pending_path(root: Path, tid: str) -> Path:
    tickets.ticket_path(root, tid)
    return run_dir(root) / "pending" / f"{tid}.jsonl"


def host() -> str:
    h = re.sub(r"[^A-Za-z0-9.-]", "-", socket.gethostname() or "localhost").strip(".-")[:200]
    return h if h and h[0].isalnum() else "localhost"


def _parse(t: str) -> float:
    return datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def pid_started(pid: int) -> str | None:
    """Start time of a process as the OS reports it (guards against pid reuse), else None."""
    if not isinstance(pid, int) or pid <= 1:
        return None
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            k = ctypes.windll.kernel32
            k.OpenProcess.restype = wintypes.HANDLE
            h = k.OpenProcess(0x1000, False, pid)
            if not h:
                return None
            try:
                c, e, kt, ut = (wintypes.FILETIME() for _ in range(4))
                if not k.GetProcessTimes(h, *(ctypes.byref(x) for x in (c, e, kt, ut))):
                    return None
                ticks = (c.dwHighDateTime << 32) | c.dwLowDateTime
                return _iso(ticks / 1e7 - 11644473600)
            finally:
                k.CloseHandle(h)
        r = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
        text = " ".join(r.stdout.split())
        if not text:
            return None
        return _iso(time.mktime(time.strptime(text, "%a %b %d %H:%M:%S %Y")))
    except Exception:
        return None


# ---------------------------------------------------------------- the lock and the record


@contextlib.contextmanager
def locked(root: Path, tid: str):
    """The per-ticket run lock. Stale after 30 s (a holder does only quick file work)."""
    lock = run_dir(root) / "tickets" / f"{tid}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    end = time.monotonic() + 10
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            try:
                stale = time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS
            except OSError:
                continue
            if stale and tickets._break_stale(lock):
                continue
            if time.monotonic() > end:
                raise Refused(f"Ticket {tid} is busy (retried for 10 s). Try again.") from None
            time.sleep(0.01)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()


def _atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read(root: Path, tid: str) -> dict | None:
    try:
        rec = json.loads(record_path(root, tid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) and rec.get("run") else None


def _write(root: Path, rec: dict) -> None:
    _atomic(record_path(root, rec["ticket"]), json.dumps(rec, indent=2, ensure_ascii=False) + "\n")


def _delete(root: Path, tid: str) -> None:
    record_path(root, tid).unlink(missing_ok=True)


def state(rec: dict, at: float | None = None) -> str:
    """alive | dead | maybe-stale for a claim record."""
    at = time.time() if at is None else at
    pid = rec.get("pid")
    if isinstance(pid, int):
        if not services.pid_alive(pid):
            return "dead"
        was = rec.get("pid_started")
        now_started = pid_started(pid) if was else None
        if was and now_started and now_started != was:
            return "dead"  # the pid now belongs to another process
        return "alive"
    try:
        idle = at - _parse(rec["renewed_at"])
    except (KeyError, ValueError):
        idle = 0
    return "maybe-stale" if idle > lease_seconds() else "alive"


def new_run_id() -> str:
    return "r_" + "".join(secrets.choice(_ALPHA) for _ in range(8))


def _new_record(tid: str, by: str, agent: str, mode: str, ticket: dict, reason: str | None) -> dict:
    t = tickets.now()
    rec = {
        "schema": "orch.run/1",
        "ticket": tid,
        "run": new_run_id(),
        "by": by,
        "agent": agent,
        "mode": mode,
        "tmux": None,
        "pid": None,
        "pid_started": None,
        "started_at": t,
        "renewed_at": t,
        "pending": False,
        "stop_requested": None,
        "seen_revision": tickets.revision(ticket),
        "seen_history": len(ticket.get("history") or []),
    }
    if reason:
        rec["reason"] = reason[:200]
    return rec


# ---------------------------------------------------------------- pending input


def _pending_read(root: Path, tid: str) -> list[dict]:
    out = []
    try:
        lines = pending_path(root, tid).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("id") and item.get("text"):
            out.append(item)
    return out


def _pending_write(root: Path, tid: str, items: list[dict]) -> None:
    delivered = [i for i in items if i.get("delivered_at")]
    keep = [i for i in items if not i.get("delivered_at")] + delivered[-200:]  # ids stay for dedupe
    keep.sort(key=lambda i: items.index(i))
    _atomic(pending_path(root, tid), "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in keep))


def undelivered(root: Path, tid: str) -> list[dict]:
    return [i for i in _pending_read(root, tid) if not i.get("delivered_at")]


def _pending_add_locked(
    root: Path, tid: str, by: str, kind: str, text: str, via: str | None, pid: str | None
) -> dict:
    if kind not in PENDING_KINDS:
        raise Refused(f"Input kind must be one of: {', '.join(PENDING_KINDS)}.")
    text = (text or "").strip()
    if not text or len(text) > 8000:
        raise Refused("The text must be 1 to 8000 characters.")
    if pid is not None and not re.fullmatch(r"p_[a-z0-9]{6,32}", pid):
        raise Refused("An input id looks like p_ followed by 6 to 32 lowercase letters or digits.")
    items = _pending_read(root, tid)
    if pid and any(i["id"] == pid for i in items):
        return next(i for i in items if i["id"] == pid)  # same id twice = once
    item = {
        "id": pid or "p_" + "".join(secrets.choice(_ALPHA) for _ in range(10)),
        "at": tickets.now(),
        "by": by,
        "kind": kind,
        "text": text,
    }
    if via:
        item["via"] = via
    _pending_write(root, tid, items + [item])
    return item


def pending_add(
    root: Path,
    tid: str,
    by: str,
    kind: str,
    text: str,
    via: str | None = None,
    pid: str | None = None,
) -> dict:
    """Queue input for a ticket (under the ticket's run lock) and flag a running claim."""
    with locked(root, tid):
        item = _pending_add_locked(root, tid, by, kind, text, via, pid)
        rec = read(root, tid)
        if rec and not rec.get("pending"):
            rec["pending"] = True
            _write(root, rec)
        return item


def mark_delivered(root: Path, tid: str, ids: list[str]) -> None:
    with locked(root, tid):
        items = _pending_read(root, tid)
        for i in items:
            if i["id"] in ids and not i.get("delivered_at"):
                i["delivered_at"] = tickets.now()
        _pending_write(root, tid, items)
        rec = read(root, tid)
        if rec is not None:
            rec["pending"] = any(not i.get("delivered_at") for i in items)
            _write(root, rec)


# ---------------------------------------------------------------- claim, renew, release


def _busy(rec: dict, why: str, queued: bool) -> Busy:
    when = rec.get("started_at", "")[11:16]
    return Busy(
        f"An agent is already working on this ticket (started by {rec.get('by', 'someone')} at {when}). "
        f"{why}".strip(),
        {
            "holder": {"by": rec.get("by"), "run": rec.get("run")},
            "since": rec.get("started_at"),
            "pending": queued,
        },
    )


def claim(
    root: Path,
    tid: str,
    by: str,
    agent: str,
    mode: str = "oneshot",
    *,
    pid: int | None = None,
    take_over: bool = False,
    reason: str | None = None,
    busy_text: str | None = None,
) -> dict:
    """Take the claim on a ticket, or raise Busy. A busy ticket queues `busy_text` as input (same lock)."""
    ticket = tickets.load(root, tid)
    with locked(root, tid):
        cur = read(root, tid)
        if cur:
            st = state(cur)
            if st == "alive" or (st == "maybe-stale" and not take_over):
                if st == "maybe-stale":
                    cur.setdefault("maybe_stale_since", tickets.now())
                    why = "It has been quiet for a while. To take it over: orch run start --take-over"
                else:
                    why = "Your request is saved; it goes in when the agent is done."
                queued = False
                if busy_text:
                    _pending_add_locked(root, tid, by, "event", busy_text, None, None)
                    cur["pending"], queued = True, True
                if queued or st == "maybe-stale":
                    _write(root, cur)
                raise _busy(cur, why, queued)
            # dead pid, or maybe-stale with --take-over: the old claim is replaced
        rec = _new_record(tid, by, agent, mode, ticket, reason)
        if pid:
            rec["pid"], rec["pid_started"] = pid, pid_started(pid)
        if any(not i.get("delivered_at") for i in _pending_read(root, tid)):
            rec["pending"] = True
        _write(root, rec)
        return rec


def set_process(root: Path, tid: str, run: str, pid: int, **fields) -> bool:
    with locked(root, tid):
        rec = read(root, tid)
        if not rec or rec["run"] != run:
            return False
        rec["pid"], rec["pid_started"] = pid, pid_started(pid)
        rec.update(fields)
        _write(root, rec)
        return True


def renew(root: Path, tid: str, run: str, ticket: dict | None = None, seen: bool = False) -> dict | None:
    """Mark an orch write by the run (lease). With seen: remember the ticket state the agent has now seen."""
    with locked(root, tid):
        rec = read(root, tid)
        if not rec or rec["run"] != run:
            return None
        rec["renewed_at"] = tickets.now()
        rec.pop("maybe_stale_since", None)
        if seen and ticket is not None:
            rec["seen_revision"] = tickets.revision(ticket)
            rec["seen_history"] = len(ticket.get("history") or [])
        _write(root, rec)
        return rec


def release(root: Path, tid: str, run: str | None = None, keep_if_pending: bool = False) -> dict:
    """End a claim. With keep_if_pending the claim stays while input waits (the wrapper runs once more)."""
    with locked(root, tid):
        rec = read(root, tid)
        waiting = bool(undelivered(root, tid))
        if not rec or (run and rec["run"] != run):
            return {"released": False, "pending": waiting}
        if keep_if_pending and waiting:
            return {"released": False, "pending": True}
        _delete(root, tid)
        return {"released": True, "pending": waiting}


# ---------------------------------------------------------------- what the agent is told


def _clip(text: str, n: int = 600) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _items_text(items: list[dict]) -> str:
    return "\n".join(f"- {i['by']}: {_clip(i['text'], 1500)}" for i in items)


def fresh_prompt(ticket: dict, items: list[dict]) -> str:
    tid = ticket["id"]
    out = [
        f"Work on orch ticket {tid}: {_clip(ticket.get('title', ''), 200)}.",
        "Read .agents/skills/orch/SKILL.md first, then follow it for this ticket.",
    ]
    if ticket.get("summary"):
        out.append(f"Where things stand: {_clip(ticket['summary'], 1500)}")
    todo = [c for c in ticket.get("checklist") or [] if not c.get("done")]
    if todo:
        out.append(
            "Still to do:\n" + "\n".join(f"- {c['id']}: {_clip(c.get('text', ''), 200)}" for c in todo[:20])
        )
    hist = (ticket.get("history") or [])[-5:]
    if hist:
        out.append(
            "What changed lately:\n"
            + "\n".join(f"- {h.get('by', '?')}: {_clip(h.get('text', ''), 300)}" for h in hist)
        )
    if items:
        out.append("New since the work was asked for:\n" + _items_text(items))
    return "\n\n".join(out)[:12000]


def resume_prompt(ticket: dict, items: list[dict], since: str | None, agent: str) -> str:
    tid = ticket["id"]
    news = []
    for h in ticket.get("history") or []:
        if since and h.get("at", "") <= since:
            continue
        if h.get("by") == f"agent:{agent}":
            continue
        news.append(f"- {h.get('by', '?')}: {_clip(h.get('text', ''), 300)}")
    parts = []
    if news:
        parts.append("New on the ticket since last time:\n" + "\n".join(news[-10:]))
    if items:
        parts.append("New input:\n" + _items_text(items))
    if not parts:
        parts.append(f"Continue orch ticket {tid}: {_clip(ticket.get('title', ''), 200)}.")
    return "\n\n".join(parts)[:12000]


def plan(
    root: Path,
    tid: str,
    *,
    fresh: bool = False,
    mode: str = "oneshot",
    allow: list[str] | None = None,
    prompt: str | None = None,
    agent: str | None = None,
    items: list[dict] | None = None,
) -> dict:
    """Resume or fresh, decided here once: resume only when the adapter can, this ticket has a session for
    this agent on this machine, and --fresh is not set."""
    ticket = tickets.load(root, tid)
    name = agent or adapters.chosen(root)
    a = adapters.load(name, root)
    items = undelivered(root, tid) if items is None else items
    sid = None if fresh else tickets.sessions_for(ticket, name, host())
    v = {"allow": adapters.allow_patterns(allow), "session": sid}
    argv = None
    resumed = False
    if sid and a["capabilities"]["resume"]:
        since = next(
            (
                s.get("last_used")
                for s in ticket.get("sessions") or []
                if s.get("agent") == name and s.get("host") == host()
            ),
            None,
        )
        v["prompt"] = prompt if prompt is not None else resume_prompt(ticket, items, since, name)
        argv = adapters.render(name, "resume", mode, v, root)
        resumed = argv is not None
    new_session = None
    if not resumed:
        sid = None
        new_session = str(uuid.uuid4()) if a["capabilities"]["choose_session_id"] else None
        v.update(
            prompt=prompt if prompt is not None else fresh_prompt(ticket, items), new_session=new_session
        )
        argv = adapters.render(name, "fresh", mode, v, root)
        if argv is None:
            raise Refused(f"'{name}' cannot run in {mode} mode here.")
    return {
        "agent": name,
        "adapter": a["adapter"],
        "mode": mode,
        "resumed": resumed,
        "session": sid if resumed else new_session,
        "tmux": None,
        "argv": argv,
        "stdin": v["prompt"] if a["prompt_via"] == "stdin" else None,
        "item_ids": [i["id"] for i in items],
    }


# ---------------------------------------------------------------- start


def start(
    root: Path,
    tid: str,
    by: str,
    *,
    fresh: bool = False,
    take_over: bool = False,
    allow: list[str] | None = None,
    mode: str = "oneshot",
    text: str | None = None,
) -> dict:
    if mode != "oneshot":
        raise Refused("Only --mode oneshot is available here.")
    name = adapters.chosen(root)
    a = adapters.load(name, root)
    notes = []
    notice = adapters.command_notice(name, mode, root)
    if notice:
        notes.append(notice)
    allow = adapters.allow_patterns(allow)
    if allow and not a["capabilities"]["permission_retry"]:
        notes.append(f"{a['label']} cannot be told which tools to allow; --allow was ignored.")
        allow = []
    rec = claim(
        root,
        tid,
        by,
        name,
        mode,
        take_over=take_over,
        busy_text=text or f"{by} asked for more work on this ticket.",
    )
    try:
        p = plan(root, tid, fresh=fresh, mode=mode, allow=allow, agent=name)
        log_rel = f".orch/run/logs/{tid}-{rec['run']}.log"
        (root / log_rel).parent.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, "-m", "orch", "run", "_wrap", rec["run"], "--ticket", tid, "--agent", name]
        cmd += ["--fresh"] if fresh else []
        for pat in allow:
            cmd += ["--allow", pat]
        if p["stdin"] is not None:
            sf = run_dir(root) / f"prompt-{rec['run']}.txt"
            _atomic(sf, p["stdin"])
            os.chmod(sf, 0o600)
            cmd += ["--stdin-file", str(sf)]
        if p["session"] and not p["resumed"]:
            cmd += ["--new-session", p["session"]]
        if p["resumed"]:
            cmd += ["--resumed"]
        cmd += ["--items", ",".join(p["item_ids"])] if p["item_ids"] else []
        cmd += ["--"] + p["argv"]
        kw: dict = {}
        if os.name == "nt":
            kw["creationflags"] = 0x00000200 | 0x00000008  # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
        else:
            kw["start_new_session"] = True
        proc = subprocess.Popen(
            cmd,
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kw,
        )
        set_process(root, tid, rec["run"], proc.pid, log=log_rel)
    except BaseException:
        release(root, tid, rec["run"])
        raise
    return {
        **{k: p[k] for k in ("agent", "adapter", "mode", "resumed", "session", "tmux")},
        "run": rec["run"],
        "log": log_rel,
        "notes": notes,
    }


# ---------------------------------------------------------------- the wrapper (runs detached)


def _run_turn(argv: list[str], root: Path, stdin: str | None, log: Path, env: dict, on_started=None):
    """One agent process. Returns (exit code, the output of this turn)."""
    log.parent.mkdir(parents=True, exist_ok=True)
    start = log.stat().st_size if log.exists() else 0
    with open(log, "ab") as out:
        try:
            proc = subprocess.Popen(
                argv,
                cwd=root,
                env=env,
                stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT,
            )
        except OSError as e:
            out.write(f"orch could not start the agent: {e}\n".encode())
            return 127, ""
        if on_started:
            on_started()  # the input is with the agent now: only then is it delivered
        if stdin is not None:
            with contextlib.suppress(OSError):
                proc.stdin.write(stdin.encode("utf-8"))
                proc.stdin.close()
        rc = proc.wait()
    with open(log, "rb") as f:
        f.seek(start)
        return rc, f.read().decode("utf-8", "replace")


def wrap(
    root: Path,
    run: str,
    tid: str,
    name: str,
    argv: list[str],
    *,
    fresh: bool = False,
    resumed: bool = False,
    allow: list[str] | None = None,
    stdin: str | None = None,
    new_session: str | None = None,
    item_ids: list[str] | None = None,
) -> int:
    """Run the agent, record its session on the ticket, deliver pending input once, release."""
    rec = read(root, tid)
    if not rec or rec["run"] != run:
        return 1
    set_process(root, tid, run, os.getpid())
    env = {**os.environ, "ORCH_RUN": run, "ORCH_TICKET": tid, "ORCH_AGENT": name}
    log = root / (rec.get("log") or f".orch/run/logs/{tid}-{run}.log")
    mode = rec.get("mode") or "oneshot"
    turns = 0
    while True:
        ids = list(item_ids or [])
        rc, out = _run_turn(
            argv, root, stdin, log, env, (lambda ids=ids: mark_delivered(root, tid, ids)) if ids else None
        )
        if resumed and rc != 0:  # the session is gone: start fresh once and keep the new id
            p = plan(root, tid, fresh=True, mode=mode, allow=allow, agent=name, items=[])
            argv, stdin, new_session = p["argv"], p["stdin"], p["session"]
            rc, out = _run_turn(argv, root, stdin, log, env)
        sid = new_session or adapters.parse_session(name, out, root)
        if sid:
            tickets.record_session(root, tid, name, sid, host())
        turns += 1
        if release(root, tid, run, keep_if_pending=turns <= MAX_DRAIN_TURNS)["released"]:
            return 0 if rc == 0 else rc
        p = plan(root, tid, mode=mode, allow=allow, agent=name)  # input came in meanwhile: one more turn
        argv, stdin, resumed = p["argv"], p["stdin"], p["resumed"]
        new_session = None if p["resumed"] else p["session"]
        item_ids = p["item_ids"]


# ---------------------------------------------------------------- the footer


def footer(root: Path, argv_by: str | None) -> str | None:
    """'New on t_x since you looked: ...' for the run this process belongs to, once per new revision."""
    run, tid = os.environ.get("ORCH_RUN"), os.environ.get("ORCH_TICKET")
    if not run or not tid or not re.fullmatch(r"t_[a-z0-9]{6,16}", tid):
        return None
    rec = read(root, tid)
    if not rec or rec["run"] != run:
        return None
    ticket = tickets.load(root, tid)
    if tickets.revision(ticket) <= rec.get("seen_revision", 0):
        renew(root, tid, run)
        return None
    own = {f"agent:{rec.get('agent')}", argv_by}
    news = [h for h in (ticket.get("history") or [])[rec.get("seen_history", 0) :] if h.get("by") not in own]
    renew(root, tid, run, ticket, seen=True)
    if not news:
        return None
    shown = "; ".join(f"{_clip(h.get('text', ''), 160)} ({h.get('by', '?')})" for h in news[:3])
    more = f" (+{len(news) - 3} more)" if len(news) > 3 else ""
    return f"New on {tid} since you looked: {shown}{more}"
