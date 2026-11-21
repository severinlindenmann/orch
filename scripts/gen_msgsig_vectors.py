"""Write contracts/vectors/msgsig-v1.json (signed messages v1, contracts/relay-api.md "Signed messages").

Run from the repo root:
  uv run --with cryptography python scripts/gen_msgsig_vectors.py [wycheproof ed25519_test.json]
Without the Wycheproof file the "wycheproof" section of the existing vector file is kept as it is.
It also writes the copy the phone tests read (mobile/OrchMobileTests/Fixtures/msgsig-v1.json).

Independent of workspace/src/orch/msgsig.py on purpose: the expected results here are written by hand per
case, so the three implementations are tested against the contract, not against each other.
The seeds below are TEST keys made from public labels; they sign nothing real.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "contracts" / "vectors" / "msgsig-v1.json"
PHONE_COPY = ROOT / "mobile" / "OrchMobileTests" / "Fixtures" / "msgsig-v1.json"

T0 = 1795000000000  # created_ms of most cases (Nov 2026)
MIN = 60_000
DAY = 86_400_000


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def seed(label: str) -> bytes:
    return hashlib.sha256(b"orch msgsig-v1 test key " + label.encode()).digest()


def pub_of(sd: bytes) -> bytes:
    return (
        Ed25519PrivateKey.from_private_bytes(sd)
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )


def kid(pub: bytes) -> str:
    return hashlib.sha256(b"ed25519" + pub).digest()[:8].hex()


CROCK = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def fpr(pub: bytes) -> str:
    n = int.from_bytes(hashlib.sha256(b"ed25519" + pub).digest()[:20], "big")
    s = "".join(CROCK[(n >> (155 - 5 * i)) & 31] for i in range(32))
    return " ".join(s[i : i + 4] for i in range(0, 32, 4))


def sig_input(purpose: str, signed: bytes) -> bytes:
    return b"orch-sig-v1\x00" + purpose.encode() + b"\x00" + signed


def sign_raw(sd: bytes, data: bytes) -> bytes:
    return Ed25519PrivateKey.from_private_bytes(sd).sign(data)


def compact(obj) -> bytes:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()


WS_A, WS_B, WS_C, PH_P = "ws_aaaaaaaaaa", "ws_bbbbbbbbbb", "ws_cccccccccc", "ph_pppppppppp"
SEEDS = {
    "ws_a": seed("ws_a"),
    "ws_b": seed("ws_b"),
    "ws_c": seed("ws_c"),
    "ph_p": seed("ph_p"),
    "mallory": seed("mallory"),
}
PUB = {k: pub_of(v) for k, v in SEEDS.items()}
A, B, C, P, M = (PUB[k] for k in ("ws_a", "ws_b", "ws_c", "ph_p", "mallory"))
IDENTITY = bytes([1]) + bytes(31)  # small-order point (the neutral element)


def env(signed: bytes, sd: bytes, purpose: str = "msg", key: bytes | None = None, **extra) -> dict:
    key = key if key is not None else pub_of(sd)
    e = {
        "sig_v": 1,
        "key_id": kid(key),
        "signed": b64u(signed),
        "sig": b64u(sign_raw(sd, sig_input(purpose, signed))),
    }
    e.update(extra)
    return e


def msg(**kw) -> dict:
    m = {
        "v": 1,
        "id": "m_0000000000000001",
        "from": WS_A,
        "to": WS_B,
        "type": "text",
        "created_ms": T0,
        "origin": "person",
        "ticket": "t_abc123",
        "body": {"text": "Hello from Pilatus"},
    }
    m.update(kw)
    return {k: v for k, v in m.items() if v is not None}


def rx(me=WS_B, accepted=None, now=T0 + 1000, seen=(), groups=()):
    return {
        "me": me,
        "accepted": accepted if accepted is not None else {WS_A: [A.hex()]},
        "now_ms": now,
        "seen": [list(s) for s in seen],
        "groups": [list(g) for g in groups],
    }


def relay(caller=WS_A, registered=None, seen=None):
    return {
        "caller": caller,
        "registered": registered if registered is not None else [A.hex()],
        "seen": seen or {},
    }


cases: list[dict] = []


def case(name, note, envelope, receiver, expect_receiver, relay_ctx, expect_relay):
    cases.append(
        {
            "name": name,
            "note": note,
            "envelope": envelope,
            "receiver": receiver,
            "expect_receiver": expect_receiver,
            "relay": relay_ctx,
            "expect_relay": expect_relay,
        }
    )


def signed_case(
    name, note, signed: bytes, expect, sd=None, receiver=None, relay_ctx=None, expect_relay=None, **envkw
):
    case(
        name,
        note,
        env(signed, sd or SEEDS["ws_a"], **envkw),
        receiver or rx(),
        expect,
        relay_ctx or relay(),
        expect_relay if expect_relay is not None else expect,
    )


# ---- good
good = compact(msg())
signed_case("good_text", "A signed text from ws_a to ws_b.", good, "ok")
signed_case(
    "good_with_relay_meta",
    "relay_meta is outside the signature and never read by decisions.",
    good,
    "ok",
    relay_meta={"from_name": "Somebody else", "type": "allow"},
)
signed_case(
    "good_file",
    "A file listed by blob id, size and hash.",
    compact(
        msg(
            id="m_0000000000000002",
            type="file",
            body={"name": "report.pdf"},
            files=[
                {
                    "blob_id": "b_0000000000000001",
                    "size": 12345,
                    "sha256": hashlib.sha256(b"report").hexdigest(),
                }
            ],
        )
    ),
    "ok",
)
q_hash = hashlib.sha256(b"the question's signed bytes").hexdigest()
signed_case(
    "good_answer",
    "An answer names the question's hash.",
    compact(
        msg(
            id="m_0000000000000003",
            type="answer",
            reply_to="m_00000000000000q1",
            question_id="q1",
            question_sha256=q_hash,
            body={"option": "Yes"},
        )
    ),
    "ok",
)
signed_case(
    "good_allow",
    "An allow carries expires_ms, at most 60 minutes after created_ms.",
    compact(
        msg(
            id="m_0000000000000004",
            type="allow",
            reply_to="m_00000000000000d1",
            expires_ms=T0 + 60 * MIN,
            body={"allow": "delegate"},
        )
    ),
    "ok",
)
signed_case(
    "good_to_phones",
    "A workspace text to every phone; the phone checks it.",
    compact(msg(id="m_0000000000000005", to="phones")),
    "ok",
    receiver=rx(me=PH_P),
)
signed_case(
    "good_from_phone",
    "The phone signs the same format, always as a person.",
    compact(msg(id="m_0000000000000006", **{"from": PH_P}, to=WS_B, ticket=None, body={"text": "Ok, go"})),
    "ok",
    sd=SEEDS["ph_p"],
    receiver=rx(accepted={PH_P: [P.hex()]}),
    relay_ctx=relay(caller=PH_P, registered=[P.hex()]),
)
signed_case(
    "good_group",
    "To a group: host, group id and member-list version are signed.",
    compact(msg(id="m_0000000000000007", to={"group": "grp_t_abc123", "host": WS_A, "members_v": 3})),
    "ok",
    receiver=rx(me=WS_C, groups=[(WS_A, "grp_t_abc123")]),
)
signed_case(
    "good_escapes",
    "Escapes and non-ASCII text are fine when well formed.",
    b'{"v":1,"id":"m_0000000000000008","from":"ws_aaaaaaaaaa","to":"ws_bbbbbbbbbb","type":"text",'
    b'"created_ms":1795000000000,"origin":"helper","body":{"text":"Gr\\u00fc\\u00dfe \\ud83d\\ude00 '
    + "Grüße 😀".encode()
    + b'","n":-42,"list":[true,false,null,{}]}}',
    "ok",
)
signed_case(
    "good_whitespace_inside",
    "Whitespace between tokens is allowed (only outside the object it is not).",
    b'{ "v" : 1 ,\n "id":"m_0000000000000009","from":"ws_aaaaaaaaaa","to":"ws_bbbbbbbbbb","type":"text",'
    b'"created_ms":1795000000000,"origin":"person","body":{}\t}',
    "ok",
)
signed_case(
    "future_within_skew",
    "Created 4 minutes ahead of the receiver's clock: allowed.",
    compact(msg(id="m_0000000000000010", created_ms=T0 + 4 * MIN)),
    "ok",
    receiver=rx(now=T0),
)
signed_case(
    "text_29_days_old", "Text up to 30 days old is still taken.", good, "ok", receiver=rx(now=T0 + 29 * DAY)
)

# ---- wrong
signed_case(
    "wrong_key",
    "Signed by another key but naming ws_a's key id.",
    good,
    "bad_signature",
    sd=SEEDS["mallory"],
    key=A,
)
signed_case(
    "wrong_key_unknown_id",
    "Signed by a key nobody accepted or registered.",
    good,
    "unknown_key",
    sd=SEEDS["mallory"],
)
signed_case(
    "wrong_purpose",
    "Signed as a problem report, presented as a message.",
    good,
    "bad_signature",
    purpose="report",
)
e = env(good, SEEDS["ws_a"])
e["sig"] = b64u(sign_raw(SEEDS["ws_a"], good))
case(
    "wrong_no_tag",
    "Signed over the bare bytes without the orch-sig-v1 tag.",
    e,
    rx(),
    "bad_signature",
    relay(),
    "bad_signature",
)
signed_case(
    "wrong_sender",
    "Valid signature by ws_a, but the signed from says ws_c.",
    compact(msg(id="m_0000000000000011", **{"from": WS_C})),
    "wrong_sender",
)
signed_case(
    "wrong_small_order_key",
    "The neutral point as a key with R = neutral, S = 0 'verifies' any text in a "
    "careless library; the key is refused.",
    good,
    "bad_signature",
    receiver=rx(accepted={WS_A: [IDENTITY.hex()]}),
    relay_ctx=relay(registered=[IDENTITY.hex()]),
)
cases[-1]["envelope"] = {
    "sig_v": 1,
    "key_id": kid(IDENTITY),
    "signed": b64u(good),
    "sig": b64u(IDENTITY + bytes(32)),
}

# ---- missing
e = env(good, SEEDS["ws_a"])
del e["sig"]
case(
    "missing_sig", "Envelope without a signature.", e, rx(), "missing_signature", relay(), "missing_signature"
)
e = env(good, SEEDS["ws_a"])
e["sig"] = ""
case("missing_sig_empty", "Empty signature.", e, rx(), "missing_signature", relay(), "missing_signature")
case(
    "missing_envelope",
    "A plain unsigned message (no envelope at all).",
    None,
    rx(),
    "missing_signature",
    relay(),
    "missing_signature",
)

# ---- changed
e = env(good, SEEDS["ws_a"])
e["signed"] = b64u(good.replace(b"Hello", b"Hallo"))
case(
    "changed_body",
    "One word of the signed bytes changed after signing.",
    e,
    rx(),
    "bad_signature",
    relay(),
    "bad_signature",
)
e = env(good, SEEDS["ws_a"])
s = bytearray(base64.urlsafe_b64decode(e["sig"] + "=="))
s[10] ^= 1
e["sig"] = b64u(bytes(s))
case(
    "changed_signature",
    "One bit of the signature flipped.",
    e,
    rx(),
    "bad_signature",
    relay(),
    "bad_signature",
)
e = env(good, SEEDS["ws_a"])
s = bytearray(base64.urlsafe_b64decode(e["sig"] + "=="))
L = 2**252 + 27742317777372353535851937790883648493
s_int = int.from_bytes(s[32:], "little") + L
e["sig"] = b64u(bytes(s[:32]) + s_int.to_bytes(32, "little"))
case(
    "changed_malleable_s",
    "S + L (same math, second spelling): refused.",
    e,
    rx(),
    "bad_signature",
    relay(),
    "bad_signature",
)

# ---- replayed
signed_case(
    "replayed",
    "The same message again: the receiver refuses a seen id; the relay answers duplicate.",
    good,
    "replayed",
    receiver=rx(seen=[(WS_A, "m_0000000000000001")]),
    relay_ctx=relay(seen={"m_0000000000000001": hashlib.sha256(good).hexdigest()}),
    expect_relay="duplicate",
)
signed_case(
    "replayed_other_bytes",
    "A seen id with other signed bytes: refused by both (relay 409 conflict).",
    compact(msg(body={"text": "Different"})),
    "replayed",
    receiver=rx(seen=[(WS_A, "m_0000000000000001")]),
    relay_ctx=relay(seen={"m_0000000000000001": hashlib.sha256(good).hexdigest()}),
)
signed_case(
    "replayed_expired_allow",
    "An allow released after it expired.",
    compact(
        msg(
            id="m_0000000000000004",
            type="allow",
            reply_to="m_00000000000000d1",
            expires_ms=T0 + 60 * MIN,
            body={"allow": "delegate"},
        )
    ),
    "expired",
    receiver=rx(now=T0 + 60 * MIN),
    expect_relay="ok",
)
signed_case(
    "replayed_old_text",
    "A text held back 31 days.",
    good,
    "too_old",
    receiver=rx(now=T0 + 31 * DAY),
    expect_relay="ok",
)
signed_case(
    "future",
    "Created 6 minutes ahead of the receiver's clock.",
    compact(msg(id="m_0000000000000012", created_ms=T0 + 6 * MIN)),
    "future",
    receiver=rx(now=T0),
    expect_relay="ok",
)

# ---- redirected
signed_case(
    "redirected",
    "Signed for ws_c, delivered to ws_b.",
    compact(msg(id="m_0000000000000013", to=WS_C)),
    "wrong_to",
    expect_relay="ok",
)
signed_case(
    "redirected_phone_text_to_other_phone",
    "Signed for one phone, delivered to another.",
    compact(msg(id="m_0000000000000014", to="ph_qqqqqqqqqq")),
    "wrong_to",
    receiver=rx(me=PH_P),
    expect_relay="ok",
)
signed_case(
    "redirected_group_not_member",
    "A group message to a workspace not in that group.",
    compact(msg(id="m_0000000000000015", to={"group": "grp_t_abc123", "host": WS_A, "members_v": 3})),
    "wrong_to",
    expect_relay="ok",
)
signed_case(
    "from_self",
    "Our own message handed back to us.",
    compact(msg(id="m_0000000000000016", to={"group": "grp_t_abc123", "host": WS_B, "members_v": 1})),
    "from_self",
    receiver=rx(me=WS_A, groups=[(WS_B, "grp_t_abc123")]),
    expect_relay="ok",
)

# ---- strict reading of the signed bytes (signed correctly, refused anyway)
STRICT_BAD = {
    "dup_key_other_unicode_spelling": '{"\u00e9":1,"e\u0301":2}'.encode(),
    "dup_key": b'{"v":1,"v":1}',
    "dup_key_escaped": b'{"id":"m_0000000000000001","\\u0069d":"m_0000000000000002"}',
    "bom": b"\xef\xbb\xbf{}",
    "leading_space": b" {}",
    "trailing_newline": b"{}\n",
    "trailing_bytes": b"{}{}",
    "not_object": b'["x"]',
    "nan": b'{"n":NaN}',
    "infinity": b'{"n":Infinity}',
    "float": b'{"n":1.5}',
    "float_zero_fraction": b'{"n":1.0}',
    "exponent": b'{"n":1e3}',
    "minus_zero": b'{"n":-0}',
    "leading_zero": b'{"n":01}',
    "int_above_2_53": b'{"n":9007199254740992}',
    "int_below_minus_2_53": b'{"n":-9007199254740992}',
    "lone_high_surrogate": b'{"s":"\\ud800"}',
    "lone_low_surrogate": b'{"s":"\\udc00x"}',
    "reversed_surrogates": b'{"s":"\\ude00\\ud83d"}',
    "invalid_utf8": b'{"s":"\xff"}',
    "overlong_utf8": b'{"s":"\xc0\xaf"}',
    "utf8_encoded_surrogate": b'{"s":"\xed\xa0\x80"}',
    "raw_control_char": b'{"s":"a\x01b"}',
    "raw_newline_in_string": b'{"s":"a\nb"}',
    "bad_escape": b'{"s":"\\x41"}',
    "single_quotes": b"{'s':1}",
    "trailing_comma": b'{"a":1,}',
    "too_deep": b'{"a":' + b"[" * 32 + b"]" * 32 + b"}",
    "unterminated": b'{"a":"b}',
}
STRICT_GOOD = {
    "empty_object": b"{}",
    "max_safe_int": b'{"n":9007199254740991}',
    "min_safe_int": b'{"n":-9007199254740991}',
    "depth_32": b'{"a":' + b"[" * 31 + b"]" * 31 + b"}",
    "escaped_slash_and_controls": b'{"s":"a\\/b\\b\\f\\n\\r\\t\\"\\\\"}',
    "surrogate_pair": b'{"s":"\\ud83d\\ude00"}',
    "utf8_4_byte": '{"s":"😀"}'.encode(),
    "same_key_in_two_objects": b'{"a":{"k":1},"b":{"k":1}}',
}
for name in (
    "dup_key_escaped",
    "bom",
    "trailing_newline",
    "float",
    "int_above_2_53",
    "lone_high_surrogate",
    "invalid_utf8",
    "too_deep",
):
    signed_case(
        f"strict_{name}",
        "Correctly signed, but the bytes break a strict reading rule.",
        STRICT_BAD[name],
        "bad_json",
    )


# ---- field rules (signed correctly, refused anyway)
def field_case(name, note, **kw):
    signed_case(f"field_{name}", note, compact(msg(id="m_00000000000000f1", **kw)), "bad_field")


field_case("unknown_top_field", "An unknown field is refused, never ignored.", extra="x")
field_case("missing_origin", "origin is required.", origin=None)
field_case("bool_as_version", "true is not the integer 1.", v=True)
field_case("created_as_string", "Times are integer milliseconds.", created_ms="2026-11-21T10:00:00Z")
field_case(
    "allow_without_expiry",
    "allow, delegate and start need expires_ms.",
    type="allow",
    reply_to="m_00000000000000d1",
)
field_case(
    "expiry_over_60_min",
    "expires_ms at most 60 minutes after created_ms.",
    type="start",
    expires_ms=T0 + 61 * MIN,
)
field_case("expiry_on_text", "expires_ms only on allow, delegate and start.", expires_ms=T0 + MIN)
field_case(
    "answer_without_question_hash",
    "An answer must sign the question's hash.",
    type="answer",
    reply_to="m_00000000000000q1",
    question_id="q1",
)
field_case("to_equals_from", "A message to itself.", to=WS_A)
field_case("file_without_files", "A file message lists its files.", type="file")
field_case(
    "file_bad_hash",
    "A file hash is 64 lowercase hex characters.",
    type="file",
    files=[{"blob_id": "b_0000000000000001", "size": 1, "sha256": "ABC"}],
)
field_case(
    "file_extra_field",
    "File entries have exactly blob_id, size, sha256.",
    type="file",
    files=[{"blob_id": "b_0000000000000001", "size": 1, "sha256": "0" * 64, "name": "x"}],
)
field_case(
    "type_from_relay_list", "Types the relay makes itself are never signed messages.", type="refresh-hint"
)
signed_case(
    "field_phone_as_helper",
    "A phone signs only as a person.",
    compact(msg(id="m_00000000000000f2", **{"from": PH_P}, origin="helper")),
    "bad_field",
    sd=SEEDS["ph_p"],
    receiver=rx(accepted={PH_P: [P.hex()]}),
    relay_ctx=relay(caller=PH_P, registered=[P.hex()]),
)
signed_case(
    "field_phone_to_phones",
    "A phone sends only to a workspace.",
    compact(msg(id="m_00000000000000f3", **{"from": PH_P}, to="phones")),
    "bad_field",
    sd=SEEDS["ph_p"],
    receiver=rx(me=PH_P, accepted={PH_P: [P.hex()]}),
    relay_ctx=relay(caller=PH_P, registered=[P.hex()]),
)


# ---- found by the outside review (OpenAI credit, 21 Nov): one spelling, one answer everywhere
field_case("ticket_trailing_newline", "A trailing newline is not part of an id pattern.", ticket="t_abc123\n")
signed_case(
    "field_id_trailing_newline",
    "A trailing newline is not part of an id pattern.",
    compact(msg(id="m_00000000000000f1\n")),
    "bad_field",
)
field_case("question_id_on_text", "question_id only on an answer.", question_id="q1")
field_case(
    "group_allow",
    "A group message is never an allow.",
    type="allow",
    reply_to="m_00000000000000d1",
    expires_ms=T0 + MIN,
    to={"group": "grp_t_abc123", "host": WS_A, "members_v": 1},
)
field_case(
    "group_start",
    "A group message is never a start.",
    type="start",
    expires_ms=T0 + MIN,
    to={"group": "grp_t_abc123", "host": WS_A, "members_v": 1},
)
field_case(
    "group_answer",
    "A group message is never an answer.",
    type="answer",
    reply_to="m_00000000000000q1",
    question_id="q1",
    question_sha256=q_hash,
    to={"group": "grp_t_abc123", "host": WS_A, "members_v": 1},
)
signed_case(
    "strict_dup_key_other_unicode_spelling",
    "Two keys that are the same text in another Unicode spelling (NFC) count as a duplicate.",
    compact(msg(id="m_00000000000000f4", body={"\u00e9": 1, "e\u0301": 2})),
    "bad_json",
)
signed_case(
    "same_key_two_contacts",
    "One key listed under two contacts: the signed from decides, never the order of the list.",
    compact(msg(id="m_00000000000000f5", **{"from": WS_C})),
    "ok",
    receiver=rx(accepted={WS_A: [A.hex()], WS_C: [A.hex()]}),
    expect_relay="wrong_sender",
)
signed_case(
    "future_exactly_5_min",
    "Exactly 5 minutes ahead is still allowed.",
    compact(msg(id="m_00000000000000f6", created_ms=T0 + 5 * MIN)),
    "ok",
    receiver=rx(now=T0),
)
signed_case(
    "expired_exactly_at_expiry",
    "At expires_ms the allow is expired.",
    compact(
        msg(
            id="m_00000000000000f7",
            type="allow",
            reply_to="m_00000000000000d1",
            expires_ms=T0 + 10 * MIN,
            body={},
        )
    ),
    "expired",
    receiver=rx(now=T0 + 10 * MIN),
    expect_relay="ok",
)
signed_case(
    "text_exactly_30_days_old",
    "Exactly 30 days old is still taken (older is refused).",
    good,
    "ok",
    receiver=rx(now=T0 + 30 * DAY),
)


# ---- envelope shape
def env_case(name, note, mutate, expect="bad_envelope"):
    e = env(good, SEEDS["ws_a"])
    mutate(e)
    case(f"envelope_{name}", note, e, rx(), expect, relay(), expect)


env_case("padded_base64", "base64url without padding only.", lambda e: e.update(sig=e["sig"] + "=="))
env_case("standard_base64_chars", "+ and / are not base64url.", lambda e: e.update(signed=e["signed"] + "+"))
_sig = base64.urlsafe_b64decode(env(good, SEEDS["ws_a"])["sig"] + "==")


def _noncanon(e):
    s = e["sig"]  # 64 bytes -> 86 chars, the last char carries 2 unused bits
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    e["sig"] = s[:-1] + alphabet[alphabet.index(s[-1]) | 1]


env_case("noncanonical_base64_bits", "Unused trailing bits must be zero (one spelling only).", _noncanon)
env_case(
    "key_id_uppercase",
    "key_id is 16 lowercase hex characters.",
    lambda e: e.update(key_id=e["key_id"].upper()),
)
env_case("sig_63_bytes", "A signature is exactly 64 bytes.", lambda e: e.update(sig=b64u(_sig[:63])))
env_case("sig_65_bytes", "A signature is exactly 64 bytes.", lambda e: e.update(sig=b64u(_sig + b"\x00")))
env_case("unknown_field", "Unknown envelope fields are refused.", lambda e: e.update(purpose="msg"))
env_case("sig_v_2", "Only sig_v 1 exists.", lambda e: e.update(sig_v=2))
env_case("relay_meta_not_object", "relay_meta is an object when present.", lambda e: e.update(relay_meta="x"))
env_case("signed_empty", "The signed bytes are not empty.", lambda e: e.update(signed=""))
env_case("sig_v_float", "sig_v is the integer 1, not 1.0.", lambda e: e.update(sig_v=1.0))

# ---- deterministic signatures (Python and Rust sign; CryptoKit signatures are randomized, Swift skips these)
sign_cases = []
for label, sd, purpose, data in (
    ("ws_a", SEEDS["ws_a"], "msg", good),
    (
        "ph_p",
        SEEDS["ph_p"],
        "msg",
        compact(
            msg(id="m_0000000000000006", **{"from": PH_P}, to=WS_B, ticket=None, body={"text": "Ok, go"})
        ),
    ),
    ("ws_a", SEEDS["ws_a"], "report", b'{"archive_sha256":"' + b"0" * 64 + b'"}'),
):
    sign_cases.append(
        {
            "name": f"{label}_{purpose}",
            "seed": sd.hex(),
            "purpose": purpose,
            "signed": b64u(data),
            "sig": b64u(sign_raw(sd, sig_input(purpose, data))),
        }
    )

parties = {}
for name, addr in (("ws_a", WS_A), ("ws_b", WS_B), ("ws_c", WS_C), ("ph_p", PH_P), ("mallory", None)):
    parties[name] = {
        "address": addr,
        "seed": SEEDS[name].hex(),
        "pub": PUB[name].hex(),
        "key_id": kid(PUB[name]),
        "fingerprint": fpr(PUB[name]),
    }

P_INT = 2**255 - 19
ORDER8_A = bytes.fromhex("c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a")
ORDER8_B = bytes.fromhex("26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05")


def with_sign(b: bytes) -> bytes:
    return b[:31] + bytes([b[31] | 0x80])


keys = [
    {"name": "good_ws_a", "pub": A.hex(), "ok": True},
    {"name": "good_ph_p", "pub": P.hex(), "ok": True},
    {"name": "neutral_point", "pub": IDENTITY.hex(), "ok": False},
    {"name": "neutral_point_sign_bit", "pub": with_sign(IDENTITY).hex(), "ok": False},
    {"name": "order_2", "pub": (P_INT - 1).to_bytes(32, "little").hex(), "ok": False},
    {"name": "order_4", "pub": bytes(32).hex(), "ok": False},
    {"name": "order_4_sign_bit", "pub": with_sign(bytes(32)).hex(), "ok": False},
    {"name": "order_8_a", "pub": ORDER8_A.hex(), "ok": False},
    {"name": "order_8_a_sign_bit", "pub": with_sign(ORDER8_A).hex(), "ok": False},
    {"name": "order_8_b", "pub": ORDER8_B.hex(), "ok": False},
    {"name": "order_8_b_sign_bit", "pub": with_sign(ORDER8_B).hex(), "ok": False},
    {"name": "y_equals_p", "pub": P_INT.to_bytes(32, "little").hex(), "ok": False},
    {"name": "y_equals_p_plus_1", "pub": (P_INT + 1).to_bytes(32, "little").hex(), "ok": False},
    {"name": "all_ff", "pub": "ff" * 32, "ok": False},
    {"name": "31_bytes", "pub": A[:31].hex(), "ok": False},
    {"name": "33_bytes", "pub": (A + b"\x00").hex(), "ok": False},
]

# ---- Wycheproof Ed25519 (C2SP/wycheproof, Apache-2.0), run through each side's verify_raw
if len(sys.argv) > 1:
    wp = json.loads(Path(sys.argv[1]).read_text())
    small = {"SmallOrderPublicKey"}
    wy_cases = []
    for g in wp["testGroups"]:
        pk = g["publicKey"]["pk"]
        for t in g["tests"]:
            if t["result"] == "valid":
                exp = True
            elif t["result"] == "invalid" or small & set(t["flags"]):
                exp = False
            else:
                # mixed-order key: libraries may differ; the relay refuses such keys at registration
                exp = "either"
            wy_cases.append(
                {
                    "tcId": t["tcId"],
                    "pk": pk,
                    "msg": t["msg"],
                    "sig": t["sig"],
                    "flags": t["flags"],
                    "expect": exp,
                }
            )
    wycheproof = {
        "source": "C2SP/wycheproof testvectors_v1/ed25519_test.json (Apache-2.0)",
        "count": len(wy_cases),
        "cases": wy_cases,
    }
else:
    wycheproof = json.loads(OUT.read_text())["wycheproof"]

doc = {
    "name": "msgsig-v1",
    "about": "Signed messages v1, contracts/relay-api.md 'Signed messages'. "
    "Made by scripts/gen_msgsig_vectors.py; "
    "do not edit by hand. Seeds are public TEST keys. Python (workspace), Rust (relay) and Swift (phone) "
    "run every section; Swift skips 'sign' (CryptoKit signatures are randomized).",
    "constants": {
        "tag": "orch-sig-v1",
        "purposes": ["msg", "report", "key-rotate", "key-withdraw"],
        "max_signed_bytes": 262144,
        "max_depth": 32,
        "future_skew_ms": 5 * MIN,
        "max_expiry_ms": 60 * MIN,
        "max_age_ms": 30 * DAY,
    },
    "parties": parties,
    "keys": keys,
    "sign": sign_cases,
    "strict_json": [{"name": k, "hex": v.hex(), "ok": False} for k, v in STRICT_BAD.items()]
    + [{"name": k, "hex": v.hex(), "ok": True} for k, v in STRICT_GOOD.items()],
    "messages": cases,
    "wycheproof": wycheproof,
}
names = [c["name"] for c in cases]
assert len(names) == len(set(names)), "duplicate case name"
text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
OUT.write_text(text)
PHONE_COPY.write_text(text)
print(
    f"wrote {OUT.relative_to(ROOT)} and the phone copy: {len(cases)} messages, {len(keys)} keys, "
    f"{len(doc['strict_json'])} strict reading, {wycheproof['count']} Wycheproof"
)
