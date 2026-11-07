"""orch relay client: inbox, send, allow, refresh, webhooks (contracts/relay-api.md, local-files.md)."""

from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import time
import unicodedata
import urllib.parse
from pathlib import Path

from orch import harness, net, runs, skillrender, skills, tickets
from orch.errors import Refused
from orch.text import clean_untrusted

ALNUM = "abcdefghijklmnopqrstuvwxyz0123456789"
MAX_BLOB = 100 * 1024 * 1024
SKILL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
SHARED_MARK = ".orch-shared"
LOCK_STALE = 30  # seconds before a relay.lock counts as left behind
ARRIVALS_MAX = 5000  # lines in arrivals.jsonl before the oldest half goes
RESERVED = {"orch", "orch-publish", "orch-relay"}  # plus every "orch-*": add-on skills (see _stage)


def new_id(prefix: str = "m_", n: int = 16) -> str:
    return prefix + "".join(secrets.choice(ALNUM) for _ in range(n))


def _cfg(root: Path) -> dict:
    return net.load_service(root, "relay")


def _api(root: Path, method: str, path: str, body=None, timeout: float = 60):
    cfg = _cfg(root)
    return net.call_json(method, cfg["url"] + path, net.auth_headers(cfg), body, timeout)


def connect(root: Path, url: str, workspace: str, token: str) -> tuple[dict, str]:
    who = net.connect_service(root, "relay", "orch-relay", url, workspace, token, "orn_")
    return who, refresh(root)


def whoami(root: Path) -> dict:
    return _api(root, "GET", "/v1/whoami")[1]


def heartbeat(root: Path, mobile_mode: dict) -> None:
    """Tell the relay we are here and whether Mobile mode is on (shape: contracts/relay-api.md)."""
    _api(root, "POST", "/v1/heartbeat", {"mobile_mode": mobile_mode}, timeout=15)


def _is_mobile_off(m: dict) -> bool:
    b = m.get("body")
    return (
        m.get("type") == "control"
        and str(m.get("from", "")).startswith("ph_")
        and isinstance(b, dict)
        and b.get("control") == "mobile_mode_off"
    )


MOBILE_OFF_MAX_AGE = 600  # seconds: an older 'off' is ignored
MOBILE_OFF_SKEW = 120  # seconds a request may be dated ahead (clock differences)


def _age_seconds(stamp) -> float | None:
    from datetime import UTC, datetime

    try:
        then = datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None
    return (datetime.now(UTC) - then).total_seconds()


def _mobile_off_ok(root: Path, m: dict) -> bool:
    """A phone may end Mobile mode only if it is still paired (last refresh), the request is at most 10
    minutes old (or 2 minutes ahead) and was made after this Mobile mode began (never ends a newer one)."""
    from orch import mobile_mode

    paired = {p.get("id") for p in _read_dir(root).get("phones", []) if isinstance(p, dict)}
    age = _age_seconds(m.get("created_at"))
    since = mobile_mode.settle(root).get("since")  # None when off
    return (
        m["from"] in paired
        and age is not None
        and -MOBILE_OFF_SKEW <= age <= MOBILE_OFF_MAX_AGE
        and since is not None
        and str(m["created_at"]) >= since
    )


def _handle_mobile_off(root: Path, m: dict) -> str:
    """Handle one phone 'turn off Mobile mode' request exactly once (inbox and mobile_controls may race)."""
    from orch import mobile_mode

    with locked(root):
        if m["id"] in seen(root):
            return "already handled"
        ok = _mobile_off_ok(root, m)
        _mark_seen(root, m["id"])
    if ok:
        mobile_mode.turn_off(root, "off")
    return (
        "Mobile mode was turned off from the phone"
        if ok
        else "ignored an old, future, unpaired or outdated Mobile mode request"
    )


def mobile_controls(root: Path) -> list[str]:
    """Pull and act on phone controls. Other messages stay saved and unseen for `orch relay inbox`."""
    _pull(root, 0)
    done_ids = []
    for f in sorted((root / ".orch" / "inbox").glob("m_*.json")):
        m = net.read_json(f, None)
        if isinstance(m, dict) and m.get("id") == f.stem and f.stem not in seen(root) and _is_mobile_off(m):
            _handle_mobile_off(root, m)
            done_ids.append(f.stem)
    return done_ids


def profile(root: Path, description: str | None, tags: list[str] | None) -> dict:
    return net.profile(root, "relay", description, tags)


# ---- local state --------------------------------------------------------------------------------


def _seen_path(root: Path) -> Path:
    return root / ".orch" / "inbox-seen.json"


def seen(root: Path) -> dict:
    return net.read_json(_seen_path(root), {})


def _mark_seen(root: Path, mid: str) -> bool:
    """Returns True when the id was new. Caller holds the relay lock."""
    s = seen(root)
    if mid in s:
        return False
    s[mid] = tickets.now()
    net.write_json(_seen_path(root), s)
    return True


def _break_stale(lock: Path) -> bool:
    """Claim a stale lock by renaming it to a name only we know (atomic: one waiter wins), then check that
    what we took is really old. A fresh lock a faster waiter just made is put back."""
    mine = lock.with_name(f"{lock.name}.{secrets.token_hex(4)}")
    try:
        os.replace(lock, mine)
    except OSError:
        return False
    try:
        if time.time() - mine.stat().st_mtime > LOCK_STALE:
            return True
        with contextlib.suppress(OSError):
            os.link(mine, lock)  # no-clobber put-back
        return False
    finally:
        with contextlib.suppress(OSError):
            mine.unlink()


@contextlib.contextmanager
def locked(root: Path, wait: float = 10.0):
    """`.orch/relay.lock`: one writer of the inbox files at a time (O_EXCL, works on every OS). Not reentrant.
    Only the owner removes it again (a token in the file), so a slow holder never frees a successor's lock."""
    lock = root / ".orch" / "relay.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(8).encode()
    end = time.monotonic() + wait
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, token)
            os.close(fd)
            break
        except FileExistsError:
            try:
                stale = time.time() - lock.stat().st_mtime > LOCK_STALE
            except OSError:
                continue
            if stale and _break_stale(lock):
                continue
            if time.monotonic() > end:
                raise Refused("The relay inbox is busy right now. Try again in a moment.") from None
            time.sleep(0.02)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            if lock.read_bytes() == token:
                lock.unlink()


def _allows_path(root: Path) -> Path:
    return net.secrets_dir(root) / "allows.json"


def allows(root: Path) -> dict:
    a = net.read_json(_allows_path(root), {})
    a.setdefault("given", [])
    a.setdefault("received", [])
    return a


def _save_allows(root: Path, a: dict) -> None:
    net.write_json(_allows_path(root), a, True)


def _check_id(mid: str) -> str:
    if not re.fullmatch(r"m_[a-z0-9]{16}", mid):
        raise Refused(f"{mid} is not a message id (m_ and 16 letters or digits).")
    return mid


def load_message(root: Path, mid: str) -> dict:
    p = root / ".orch" / "inbox" / f"{_check_id(mid)}.json"
    if not p.is_file():
        raise Refused(f"Message {mid} is not in .orch/inbox/. Run: orch relay inbox")
    return json.loads(p.read_text(encoding="utf-8"))


# ---- allows (local-files.md, inbox rule 3) -------------------------------------------------------


def allowed(root: Path, msg: dict) -> str | None:
    """'once', 'permanent' or None for a delegate/start message."""
    if msg.get("type") not in ("delegate", "start"):
        return None
    kind, key = msg["type"], msg.get("body", {}).get("key")
    tok = msg.get("body", {}).get("allow_token")
    for g in allows(root)["given"]:
        if g.get("peer") != msg.get("from") or g.get("kind") != kind:
            continue
        if g.get("message_id") == msg["id"] and not g.get("used"):
            # the message the human just allowed runs once, for --once and --permanent alike
            return "once" if g.get("mode") == "once" else "permanent"
        if (
            g.get("mode") == "permanent"
            and (kind != "start" or g.get("key") == key)
            and isinstance(tok, str)
            and hmac.compare_digest(tok, str(g.get("token", "")))
        ):
            return "permanent"
    return None


