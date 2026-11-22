"""Signed messages v1 (contracts/msgsig.md, vectors/msgsig-v1.json).

Pure functions, no I/O: the format, strict reading, key ids, fingerprints, signing and the checks a receiver
runs. Where the trust store, seen ids and held messages live is the job of the code that calls this (later
tickets); here they come in as plain arguments so the shared test examples can drive every rule.

Rules in one place (the contract is the source of truth):
- Signature input = b"orch-sig-v1" 0x00 purpose 0x00 signed_bytes, Ed25519, raw 32-byte keys.
- The signed bytes are one UTF-8 JSON object, read strictly (read_strict_json).
- Decision code reads only what verify returned; never the envelope's relay_meta.
"""

from __future__ import annotations

import base64
import hashlib
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

SIG_TAG = b"orch-sig-v1"
PURPOSES = ("msg", "report", "key-rotate", "key-withdraw")
MAX_SIGNED_BYTES = 262144
MAX_DEPTH = 32
MAX_SAFE_INT = 2**53 - 1
FUTURE_SKEW_MS = 5 * 60 * 1000
MAX_EXPIRY_MS = 60 * 60 * 1000
MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000
MAX_FILE_SIZE = 100 * 1024 * 1024
MAX_FILES = 20

TYPES = ("text", "file", "question", "answer", "delegate", "start", "allow")
EXPIRING_TYPES = ("allow", "delegate", "start")
FILE_TYPES = ("text", "file", "question", "answer")
GROUP_TYPES = ("text", "file", "question")

_P = 2**255 - 19
# y coordinates (low 255 bits) of the eight small-order points: 0, 1, p-1 and the two order-8 values.
_SMALL_ORDER_Y = {
    0,
    1,
    _P - 1,
    int.from_bytes(
        bytes.fromhex("c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a"), "little"
    ),
    int.from_bytes(
        bytes.fromhex("26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05"), "little"
    ),
}
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

_RE_WS = re.compile(r"^ws_[a-z0-9]{10}$")
_RE_PH = re.compile(r"^ph_[a-z0-9]{10}$")
_RE_MSG = re.compile(r"^m_[a-z0-9]{16}$")
_RE_TICKET = re.compile(r"^t_[a-z0-9]{6,16}$")
_RE_GROUP = re.compile(r"^grp_t_[a-z0-9]{6,16}$")
_RE_BLOB = re.compile(r"^b_[a-z0-9]{16}$")
_RE_QID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_RE_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_RE_KEY_ID = re.compile(r"^[0-9a-f]{16}$")
_RE_B64URL = re.compile(r"^[A-Za-z0-9_-]*$")


class SigError(Exception):
    """A refusal. `code` is one of the codes in the contract (bad_envelope, missing_signature, unknown_key,
    bad_signature, bad_json, bad_field, wrong_sender, from_self, wrong_to, future, expired, too_old,
    replayed)."""

    def __init__(self, code: str, why: str = ""):
        super().__init__(f"{code}: {why}" if why else code)
        self.code = code


# ---------------------------------------------------------------- keys


def key_hash(pub: bytes) -> bytes:
    return hashlib.sha256(b"ed25519" + pub).digest()


def key_id(pub: bytes) -> str:
    """16 hex characters. Only an index to find the key; trust is always the full key."""
    return key_hash(pub)[:8].hex()


def fingerprint(pub: bytes) -> str:
    """What people compare: the first 160 bits of the key hash in Crockford base32, 8 groups of 4."""
    n = int.from_bytes(key_hash(pub)[:20], "big")
    chars = "".join(_CROCKFORD[(n >> (155 - 5 * i)) & 31] for i in range(32))
    return " ".join(chars[i : i + 4] for i in range(0, 32, 4))


def public_key_ok(pub: bytes) -> bool:
    """A raw Ed25519 key we accept: 32 bytes, canonical y (< p), not one of the small-order points
    (whatever the sign bit). Points off the curve fail at verify. The relay also refuses keys with a torsion
    part at registration; the workspace and the phone cannot test that cheaply and need not (contract)."""
    if not isinstance(pub, (bytes, bytearray)) or len(pub) != 32:
        return False
    y = int.from_bytes(pub, "little") & ((1 << 255) - 1)
    return y < _P and y not in _SMALL_ORDER_Y


