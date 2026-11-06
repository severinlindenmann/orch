"""The ticket snapshot the phone's ticket chat shows (message.schema.json `body.ticket_view`).

Built from the ticket file: title, status, tasks, the last 30 history lines in plain words, and
the proof marked for the phone (evidence with role result or check: files are uploaded as relay
blobs, URLs and PRs become links) plus the ticket's links. Secrets are cut from every text before
it leaves. No other file content is ever sent.

It rides on update texts to phones (result, failure, stopped, question) and, quietly (kind note,
never pushed), when the tasks of a ticket the phone follows change: `sync` runs on every relay
inbox pull, at most once per DEBOUNCE seconds per ticket. State: .orch/secrets/phone-views.json.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import stat
import time
import urllib.parse
from pathlib import Path

from orch import net, runs, tickets
from orch.errors import Refused
from orch.text import clean_untrusted

CAP = 16384  # the relay refuses a bigger ticket_view (compact UTF-8 JSON)
BUDGET = 15000  # what we aim for, a margin below the cap
SEND_KINDS = ("result", "failure", "stopped", "question")
PHONE_ROLES = ("result", "check")
DEBOUNCE = 20  # seconds between two quiet snapshots of one ticket
BLOB_DAYS = 30  # re-upload a cached blob after this (the relay deletes blobs after 90 days)
HISTORY = 30
ATTACHMENTS = 50
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic"}

_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S),
    re.compile(r"\b(?:orn|orp|ora|whk|opk|apv)_[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:sk|pk|rk)[-_](?:live|test|proj|ant)?[-_]?[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}|\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),  # JWT
    re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}"),
]
_SECRET_KV = re.compile(
    r"(?i)\b([\w-]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)[\w-]*)"
    r"(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|\S+)"
)
_SECRET_PARAM = re.compile(r"(?i)token|secret|key|sig|signature|password|passwd|auth|code|credential")
HIDDEN = "[hidden]"
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z")


def redact(text: str) -> str:
    """Plain, safe text for the phone: invisible/control characters and comments go (clean_untrusted), then
    anything that looks like a key, token or password is replaced by [hidden]."""
    t = clean_untrusted(str(text), 20000)
    for rx in _SECRET_PATTERNS:
        t = rx.sub(HIDDEN, t)
    return _SECRET_KV.sub(lambda m: m.group(1) + m.group(2) + HIDDEN, t)


def _clip(text: str, n: int) -> str:
    t = redact(text).strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def safe_url(url: str) -> str | None:
    """http(s) URLs only, without user:password, secret-looking query values hidden. None otherwise."""
    u = str(url).strip()
    try:
        p = urllib.parse.urlsplit(u)
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.hostname or any(c.isspace() for c in u):
        return None
    host = p.hostname + (f":{p.port}" if p.port else "")
    q = urllib.parse.parse_qsl(p.query, keep_blank_values=True)
    query = urllib.parse.urlencode([(k, HIDDEN if _SECRET_PARAM.search(k) else redact(v)) for k, v in q])
    out = urllib.parse.urlunsplit((p.scheme, host, redact(p.path), query, ""))
    return out if len(out) <= 2000 else None


def size_of(view: dict) -> int:
    return len(json.dumps(view, separators=(",", ":"), ensure_ascii=False).encode())


def _who(by: str) -> tuple[str, str]:
    kind, _, name = str(by).partition(":")
    name = _clip(name or kind, 64) or "Someone"
    if kind == "agent":
        return name[:1].upper() + name[1:], "agent"
    return name, "person"


def _agent(root: Path, ticket: dict) -> tuple[str | None, bool]:
    """(agent display name, running now)."""
    rec = runs.read(root, ticket["id"])
    running = bool(rec) and runs.state(rec) != "dead"
    name = (rec or {}).get("agent") if running else None
    if not name:
        sessions = sorted(ticket.get("sessions") or [], key=lambda s: str(s.get("last_used", "")))
        name = sessions[-1].get("agent") if sessions else None
    return (_who(f"agent:{name}")[0] if name else None), running


def phone_proof(root: Path, ticket: dict) -> list[dict]:
    """Evidence marked for the phone (role result or check), newest last, from every task."""
    out = []
    for c in ticket.get("checklist") or []:
        for ev in c.get("evidence") or []:
            if ev.get("role") in PHONE_ROLES:
                out.append(ev)
    return out


def _proof_file(root: Path, tid: str, ev: dict) -> tuple[str, bytes] | None:
    """(name, bytes) of a copied proof file of this ticket, .orch/tickets/<tid>/evidence/<name>, never
    anything else: the ref has exactly that shape; the folders are opened one by one from the workspace
    without following links (dir_fd), the file too (O_NOFOLLOW, O_NONBLOCK: never a FIFO); it must be a
    regular file with one link (no hard link to a secret) and at most 25 MB, read from that handle."""
    ref = str(ev.get("ref", ""))
    parts = ref.split("/")
    name = parts[4] if len(parts) == 5 else ""
    if (
        len(parts) != 5
        or parts[:4] != [".orch", "tickets", tid, "evidence"]
        or name in ("", ".", "..")
        or "\\" in ref
        or "\0" in ref
        or not tickets._ID_RE.fullmatch(tid)
    ):
        return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    dir_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_DIRECTORY", 0)
    fds: list[int] = []
    try:
        if os.open in os.supports_dir_fd and hasattr(os, "O_DIRECTORY"):
            # walk folder by folder from the workspace, each opened relative to the last one and never
            # through a link: a folder swapped for a link while we look is refused, not followed
            fds.append(os.open(os.path.realpath(root), os.O_RDONLY | os.O_DIRECTORY))
            for part in parts[:4]:
                fds.append(os.open(part, dir_flags, dir_fd=fds[-1]))
            fd = os.open(name, flags, dir_fd=fds[-1])
        else:  # Windows: no dir_fd; check every part for links, then open
            cur = Path(os.path.realpath(root))
            for part in parts:
                cur = cur / part
                if cur.is_symlink():
                    return None
            if not stat.S_ISREG(os.lstat(cur).st_mode):
                return None
            fd = os.open(cur, flags)
    except OSError:
        return None
    finally:
        for d in fds:
            os.close(d)
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        # a regular file with exactly one name: a hard link to e.g. .orch/secrets/relay.json is refused
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > tickets.MAX_PROOF_BYTES:
            return None
        data = f.read(tickets.MAX_PROOF_BYTES + 1)
    if len(data) > tickets.MAX_PROOF_BYTES:
        return None
    return name, data


def _state_path(root: Path) -> Path:
    return net.secrets_dir(root) / "phone-views.json"


def load_state(root: Path) -> dict:
    s = net.read_json(_state_path(root), {})
    if not isinstance(s, dict):
        s = {}
    s.setdefault("tickets", {})
    s.setdefault("blobs", {})
    return s


def save_state(root: Path, s: dict) -> None:
    net.write_json(_state_path(root), s, True)


def _upload(root: Path, data: bytes, state: dict) -> dict | None:
    """Upload a proof file once (cached by content); {blob_id, size} or None when the relay says no."""
    from orch import relay

    sha = hashlib.sha256(data).hexdigest()
    got = state["blobs"].get(sha)
    if got and time.time() - got.get("at", 0) < BLOB_DAYS * 86400:
        return got
    try:
        blob = relay._api(root, "POST", "/v1/blobs", data, 300)[1]
    except Refused:
        return None
    if not isinstance(blob, dict) or blob.get("sha256") != sha or blob.get("size") != len(data):
        return None
    got = {"blob_id": blob["blob_id"], "size": len(data), "at": time.time()}
    state["blobs"][sha] = got
    return got


def attachments(root: Path, ticket: dict, state: dict | None, upload: bool = True) -> list[dict]:
    """Proof files (uploaded), proof links and ticket links, newest first, at most 50."""
    tid = ticket["id"]
    at0 = ticket["updated_at"] if _TIME.fullmatch(str(ticket.get("updated_at"))) else tickets.now()
    out: list[dict] = []
    for ev in phone_proof(root, ticket):
        at = ev["at"] if _TIME.fullmatch(str(ev.get("at"))) else at0
        if ev.get("type") == "file":
            f = _proof_file(root, tid, ev)
            b = _upload(root, f[1], state) if (f and upload and state is not None) else None
            if not b:
                continue
            kind = "image" if Path(f[0]).suffix.lower() in IMAGE_EXT else "file"
            name = _clip(f[0], 255) or "file"
            out.append(
                {
                    "kind": kind,
                    "title": _clip(ev.get("title") or f[0], 200) or name,
                    "blob_id": b["blob_id"],
                    "name": name,
                    "size": b["size"],
                    "at": at,
                }
            )
        elif ev.get("type") in ("url", "pr") and (url := safe_url(ev.get("ref", ""))):
            out.append(
                {"kind": "link", "title": _clip(ev.get("title") or url, 200) or "Link", "url": url, "at": at}
            )
    for ln in ticket.get("links") or []:
        if url := safe_url(ln.get("url", "")):
            out.append(
                {"kind": "link", "title": _clip(ln.get("title") or url, 200) or "Link", "url": url, "at": at0}
            )
    out.sort(key=lambda a: a["at"], reverse=True)
    return out[:ATTACHMENTS]


def build(root: Path, ticket: dict, atts: list[dict]) -> dict:
    checklist = ticket.get("checklist") or []
    done, total = tickets.checks_done(ticket)
    agent, running = _agent(root, ticket)
    hist = []
    for h in (ticket.get("history") or [])[-HISTORY:]:
        text = _clip(tickets.history_line(str(h.get("text", "")), checklist), 1000)
        if not text:
            continue
        at = str(h.get("at") or "")
        if not _TIME.fullmatch(at):
            continue
        who, role = _who(h.get("by", ""))
        hist.append({"at": at, "who": who, "role": role, "text": text})
    view: dict = {
        "title": _clip(ticket.get("title", ""), 200) or "Ticket",
        "status": ticket.get("status", "open"),
        "running": running,
        "checklist": [
            {"text": _clip(c.get("text", ""), 500) or "Task", "done": bool(c.get("done"))}
            for c in checklist[:200]
        ],
        "done": done,
        "total": total,
        "history_tail": hist,
        "attachments": atts,
    }
    if agent:
        view["agent"] = agent
    if ticket.get("summary"):
        view["summary"] = _clip(ticket["summary"], 200)
    return fit(view)


def fit(view: dict) -> dict:
    """Shrink under BUDGET: oldest history lines, then oldest attachments, then long task texts."""
    while size_of(view) > BUDGET and view["history_tail"]:
        view["history_tail"].pop(0)
    while size_of(view) > BUDGET and view["attachments"]:
        view["attachments"].pop()
    for n in (120, 40):
        if size_of(view) > BUDGET:
            for c in view["checklist"]:
                c["text"] = c["text"] if len(c["text"]) <= n else c["text"][: n - 1] + "…"
    while size_of(view) > BUDGET and view["checklist"]:
        view["checklist"].pop()
    return view


def view_for(root: Path, tid: str) -> dict | None:
    """The snapshot of a ticket now (uploads proof files on the way). None when the ticket can't be read."""
    try:
        ticket = tickets.load(root, tid)
    except (Refused, ValueError, KeyError, OSError):
        return None
    state = load_state(root)
    atts = attachments(root, ticket, state)
    save_state(root, state)
    return build(root, ticket, atts)


