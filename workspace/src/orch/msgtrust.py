"""Signed messages on the workspace side: sign what we send, check what we get (ORCH-1202, design ORCH-1198).

The receiver is the decisive gate. It never trusts the relay's own check:

- `seal_outgoing` adds the `envelope` (relay-api.md "Signed messages (v1)") to every message this workspace
  sends, when it has a signing key. `origin` is set here by orch itself: `person` only inside `as_person()`
  (a person's own action) or from the CLI at a terminal outside a helper; everything else is `helper`.
- `gate` runs on every message the relay hands over, before it is saved to .orch/inbox, so nothing downstream
  (inbox handling, Chat import, phone views) ever sees a refused or held message. It verifies the exact signed
  bytes with a key a person accepted, checks that the outer fields equal the signed ones, the `to`, freshness
  and
  the replay list, and for a group copy the author's own signature.
- First contact is held: a valid signature from a key nobody accepted yet is kept inert in the guarded home
  until a person presses Accept (`accept`). A wrong, missing or changed signature is never held: refused,
  counted and shown as Not valid.
- Everything lives in the guarded orch home (keys/<workspace>/trust.json and held/), outside the workspace
  folder, so no helper, sync or relay can change who is accepted. Seen ids are kept 30 days.

`signed_only` is this computer's own switch (off until the cut-over, ORCH-1205). Off: an unsigned message
still goes through as today; a signed one is checked all the same. On: an unsigned one is refused too. No
relay flag or message can change it; only a person (`set_refuse_unsigned`).
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from orch import msgsig
from orch.errors import Refused
from orch.text import clean_untrusted

SCHEMA = "orch.trust/1"
# seen ids cover the whole time a message is taken: 30 days of age plus the 5 minutes it may be ahead
SEEN_KEEP_MS = msgsig.MAX_AGE_MS + 2 * msgsig.FUTURE_SKEW_MS
HELD_PER_CONTACT = 50
HELD_TOTAL = 500
REFUSED_KEEP = 100
# Made by the relay itself, never signed: a closed list (relay-api.md). None of them is an allow, a person's
# answer, a start or a trust change (test_msgtrust.py checks each).
RELAY_MADE_TYPES = ("refresh-hint", "webhook", "control")
PERSON_ACTIONS = ("allow", "answer")  # a held one is never run by itself on Accept
# a refusal that means "forged or changed on the way": counted and shown as Not valid on the contact
NOT_VALID_CODES = {
    "bad_signature",
    "bad_envelope",
    "bad_json",
    "bad_field",
    "wrong_sender",
    "signed_mismatch",
    "missing_signature",
    "author_mismatch",
}
_WS = re.compile(r"ws_[a-z0-9]{10}")
_PEER = re.compile(r"(ws|ph)_[a-z0-9]{10}")
_HIDDEN = re.compile(r"[\u0000-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]")

_ORIGIN: contextvars.ContextVar[str | None] = contextvars.ContextVar("orch_msg_origin", default=None)


# ---------------------------------------------------------------- origin: person or helper


@contextlib.contextmanager
def as_person(on: bool = True):
    """Inside: what this process signs is a person's own action (dashboard click on this computer, CLI at a
    terminal, an answer proven to come from a person). Helpers have no way to enter it."""
    tok = _ORIGIN.set("person" if on else "helper")
    try:
        yield
    finally:
        _ORIGIN.reset(tok)


def current_origin() -> str:
    o = _ORIGIN.get()
    if o:
        return o
    from orch import tickets

    if tickets.agent_tool() is None and _is_tty():
        return "person"
    return "helper"


def _is_tty() -> bool:
    from orch import term

    return term.is_terminal(sys.stdin)


# ---------------------------------------------------------------- the trust store (guarded orch home)


def _dir(root: Path, create: bool = True) -> Path:
    from orch import home as orch_home

    return orch_home.key_dir(root, create=create)


def _path(root: Path) -> Path:
    return _dir(root) / "trust.json"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _empty(root: Path | None = None) -> dict:
    # floor: when this list is new on a workspace that already handled messages (a reinstall, a restore, a
    # lost guarded home), anything that acts and was made before now is refused, so an old allow or start
    # cannot be played again. A brand-new workspace has nothing to replay.
    used = root is not None and (root / ".orch" / "inbox-seen.json").exists()
    return {
        "schema": SCHEMA,
        "floor_ms": _now_ms() if used else 0,
        "signed_only": False,
        "contacts": {},
        "seen": {},
        "refused": [],
    }


def _load(root: Path) -> dict:
    from orch import home as orch_home

    p = _path(root)
    try:
        raw = orch_home._read_guarded(p)
    except FileNotFoundError:
        return _empty(root)
    except orch_home.LooseFile:
        raise Refused("The list of accepted workspaces has the wrong rights. Fix: orch doctor") from None
    try:
        st = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Refused("The list of accepted workspaces is damaged. Fix: orch doctor") from None
    if not isinstance(st, dict) or st.get("schema") != SCHEMA:
        raise Refused("The list of accepted workspaces is damaged. Fix: orch doctor")
    for k, v in _empty().items():
        st.setdefault(k, v)
    return st


def _save(root: Path, st: dict) -> None:
    from orch import home as orch_home

    orch_home._write_private(_path(root), json.dumps(st, sort_keys=True, separators=(",", ":")) + "\n")


@contextlib.contextmanager
def _state(root: Path):
    """Read-modify-write of trust.json under the key folder's lock."""
    from orch import home as orch_home

    with orch_home._key_lock(_dir(root)):
        st = _load(root)
        yield st
        _save(root, st)


