"""The ticket snapshot the phone's ticket chat shows (message.schema.json `body.ticket_view`).

Built from the ticket file: title, status, tasks, the last 30 history lines in plain words, and
the proof marked for the phone (evidence with role result or check: files are uploaded as relay
blobs, URLs and PRs become links) plus the ticket's refs. Secrets are cut from every text before
it leaves. No other file content is ever sent.

It rides on update texts to phones (result, failure, stopped, question) and, quietly (kind note,
never pushed), when the tasks of a ticket the phone follows change: `sync` runs on every relay
inbox pull, at most once per DEBOUNCE seconds per ticket. State: .orch/secrets/phone-views.json.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

from orch import net, refs, runs, safefile, tickets
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


_ADMIN_NOTE = re.compile(
    r"(?:Set|Removed) ext\."
)  # add-on settings notes: admin business, not for a phone chat
_FROM_PREFIX = re.compile(r"From [^:\n]{1,100}: ")
_RELAY_BY = re.compile(r"agent:relay from (ph_\S+)")  # a phone only; a workspace keeps its own label


def _phone_line(root: Path, h: dict) -> tuple[str, str, str] | None:
    """(who, role, text) of a text that came from a phone: its name (never the raw ph_ id), as a person."""
    from orch import relay

    m = _RELAY_BY.fullmatch(str(h.get("by", "")))
    if not m:
        return None
    text = str(h.get("text", ""))
    if h.get("via") == "phone":
        text = _FROM_PREFIX.sub("", text, count=1)
    return _clip(relay.name_of(root, m.group(1)), 64) or "Phone", "person", text


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
    anything else: the ref has exactly that shape and the read goes through orch.safefile (the one reader)."""
    parts = str(ev.get("ref", "")).split("/")
    if len(parts) != 5 or parts[:4] != [".orch", "tickets", tid, "evidence"]:
        return None
    try:
        data = safefile.read_ticket_file(root, tid, "evidence", parts[4], tickets.MAX_PROOF_BYTES)
    except safefile.TooLarge:
        return None
    return (parts[4], data) if data is not None else None


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


def artifact_id(source: str, ref: str) -> str:
    """a_ + 12 hex of sha256("<source>\\n<ref>"): stable across revisions (vectors/phone-v3-v1.json).
    source = the evidence type (pr, commit, file, url, command, note) or "link" for ticket refs."""
    return "a_" + hashlib.sha256(f"{source}\n{ref}".encode()).hexdigest()[:12]


def _short(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


_PUBLISHED = re.compile(r"^/(?:f|a)/([A-Za-z0-9_.-]+)")


def _url_art(source: str, url: str, kind_hint: str | None = None) -> tuple[str, str]:
    """(kind, rev) of an artifact that is a link: a published page or app is html (rev = its publish id or app
    name), a pull request pr, a commit commit (rev = the commit sha), anything else link."""
    path = urllib.parse.urlsplit(url).path
    if m := _PUBLISHED.match(path):
        return "html", m.group(1)
    if source == "pr" or kind_hint == "pr":
        return "pr", _short(url)
    if source == "commit" or kind_hint == "commit" or re.search(r"/commit/([0-9a-f]{7,40})", path):
        c = re.search(r"/commit/([0-9a-f]{7,40})", path)
        return "commit", c.group(1) if c else _short(url)
    return "link", _short(url)


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
                    "id": artifact_id("file", str(ev.get("ref", ""))),
                    "rev": hashlib.sha256(f[1]).hexdigest(),
                }
            )
        elif ev.get("type") in ("url", "pr", "commit") and (url := safe_url(ev.get("ref", ""))):
            kind, rev = _url_art(ev["type"], url)
            out.append(
                {
                    "kind": kind,
                    "title": _clip(ev.get("title") or url, 200) or "Link",
                    "url": url,
                    "at": at,
                    "id": artifact_id(ev["type"], str(ev.get("ref", ""))),
                    "rev": rev,
                }
            )
        elif ev.get("type") == "commit" and re.fullmatch(r"[0-9a-f]{7,40}", str(ev.get("ref", ""))):
            pass  # a bare commit sha has no address to open: nothing for the phone to show
    kinds = refs.active_kinds(root) if ticket.get("refs") else []
    for ln in ticket.get("refs") or []:
        if not isinstance(ln, dict) or not (url := safe_url(ln.get("url", ""))):
            continue
        d = refs.describe(ln, kinds)  # same label, icon and status as the dashboard and CLI
        at = ln["at"] if _TIME.fullmatch(str(ln.get("at"))) else at0
        kind, rev = _url_art("link", url)
        a = {
            "kind": kind,
            "title": _clip(ln.get("title") or url, 200) or "Link",
            "url": url,
            "at": at,
            "id": artifact_id("link", str(ln.get("url", ""))),
            "rev": rev,
        }
        a.update(label=_clip(d["label"], 60) or "Link", icon=d["icon"])
        if d["mono"]:
            a["mono"] = d["mono"][:3]
        if d["status"]:
            a["status"] = d["status"]
        out.append(a)
    out.sort(key=lambda a: a["at"], reverse=True)
    return out[:ATTACHMENTS]


