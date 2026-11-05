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
import urllib.parse
from pathlib import Path

from orch import net, skills, tickets
from orch.errors import Refused

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


def give_allow(root: Path, mid: str, mode: str) -> dict:
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
    body = {"mode": mode, "kind": kind, "token": token}
    if key:
        body["key"] = key
    out = _message(root, msg["from"], "allow", body, reply_to=mid)
    a = allows(root)
    a["given"].append(entry)
    _save_allows(root, a)
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
    """The relay could not be reached or failed on its side (net.py words), so the message may be retried."""
    t = str(e)
    return t.startswith("Can't reach") or t.startswith("The server answered 5")


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
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(p, flags, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(raw)
    return p


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
    if reply_to:
        msg["reply_to"] = reply_to
    raw = json.dumps(msg).encode("utf-8")
    path = _write_outbox(root, msg["id"], raw)
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


def send_text(root: Path, target: str, text: str, ticket: str | None = None) -> dict:
    return _message(root, resolve(root, target), "text", {"text": text}, ticket)


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


def send_question(root: Path, ticket: dict, q: dict) -> dict:
    body = {
        "question_id": q["id"],
        "title": ticket["title"],
        "text": q["text"],
        "options": q["options"],
        "recommended": q["recommended"],
    }
    msg = _message(root, "phones", "question", body, ticket["id"])
    asked = net.read_json(_asked_path(root), {})
    asked[msg["id"]] = {"ticket": ticket["id"], "question_id": q["id"], "to": "phones"}
    net.write_json(_asked_path(root), asked, True)
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
    if not (frm.startswith("ph_") if asked["to"] == "phones" else frm == asked["to"]):
        return None, f"ignored: {frm} was not asked"
    if b.get("question_id") != asked["question_id"]:
        return None, "ignored: answer is for another question"
    return asked, ""


def _answer_by(msg: dict) -> tuple[str, str]:
    frm, b = str(msg.get("from", "")), msg.get("body", {})
    by = b.get("answered_by")
    ok_prefix = "human:" if frm.startswith("ph_") else ("human:", "agent:")
    if not (isinstance(by, str) and by.startswith(ok_prefix)):
        by = f"human:{frm}" if frm.startswith("ph_") else f"agent:{frm}"
    return by, ("phone" if frm.startswith("ph_") else "relay")


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
        tickets.answer(
            root, asked["ticket"], asked["question_id"], str(msg.get("body", {}).get("answer")), by, via
        )
    except Refused as e:
        if _applied_ticket(root, msg):  # a crash after the write, before "seen": same answer, nothing to redo
            return f"answered {asked['question_id']} on {asked['ticket']} (via {via})", asked["ticket"]
        return f"not applied to {asked['ticket']}: {e}", None
    return f"answered {asked['question_id']} on {asked['ticket']} (via {via})", asked["ticket"]


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


def inbox(root: Path, wait: int = 0) -> list[dict]:
    """Pull, save, journal, ack, then handle the ones not seen. Returns [{message, note, allowed}]."""
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
            if m.get("type") in ("answer", "allow"):
                with locked(root):
                    if m["id"] not in seen(root):  # another reader may have handled it meanwhile
                        if m["type"] == "answer":
                            note, applied = _apply_answer(root, m)
                        else:
                            note = _store_allow(root, m)
                        auto = True
                        _mark_seen(root, m["id"])  # last
                if not auto:
                    continue
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
    if not [e for e in _read_arrivals(root) if e["seq"] > seq]:
        _pull(root, wait)
    else:
        _pull(root, 0)
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
    return {"next": have[-1]["seq"] if have else seq, "items": items}


def _ticket_by_message(root: Path, mid: str) -> str | None:
    for t in tickets.list_all(root):
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
    if msg["type"] == "start":
        for t in tickets.list_all(root):
            r = t.get("ext", {}).get("relay", {})
            if (
                r.get("start_key") == b["key"]
                and r.get("from") == msg["from"]
                and t.get("status") in ("open", "active", "waiting")
            ):  # remember this message too, so a second `done` finds the same ticket
                more = [*r.get("messages", []), msg["id"]]
                tickets.ext_set(root, t["id"], "relay", json.dumps({"messages": more[-20:]}), by)
                return t["id"]
        title = f"Relay task {b['key']}"
    else:
        title = b["title"]
    t = tickets.create(root, title, by)
    ext = {"from": msg["from"], "message": msg["id"]}
    if msg["type"] == "start":
        ext["start_key"] = b["key"]
    tickets.ext_set(root, t["id"], "relay", json.dumps(ext), by)
    for item in b.get("checklist", []) if msg["type"] == "delegate" else []:
        tickets.check_add(root, t["id"], str(item), by)
    return t["id"]


def safe_name(name: str) -> str:
    base = re.split(r"[\\/]", str(name))[-1].strip().strip(".")
    base = re.sub(r'[<>:"|?*\x00-\x1f]', "_", base)
    if not base:
        raise Refused("The file has no usable name.")
    return base[:200]


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
    dest = root / ".orch" / "inbox" / "files" / b["blob_id"] / safe_name(b["name"])
    net.write_atomic(dest, raw)
    return dest


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
    os.replace(stage / "credentials.json", sec / "credentials.json")
    os.replace(stage / "mcp.json", sec / "mcp.json")
    skills.link_claude_skills(root)
    os.replace(stage / "shared.json", sec / "shared.json")


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