def give_allow(root: Path, mid: str, mode: str, by: str | None = None, via: str | None = None) -> dict:
    msg = load_message(root, mid)
    if msg.get("type") not in ("delegate", "start"):
        raise Refused("Only a delegate or start message can be allowed.")
    kind = msg["type"]
    key = msg.get("body", {}).get("key") if kind == "start" else None
    token = "ora_" + secrets.token_urlsafe(16)[:22]
    entry = {
        "token": token,
        "peer": msg["from"],
        "kind": kind,
        "key": key,
        "mode": mode,
        "message_id": mid,
        "used": False,
    }
    if by:
        entry["by"], entry["via"] = by, via
    body = {"mode": mode, "kind": kind, "token": token}
    if key:
        body["key"] = key
    # save the allow first: a second attempt (slow relay, stale lock) must see it and not give another
    a = allows(root)
    a["given"].append(entry)
    _save_allows(root, a)
    try:
        out = _message(root, msg["from"], "allow", body, reply_to=mid)
    except Refused:  # the relay said no: nothing was given
        a = allows(root)
        a["given"] = [g for g in a["given"] if g.get("token") != token]
        _save_allows(root, a)
        raise
    if (atid := _allow_ticket(root, mid)) is not None:  # allowed from any surface: the question is settled
        who = by if by else "someone"
        word = "Allow once" if mode == "once" else "Always"

        def settle(tk):
            q = next((x for x in tk["questions"] if x.get("kind") == "relay:allow"), None)
            if q is not None and q["answer"] is None:  # allowed by the CLI, not by answering the question
                q["answer"], q["answered_by"], q["via"] = word, by or "unknown", via or "cli"
                tk["waiting_on"] = None
                if tk["status"] == "waiting":
                    tk["status"] = "active"
            tickets.add_history(tk, "agent:relay", f"Allowed by {who} ({via or 'cli'})", "relay")

        tickets.apply_op(root, atid, settle)
        # the ticket stays: `relay done` turns it into the task's ticket (one delegate = one ticket)
    return out


def _use_once(root: Path, msg: dict) -> None:
    a = allows(root)
    for g in a["given"]:
        if g.get("message_id") == msg["id"]:
            g["used"] = True
    _save_allows(root, a)


def _received_token(root: Path, peer: str, kind: str, key: str | None) -> str | None:
    for r in allows(root)["received"]:
        if r.get("peer") == peer and r.get("kind") == kind and (kind != "start" or r.get("key") == key):
            return r["token"]
    return None


# ---- sending ------------------------------------------------------------------------------------


def _read_dir(root: Path) -> dict:
    return net.read_json(root / ".agents" / "skills" / "orch-relay" / "workspaces.json", {})


def _directory(root: Path) -> list[dict]:
    """Workspaces and paired phones from workspaces.json (refresh writes it)."""
    d = _read_dir(root)
    return [*d.get("workspaces", []), *d.get("phones", [])]


def resolve(root: Path, target: str) -> str:
    """ws_/ph_ id, 'phones', or a workspace or phone name from workspaces.json."""
    if re.fullmatch(r"ws_[a-z0-9]{10}|phones|ph_[a-z0-9]{10}", target):
        return target
    entries = _directory(root)
    for w in entries:
        if w.get("id") == target:
            return w["id"]
    # Workspaces are matched before phones. Two entries with the same name: ask for the id.
    d = _read_dir(root)
    for kind, label in (("workspaces", "workspaces"), ("phones", "phones")):
        hits = [w for w in d.get(kind, []) if target.lower() == str(w.get("name", "")).lower()]
        if len(hits) == 1:
            return hits[0]["id"]
        if len(hits) > 1:
            count = {2: "Two"}.get(len(hits), str(len(hits)))
            raise Refused(
                f"{count} {label} are called {target}: {', '.join(h['id'] for h in hits)}. Send to the id."
            )
    names = [w["name"] for w in _directory(root) if w.get("name")]
    known = " You can message: " + ", ".join(names) + "." if names else ""
    raise Refused(
        f"No reachable workspace called {target}. Ask the admin.{known} "
        "Run: orch relay refresh to update the list."
    )


def name_of(root: Path, ws_id: str) -> str:
    """A workspace's or phone's name from workspaces.json, else the id (phones, admin, unknown)."""
    for w in _directory(root):
        if w.get("id") == ws_id:
            return w["name"]
    return {"phones": "the phones", "admin": "the admin"}.get(ws_id, ws_id)


def _unreachable(e: Refused) -> bool:
    """No answer, a server error (5xx), too many requests (429) or a timeout (408): keep and retry.
    Only a clear 4xx from the relay means it will never take this message."""
    status = getattr(e, "status", None)
    return status is None or status >= 500 or status in (408, 429)


def _post_message(root: Path, raw: bytes) -> None:
    cfg = _cfg(root)
    headers = {**net.auth_headers(cfg), "Content-Type": "application/json"}
    net.call_json("POST", cfg["url"] + "/v1/messages", headers, raw, 60)


def _outbox(root: Path) -> Path:
    return root / ".orch" / "outbox"