def verify_raw(pub: bytes, data: bytes, sig: bytes) -> bool:
    if not public_key_ok(pub) or len(sig) != 64:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(bytes(pub)).verify(bytes(sig), bytes(data))
        return True
    except (InvalidSignature, ValueError):
        return False


def signature_input(purpose: str, signed: bytes) -> bytes:
    if purpose not in PURPOSES:
        raise ValueError(f"unknown purpose {purpose!r}")
    return SIG_TAG + b"\x00" + purpose.encode("ascii") + b"\x00" + signed


# ---------------------------------------------------------------- base64url, strict


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode_strict(text: Any) -> bytes:
    """No padding, URL alphabet only, unused trailing bits zero (one spelling per byte string)."""
    if not isinstance(text, str) or not _RE_B64URL.fullmatch(text) or len(text) % 4 == 1:
        raise ValueError("not base64url")
    raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    if b64url(raw) != text:
        raise ValueError("not canonical base64url")
    return raw


# ---------------------------------------------------------------- strict JSON


class _Reader:
    def __init__(self, s: str):
        self.s = s
        self.i = 0

    def fail(self, why: str):
        raise ValueError(f"{why} at {self.i}")

    def ws(self):
        s, i = self.s, self.i
        while i < len(s) and s[i] in " \t\n\r":
            i += 1
        self.i = i

    def value(self, depth: int):
        self.ws()
        if self.i >= len(self.s):
            self.fail("end of text")
        c = self.s[self.i]
        if c == "{":
            return self.obj(depth + 1)
        if c == "[":
            return self.arr(depth + 1)
        if c == '"':
            return self.string()
        if c == "-" or "0" <= c <= "9":
            return self.number()
        for word, val in (("true", True), ("false", False), ("null", None)):
            if self.s.startswith(word, self.i):
                self.i += len(word)
                return val
        self.fail("unexpected character")

    def obj(self, depth: int):
        if depth > MAX_DEPTH:
            self.fail("too deep")
        self.i += 1
        out: dict = {}
        seen_keys: set[str] = set()
        self.ws()
        if self.s.startswith("}", self.i):
            self.i += 1
            return out
        while True:
            self.ws()
            if not self.s.startswith('"', self.i):
                self.fail("key expected")
            k = self.string()
            nk = unicodedata.normalize("NFC", k)
            if nk in seen_keys:
                self.fail("duplicate key")
            seen_keys.add(nk)
            self.ws()
            if not self.s.startswith(":", self.i):
                self.fail("colon expected")
            self.i += 1
            out[k] = self.value(depth)
            self.ws()
            if self.s.startswith(",", self.i):
                self.i += 1
                continue
            if self.s.startswith("}", self.i):
                self.i += 1
                return out
            self.fail("comma or } expected")

    def arr(self, depth: int):
        if depth > MAX_DEPTH:
            self.fail("too deep")
        self.i += 1
        out: list = []
        self.ws()
        if self.s.startswith("]", self.i):
            self.i += 1
            return out
        while True:
            out.append(self.value(depth))
            self.ws()
            if self.s.startswith(",", self.i):
                self.i += 1
                continue
            if self.s.startswith("]", self.i):
                self.i += 1
                return out
            self.fail("comma or ] expected")

    def hex4(self) -> int:
        h = self.s[self.i : self.i + 4]
        if len(h) != 4 or any(c not in "0123456789abcdefABCDEF" for c in h):
            self.fail("bad \\u escape")
        self.i += 4
        return int(h, 16)

    def string(self) -> str:
        self.i += 1
        s = self.s
        out = []
        while True:
            if self.i >= len(s):
                self.fail("unterminated string")
            c = s[self.i]
            if c == '"':
                self.i += 1
                return "".join(out)
            if c == "\\":
                self.i += 1
                e = s[self.i : self.i + 1]
                self.i += 1
                simple = {
                    '"': '"',
                    "\\": "\\",
                    "/": "/",
                    "b": "\b",
                    "f": "\f",
                    "n": "\n",
                    "r": "\r",
                    "t": "\t",
                }
                if e in simple:
                    out.append(simple[e])
                elif e == "u":
                    cp = self.hex4()
                    if 0xD800 <= cp <= 0xDBFF:
                        if s[self.i : self.i + 2] != "\\u":
                            self.fail("lone surrogate")
                        self.i += 2
                        lo = self.hex4()
                        if not 0xDC00 <= lo <= 0xDFFF:
                            self.fail("lone surrogate")
                        cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)
                    elif 0xDC00 <= cp <= 0xDFFF:
                        self.fail("lone surrogate")
                    out.append(chr(cp))
                else:
                    self.fail("bad escape")
                continue
            if ord(c) < 0x20:
                self.fail("control character in string")
            out.append(c)
            self.i += 1

    def number(self) -> int:
        m = re.compile(r"-?(0|[1-9][0-9]*)").match(self.s, self.i)
        if not m:
            self.fail("bad number")
        tail = self.s[m.end() : m.end() + 1]
        if tail in (".", "e", "E"):
            self.fail("only integers")
        txt = m.group(0)
        if txt == "-0":
            self.fail("-0")
        if len(txt.lstrip("-")) > 16:
            self.fail("integer too large")
        n = int(txt)
        if abs(n) > MAX_SAFE_INT:
            self.fail("integer too large")
        self.i = m.end()
        return n