def artifact_title(root: Path, ticket: dict, aid: str) -> str | None:
    """The title of the proof or link a phone feedback names (by artifact id), or None."""
    for ev in phone_proof(root, ticket):
        if artifact_id(str(ev.get("type")), str(ev.get("ref", ""))) == aid:
            return _clip(ev.get("title") or Path(str(ev.get("ref", ""))).name, 200) or None
    for ln in ticket.get("refs") or []:
        if isinstance(ln, dict) and artifact_id("link", str(ln.get("url", ""))) == aid:
            return _clip(ln.get("title") or ln.get("url", ""), 200) or None
    return None


def reference_views(root: Path, ticket: dict) -> list[dict]:
    """Shared references for the phone; local computer paths never leave this machine."""
    out = []
    for ref in (ticket.get("refs") or [])[:ATTACHMENTS]:
        if not isinstance(ref, dict) or ref.get("local"):
            continue
        kind = ref.get("kind")
        if kind in ("ticket", "artifact"):
            tid = ref.get("ticket")
            if not isinstance(tid, str) or not re.fullmatch(r"t_[a-z0-9]{6,16}", tid):
                continue
            row = {"kind": kind, "ticket": tid}
            try:
                other = tickets.load(root, tid)
                row.update(title=_clip(other["title"], 200), status=other["status"])
            except (Refused, OSError, ValueError, KeyError):
                pass
            if kind == "artifact":
                if safefile._parts(ref.get("name")) is None:
                    continue
                row["name"] = _clip(ref["name"], 240)
        elif kind == "file":
            path = ref.get("path")
            if not safefile.file_ref_ok(root, path):
                continue
            row = {"kind": kind, "path": _clip(path, 240)}
            line = ref.get("line")
            if type(line) is int and line > 0:
                row["line"] = line
        else:
            url = safe_url(ref.get("url", ""))
            if not url or not isinstance(kind, str) or not refs.KIND_RE.fullmatch(kind):
                continue
            row = {"kind": kind, "url": url, "title": _clip(ref.get("title") or url, 200)}
        out.append(row)
    return out


def build(root: Path, ticket: dict, atts: list[dict]) -> dict:
    checklist = ticket.get("checklist") or []
    done, total = tickets.checks_done(ticket)
    agent, running = _agent(root, ticket)
    hist = []
    for h in (ticket.get("history") or [])[-HISTORY:]:
        if _ADMIN_NOTE.match(str(h.get("text", ""))):
            continue
        pl = _phone_line(root, h)
        raw = pl[2] if pl else str(h.get("text", ""))
        text = _clip(tickets.history_line(raw, checklist), 1000)
        if not text:
            continue
        at = str(h.get("at") or "")
        if not _TIME.fullmatch(at):
            continue
        who, role = pl[:2] if pl else _who(h.get("by", ""))
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
    if shared_refs := reference_views(root, ticket):
        view["refs"] = shared_refs
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
    while size_of(view) > BUDGET and view.get("refs"):
        view["refs"].pop()
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


