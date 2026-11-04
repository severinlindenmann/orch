"""orch relay client: inbox, send, allow, refresh, webhooks (contracts/relay-api.md, local-files.md)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import urllib.parse
from pathlib import Path

from orch import net, skills, tickets
from orch.errors import Refused

ALNUM = "abcdefghijklmnopqrstuvwxyz0123456789"
MAX_BLOB = 100 * 1024 * 1024
SKILL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
SHARED_MARK = ".orch-shared"
RESERVED = {"orch", "orch-publish", "orch-relay", "orch-dashboard", "orch-scheduler"}


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


# ---- local state --------------------------------------------------------------------------------


def _seen_path(root: Path) -> Path:
    return root / ".orch" / "inbox-seen.json"


def seen(root: Path) -> dict:
    return net.read_json(_seen_path(root), {})


def mark_seen(root: Path, mid: str) -> bool:
    """Returns True when the id was new. Written before anyone acts on the message."""
    s = seen(root)
    if mid in s:
        return False
    s[mid] = tickets.now()
    net.write_json(_seen_path(root), s)
    return True


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
        if g.get("mode") == "once" and g.get("message_id") == msg["id"] and not g.get("used"):
            return "once"
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
        if g.get("mode") == "once" and g.get("message_id") == msg["id"]:
            g["used"] = True
    _save_allows(root, a)


def _received_token(root: Path, peer: str, kind: str, key: str | None) -> str | None:
    for r in allows(root)["received"]:
        if r.get("peer") == peer and r.get("kind") == kind and (kind != "start" or r.get("key") == key):
            return r["token"]
    return None


# ---- sending ------------------------------------------------------------------------------------


def resolve(root: Path, target: str) -> str:
    """ws_ id, 'phones', or a name/tag from workspaces.json."""
    if re.fullmatch(r"ws_[a-z0-9]{10}|phones|ph_[a-z0-9]{10}", target):
        return target
    wf = root / ".agents" / "skills" / "orch-relay" / "workspaces.json"
    for w in net.read_json(wf, {}).get("workspaces", []):
        if target.lower() in (w["name"].lower(), w["id"]):
            return w["id"]
    raise Refused(f"No workspace called {target!r}. See .agents/skills/orch-relay/workspaces.json")


def _message(
    root: Path, to: str, type_: str, body: dict, ticket: str | None = None, reply_to: str | None = None
) -> dict:
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
    _api(root, "POST", "/v1/messages", msg)
    return msg


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


def _apply_answer(root: Path, msg: dict) -> str:
    """Only for a question this workspace sent; ticket and question come from our own record."""
    asked = net.read_json(_asked_path(root), {}).get(str(msg.get("reply_to")))
    frm, b = str(msg.get("from", "")), msg.get("body", {})
    if not asked:
        return "ignored: not an answer to a question this workspace sent"
    if not (frm.startswith("ph_") if asked["to"] == "phones" else frm == asked["to"]):
        return f"ignored: {frm} was not asked"
    if b.get("question_id") != asked["question_id"]:
        return "ignored: answer is for another question"
    by = b.get("answered_by")
    ok_prefix = "human:" if frm.startswith("ph_") else ("human:", "agent:")
    if not (isinstance(by, str) and by.startswith(ok_prefix)):
        by = f"human:{frm}" if frm.startswith("ph_") else f"agent:{frm}"
    via = "phone" if frm.startswith("ph_") else "relay"
    try:
        tickets.answer(root, asked["ticket"], asked["question_id"], str(b.get("answer")), by, via)
    except Refused as e:
        return f"not applied to {asked['ticket']}: {e}"
    return f"answered {asked['question_id']} on {asked['ticket']} (via {via})"


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


def inbox(root: Path, wait: int = 0) -> list[dict]:
    """Pull, save every message, ack, then handle the ones not seen. Returns [{message, note, allowed}]."""
    wait = max(0, min(30, wait))
    _, resp = _api(root, "GET", f"/v1/inbox?wait={wait}", timeout=wait + 30)
    msgs = net.items(resp)
    d = root / ".orch" / "inbox"
    ok = []
    arrival = {str(m.get("id")): n for n, m in enumerate(msgs) if isinstance(m, dict)}
    for m in msgs:
        if not isinstance(m, dict) or not re.fullmatch(r"m_[a-z0-9]{16}", str(m.get("id", ""))):
            continue
        net.write_json(d / f"{m['id']}.json", m)
        ok.append(m)
    if ok:
        _api(root, "POST", "/v1/inbox/ack", {"ids": [m["id"] for m in ok]})
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
        note, auto = "", False
        try:
            if m.get("type") == "answer":
                mark_seen(root, m["id"])
                note, auto = _apply_answer(root, m), True
            elif m.get("type") == "allow":
                mark_seen(root, m["id"])
                note, auto = _store_allow(root, m), True
        except (KeyError, TypeError) as e:
            note = f"could not read this message: {e}"
        out.append({"message": m, "note": note, "auto": auto, "allowed": allowed(root, m)})
    return out


def done(root: Path, mid: str) -> dict:
    """Mark seen first. An allowed delegate/start then gets its ticket (inbox rule 4)."""
    msg = load_message(root, mid)
    first = mark_seen(root, mid)
    res: dict = {"id": mid, "new": first, "ticket": None}
    mode = allowed(root, msg) if first else None
    if mode:
        res["ticket"] = _ticket_for(root, msg)
        if mode == "once":
            _use_once(root, msg)
    return res


def _ticket_for(root: Path, msg: dict) -> str:
    b, by = msg["body"], f"agent:relay from {msg['from']}"
    if msg["type"] == "start":
        for t in tickets.list_all(root):
            if t.get("ext", {}).get("relay", {}).get("start_key") == b["key"]:
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
    msg = f"Updated workspaces.json ({n} workspace{'s' if n != 1 else ''} you can reach)"
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
            if not isinstance(name, str) or not SKILL_RE.match(name) or name in RESERVED:
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