def _tasks_sig(ticket: dict) -> str:
    items = [[c.get("text"), bool(c.get("done"))] for c in ticket.get("checklist") or []]
    return hashlib.sha256(json.dumps([items, ticket.get("status")]).encode()).hexdigest()[:16]


def remember(root: Path, tid: str, to: str) -> None:
    """The phone follows this ticket now: later task changes go to `to` quietly."""
    if not (to == "phones" or to.startswith("ph_")):
        return
    state = load_state(root)
    try:
        sig = _tasks_sig(tickets.load(root, tid))
    except (Refused, ValueError, KeyError, OSError):
        return
    state["tickets"][tid] = {"to": to, "sig": sig, "at": time.time()}
    save_state(root, state)


def sync(root: Path, now: float | None = None) -> list[str]:
    """Quiet snapshots (kind note, never pushed) for followed tickets whose tasks changed, at most
    one per ticket every DEBOUNCE seconds (a change in between waits for the next pull).
    Returns the ticket ids sent."""
    from orch import relay

    now = time.time() if now is None else now
    sent = []
    for tid, rec in list(load_state(root)["tickets"].items()):
        try:
            ticket = tickets.load(root, tid)
        except (Refused, ValueError, KeyError, OSError):
            continue
        if _tasks_sig(ticket) == rec.get("sig") or now - rec.get("at", 0) < DEBOUNCE:
            continue
        done, total = tickets.checks_done(ticket)
        with contextlib.suppress(Refused):
            relay.send_text(root, rec["to"], f"Tasks: {done} of {total} done", tid, "note", view=True)
            sent.append(tid)
    return sent