def read_strict_json(data: bytes) -> dict:
    """The signed bytes as one JSON object, or ValueError. Refused: invalid UTF-8, a BOM, anything before
    `{` or after the closing `}` (whitespace too), duplicate keys (after unescaping), lone surrogates,
    control characters,
    numbers with a fraction or exponent, -0, integers beyond 2^53-1, NaN/Infinity, nesting deeper than 32."""
    if len(data) > MAX_SIGNED_BYTES:
        raise ValueError("too large")
    if data[:1] != b"{" or data[-1:] != b"}":
        raise ValueError("must be one object with nothing around it")
    text = data.decode("utf-8")  # strict: refuses overlong forms, encoded surrogates and bad bytes
    r = _Reader(text)
    val = r.value(0)
    if r.i != len(text):
        raise ValueError("trailing bytes")
    return val


# ---------------------------------------------------------------- the message fields

_TOP_FIELDS = {
    "v",
    "id",
    "from",
    "to",
    "type",
    "created_ms",
    "origin",
    "body",
    "ticket",
    "reply_to",
    "question_id",
    "question_sha256",
    "expires_ms",
    "files",
}


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def check_fields(m: dict) -> dict:
    """Field rules of a `msg` signed object; returns it or raises SigError('bad_field')."""

    def bad(why: str):
        raise SigError("bad_field", why)

    if not isinstance(m, dict):
        bad("not an object")
    extra = set(m) - _TOP_FIELDS
    if extra:
        bad(f"unknown field {sorted(extra)[0]}")
    for k in ("v", "id", "from", "to", "type", "created_ms", "origin", "body"):
        if k not in m:
            bad(f"missing {k}")
    if m["v"] != 1 or not _is_int(m["v"]):
        bad("v")
    if not isinstance(m["id"], str) or not _RE_MSG.fullmatch(m["id"]):
        bad("id")
    frm = m["from"]
    if not isinstance(frm, str) or not (_RE_WS.fullmatch(frm) or _RE_PH.fullmatch(frm)):
        bad("from")
    to = m["to"]
    if isinstance(to, str):
        if not (_RE_WS.fullmatch(to) or _RE_PH.fullmatch(to) or to == "phones"):
            bad("to")
        if to == frm:
            bad("to equals from")
        if (to == "phones" or _RE_PH.fullmatch(to)) and not _RE_WS.fullmatch(frm):
            bad("only a workspace sends to phones")
    elif isinstance(to, dict):
        if set(to) != {"group", "host", "members_v"}:
            bad("to group fields")
        if not isinstance(to["group"], str) or not _RE_GROUP.fullmatch(to["group"]):
            bad("to.group")
        if not isinstance(to["host"], str) or not _RE_WS.fullmatch(to["host"]):
            bad("to.host")
        if not _is_int(to["members_v"]) or to["members_v"] < 0:
            bad("to.members_v")
        if not _RE_WS.fullmatch(frm):
            bad("only a workspace sends to a group")
    else:
        bad("to")
    if isinstance(to, dict) and m["type"] not in GROUP_TYPES:
        bad("a group message is only text, file or question")
    if _RE_PH.fullmatch(frm) and not (isinstance(to, str) and _RE_WS.fullmatch(to)):
        bad("a phone sends only to a workspace")
    typ = m["type"]
    if typ not in TYPES:
        bad("type")
    if not _is_int(m["created_ms"]) or m["created_ms"] <= 0:
        bad("created_ms")
    if m["origin"] not in ("person", "helper"):
        bad("origin")
    if _RE_PH.fullmatch(frm) and m["origin"] != "person":
        bad("a phone signs only as a person")
    if not isinstance(m["body"], dict):
        bad("body")
    if "ticket" in m and (not isinstance(m["ticket"], str) or not _RE_TICKET.fullmatch(m["ticket"])):
        bad("ticket")
    if "reply_to" in m and (not isinstance(m["reply_to"], str) or not _RE_MSG.fullmatch(m["reply_to"])):
        bad("reply_to")
    if "question_id" in m and (
        not isinstance(m["question_id"], str) or not _RE_QID.fullmatch(m["question_id"])
    ):
        bad("question_id")
    if "question_sha256" in m and (
        not isinstance(m["question_sha256"], str) or not _RE_HEX64.fullmatch(m["question_sha256"])
    ):
        bad("question_sha256")
    if typ == "answer":
        for k in ("reply_to", "question_id", "question_sha256"):
            if k not in m:
                bad(f"answer needs {k}")
    elif "question_sha256" in m or "question_id" in m:
        bad("question_id and question_sha256 only on answer")
    if typ == "allow" and "reply_to" not in m:
        bad("allow needs reply_to")
    if typ in EXPIRING_TYPES:
        e = m.get("expires_ms")
        if not _is_int(e):
            bad(f"{typ} needs expires_ms")
        if not m["created_ms"] < e <= m["created_ms"] + MAX_EXPIRY_MS:
            bad("expires_ms out of range")
    elif "expires_ms" in m:
        bad("expires_ms only on allow, delegate, start")
    if "files" in m:
        files = m["files"]
        if typ not in FILE_TYPES:
            bad("files not allowed on this type")
        if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
            bad("files")
        seen = set()
        for f in files:
            if not isinstance(f, dict) or set(f) != {"blob_id", "size", "sha256"}:
                bad("file fields")
            if (
                not isinstance(f["blob_id"], str)
                or not _RE_BLOB.fullmatch(f["blob_id"])
                or f["blob_id"] in seen
            ):
                bad("file blob_id")
            seen.add(f["blob_id"])
            if not _is_int(f["size"]) or not 0 <= f["size"] <= MAX_FILE_SIZE:
                bad("file size")
            if not isinstance(f["sha256"], str) or not _RE_HEX64.fullmatch(f["sha256"]):
                bad("file sha256")
    elif typ == "file":
        bad("file needs files")
    return m