def _tasks_sig(ticket: dict, root: Path | None = None) -> str:
    """What the phone's snapshot depends on: tasks, status and whether an agent runs now (so "<agent> is
    working" on the phone ends when the agent stops, not only when a task changes)."""
    items = [[c.get("text"), bool(c.get("done"))] for c in ticket.get("checklist") or []]
    running = _agent(root, ticket)[1] if root is not None else None
    return hashlib.sha256(json.dumps([items, ticket.get("status"), running]).encode()).hexdigest()[:16]


def remember(root: Path, tid: str, to: str) -> None:
    """The phone follows this ticket now: later task changes go to `to` quietly."""
    if not (to == "phones" or to.startswith("ph_")):
        return
    state = load_state(root)
    try:
        sig = _tasks_sig(tickets.load(root, tid), root)
    except (Refused, ValueError, KeyError, OSError):
        return
    state["tickets"][tid] = {"to": to, "sig": sig, "at": time.time()}
    if to.startswith("ph_"):  # this phone has a chat for the ticket now: sync_open skips it
        state.setdefault("synced", {}).setdefault(to, [])
        if tid not in state["synced"][to]:
            state["synced"][to].append(tid)
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
        if _tasks_sig(ticket, root) == rec.get("sig") or now - rec.get("at", 0) < DEBOUNCE:
            continue
        done, total = tickets.checks_done(ticket)
        with contextlib.suppress(Refused):
            relay.send_text(root, rec["to"], f"Tasks: {done} of {total} done", tid, "note", view=True)
            sent.append(tid)
    return sent


NEW_TEXT = "Ticket on your workspace"
OPEN_MAX = 20  # open tickets the phone gets a chat for (newest first)
DONE_HOURS = 24  # a finished ticket stays on the phone this long


def _is_recent(ticket: dict, now: float) -> bool:
    if ticket.get("status") not in ("done", "dropped"):
        return True
    try:
        at = datetime.fromisoformat(str(ticket.get("updated_at"))).timestamp()
    except ValueError:
        return False
    return now - at <= DONE_HOURS * 3600


def sync_open(root: Path, now: float | None = None) -> list[str]:
    """Every open ticket (and a done one for 24 h) gets a chat on every paired phone: one quiet note with
    the snapshot (kind note, never pushed), at most OPEN_MAX, newest first, once per ticket and phone.
    It goes to the phone's own address: a note to "phones" is only shown to phones that were paired when
    it was sent, so a phone paired later would never see the old tickets. Returns the ticket ids sent."""
    from orch import relay

    now = time.time() if now is None else now
    phones = [
        p["id"] for p in relay._read_dir(root).get("phones", []) if str(p.get("id", "")).startswith("ph_")
    ]
    if not phones:
        return []
    state = load_state(root)
    done_for = state.setdefault("synced", {})
    open_ = [t for t in tickets.list_all(root) if _is_recent(t, now)]
    open_.sort(key=lambda t: str(t.get("created_at", "")), reverse=True)
    sent: list[str] = []
    for ph in phones:
        have = set(done_for.get(ph, []))
        for t in [t for t in open_[:OPEN_MAX] if t["id"] not in have]:
            done, total = tickets.checks_done(t)
            text = f"Tasks: {done} of {total} done" if total else NEW_TEXT
            try:
                relay.send_text(root, ph, text, t["id"], "note", view=True)
            except Refused:
                break  # the relay is away or refuses this phone: the next pull tries again
            have.add(t["id"])
            done_for[ph] = sorted(have)
            save_state(root, {**load_state(root), "synced": done_for})
            if t["id"] not in sent:
                sent.append(t["id"])
    return sent