def _write_outbox(root: Path, mid: str, raw: bytes) -> Path:
    d = _outbox(root)
    d.parent.mkdir(parents=True, exist_ok=True)
    d.mkdir(exist_ok=True)
    if d.is_symlink():
        raise Refused(".orch/outbox is a link. Not sending.")
    p = d / f"{mid}.json"
    skills.ensure_gitignore(root)
    harness.check_private_path(root, p)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(p, flags, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(raw)
    return p


def _own_key(root: Path, tid: str) -> str | None:
    try:
        return tickets.load(root, tid).get("key")
    except (Refused, OSError, ValueError):
        return None


def _message(
    root: Path, to: str, type_: str, body: dict, ticket: str | None = None, reply_to: str | None = None
) -> dict:
    """Save the exact bytes first, then post. When the relay can't be reached the file stays in
    .orch/outbox/ and the result carries sent=False: the next orch relay command sends the same bytes."""
    msg = {
        "schema": "orch.msg/1",
        "id": new_id(),
        "from": _cfg(root)["workspace"],
        "to": to,
        "type": type_,
        "created_at": tickets.now(),
        "body": body,
    }
    if ticket:
        msg["ticket"] = ticket
        key = _own_key(root, ticket) if type_ != "answer" else None  # an answer's ticket is the asker's
        if key:
            msg["key"] = key  # display key next to the id (relay-api.md): phones show it
    if reply_to:
        msg["reply_to"] = reply_to
    raw = json.dumps(msg).encode("utf-8")
    path = _write_outbox(root, msg["id"], raw)
    from orch import relay_view

    relay_view.record_sent(root, msg)
    try:
        _post_message(root, raw)
    except Refused as e:
        if _unreachable(e):
            return {**msg, "sent": False}
        path.unlink(missing_ok=True)  # the relay said no: nothing to retry
        raise
    path.unlink(missing_ok=True)
    return msg


def outbox_list(root: Path) -> list[dict]:
    """Messages saved but not taken by the relay yet, oldest first: [{id, to, type, created_at}]."""
    out = []
    d = _outbox(root)
    if d.is_symlink() or not d.is_dir():
        return out
    for f in sorted(d.glob("m_*.json")):
        if f.is_symlink() or not re.fullmatch(r"m_[a-z0-9]{16}", f.stem):
            continue
        m = net.read_json(f, None)
        if isinstance(m, dict) and m.get("id") == f.stem:
            out.append({k: m.get(k) for k in ("id", "to", "type", "created_at")})
    return sorted(out, key=lambda m: (str(m["created_at"]), m["id"]))


def resend_outbox(root: Path) -> dict:
    """Post what is left in .orch/outbox/, byte for byte (same id: the relay never makes a second message).
    Returns {"sent": [ids], "waiting": [ids], "dropped": [{id, reason}]}. Stops at the first unreachable."""
    res: dict = {"sent": [], "waiting": [], "dropped": []}
    with contextlib.suppress(Refused):
        apply_allow_answers(root)  # the next orch relay command applies an answered allow question
    items = outbox_list(root)
    for n, m in enumerate(items):
        p = _outbox(root) / f"{m['id']}.json"
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        try:
            _post_message(root, raw)
        except Refused as e:
            if _unreachable(e):
                res["waiting"] = [x["id"] for x in items[n:]]
                break
            res["dropped"].append({"id": m["id"], "reason": str(e)})
        else:
            res["sent"].append(m["id"])
        p.unlink(missing_ok=True)
    return res


UPDATE_KINDS = ("ack", "working", "note", "result", "question", "failure", "stopped")


def _update_title(root: Path, ticket: str) -> str | None:
    """The ticket's title as the phone's one-line title (letters, numbers, punctuation, symbols, spaces)."""
    try:
        title = tickets.load(root, ticket)["title"]
    except (Refused, ValueError, KeyError):
        return None
    line = " ".join(clean_untrusted(title, 200).split())
    line = "".join(c for c in line if unicodedata.category(c)[0] in "LMNPS" or c == " ")
    return line[:120].strip() or None


def _is_general(root: Path, ticket: str | None) -> bool:
    if not ticket:
        return False
    try:
        return tickets.load(root, ticket).get("general") is True
    except (Refused, ValueError, OSError):
        return False


_DE_WORDS = re.compile(
    r"\b(der|die|das|und|nicht|ist|ich|wir|ein|eine|f\u00fcr|mit|auf|den|dem|von|zu|wurde|haben|bitte|sind|auch|noch)\b",
    re.I,
)
_EN_WORDS = re.compile(r"\b(the|and|is|to|of|for|with|that|this|you|are|was|have|it|in|on|please)\b", re.I)


def guess_lang(text: str) -> str:
    """de or en from the words of a text (simple on purpose)."""
    de = len(_DE_WORDS.findall(text)) + len(re.findall("[\u00e4\u00f6\u00fc\u00df]", text, re.I))
    return "de" if de > len(_EN_WORDS.findall(text)) else "en"


def speak_hint(root: Path, ticket: str | None, text: str, summary: str | None = None) -> dict:
    """body.speak = {lang, summary?}; lang: the ticket's last voice message (de-CH is de), else guessed"""
    lang = None
    if ticket:
        last = str(_v3_state(root).get("lang", {}).get(ticket, ""))[:2]
        lang = last if last in ("de", "en") else None
    hint = {"lang": lang or guess_lang(f"{text} {summary or ''}")}
    if summary is not None:
        summary = " ".join(clean_untrusted(summary, 600).split())
        if not summary:
            raise Refused("The spoken summary is empty.")
        hint["summary"] = summary[:600]
    return hint


def send_text(
    root: Path,
    target: str,
    text: str,
    ticket: str | None = None,
    update: str | None = None,
    reply_to: str | None = None,
    view: bool | None = None,
    general: bool = False,
    speak: dict | None = None,
) -> dict:
    """view: add the ticket snapshot for the phone (body.ticket_view); default for result, failure,
    stopped and question updates to a phone. A snapshot the relay refuses never blocks the text:
    it goes again without one. general (or a General ticket): the text goes to the General conversation
    (body.general, no ticket, only the ack and working updates). speak: body.speak."""
    from orch import phone_view

    body: dict = {"text": text}
    to = resolve(root, target)
    general = general or _is_general(root, ticket)
    if general:
        ticket = None
        body["general"] = True
    if speak:
        body["speak"] = speak
    if update:
        if update not in UPDATE_KINDS:
            raise Refused(f"--update is one of: {', '.join(UPDATE_KINDS)}.")
        if general and update not in ("ack", "working"):
            raise Refused("In General only the updates ack and working exist.")
        if not ticket and not general:
            raise Refused("An update belongs to a ticket. Add --ticket <id>.")
        body["update"] = {"kind": update}
        if ticket and (title := _update_title(root, ticket)):
            body["update"]["title"] = title
    to_phone = to == "phones" or to.startswith("ph_")
    if view is None:
        view = to_phone and update in phone_view.SEND_KINDS
    if update and ticket and view and (tv := phone_view.view_for(root, ticket)):
        try:
            msg = _message(root, to, "text", {**body, "ticket_view": tv}, ticket, reply_to)
        except Refused:
            msg = _message(root, to, "text", body, ticket, reply_to)
    else:
        msg = _message(root, to, "text", body, ticket, reply_to)
    if update and ticket and to_phone:
        phone_view.remember(root, ticket, to)
    return msg


def send_file(root: Path, target: str, path: Path, text: str | None, ticket: str | None = None) -> dict:
    if not path.is_file():
        raise Refused(f"{path} is not a file.")
    if path.stat().st_size > MAX_BLOB:
        raise Refused("The file is bigger than 100 MB.")
    to = resolve(root, target)
    data = path.read_bytes()
    blob = _api(root, "POST", "/v1/blobs", data, 300)[1]
    body = {"blob_id": blob["blob_id"], "name": path.name, "size": len(data), "sha256": blob["sha256"]}
    if blob["sha256"] != hashlib.sha256(data).hexdigest() or blob["size"] != len(data):
        raise Refused("The relay stored something different from the file. Not sent.")
    if text:
        body["text"] = text
    return _message(root, to, "file", body, ticket)


def send_delegate(
    root: Path, target: str, title: str, text: str, checklist: list[str], ticket: str | None
) -> dict:
    to = resolve(root, target)
    body: dict = {"title": title, "text": text}
    if checklist:
        body["checklist"] = checklist
    tok = _received_token(root, to, "delegate", None)
    if tok:
        body["allow_token"] = tok
    return _message(root, to, "delegate", body, ticket)


def send_start(root: Path, target: str, key: str, text: str, ticket: str | None) -> dict:
    if not re.fullmatch(r"[a-z0-9-]{1,48}", key):
        raise Refused("A start key has lowercase letters, digits and dashes (max 48).")
    to = resolve(root, target)
    body = {"key": key, "text": text}
    tok = _received_token(root, to, "start", key)
    if tok:
        body["allow_token"] = tok
    return _message(root, to, "start", body, ticket)


PERMISSION_OPTIONS = ("Once", "Always", "No")


def question_extras(q: dict, previews: list[str] | None, scope: str | None) -> dict:
    """body.previews ({option: attachment id}) and body.scope for a question to the phones. Refused
    when an option is not one of the question's, an id is not an artifact id, or --scope is not a
    permission question (options Once, Always, No)."""
    out: dict = {}
    if previews:
        pv = {}
        for item in previews:
            opt, eq, aid = item.rpartition("=")
            opt = opt.strip()
            if not eq or opt not in q["options"]:
                opts = ", ".join(q["options"])
                raise Refused(f'--preview is "<option>=<attachment id>"; the options are: {opts}.')
            if not re.fullmatch(r"a_[0-9a-f]{12}", aid.strip()):
                raise Refused("An attachment id looks like a_ and 12 letters or digits.")
            pv[opt] = aid.strip()
        out["previews"] = pv
    if scope is not None:
        scope = " ".join(clean_untrusted(scope, 120).split())
        if not scope:
            raise Refused("--scope is empty.")
        if not all(o in q["options"] for o in PERMISSION_OPTIONS):
            raise Refused("--scope goes with a permission question: options Once, Always and No.")
        out["scope"] = scope[:120]
    return out


def send_question(
    root: Path, ticket: dict, q: dict, previews: list[str] | None = None, scope: str | None = None
) -> dict:
    body = {
        "question_id": q["id"],
        "title": ticket["title"],
        "text": q["text"],
        "options": q["options"],
        "recommended": q["recommended"],
        **question_extras(q, previews, scope),
    }
    msg = _message(root, "phones", "question", body, ticket["id"])
    asked = net.read_json(_asked_path(root), {})
    asked[msg["id"]] = {"ticket": ticket["id"], "question_id": q["id"], "to": "phones"}
    net.write_json(_asked_path(root), asked, True)
    # the ticket chat gets the snapshot too (a question carries none): quietly, never pushed
    with contextlib.suppress(Refused):
        send_text(root, "phones", "Waiting for your answer", ticket["id"], "note", view=True)
    return msg


# ---- inbox --------------------------------------------------------------------------------------


def _asked_path(root: Path) -> Path:
    return net.secrets_dir(root) / "questions-sent.json"


def asked_to_phones(root: Path, tid: str, qid: str) -> bool:
    """True when this question was also sent to the phones (only a human answers those)."""
    return any(
        a.get("ticket") == tid and a.get("question_id") == qid and a.get("to") == "phones"
        for a in net.read_json(_asked_path(root), {}).values()
        if isinstance(a, dict)
    )


def _answer_asked(root: Path, msg: dict) -> tuple[dict | None, str]:
    """(our record of the question, '') when this answer is one we asked for, else (None, why)."""
    asked = net.read_json(_asked_path(root), {}).get(str(msg.get("reply_to")))
    frm, b = str(msg.get("from", "")), msg.get("body", {})
    if not isinstance(asked, dict):
        return None, "ignored: not an answer to a question this workspace sent"
    # Questions to the phones: answered by a phone, or by a relay subscriber allowed to answer (sub_).
    if not (frm.startswith(("ph_", "sub_")) if asked["to"] == "phones" else frm == asked["to"]):
        return None, f"ignored: {frm} was not asked"
    if b.get("question_id") != asked["question_id"]:
        return None, "ignored: answer is for another question"
    return asked, ""


def _answer_by(msg: dict) -> tuple[str, str]:
    frm, b = str(msg.get("from", "")), msg.get("body", {})
    by = b.get("answered_by")
    if isinstance(by, str):  # untrusted: it is pasted to the agent as "From <by>: ..."
        by = " ".join(clean_untrusted(by, 100).split())
    # A subscriber is another system: always agent:, never a person.
    ok_prefix = (
        "human:" if frm.startswith("ph_") else "agent:" if frm.startswith("sub_") else ("human:", "agent:")
    )
    if not (isinstance(by, str) and by.startswith(ok_prefix)):
        by = f"human:{frm}" if frm.startswith("ph_") else f"agent:{frm}"
    via = "phone" if frm.startswith("ph_") else "subscriber" if frm.startswith("sub_") else "relay"
    return by, via


def _applied_ticket(root: Path, msg: dict) -> str | None:
    """The ticket this answer was written into (by this message), else None. Read-only."""
    asked, _ = _answer_asked(root, msg)
    if not asked:
        return None
    by, via = _answer_by(msg)
    try:
        q = next(
            x for x in tickets.load(root, asked["ticket"])["questions"] if x["id"] == asked["question_id"]
        )
    except (Refused, StopIteration, ValueError, KeyError):
        return None
    return (
        asked["ticket"]
        if q.get("answer") is not None and q.get("answered_by") == by and q.get("via") == via
        else None
    )


def _apply_answer(root: Path, msg: dict) -> tuple[str, str | None]:
    """(note, ticket id when the answer was applied). Only for a question this workspace sent."""
    asked, why = _answer_asked(root, msg)
    if not asked:
        return why, None
    by, via = _answer_by(msg)
    try:
        t, q = tickets.answer(
            root,
            asked["ticket"],
            asked["question_id"],
            clean_untrusted(str(msg.get("body", {}).get("answer")), 2000),
            by,
            via,
        )
    except Refused as e:
        if _applied_ticket(root, msg):  # a crash after the write, before "seen": same answer, nothing to redo
            return f"answered {asked['question_id']} on {asked['ticket']} (via {via})", asked["ticket"]
        return f"not applied to {asked['ticket']}: {e}", None
    _to_waiting_agent(root, t["id"], q, by)
    return f"answered {asked['question_id']} on {asked['ticket']} (via {via})", asked["ticket"]


def _to_waiting_agent(root: Path, tid: str, q: dict, by: str) -> None:
    """An agent runs on the ticket: the answer goes into its answer queue, like `orch answer` (live: pasted
    when it is idle). A phone's answer is a person's; another workspace's (agent:<name>) goes in too, since
    the agent here is still waiting for it. The answer is saved either way: a busy run only delays it."""
    from orch import runs_live

    with contextlib.suppress(Refused, OSError):
        if by.startswith("human:"):
            runs_live.pass_answer(root, tid, q, by)
        elif (rec := runs.read(root, tid)) and runs.state(rec) == "alive":
            runs_live.send(
                root, tid, by, f"Answer to your question {q['id']} ({q['text']}): {q['answer']}", "answer"
            )


def _store_allow(root: Path, msg: dict) -> str:
    b = msg["body"]
    if b.get("mode") == "permanent":
        a = allows(root)
        a["received"].append(
            {"token": b["token"], "peer": msg["from"], "kind": b["kind"], "key": b.get("key")}
        )
        _save_allows(root, a)
        return "permanent allow saved"
    return "one-time allow (nothing to keep)"


def _arrivals_path(root: Path) -> Path:
    return root / ".orch" / "inbox" / "arrivals.jsonl"


def _read_arrivals(root: Path) -> list[dict]:
    try:
        lines = _arrivals_path(root).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if isinstance(e, dict) and isinstance(e.get("seq"), int) and isinstance(e.get("id"), str):
            out.append(e)
    return out


def _journal(root: Path, msgs: list[dict]) -> None:
    """Append every id not yet in arrivals.jsonl: {seq, id, type, from, at}. Under the lock, an id once."""
    with locked(root):
        have = _read_arrivals(root)
        known = {e["id"] for e in have}
        seq = max((e["seq"] for e in have), default=0)
        new = []
        for m in msgs:
            if m["id"] in known:
                continue
            known.add(m["id"])
            seq += 1
            new.append(
                {"seq": seq, "id": m["id"], "type": m.get("type"), "from": m.get("from"), "at": tickets.now()}
            )
        if not new:
            return
        path = _arrivals_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        if len(have) + len(new) > ARRIVALS_MAX:  # rotate: keep the newest half
            keep = (have + new)[-(ARRIVALS_MAX // 2) :]
            data = "".join(json.dumps(e) + "\n" for e in keep)
            net.write_atomic(path, data.encode("utf-8"))
        else:
            with open(path, "a", encoding="utf-8") as f:
                f.write("".join(json.dumps(e) + "\n" for e in new))


def _pull(root: Path, wait: int) -> tuple[list[dict], dict[str, int]]:
    """Download, save every message first, journal the new ids, then ack. Marks nothing seen."""
    wait = max(0, min(30, wait))
    _, resp = _api(root, "GET", f"/v1/inbox?wait={wait}", timeout=wait + 30)
    d = root / ".orch" / "inbox"
    ok = []
    arrival = {}
    for n, m in enumerate(net.items(resp)):
        if not isinstance(m, dict) or not re.fullmatch(r"m_[a-z0-9]{16}", str(m.get("id", ""))):
            continue
        net.write_json(d / f"{m['id']}.json", m)
        arrival[m["id"]] = n
        ok.append(m)
    if ok:
        _journal(root, ok)
        _api(root, "POST", "/v1/inbox/ack", {"ids": [m["id"] for m in ok]})
    return ok, arrival


# ---- phone texts and the allow question (SA-01, SA-12, UX-02) -----------------------------------

ALLOW_OPTIONS = ("Allow once", "Always", "Ignore")
_ALLOW_WORDS = {
    "allow once": "once",
    "once": "once",
    "always": "permanent",
    "ignore": "ignore",
    "no": "ignore",
}


def _by_relay(frm: str) -> str:
    return f"agent:relay from {frm}"


def _mark_described(root: Path, mid: str) -> None:
    st = _v3_state(root)
    if mid not in st["described"]:
        st["described"].append(mid)
        st["described"] = st["described"][-V3_STATE_KEEP:]
        _v3_save(root, st)


def _ticket_exists(root: Path, tid) -> bool:
    try:
        tickets.load(root, str(tid))
    except (Refused, ValueError, OSError):
        return False
    return True


def _relay_ext(root: Path, tid: str) -> dict:
    r = tickets.load(root, tid).get("ext", {}).get("relay", {})
    return r if isinstance(r, dict) else {}


def _phone_title(root: Path, text: str, frm: str) -> str:
    line = " ".join(clean_untrusted(text, 400).split())[:120].strip()
    return line or f"Message from {name_of(root, frm)}"


# State of the phone conversation: .orch/secrets/phone-v3.json
#   acked   message ids of phone texts that got their ack (written before the ack is sent: never twice)
#   working {message id: {ticket, to, general, kind: item|run, at}} acks waiting for "working"
#   lang    {ticket id: language of the last voice message there}
V3_STATE_KEEP = 300
WORKING_DAYS = 7


def _v3_path(root: Path) -> Path:
    return net.secrets_dir(root) / "phone-v3.json"


def _v3_state(root: Path) -> dict:
    s = net.read_json(_v3_path(root), {})
    s = s if isinstance(s, dict) else {}
    for k, v in (
        ("acked", []),
        ("working", {}),
        ("lang", {}),
        ("saved", {}),
        ("tries", {}),
        ("described", []),
    ):
        if not isinstance(s.get(k), type(v)):
            s[k] = v
    return s


def _v3_save(root: Path, s: dict) -> None:
    s["acked"] = s["acked"][-V3_STATE_KEEP:]
    net.write_json(_v3_path(root), s, True)


def _num(v) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


PHONE_BLOB_MAX = 25 * 1024 * 1024
PHONE_TRIES = (
    5  # tries after a transient relay error, and at least PHONE_RETRY_SECONDS since the first failure,
)
PHONE_RETRY_SECONDS = 60  # then the last pull finishes the message without the files it could not fetch


class Transient(Refused):
    """The relay could not be reached just now: the phone message is kept and tried again on the next pull."""


def _fetch_blob(root: Path, blob_id, size, sha256=None) -> bytes | None:
    """The bytes of a phone upload, or None: bad id, over 25 MB, wrong size, a clear refusal, or (when the
    message names one) wrong sha256. No answer, 5xx or 429 raises Transient: retry later."""
    if not re.fullmatch(r"b_[a-z0-9]{16}", str(blob_id)):
        return None
    if isinstance(size, int) and not isinstance(size, bool) and size > PHONE_BLOB_MAX:
        return None
    cfg = _cfg(root)
    try:
        _, raw = net.call(
            "GET",
            f"{cfg['url']}/v1/blobs/{blob_id}",
            net.auth_headers(cfg),
            timeout=300,
            limit=PHONE_BLOB_MAX,
        )
    except Refused as e:
        if _unreachable(e):
            raise Transient(str(e)) from None  # no answer or a server error: tried again, nothing is dropped
        return None  # a clear 4xx (gone, not yours) or too big: it will never work
    if not isinstance(raw, bytes):
        return None
    if isinstance(size, int) and len(raw) != size:
        return None
    if isinstance(sha256, str) and hashlib.sha256(raw).hexdigest() != sha256.lower():
        return None
    return raw


def _save_phone_file(root: Path, tid: str, mid: str, att: dict, final: bool = False) -> str:
    """Download one attachment of a phone text into .orch/tickets/<tid>/files/ and return the line the agent
    sees. Name, kind and mime come from the phone and are not trusted: only a cleaned base name is used."""
    kind = att.get("kind")
    label = {"image": "Photo", "voice": "Voice recording"}.get(kind, "File")
    shown = _line(att.get("name", ""), 80) or "file"
    key = f"{mid}:{att.get('blob_id')}"
    st = _v3_state(root)
    if (done := st.setdefault("saved", {}).get(key)) and (root / done).is_file():
        return f"{label}: {done}"  # a retry of this message: never download or save it twice
    try:
        raw = _fetch_blob(root, att.get("blob_id"), att.get("size"), att.get("sha256"))
    except Transient:
        if not final:
            raise
        raw = None  # last try: the ticket is finished without this file
    if raw is None:
        return f"{label} {shown}: could not be downloaded."
    try:
        name = safe_name(att.get("name", ""))
    except Refused:
        name = "file"
    dest = _save_into(tickets.files_dir(root, tid), name, raw)
    rel = dest.relative_to(root).as_posix()
    st["saved"][key] = rel
    st["saved"] = dict(list(st["saved"].items())[-V3_STATE_KEEP:])
    _v3_save(root, st)
    return f"{label}: {rel}"


def _line(v, n: int) -> str:
    """One line of phone-supplied free text: cleaned, whitespace collapsed (no line breaks), cut to n."""
    return " ".join(clean_untrusted(str(v), n * 2).split())[:n]


def _int_in(v, lo: int, hi: int) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi else None


def _frac(v) -> int | None:
    f = _num(v)
    return round(f * 100) if f is not None and 0 <= f <= 1 else None


def _pin_line(pin: dict) -> str:
    a = pin.get("anchor") if isinstance(pin.get("anchor"), dict) else {}
    kind = a.get("type")
    if kind == "html":
        q = _line(a.get("quote") or a.get("selector") or "", 200)
        where = f'"{q}"' if q else "the page"
    elif kind == "pdf":
        page = _int_in(a.get("page"), 1, 99999)
        where = f"page {page}" if page else "a page"
    else:
        x, y = _frac(a.get("x")), _frac(a.get("y"))
        where = f"the picture at {x}% across, {y}% down" if x is not None and y is not None else "the picture"
    said = _line(pin.get("text") or pin.get("transcript") or "", 300)
    n = _int_in(pin.get("n"), 1, 50) or "-"
    return f"  {n}. {where}: {said}".rstrip(": ")


DESCRIBE_MAX = 7500  # runs.pending_add takes 8000
LISTED = 10


def _more(n: int, what: str) -> str:
    return f"  (+{n} more {what} not shown)"


def _describe(root: Path, tid: str, mid: str, who: str, body: dict, final: bool = False) -> str:
    """What a phone text says in plain words for the ticket's history and the agent: the text, the voice
    transcript (and its language), saved photos and files (paths), the location with a map link and the
    feedback on a proof. Files are downloaded on the way."""
    from orch import phone_view

    lines = []
    text = _line(body.get("text", ""), 2000)  # one line: it cannot fake the lines orch adds below
    if text:
        lines.append(text)
    voice = body.get("voice")
    if isinstance(voice, dict):
        said = _line(voice.get("transcript", ""), 2000)
        lang = str(voice.get("lang", ""))
        lang = lang if re.fullmatch(r"[a-z]{2}(-[A-Z]{2})?", lang) else "unknown"
        lines.append(
            f'Voice message ({lang}): "{said}"' if said else "Voice message (nothing could be understood)"
        )
        if lang != "unknown":
            st = _v3_state(root)
            st["lang"][tid] = lang
            _v3_save(root, st)
    atts = body.get("attachments")
    atts = atts if isinstance(atts, list) else []
    for att in atts[:LISTED]:
        if isinstance(att, dict):
            try:
                lines.append(_save_phone_file(root, tid, mid, att, final))
            except Transient:
                raise
            except (Refused, OSError):
                lines.append("A file could not be saved.")
    if len(atts) > LISTED:
        lines.append(_more(len(atts) - LISTED, "files"))
    loc = body.get("location")
    lat, lon = (_num(loc.get("lat")), _num(loc.get("lon"))) if isinstance(loc, dict) else (None, None)
    if lat is not None and lon is not None:
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            label = _line(loc.get("label", ""), 100)
            q = urllib.parse.urlencode({"ll": f"{lat},{lon}", **({"q": label} if label else {})})
            lines.append(
                f"Location: {lat:.5f}, {lon:.5f}"
                + (f" ({label})" if label else "")
                + f" - https://maps.apple.com/?{q}"
            )
    fb = body.get("feedback")
    if isinstance(fb, dict):
        try:
            ticket = tickets.load(root, tid)
        except (Refused, OSError, ValueError):
            ticket = {}
        title = (
            _line(phone_view.artifact_title(root, ticket, str(fb.get("artifact_id", ""))) or "", 100)
            or "a file"
        )
        rev = re.sub(r"[^A-Za-z0-9._:-]", "", str(fb.get("artifact_rev", "")))[:12]
        head = f"Feedback on {title}" + (f" ({rev})" if rev else "")
        if fb.get("verdict") == "approve":
            lines.append(f"{head}: \U0001f44d Looks good")
        else:
            lines.append(f"{head}: changes wanted")
        pins = [
            p for p in (fb.get("pins") if isinstance(fb.get("pins"), list) else []) if isinstance(p, dict)
        ]
        lines += [_pin_line(p) for p in pins[:LISTED]]
        if len(pins) > LISTED:
            lines.append(_more(len(pins) - LISTED, "comments"))
    first = f"From {who}: {lines[0]}" if lines else f"From {who}: (empty)"
    out = "\n".join([first, *lines[1:]])
    return (
        out
        if len(out) <= DESCRIBE_MAX
        else out[: DESCRIBE_MAX - 40].rstrip() + "…\n  (the rest is not shown)"
    )


def _ack_once(root: Path, mid: str, to: str, tid: str, general: bool, text: str) -> None:
    """The ack of a phone text, at most once (marked before it goes out: the outbox keeps it until the relay
    takes it). Not reachable now: the work goes on, nobody is blocked."""
    st = _v3_state(root)
    if mid in st["acked"]:
        return
    st["acked"].append(mid)
    _v3_save(root, st)
    with contextlib.suppress(Refused):
        if general:
            send_text(root, to, text, None, "ack", mid, general=True)
        else:
            send_text(root, to, text, tid, "ack", mid)


def _working_add(root: Path, mid: str, to: str, tid: str, general: bool, kind: str) -> None:
    st = _v3_state(root)
    if mid not in st["working"]:
        st["working"][mid] = {"ticket": tid, "to": to, "general": general, "kind": kind, "at": time.time()}
        _v3_save(root, st)


def send_working(root: Path) -> list[str]:
    """The "working" update for phone texts whose agent run has started: the text went into a run
    (kind item: its queued input was delivered) or the run of a new ticket exists (kind run). Once each."""
    st = _v3_state(root)
    sent = []
    for mid, w in list(st["working"].items()):
        tid, ready = w.get("ticket"), False
        if time.time() - float(w.get("at", 0)) > WORKING_DAYS * 86400 or not _ticket_exists(root, tid):
            st["working"].pop(mid)
            continue
        if w.get("kind") == "run":
            rec = runs.read(root, tid)
            ready = bool(rec) and runs.state(rec) != "dead"
        else:
            item = next((i for i in runs._pending_read(root, tid) if i["id"] == "p_" + mid[2:]), None)
            if item is None:
                st["working"].pop(mid)
                continue
            ready = bool(item.get("delivered_at"))
        if not ready:
            continue
        st["working"].pop(mid)
        _v3_save(root, st)  # first: never twice
        with contextlib.suppress(Refused):
            if w.get("general"):
                send_text(root, w["to"], "Working on it", None, "working", mid, general=True)
            else:
                send_text(root, w["to"], "Working on it", tid, "working", mid)
            sent.append(mid)
    _v3_save(root, st)
    return sent


def _continue(
    root: Path, tid: str, mid: str, who: str, by: str, body: dict, general: bool, final: bool = False
) -> None:
    """A phone text into an existing ticket (or the General ticket): queue it for the running agent, then
    record it. Same message id twice = once."""
    if mid in _relay_ext(root, tid).get("messages", []):
        return
    text = _describe(root, tid, mid, who, body, final)
    if general:
        text += f'\n(Phone message {mid}. To make a ticket of it: orch relay topic --from {mid} "<title>")'
    runs.pending_add(root, tid, who, "message", text, "phone", "p_" + mid[2:])

    def op(t):
        r = t.setdefault("ext", {}).setdefault("relay", {})
        if mid in r.get("messages", []):
            return
        r["messages"] = [*r.get("messages", []), mid][-50:]
        tickets.add_history(t, by, text, "phone")
        t["waiting_on"] = None
        if general:
            return
        if t["status"] in ("done", "dropped"):
            t["status"] = "open"
            tickets.add_history(t, by, "Reopened by a text from the phone", "phone")
        elif t["status"] == "waiting":
            t["status"] = "active"

    tickets.apply_op(root, tid, op)


def _phone_text(root: Path, msg: dict, final: bool = False) -> tuple[str, str]:
    """Act on a text from a phone (under relay.lock). General (body.general) goes to the hidden General
    ticket, a text naming a local ticket continues it, any other makes a new ticket. Every phone text gets
    an ack (reply_to = its id) and later a "working" update. Idempotent by message id.
    Returns (note, ticket id)."""
    mid, frm = msg["id"], msg["from"]
    body = msg.get("body") if isinstance(msg.get("body"), dict) else {}
    who = _line(name_of(root, frm), 100) or _line(frm, 100)
    by = _by_relay(frm)
    general = body.get("general") is True and not msg.get("ticket")
    tid = _ticket_by_message(root, mid)
    if tid is not None and _relay_ext(root, tid).get("message") != mid:
        # a re-run of a text that continued a ticket: only an ack that did not go out is still sent
        _ack_once(root, mid, frm, tid, general, "Got it")
        return f"added to {tid}", tid
    if tid is None and general:
        tid = tickets.ensure_general(root, by)
        _continue(root, tid, mid, who, by, body, True, final)
        _working_add(root, mid, frm, tid, True, "item")
        _ack_once(root, mid, frm, tid, True, "Got it")
        return "General conversation", tid
    if tid is None and msg.get("ticket") and _ticket_exists(root, msg["ticket"]):
        tid = msg["ticket"]
        _continue(root, tid, mid, who, by, body, False, final)
        _working_add(root, mid, frm, tid, False, "item")
        _ack_once(root, mid, frm, tid, False, "Got it")
        return f"added to {tid}", tid
    if tid is None:
        spoken = body.get("voice", {}).get("transcript", "") if isinstance(body.get("voice"), dict) else ""
        t = tickets.create(root, _phone_title(root, str(body.get("text") or spoken or ""), frm), by)
        tid = t["id"]
        tickets.ext_set(root, tid, "relay", json.dumps({"origin": "phone", "from": frm, "message": mid}), by)
    if mid not in _v3_state(root)["described"]:
        # also the retry of a message whose files could not be fetched the first time (Transient)
        text = _describe(root, tid, mid, who, body, final)
        tickets.apply_op(root, tid, lambda t: tickets.add_history(t, by, text, "phone"))
        _mark_described(root, mid)
        _working_add(root, mid, frm, tid, False, "run")
    _ack_once(root, mid, frm, tid, False, f"Got it: {tickets.load(root, tid)['title']}"[:300])
    return f"new ticket {tid}", tid


def topic(root: Path, mid: str, title: str, by: str) -> dict:
    """`orch relay topic --from <message id> "<title>"`: a phone text (usually in General) becomes a normal
    ticket with that message as its first input. The ack names the new ticket and its key (reply_to = the
    message), so the phone shows "<key> started"."""
    msg = load_message(root, mid)
    if msg.get("type") != "text" or not str(msg.get("from", "")).startswith("ph_"):
        raise Refused(f"{mid} is not a text from a phone.")
    frm = msg["from"]
    body = msg.get("body") if isinstance(msg.get("body"), dict) else {}
    who = _line(name_of(root, frm), 100) or _line(frm, 100)
    for t in tickets.list_all(root):
        if _relay_ext(root, t["id"]).get("message") == mid:
            if mid in _v3_state(root)["described"]:
                raise Refused(f"That message already started {t.get('key') or t['id']}.")
            # started but never finished (an error half way): finish it now
            tid = t["id"]
            text = _describe(root, tid, mid, who, body, True)
            tickets.apply_op(root, tid, lambda tk, text=text: tickets.add_history(tk, by, text, "phone"))
            _mark_described(root, mid)
            st = _v3_state(root)
            st["acked"].append(mid)
            _v3_save(root, st)
            ack = send_text(root, frm, f"Got it: {t['title']}"[:300], tid, "ack", mid)
            return {"ticket": tid, "key": t.get("key"), "message": ack}
    title = " ".join(clean_untrusted(title, 400).split())[:200].strip()
    if not title:
        raise Refused("A topic needs a title.")
    t = tickets.create(root, title, by)
    tid = t["id"]
    tickets.ext_set(root, tid, "relay", json.dumps({"origin": "phone", "from": frm, "message": mid}), by)
    text = _describe(root, tid, mid, who, body, True)
    tickets.apply_op(root, tid, lambda t: tickets.add_history(t, by, text, "phone"))
    _mark_described(root, mid)
    st = _v3_state(root)
    st["acked"].append(mid)  # this ack names the ticket; the General "Got it" is not sent again
    _v3_save(root, st)
    ack = send_text(root, frm, f"Got it: {title}"[:300], tid, "ack", mid)
    return {"ticket": tid, "key": t.get("key"), "message": ack}


def _task_of(msg: dict) -> str:
    b = msg.get("body", {})
    return clean_untrusted(str(b.get("title") or b.get("key") or "a task"), 120)


def _allow_ticket(root: Path, mid: str) -> str | None:
    for t in tickets.list_all(root):
        r = t.get("ext", {}).get("relay", {})
        if isinstance(r, dict) and r.get("allow_message") == mid:
            return t["id"]
    return None


def _ensure_allow_question(root: Path, msg: dict) -> str:
    """A delegate/start without an allow becomes a waiting ticket with the relay:allow question, once."""
    if (tid := _allow_ticket(root, msg["id"])) is not None:
        return tid
    peer = clean_untrusted(name_of(root, msg["from"]), 100) or msg["from"]
    me = clean_untrusted(name_of(root, _cfg(root)["workspace"]), 100)
    task, by = _task_of(msg), _by_relay(msg["from"])
    t = tickets.create(root, f"{peer} wants to: {task}"[:200], by)
    tid = t["id"]
    b = msg.get("body", {})
    ext = {"origin": "workspace", "from": msg["from"], "allow_message": msg["id"]}
    tickets.ext_set(root, tid, "relay", json.dumps(ext), by)
    action = {
        "message": msg["id"],
        "peer": msg["from"],
        "kind": msg["type"],
        "key": b.get("key") if msg["type"] == "start" else None,
    }
    text = f"{peer} wants {me or 'this workspace'} to: {task}. Allow it?"
    tickets.ask(root, tid, text, list(ALLOW_OPTIONS), None, by, kind="relay:allow", action=json.dumps(action))
    return tid


def _drop_note(root: Path, mid: str, note: str) -> None:
    p = root / ".orch" / "inbox-notes.json"
    notes = net.read_json(p, {})
    notes[mid] = {"at": tickets.now(), "note": note}
    net.write_json(p, notes)


def _person(answered_by) -> str:
    s = str(answered_by or "someone")
    return s[6:] if s.startswith("human:") else s


def apply_allow_answers(root: Path) -> list[str]:
    """Apply each answered relay:allow question once (any surface answered it). Returns notes."""
    notes = []
    with locked(root):
        for t in tickets.list_all(root):
            r = t.get("ext", {}).get("relay", {})
            mid = r.get("allow_message") if isinstance(r, dict) else None
            if not mid or t.get("status") in ("done", "dropped"):
                continue
            q = next(
                (x for x in t["questions"] if x.get("kind") == "relay:allow" and x.get("answer") is not None),
                None,
            )
            if q is None or r.get("allow_applied") == q["id"]:
                continue
            choice = _ALLOW_WORDS.get(str(q["answer"]).strip().casefold())
            if choice is None:
                if r.get("allow_note") != q["id"]:
                    ans = clean_untrusted(str(q["answer"]), 100)

                    def note(tk, qid=q["id"], ans=ans, mid=mid):
                        tk["ext"]["relay"]["allow_note"] = qid
                        tickets.add_history(
                            tk,
                            "agent:relay",
                            f"Answer not understood: {ans} - run: orch relay allow {mid} --once "
                            f"(or --permanent), or: orch relay done {mid} to ignore it",
                            "relay",
                        )

                    tickets.apply_op(root, t["id"], note)
                continue
            who, via, by = (
                _person(q.get("answered_by")),
                q.get("via") or "cli",
                q.get("answered_by") or "unknown",
            )
            if choice == "ignore":
                _drop_note(root, mid, f"ignored by {who} ({via})")
                if mid not in seen(root):
                    _mark_seen(root, mid)
                label, status = f"Ignored by {who} ({via})", "dropped"
            else:
                try:
                    if not any(g.get("message_id") == mid for g in allows(root)["given"]):
                        give_allow(root, mid, choice, who, via)
                except Refused as e:
                    notes.append(f"could not allow {mid}: {e}")
                    continue
                label, status = f"Allowed by {who} ({via})", None  # give_allow wrote the history line

            def op(tk, qid=q["id"], label=label, status=status, by=by):
                tk["ext"]["relay"]["allow_applied"] = qid
                if status:  # ignored: the ticket is dropped
                    tickets.add_history(tk, by, label, "relay")
                    tk["status"], tk["waiting_on"] = status, None

            tickets.apply_op(root, t["id"], op)
            notes.append(label)
    return notes


def _allow_history(root: Path, msg: dict) -> str | None:
    for g in allows(root)["given"]:
        if g.get("message_id") == msg["id"] and g.get("by"):
            return f"Allowed by {g['by']} ({g.get('via') or 'cli'})"
    return None


def sync_phone_views(root: Path) -> None:
    """Best effort: task changes of tickets the phone follows go out quietly (phone_view.sync)."""
    from orch import phone_view

    with contextlib.suppress(Refused, OSError, ValueError, TimeoutError):
        phone_view.sync_open(root)
        phone_view.sync(root)
    with contextlib.suppress(Refused, OSError, ValueError, TimeoutError):
        send_working(root)


def _hint_applied(root: Path, m: dict) -> bool:
    """A refresh-hint for a version `orch relay refresh` has already installed (or an older one)."""
    v = (m.get("body") or {}).get("version")
    have = net.read_json(net.secrets_dir(root) / "shared.json", {})
    return (
        isinstance(v, int)
        and isinstance(have, dict)
        and isinstance(have.get("version"), int)
        and v <= have["version"]
    )


def inbox(root: Path, wait: int = 0) -> list[dict]:
    """Pull, save, journal, ack, then handle the ones not seen. Returns [{message, note, allowed}]."""
    with contextlib.suppress(Refused):
        apply_allow_answers(root)
    sync_phone_views(root)
    _, arrival = _pull(root, wait)
    d = root / ".orch" / "inbox"
    pending = []
    for f in d.glob("m_*.json"):  # everything saved and not yet seen, also from earlier pulls
        m = net.read_json(f, None)
        if isinstance(m, dict) and m.get("id") == f.stem and f.stem not in seen(root):
            pending.append(m)
    out = []
    for m in sorted(
        pending,
        # earlier pulls first, then this pull in the relay's order (created_at has 1 s resolution: ties
        # must not be broken by the random id)
        key=lambda m: (m["id"] in arrival, arrival.get(m["id"], 0), str(m.get("created_at")), m["id"]),
    ):
        note, auto, applied = "", False, None
        try:
            typ = m.get("type")
            if typ in ("answer", "allow"):
                with locked(root):
                    if m["id"] not in seen(root):  # another reader may have handled it meanwhile
                        if typ == "answer":
                            note, applied = _apply_answer(root, m)
                        else:
                            note = _store_allow(root, m)
                        auto = True
                        _mark_seen(root, m["id"])  # last
            elif _is_mobile_off(m):
                note, auto = _handle_mobile_off(root, m), True
            elif typ == "text" and str(m.get("from", "")).startswith("ph_"):
                with locked(root):
                    if m["id"] not in seen(root):
                        tr = _v3_state(root)["tries"].get(m["id"])
                        final = (
                            isinstance(tr, dict)
                            and tr.get("n", 0) >= PHONE_TRIES
                            and time.time() - float(tr.get("first", 0)) >= PHONE_RETRY_SECONDS
                        )
                        try:
                            note, applied = _phone_text(root, m, final)
                        except Transient:
                            st = _v3_state(root)
                            tr = st["tries"].get(m["id"])
                            tr = tr if isinstance(tr, dict) else {"n": 0, "first": time.time()}
                            st["tries"][m["id"]] = {"n": int(tr.get("n", 0)) + 1, "first": tr.get("first")}
                            st["tries"] = dict(list(st["tries"].items())[-V3_STATE_KEEP:])
                            _v3_save(root, st)
                            continue  # not marked seen: the next pull tries again (the last one finishes it)
                        except (Refused, OSError, ValueError, KeyError, TypeError) as e:
                            # one bad message never blocks the ones behind it: it is marked seen with a note
                            note = f"could not use this phone message: {clean_untrusted(str(e), 200)}"
                        auto = True
                        _mark_seen(root, m["id"])  # last
            elif typ == "refresh-hint" and _hint_applied(root, m):
                with locked(root):
                    _mark_seen(root, m["id"])  # the refresh already ran for this version: nothing to tell
                continue
            elif typ in ("delegate", "start") and not _allowed_or_made(root, m):
                with locked(root):
                    applied = _ensure_allow_question(root, m)
                note = f"waiting for your answer on {applied}"
                auto = True
            if not auto and (
                typ in ("answer", "allow") or typ == "text" and str(m.get("from", "")).startswith("ph_")
            ):
                continue  # another reader handled it meanwhile
        except (KeyError, TypeError) as e:
            note = f"could not read this message: {e}"
        out.append(
            {
                "message": m,
                "note": note,
                "auto": auto,
                "applied": applied,
                "allowed": _allowed_or_made(root, m),
            }
        )
    return out


def since(root: Path, seq: int, wait: int = 0) -> dict:
    """Every arrival after `seq`, seen or not: {"next", "items": [{seq, id, type, from, at, seen, applied,
    allowed}]}. Pulls (waiting up to `wait` s when nothing newer is journaled) but marks nothing seen.
    The journal is a hint: the flags come from the saved message file and the local state."""
    warning = None
    with contextlib.suppress(Refused):
        apply_allow_answers(root)
    sync_phone_views(root)
    try:
        _pull(root, 0 if [e for e in _read_arrivals(root) if e["seq"] > seq] else wait)
    except Refused as e:  # best effort: the journal on disk is still true
        warning = str(e)
    have = _read_arrivals(root)
    if have and seq < have[0]["seq"] - 1:
        seq = have[0]["seq"] - 1  # the cursor is older than what was kept: start from the oldest kept
    done_ids = seen(root)
    items = []
    for e in have:
        if e["seq"] <= seq:
            continue
        m = net.read_json(root / ".orch" / "inbox" / f"{e['id']}.json", None)
        if not isinstance(m, dict) or m.get("id") != e["id"]:
            continue
        items.append(
            {
                "seq": e["seq"],
                "id": e["id"],
                "type": m.get("type"),
                "from": m.get("from"),
                "at": e.get("at"),
                "seen": e["id"] in done_ids,
                "applied": _applied_ticket(root, m) if m.get("type") == "answer" else None,
                "allowed": bool(_allowed_or_made(root, m)),
            }
        )
    out = {"next": have[-1]["seq"] if have else seq, "items": items}
    if warning:
        out["warning"] = warning
    return out


def _ticket_by_message(root: Path, mid: str) -> str | None:
    for t in tickets.list_all(root, include_general=True):
        r = t.get("ext", {}).get("relay", {})
        if r.get("message") == mid or mid in r.get("messages", []):
            return t["id"]
    return None


def _allowed_or_made(root: Path, msg: dict) -> str | None:
    """An allow for this message, or 'once' when its ticket exists already (the allow was spent)."""
    mode = allowed(root, msg)
    if mode is None and msg.get("type") in ("delegate", "start") and _ticket_by_message(root, msg["id"]):
        return "once"
    return mode


def done(root: Path, mid: str) -> dict:
    """Under the lock: an allowed delegate/start gets its ticket (the one for this message if it exists),
    then the id is written to seen LAST. Running it twice gives the same ticket (inbox rule 2)."""
    msg = load_message(root, mid)
    with contextlib.suppress(Refused):
        apply_allow_answers(root)
    with locked(root):
        res: dict = {"id": mid, "new": mid not in seen(root), "ticket": None}
        if msg.get("type") in ("delegate", "start"):
            tid = _ticket_by_message(root, mid)
            if tid is None and allowed(root, msg):
                tid = _ticket_for(root, msg)
                _use_once(root, msg)
            res["ticket"] = tid
        _mark_seen(root, mid)
        return res


def _ticket_for(root: Path, msg: dict) -> str:
    """A start reuses a ticket only for the same sender and key while it is open; else a new one."""
    b, by = msg["body"], f"agent:relay from {msg['from']}"
    peer = clean_untrusted(name_of(root, msg["from"]), 60) or msg["from"]
    if msg["type"] == "start":
        for t in tickets.list_all(root):
            r = t.get("ext", {}).get("relay", {})
            if (
                r.get("start_key") == b["key"]
                and r.get("from") == msg["from"]
                and t.get("status") in ("open", "active", "waiting")
            ):  # remember this message too, so a second `done` finds the same ticket
                if (atid := _allow_ticket(root, msg["id"])) is not None and atid != t["id"]:
                    _merge_allow(root, atid, t["id"], by)  # before the record below: safe to run twice
                more = [*r.get("messages", []), msg["id"]]
                tickets.ext_set(root, t["id"], "relay", json.dumps({"messages": more[-20:]}), by)
                return t["id"]
        title = f"Relay task {b['key']}"
    else:
        # outside text is data: cleaned, one line, framed with who sent it, never longer than a title
        peer = clean_untrusted(name_of(root, msg["from"]), 60) or msg["from"]
        said = " ".join(clean_untrusted(b["title"], 200).split()) or "a task"
        title = f"From {peer}: {said}"[:200]
    atid = _allow_ticket(root, msg["id"])  # the allow question's ticket becomes the task's ticket
    if atid is not None:
        tid = atid

        def retitle(tk):
            tk["title"] = title
            tk["waiting_on"] = None
            if tk["status"] in ("waiting", "dropped"):
                tk["status"] = "active"

        tickets.apply_op(root, tid, retitle)
    else:
        tid = tickets.create(root, title, by)["id"]
        # a re-run after a crash finds this ticket (allow_message) and reuses it, never makes a second
        first = {"allow_message": msg["id"], "from": msg["from"]}
        tickets.ext_set(root, tid, "relay", json.dumps(first), by)
        if line := _allow_history(root, msg):
            tickets.apply_op(root, tid, lambda tk: tickets.add_history(tk, by, line, "relay"))
    if not tickets.load(root, tid)["checklist"]:
        for item in b.get("checklist", []) if msg["type"] == "delegate" else []:
            said = " ".join(clean_untrusted(str(item), 200).split()) or "(empty)"
            tickets.check_add(root, tid, f"From {peer}: {said}"[:200], by)
    ext = {"from": msg["from"], "message": msg["id"]}
    if msg["type"] == "start":
        ext["start_key"] = b["key"]
    tickets.ext_set(root, tid, "relay", json.dumps(ext), by)  # last: `done` finds the ticket by this
    return tid


def _merge_allow(root: Path, atid: str, into: str, by: str) -> None:
    """A start that joins an open ticket: its allow-question ticket is not a second task."""

    def op(tk):
        if tk["status"] not in ("done", "dropped"):
            tk["status"], tk["waiting_on"] = "dropped", None
            tickets.add_history(tk, by, f"Joined {into}", "relay")

    tickets.apply_op(root, atid, op)


_WIN_RESERVED = re.compile(
    r"^(con|prn|aux|nul|conin\$|conout\$|com[0-9\u00b9\u00b2\u00b3]|lpt[0-9\u00b9\u00b2\u00b3])(\..*)?$", re.I
)


def safe_name(name: str) -> str:
    """Base name only; characters Windows refuses become _, reserved device names get a leading _."""
    name = clean_untrusted(str(name), 1000)  # the same cleaning as the inbox line: saved name == shown name
    base = re.split(r"[\\/]", name)[-1].strip().strip(". ")
    base = re.sub(r'[<>:"|?*\x00-\x1f]', "_", base)
    if not base:
        raise Refused("The file has no usable name (it was empty or only invisible characters). Not saved.")
    if _WIN_RESERVED.match(base):
        base = "_" + base
    return base.encode("utf-8")[:200].decode("utf-8", "ignore").rstrip(". ")


def _save_received(root: Path, name: str, raw: bytes) -> Path:
    """received/<name>; a clash gets ' (2)', ' (3)' ... before the extension (created with O_EXCL)."""
    d = root / "received"
    if d.is_symlink():
        raise Refused("received is a link. Not saving.")
    if d.exists() and not d.is_dir():
        raise Refused(
            "There is a file called received in this folder. Move it away so downloads can go there."
        )
    d.mkdir(exist_ok=True)
    return _save_into(d, name, raw)


def _save_into(d: Path, name: str, raw: bytes) -> Path:
    """<d>/<name> (d exists and is not a link); a clash gets ' (2)', ' (3)' ... (created with O_EXCL)."""
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        stem, ext = name, ""
    else:
        ext = "." + ext
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    for n in range(1, 1000):
        dest = d / (name if n == 1 else f"{stem} ({n}){ext}")
        try:
            fd = os.open(dest, flags, 0o644)
        except FileExistsError:
            continue
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        return dest
    raise Refused("Too many files with that name in received/.")


def download(root: Path, mid: str) -> Path:
    msg = load_message(root, mid)
    if msg.get("type") != "file":
        raise Refused(f"{mid} is not a file message.")
    b = msg["body"]
    if not re.fullmatch(r"b_[a-z0-9]{16}", str(b.get("blob_id", ""))):
        raise Refused("The message has no valid blob id.")
    cfg = _cfg(root)
    _, raw = net.call("GET", f"{cfg['url']}/v1/blobs/{b['blob_id']}", net.auth_headers(cfg), timeout=300)
    if len(raw) != b.get("size") or hashlib.sha256(raw).hexdigest() != b.get("sha256"):
        raise Refused("The downloaded file does not match the message (size or sha256). Not saved.")
    return _save_received(root, safe_name(b["name"]), raw)


# ---- refresh ------------------------------------------------------------------------------------


def _safe_rel(rel: str) -> Path:
    if (
        not isinstance(rel, str)
        or not rel
        or rel.startswith(("/", "\\"))
        or "\\" in rel
        or "\x00" in rel
        or re.match(r"^[A-Za-z]:", rel)
    ):
        raise Refused(f"unsafe path {rel!r}")
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts) or any(":" in p for p in parts):
        raise Refused(f"unsafe path {rel!r}")
    return Path(*parts)


def refresh(root: Path) -> str:
    """Apply the full snapshot whole or not at all. Returns a plain-words line."""
    _, snap = _api(root, "GET", "/v1/refresh")
    if not isinstance(snap, dict) or not isinstance(snap.get("version"), int):
        raise Refused("The relay sent an unreadable snapshot. Nothing changed.")
    stage = root / ".orch" / "tmp-refresh"
    if stage.exists():
        shutil.rmtree(stage)
    skipped: list[str] = []
    try:
        names = _stage(stage, snap, skipped)
        _commit(root, stage, snap, names)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    skillrender.refresh_skills(root)
    sync_phone_views(root)
    with locked(root):  # the refresh-hints waiting in the inbox are handled now
        for f in (root / ".orch" / "inbox").glob("m_*.json"):
            m = net.read_json(f, None)
            if isinstance(m, dict) and m.get("id") == f.stem and m.get("type") == "refresh-hint":
                _mark_seen(root, f.stem)
    n = len(snap.get("workspaces", {}).get("workspaces", []))
    p = len(snap.get("workspaces", {}).get("phones", []))
    msg = (
        f"Updated workspaces.json ({n} workspace{'s' if n != 1 else ''}"
        f" and {p} phone{'s' if p != 1 else ''} you can reach)"
    )
    if names:
        msg += f", shared skills: {', '.join(names)}"
    if skipped:
        msg += "\nSkipped: " + "; ".join(skipped)
    return msg


def _stage(stage: Path, snap: dict, skipped: list[str]) -> list[str]:
    names = []
    for sk in snap.get("skills", []):
        name = sk.get("name") if isinstance(sk, dict) else None
        try:
            if (
                not isinstance(name, str)
                or not SKILL_RE.match(name)
                or name in RESERVED
                or name.startswith("orch-")
            ):
                raise Refused(f"bad skill name {name!r}")
            files = sk.get("files")
            if not isinstance(files, dict) or not files:
                raise Refused("no files")
            base = stage / "skills" / name
            for rel, b64 in files.items():
                rp = _safe_rel(rel)
                try:
                    data = base64.b64decode(b64, validate=True)
                except (binascii.Error, TypeError):
                    raise Refused(f"bad data for {rel}") from None
                net.write_atomic(base / rp, data)
            net.write_atomic(base / SHARED_MARK, b"")
            names.append(name)
        except Refused as e:
            if isinstance(name, str):
                shutil.rmtree(stage / "skills" / name, ignore_errors=True)
            skipped.append(f"skill {name}: {e}")
    mcp, cred = snap.get("mcp", {}), snap.get("credentials", {})
    if not isinstance(mcp, dict) or not isinstance(cred, dict):
        raise Refused("The snapshot has bad MCP or credentials. Nothing changed.")
    net.write_json(stage / "mcp.json", {"mcpServers": mcp}, True)
    net.write_json(stage / "credentials.json", cred, True)
    net.write_json(stage / "shared.json", {"version": snap["version"], "skills": names})
    ws = snap.get("workspaces")
    if not isinstance(ws, dict) or not isinstance(ws.get("workspaces"), list):
        raise Refused("The snapshot has no workspace directory. Nothing changed.")
    net.write_json(stage / "workspaces.json", ws)
    return names


def _commit(root: Path, stage: Path, snap: dict, names: list[str]) -> None:
    agents = root / ".agents" / "skills"
    for n in names:  # refuse before changing anything
        dest = agents / n
        skills.check_inside(root, dest)
        if dest.exists() and not (dest / SHARED_MARK).exists():
            raise Refused(f"{dest} exists and is not a shared skill. Nothing changed.")
    skills.check_inside(root, agents / "orch-relay")
    sec = net.secrets_dir(root)
    sec.mkdir(parents=True, exist_ok=True)
    skills.ensure_gitignore(root)
    for fn in ("credentials.json", "mcp.json", "shared.json"):
        harness.check_private_path(root, sec / fn)  # refuse before changing anything
    (agents / "orch-relay").mkdir(parents=True, exist_ok=True)
    os.replace(stage / "workspaces.json", agents / "orch-relay" / "workspaces.json")
    for n in names:
        dest = agents / n
        if dest.exists():
            shutil.rmtree(dest)
        os.replace(stage / "skills" / n, dest)
    if agents.is_dir():  # shared skills that are no longer assigned
        for d in sorted(agents.iterdir()):
            if d.is_dir() and not skills._is_link(d) and (d / SHARED_MARK).exists() and d.name not in names:
                shutil.rmtree(d)
                skills.unlink_skill(root, d.name)
    net.replace_private(stage / "credentials.json", sec / "credentials.json")
    net.replace_private(stage / "mcp.json", sec / "mcp.json")
    skills.apply_agent_files(root)
    net.replace_private(stage / "shared.json", sec / "shared.json")


# ---- webhooks -----------------------------------------------------------------------------------


def webhook_new(root: Path, mode: str, ticket: str | None) -> dict:
    body: dict = {"mode": mode}
    if ticket:
        body["ticket"] = ticket
    return _api(root, "POST", "/v1/webhooks", body)[1]


def webhook_list(root: Path) -> list[dict]:
    return net.items(_api(root, "GET", "/v1/webhooks")[1])


def webhook_delete(root: Path, wid: str) -> None:
    _api(root, "DELETE", f"/v1/webhooks/{urllib.parse.quote(wid, safe='')}")