# ---------------------------------------------------------------- envelope, sign, verify

_ENV_FIELDS = {"sig_v", "key_id", "signed", "sig", "relay_meta"}


@dataclass(frozen=True)
class Envelope:
    key_id: str
    signed: bytes
    sig: bytes


def read_envelope(env: Any) -> Envelope:
    if env is None:
        raise SigError("missing_signature", "no envelope")
    if not isinstance(env, dict):
        raise SigError("bad_envelope", "not an object")
    if set(env) - _ENV_FIELDS:
        raise SigError("bad_envelope", "unknown field")
    if env.get("sig_v") != 1 or not _is_int(env.get("sig_v")):
        raise SigError("bad_envelope", "sig_v")
    if "relay_meta" in env and not isinstance(env["relay_meta"], dict):
        raise SigError("bad_envelope", "relay_meta")
    if env.get("sig") in (None, ""):
        raise SigError("missing_signature", "no sig")
    kid = env.get("key_id")
    if not isinstance(kid, str) or not _RE_KEY_ID.fullmatch(kid):
        raise SigError("bad_envelope", "key_id")
    try:
        signed = b64url_decode_strict(env.get("signed"))
        sig = b64url_decode_strict(env["sig"])
    except ValueError as e:
        raise SigError("bad_envelope", str(e)) from None
    if not 2 <= len(signed) <= MAX_SIGNED_BYTES:
        raise SigError("bad_envelope", "size of the message bytes")
    if len(sig) != 64:
        raise SigError("bad_envelope", "sig size")
    return Envelope(kid, signed, sig)