def _contact(st: dict, peer: str) -> dict:
    return st["contacts"].setdefault(peer, {"keys": [], "not_valid": 0})


def refuse_unsigned(root: Path) -> bool:
    try:
        return bool(_load(root).get("signed_only"))
    except Refused:
        return True  # a damaged list never opens the door


def set_refuse_unsigned(root: Path, on: bool, by: str) -> dict:
    """This computer's own switch. Only a person changes it (the CLI checks that)."""
    with _state(root) as st:
        st["signed_only"] = bool(on)
        st["signed_only_by"] = {"by": by, "at": _iso(_now_ms())}
    return {"refuse_unsigned": bool(on)}


# ---------------------------------------------------------------- keys: accepted and hinted


def _hint_key(root: Path, peer: str) -> bytes | None:
    """The key the relay lists for `peer` (workspaces.json signing_key). A HINT: only to tell a valid first
    contact (held) from a forgery (refused), and as the key a person accepts after seeing its fingerprint."""
    from orch import relay

    for w in relay._directory(root):
        if w.get("id") != peer:
            continue
        sk = w.get("signing_key")
        if not isinstance(sk, dict) or sk.get("alg") != "ed25519":
            return None
        try:
            raw = msgsig.b64url_decode_strict(sk.get("public_key"))
        except ValueError:
            return None
        return raw if msgsig.public_key_ok(raw) else None
    return None


def _accepted(st: dict, peer: str) -> list[bytes]:
    c = st["contacts"].get(peer) or {}
    if c.get("withdrawn"):
        return []
    out = []
    for k in c.get("keys", []):
        with contextlib.suppress(ValueError, TypeError):
            raw = bytes.fromhex(k["pub"])
            if msgsig.public_key_ok(raw):
                out.append(raw)
    return out


def own_id(root: Path) -> str:
    from orch import relay

    return relay._cfg(root)["workspace"]


# ---------------------------------------------------------------- sending


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ms_of(created_at: str | None) -> int:
    if created_at:
        with contextlib.suppress(ValueError):
            t = created_at[:-1] + "+00:00" if created_at.endswith("Z") else created_at
            return int(datetime.fromisoformat(t).timestamp() * 1000)
    return _now_ms()