def sign(seed: bytes, purpose: str, signed: bytes) -> dict:
    """The envelope for `signed` (the exact bytes the caller wrote). Only orch itself calls this; helpers have
    no signing command (contract: origin)."""
    sk = Ed25519PrivateKey.from_private_bytes(seed)
    from cryptography.hazmat.primitives import serialization

    pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    sig = sk.sign(signature_input(purpose, signed))
    return {"sig_v": 1, "key_id": key_id(pub), "signed": b64url(signed), "sig": b64url(sig)}


def verify(env: Any, purpose: str, keys: Iterable[tuple[str, bytes]]) -> tuple[str, dict]:
    """Envelope + the keys this side trusts as (owner, raw key) -> (owner, signed object). Checks, in this
    order: envelope, key, signature, strict JSON, fields, signed `from` is an owner of a key that verified (so
    the answer never depends on the order of the keys)."""
    e = read_envelope(env)
    cands = [(o, k) for o, k in keys if key_id(k) == e.key_id]
    if not cands:
        raise SigError("unknown_key")
    data = signature_input(purpose, e.signed)
    owners = {o for o, k in cands if verify_raw(k, data, e.sig)}
    if not owners:
        raise SigError("bad_signature")
    try:
        m = read_strict_json(e.signed)
    except ValueError as err:
        raise SigError("bad_json", str(err)) from None
    if purpose == "msg":
        check_fields(m)
        if m["from"] not in owners:
            raise SigError("wrong_sender")
        return m["from"], m
    return min(owners), m


def receiver_check(
    env: Any,
    *,
    me: str,
    accepted: dict[str, list[bytes]],
    now_ms: int,
    seen: set[tuple[str, str]] = frozenset(),
    groups: Iterable[tuple[str, str]] = (),
) -> dict:
    """The receiver's signature, format and freshness checks for a `msg`. `accepted` = contact -> keys a
    person accepted; `seen` = (from, id) already handled; `groups` = (host, group id) this workspace is in.
    On success the caller marks (from, id) seen atomically before acting; an answer still needs its open
    question."""
    keys = [(o, k) for o, ks in accepted.items() for k in ks]
    _, m = verify(env, "msg", keys)
    frm, to = m["from"], m["to"]
    if frm == me:
        raise SigError("from_self")
    if isinstance(to, dict):
        ok = me.startswith("ws_") and (to["host"], to["group"]) in set(groups)
    else:
        ok = to == me or (to == "phones" and me.startswith("ph_"))
    if not ok:
        raise SigError("wrong_to")
    if m["created_ms"] > now_ms + FUTURE_SKEW_MS:
        raise SigError("future")
    if "expires_ms" in m:
        if now_ms >= m["expires_ms"]:
            raise SigError("expired")
    elif m["created_ms"] < now_ms - MAX_AGE_MS:
        raise SigError("too_old")
    if (frm, m["id"]) in seen:
        raise SigError("replayed")
    return m


def relay_check(env: Any, *, caller: str, registered: list[bytes], seen: dict[str, str]) -> tuple[str, dict]:
    """The relay's gate (first gate; the Rust relay implements the same, this one runs the vectors in Python
    too). `seen` = message id -> sha256 hex of its signed bytes. Returns ("ok" | "duplicate", object)."""
    _, m = verify(env, "msg", [(caller, k) for k in registered])
    signed = read_envelope(env).signed
    h = hashlib.sha256(signed).hexdigest()
    old = seen.get(m["id"])
    if old is None:
        return "ok", m
    if old == h:
        return "duplicate", m
    raise SigError("replayed")