def _question_hash(root: Path, reply_to: str | None) -> tuple[str, str] | None:
    """(question id, sha256 of its signed bytes) of a question we received signed, for an answer."""
    if not reply_to or not re.fullmatch(r"m_[a-z0-9]{16}", reply_to):
        return None
    from orch import net

    q = net.read_json(root / ".orch" / "inbox" / f"{reply_to}.json", None)
    if not isinstance(q, dict) or not isinstance(q.get("envelope"), dict):
        return None
    try:
        signed = msgsig.read_envelope(q["envelope"]).signed
    except msgsig.SigError:
        return None
    qid = (q.get("body") or {}).get("question_id") or (q.get("body") or {}).get("qid")
    if not isinstance(qid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", qid):
        return None
    return qid, hashlib.sha256(signed).hexdigest()


def signed_object(root: Path, msg: dict, origin: str | None = None) -> dict | None:
    """The `msg` object to sign for an outgoing message, or None when this message cannot be signed (then it
    goes out unsigned and a receiver with signed_only refuses it)."""
    o = {
        "v": 1,
        "id": msg["id"],
        "from": msg["from"],
        "to": msg["to"],
        "type": msg["type"],
        "created_ms": _ms_of(msg.get("created_at")),
        "origin": origin or current_origin(),
        "body": msg["body"],
    }
    for k in ("ticket", "reply_to"):
        if msg.get(k):
            o[k] = msg[k]
    b = msg["body"] if isinstance(msg.get("body"), dict) else {}
    if msg["type"] == "file" and {"blob_id", "size", "sha256"} <= set(b):
        o["files"] = [{"blob_id": b["blob_id"], "size": b["size"], "sha256": b["sha256"]}]
    if msg["type"] in msgsig.EXPIRING_TYPES:
        o["expires_ms"] = o["created_ms"] + msgsig.MAX_EXPIRY_MS
    if msg["type"] == "answer":
        qh = _question_hash(root, msg.get("reply_to"))
        if qh is None:
            return None
        o["question_id"], o["question_sha256"] = qh
    return o


def _encode(o: dict) -> bytes | None:
    """The exact bytes, or None when they would not pass the receiver's strict reading (a float, a lone
    surrogate, a too-big body)."""
    try:
        b = json.dumps(o, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        msgsig.check_fields(msgsig.read_strict_json(b))
    except (ValueError, UnicodeEncodeError, msgsig.SigError):
        return None
    return b if len(b) <= msgsig.MAX_SIGNED_BYTES else None


def seal_outgoing(root: Path, msg: dict, origin: str | None = None) -> dict:
    """`msg` with its `envelope`, or unchanged when this workspace has no signing key yet or the message
    cannot be signed. The private key is only touched inside signkey.sign_bytes."""
    from orch import signkey

    try:
        pub = signkey.public_key(root)
    except Refused:
        return msg
    if pub is None:
        return msg
    o = signed_object(root, msg, origin)
    data = _encode(o) if o is not None else None
    if data is None:
        return msg
    sig = signkey.sign_bytes(root, msgsig.signature_input("msg", data))
    env = {"sig_v": 1, "key_id": msgsig.key_id(pub), "signed": msgsig.b64url(data), "sig": msgsig.b64url(sig)}
    return {**msg, "envelope": env}


# ---------------------------------------------------------------- receiving: the gate


class Verdict:
    """kind: ok (signed and checked) | plain (unsigned, let through: relay-made, or signed_only is off) |
    duplicate (the same signed message again: ignore) | held (valid first contact, kept until Accept) |
    refused (never handled)."""

    def __init__(self, kind: str, code: str = "", message: dict | None = None, peer: str | None = None):
        self.kind, self.code, self.message, self.peer = kind, code, message, peer

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Verdict({self.kind!r}, {self.code!r})"


def _outer_matches(m: dict, s: dict) -> bool:
    """relay-api.md: outer id, from, type, ticket, reply_to, body and a string `to` equal the signed ones."""
    for k in ("id", "from", "type", "ticket", "reply_to", "body"):
        if m.get(k) != s.get(k):
            return False
    return not isinstance(s["to"], str) or m.get("to") == s["to"]


def _check(root: Path, st: dict, m: dict, env, keys: dict[str, list[bytes]], now_ms: int, me: str) -> dict:
    """msgsig.receiver_check with our own replay rule (done by the caller) + the outer-field rule."""
    s = msgsig.receiver_check(env, me=me, accepted=keys, now_ms=now_ms)
    if not _outer_matches(m, s):
        raise msgsig.SigError("signed_mismatch")
    if s["type"] == "allow" and s["origin"] != "person":
        raise msgsig.SigError("not_person")  # an allow is a person's action, never a helper's
    if s["type"] in msgsig.EXPIRING_TYPES and s["created_ms"] < st.get("floor_ms", 0):
        raise msgsig.SigError("before_floor")
    return s


def _try_hint(root: Path, st: dict, m: dict, env, peer: str, now_ms: int, me: str) -> str | None:
    """A key not accepted: does it verify with the key the relay lists for `peer`? Returns the held reason, or
    None (then it is refused)."""
    hint = _hint_key(root, peer)
    if hint is None:
        return None
    try:
        _check(root, st, m, env, {peer: [hint]}, now_ms, me)
    except msgsig.SigError:
        return None
    c = st["contacts"].get(peer) or {}
    if c.get("withdrawn"):
        return "withdrawn"
    return "new_key" if c.get("keys") else "not_accepted"


def _refuse(st: dict, m: dict, code: str, peer: str | None = None) -> Verdict:
    frm = str(m.get("from", ""))
    who = peer or frm
    rec = {
        "at": _iso(_now_ms()),
        "from": clean_untrusted(frm, 40),
        "id": clean_untrusted(str(m.get("id")), 40),
    }
    rec["code"] = code
    if peer and peer != frm:
        rec["author"] = peer
    st["refused"] = [*st.get("refused", []), rec][-REFUSED_KEEP:]
    if code in NOT_VALID_CODES and _PEER.fullmatch(who):
        c = _contact(st, who)
        c["not_valid"] = int(c.get("not_valid", 0)) + 1
        c["last_bad"] = {"at": rec["at"], "code": code}
    return Verdict("refused", code, m, who)


def _group_author(root: Path, st: dict, m: dict, now_ms: int) -> Verdict | None:
    """A group copy the host passed on from a member: the member's own envelope rides in body.author and must
    verify with a key we accepted for that member, name the host as `to`, carry the same group, text and id,
    and
    the member must be in the member list the host signed. None = fine (or not a member's copy)."""
    from orch import chat_groups, phone_view

    b = m.get("body") or {}
    g = b.get("group") if isinstance(b.get("group"), dict) else None
    if g is None:
        return None
    o = b.get("origin") if isinstance(b.get("origin"), dict) else None
    host, by = m.get("from"), b.get("by")
    # a copy that names a member as its author is that member's words: `by` and `origin.from` must agree, and
    # a copy cannot drop `origin` to dodge the author check
    if isinstance(by, str) and _WS.fullmatch(by) and by != host and (o is None or o.get("from") != by):
        return _refuse(st, m, "author_mismatch", by)
    if o is None:
        return None
    author = o.get("from")
    if isinstance(author, str) and _WS.fullmatch(author) and author != host and by != author:
        return _refuse(st, m, "author_mismatch", author)
    if not isinstance(author, str) or not _WS.fullmatch(author) or author == host:
        return None  # the host's own words (its signature is the outer one) or a phone's (relay-made today)
    env = b.get("author")
    if env is None:
        return _refuse(st, m, "missing_signature", author)
    keys = _accepted(st, author)
    try:
        if not keys:
            raise msgsig.SigError("unknown_key")
        s = msgsig.verify(env, "msg", [(author, k) for k in keys])[1]
    except msgsig.SigError as e:
        if e.code == "unknown_key":
            hint = _hint_key(root, author)
            try:
                if hint is None:
                    raise
                s = msgsig.verify(env, "msg", [(author, hint)])[1]
            except msgsig.SigError:
                return _refuse(st, m, "unknown_key", author)
            if not _author_bound(s, m, host, author, g, o, chat_groups, phone_view):
                return _refuse(st, m, "author_mismatch", author)
            stale = _author_stale(s, now_ms)
            if stale:
                return _refuse(st, m, stale, author)
            return Verdict("held", "author_not_accepted", m, author)
        return _refuse(st, m, e.code, author)
    if not _author_bound(s, m, host, author, g, o, chat_groups, phone_view):
        return _refuse(st, m, "author_mismatch", author)
    stale = _author_stale(s, now_ms)
    if stale:
        return _refuse(st, m, stale, author)
    # one member message is one group copy for us: the host cannot hand the same words over again under a
    # new copy id
    akey = f"author:{author}/{s['id']}"
    if st["seen"].get(akey, [0, m.get("id")])[1] != m.get("id"):
        return _refuse(st, m, "replayed", author)
    st["seen"][akey] = [s["created_ms"], m.get("id"), now_ms]
    return None


def _author_stale(s: dict, now_ms: int) -> str | None:
    if s["created_ms"] > now_ms + msgsig.FUTURE_SKEW_MS:
        return "future"
    if "expires_ms" in s and now_ms >= s["expires_ms"]:
        return "expired"
    if s["created_ms"] < now_ms - msgsig.MAX_AGE_MS:
        return "too_old"
    return None


def _author_fields_match(s: dict, b: dict, chat_groups) -> bool:
    """The member's own fields the host passes on (`via`, `task`, `update`) come from its signed body."""
    from orch import tickets

    sb = s.get("body") or {}
    if b.get("via") == tickets.PERSON_VIA and (
        sb.get("via") != tickets.PERSON_VIA or s["origin"] != "person"
    ):
        return False  # "written by the person" only when the member signed it as its person's own words
    t, st_ = b.get("task"), sb.get("task")
    if t is not None:
        if not isinstance(t, dict) or not isinstance(st_, dict):
            return False
        if any(t.get(k) != st_.get(k) for k in ("delegate", "status")):
            return False
    u, su = b.get("update"), sb.get("update")
    if u is not None:
        if not isinstance(u, dict) or not isinstance(su, dict) or u.get("kind") != su.get("kind"):
            return False
        if "title" in u and u["title"] != chat_groups._line(su.get("title") or "", chat_groups.TITLE_MAX):
            return False
    return True


def _author_bound(s, m, host, author, g, o, chat_groups, phone_view) -> bool:
    sb = s.get("body") or {}
    sg = sb.get("group") if isinstance(sb.get("group"), dict) else {}
    members = {x.get("ws") for x in g.get("members", []) if isinstance(x, dict)}
    shown = phone_view.redact(clean_untrusted(str(sb.get("text", "")), chat_groups.TEXT_MAX))[
        : chat_groups.TEXT_MAX
    ]
    return (
        s["from"] == author
        and s["type"] == m.get("type")
        and s["to"] == host
        and s["id"] == o.get("id")
        and sg.get("id") == g.get("id")
        and author in members
        and (shown or "-") == (m.get("body") or {}).get("text")
        and _author_fields_match(s, m.get("body") or {}, chat_groups)
    )


def check_incoming(root: Path, m: dict, now_ms: int | None = None) -> Verdict:
    """The receiver's whole decision for one message from the relay (see the module text)."""
    now_ms = _now_ms() if now_ms is None else now_ms
    typ, frm = m.get("type"), str(m.get("from", ""))
    env = m.get("envelope")
    me = own_id(root) if env is not None else ""
    with _state(root) as st:
        # nothing unverified may look verified downstream: no `signed` and no group author on a plain message
        plain = {k: v for k, v in m.items() if k != "signed"}
        if isinstance(plain.get("body"), dict) and "author" in plain["body"]:
            plain["body"] = {k: v for k, v in plain["body"].items() if k != "author"}
        if typ in RELAY_MADE_TYPES and env is None:
            return Verdict("plain", "relay_made", plain)
        if env is None:
            if st.get("signed_only"):
                return _refuse(st, m, "missing_signature")
            return Verdict("plain", "unsigned", plain)
        if not _PEER.fullmatch(frm):
            return _refuse(st, m, "wrong_sender")
        try:
            s = _check(root, st, m, env, {frm: _accepted(st, frm)}, now_ms, me)
        except msgsig.SigError as e:
            if e.code == "unknown_key":
                why = _try_hint(root, st, m, env, frm, now_ms, me)
                if why is not None:
                    return Verdict("held", why, m, frm)
            return _refuse(st, m, e.code)
        signed = msgsig.read_envelope(env).signed
        digest = hashlib.sha256(signed).hexdigest()
        out = dict(m)
        out["created_at"] = _iso(s["created_ms"])
        out["signed"] = {"origin": s["origin"], "created_ms": s["created_ms"], "key_id": env.get("key_id")}
        if "expires_ms" in s:
            out["signed"]["expires_ms"] = s["expires_ms"]
        key = f"{frm}/{s['id']}"
        old = st["seen"].get(key)
        if old is not None:
            if old[1] == digest:
                # the relay sent it again (a lost ack); "dropped": a held person action that is never run
                return Verdict("duplicate", "dropped" if old[3:] == ["dropped"] else "seen", out, frm)
            return _refuse(st, m, "replayed")
        ga = _group_author(root, st, m, now_ms)
        if ga is not None:
            return ga
        st["seen"][key] = [s["created_ms"], digest, now_ms]  # marked before anything acts
        cut = now_ms - SEEN_KEEP_MS
        st["seen"] = {k: v for k, v in st["seen"].items() if max(v[0], v[2]) >= cut}
        return Verdict("ok", "", out, frm)


# ---------------------------------------------------------------- held messages


def _held_dir(root: Path) -> Path:
    from orch import home as orch_home

    d = _dir(root) / "held"
    if not d.exists():
        d.mkdir(mode=0o700)
    if d.is_symlink():
        raise Refused("The held messages folder is a link. Not using it.")
    orch_home._check_dir(d)
    return d


def hold(root: Path, v: Verdict) -> None:
    """Keep a held message inert in the guarded home (bounded per contact and in total, oldest dropped)."""
    from orch import home as orch_home

    m = v.message or {}
    mid = str(m.get("id", ""))
    if not re.fullmatch(r"m_[a-z0-9]{16}", mid):
        return
    d = _held_dir(root)
    f = d / f"{mid}.json"
    if f.exists():
        with contextlib.suppress(OSError, ValueError, Refused):
            old = json.loads(orch_home._read_guarded(f).decode("utf-8"))
            if (old.get("message") or {}).get("from") != m.get("from"):
                return  # an id another sender's held message already has: never overwritten
    rec = {"peer": v.peer, "why": v.code, "at": _now_ms(), "message": m}
    orch_home._write_private(f, json.dumps(rec) + "\n")
    items = held(root)
    mine = [x for x in items if x["peer"] == v.peer]
    for x in mine[: max(0, len(mine) - HELD_PER_CONTACT)] + items[: max(0, len(items) - HELD_TOTAL)]:
        with contextlib.suppress(OSError):
            (d / f"{x['id']}.json").unlink()


def held(root: Path, peer: str | None = None) -> list[dict]:
    """Held messages, oldest first: [{id, peer, why, at, type}] (the content stays inert, not shown here)."""
    from orch import home as orch_home

    out = []
    try:
        d = _held_dir(root)
    except Refused:
        return out
    for f in d.glob("m_*.json"):
        try:
            rec = json.loads(orch_home._read_guarded(f).decode("utf-8"))
        except (OSError, ValueError, Refused):
            continue
        if peer and rec.get("peer") != peer:
            continue
        msg = rec.get("message") or {}
        out.append(
            {
                "id": f.stem,
                "peer": rec.get("peer"),
                "why": rec.get("why"),
                "at": rec.get("at", 0),
                "type": msg.get("type"),
            }
        )
    return sorted(out, key=lambda x: (x["at"], x["id"]))


def release(root: Path, peer: str) -> list[dict]:
    """After Accept: every held message of `peer` is checked again from the start (signature, to, freshness,
    replay). The ones that pass are saved to .orch/inbox for the normal handling; a held person action (an
    allow or an answer) is dropped, never run by itself: the sender sends it again. Returns notes."""
    from orch import home as orch_home
    from orch import net

    notes = []
    d = _held_dir(root)
    for x in held(root):
        f = d / f"{x['id']}.json"
        try:
            rec = json.loads(orch_home._read_guarded(f).decode("utf-8"))
        except (OSError, ValueError, Refused):
            continue
        m = rec.get("message") or {}
        author = ((m.get("body") or {}).get("origin") or {}).get("from")
        if rec.get("peer") != peer and author != peer:
            continue
        if m.get("type") in PERSON_ACTIONS:
            _tombstone(root, m)  # the same signed bytes sent again later are a duplicate, never run
            f.unlink(missing_ok=True)
            notes.append(
                {"id": x["id"], "result": "dropped", "why": "a held person action is never run by itself"}
            )
            continue
        v = check_incoming(root, m)
        if v.kind == "ok":
            dest = root / ".orch" / "inbox" / f"{x['id']}.json"
            if not inbox_slot_free(dest, m):
                notes.append({"id": x["id"], "result": "refused", "why": "id_taken"})
            else:
                net.write_json(dest, v.message)
                notes.append({"id": x["id"], "result": "released"})
            f.unlink(missing_ok=True)
        elif v.kind == "held":
            f.unlink(missing_ok=True)
            hold(root, v)  # another key still missing (a group copy whose author nobody accepted)
            notes.append({"id": x["id"], "result": "still held", "why": v.code})
        else:
            f.unlink(missing_ok=True)
            notes.append({"id": x["id"], "result": v.kind, "why": v.code})
    return notes


def _tombstone(root: Path, m: dict) -> None:
    """Mark a dropped held message seen (by its signed bytes), so a resend of it is only a duplicate."""
    env = m.get("envelope")
    try:
        signed = msgsig.read_envelope(env).signed
    except msgsig.SigError:
        return
    now = _now_ms()
    with _state(root) as st:
        st["seen"].setdefault(
            f"{m.get('from')}/{m.get('id')}", [now, hashlib.sha256(signed).hexdigest(), now, "dropped"]
        )


def inbox_slot_free(dest: Path, m: dict) -> bool:
    """A saved message with this id from another sender is never replaced (ids are not per sender on disk)."""
    from orch import net

    old = net.read_json(dest, None) if dest.exists() else None
    return not isinstance(old, dict) or old.get("from") == m.get("from")


# ---------------------------------------------------------------- Accept, withdraw, the list


def _own_name(name: str | None) -> str | None:
    """The person's own name for a contact (ORCH-1203): one plain line, at most 60 characters; empty = the
    relay's name."""
    if name is None:
        return None
    if _HIDDEN.search(str(name)):
        raise Refused("Use plain text for the name, on one line.")
    n = " ".join(str(name).split())
    if len(n) > 60:
        raise Refused("A name has at most 60 characters.")
    return n


def accept(
    root: Path, peer: str, by: str, via: str, fingerprint: str | None = None, name: str | None = None
) -> dict:
    """A person accepts `peer`'s key: the one the relay lists now, after they saw its fingerprint. With
    `fingerprint` it must be that one (so a key swapped meanwhile is never the one accepted). `name` is the
    person's own name for the contact (empty keeps the relay's name)."""
    own = _own_name(name)
    if not _PEER.fullmatch(peer):
        raise Refused("Accept takes a workspace or phone id (ws_… or ph_…).")
    if peer == own_id(root):
        raise Refused("This is this workspace itself.")
    raw = _hint_key(root, peer)
    if raw is None:
        raise Refused("This workspace has no signing key on the relay yet. Run: orch relay refresh")
    fp = msgsig.fingerprint(raw)
    if fingerprint is not None and _norm_fp(fingerprint) != _norm_fp(fp):
        raise Refused("The fingerprint does not match the key the relay lists now. Nothing was accepted.")
    with _state(root) as st:
        c = _contact(st, peer)
        old = [k for k in c.get("keys", []) if k.get("pub") != raw.hex()]
        if old:
            c["old_keys"] = [*c.get("old_keys", []), *old][-10:]
        c["keys"] = [{"pub": raw.hex(), "accepted_at": _iso(_now_ms()), "by": by, "via": via}]
        c.pop("withdrawn", None)
        c["accepted_after_bad"] = int(c.get("not_valid", 0))
        if own is not None:
            if own:
                c["name"] = own
            else:
                c.pop("name", None)
    notes = release(root, peer)
    return {"peer": peer, "fingerprint": fp, "state": "accepted", "released": notes}


def withdraw(root: Path, peer: str, by: str, via: str) -> dict:
    """Take back our own Accept at once (choice B1): its messages are held again, none is handled."""
    with _state(root) as st:
        c = _contact(st, peer)
        c["withdrawn"] = {"by": by, "via": via, "at": _iso(_now_ms())}
    return {"peer": peer, "state": "withdrawn"}


def _norm_fp(fp: str) -> str:
    return re.sub(r"\s+", "", str(fp)).upper()


def state_of(st: dict, peer: str, hint: bytes | None) -> str:
    """accepted | not_accepted | new_key | not_valid | withdrawn (design note section 6)."""
    c = st["contacts"].get(peer) or {}
    if c.get("withdrawn"):
        return "withdrawn"
    if int(c.get("not_valid", 0)) > int(c.get("accepted_after_bad", 0)):
        return "not_valid"
    keys = [k.get("pub") for k in c.get("keys", [])]
    if not keys:
        return "not_accepted"
    if hint is not None and hint.hex() not in keys:
        return "new_key"
    return "accepted"


def _kept_fp(c: dict) -> str | None:
    """The fingerprint of the key a person accepted, kept while withdrawn or not valid (ORCH-1203: the page
    still shows a key swap then)."""
    try:
        pub = bytes.fromhex(str((c.get("keys") or [{}])[0].get("pub") or ""))
    except (ValueError, AttributeError):
        return None
    return msgsig.fingerprint(pub) if len(pub) == 32 else None


def contacts(root: Path) -> list[dict]:
    """Every workspace and phone we know (directory + trust store): id, name, fingerprint (of the key the
    relay
    lists, or of the accepted key), state, held count. For `orch relay contacts` and the Contacts page."""
    from orch import relay

    st = _load(root)
    ids = {w.get("id") for w in relay._directory(root) if _PEER.fullmatch(str(w.get("id", "")))}
    ids |= set(st["contacts"])
    me = own_id(root)
    counts: dict[str, int] = {}
    for x in held(root):
        counts[x["peer"]] = counts.get(x["peer"], 0) + 1
    out = []
    for peer in sorted(i for i in ids if i and i != me):
        hint = _hint_key(root, peer)
        acc = _accepted(st, peer)
        shown = hint or (acc[0] if acc else None)
        c = st["contacts"].get(peer) or {}
        relay_name = relay._shown_name(root, peer, peer)
        keys = c.get("keys") or [{}]
        out.append(
            {
                "id": peer,
                "name": c.get("name") or relay_name,
                "relay_name": relay_name,
                "kind": "phone" if peer.startswith("ph_") else "workspace",
                "accepted_at": keys[0].get("accepted_at"),
                "withdrawn_at": (c.get("withdrawn") or {}).get("at"),
                "fingerprint": msgsig.fingerprint(shown) if shown else None,
                "accepted_fingerprint": msgsig.fingerprint(acc[0]) if acc else _kept_fp(c),
                "state": state_of(st, peer, hint),
                "held": counts.get(peer, 0),
                "not_valid": int((st["contacts"].get(peer) or {}).get("not_valid", 0)),
            }
        )
    return out


def refused(root: Path) -> list[dict]:
    return list(_load(root).get("refused", []))


def require_person(what: str, root: Path | None = None, by: str | None = None) -> None:
    require_person_via(what, root, by)


def require_person_via(what: str, root: Path | None = None, by: str | None = None) -> bool:
    """Accept, withdraw and the signed-only switch are a person's own action: never from a helper. The proof
    is the one-time grant the dashboard's signed-in page session hands this call (the Contacts page,
    ORCH-1203), or a terminal. The grant is always used up first, so no child inherits it. True = the
    dashboard's grant."""
    import os

    from orch import ownerpick, renew, tickets

    if root is not None and ownerpick.person_granted(root, by):
        return True
    if (
        tickets.agent_tool() is not None
        or (by or "").startswith("agent:")
        or any(os.environ.get(k) for k in renew.RUN_MARKS)  # inside a helper run, a terminal is no proof
        or not _is_tty()
    ):
        raise Refused(f"Only a person can do this ({what}), on the Contacts page or at a terminal.")
    return False
