# Signed messages (v1)

Part of the relay contract (relay-api.md points here). Kept in its own file because R4.1 lists signing among the
concepts that need the owner: he asked for signed messages himself (ORCH-1027, 20 Nov 2026) and took every
recommended choice of the design (ORCH-1198, 21 Nov 2026). `scripts/banned_words_allowlist.txt` names the files.

Workspaces and phones sign what they send, so a receiver acts only on messages from a sender a person accepted, even
if the relay or the network is broken into (design: ORCH-1198, decided 21 Nov 2026). This section is the format.
Wiring it into the routes, key registration, Accept and the switch that makes signing required come with the
sibling tickets of ORCH-1027. Code: `workspace/src/orch/msgsig.py`, `relay/src/msgsig.rs`,
`mobile/OrchMobile/MessageSignature.swift`. Shared test examples: `vectors/msgsig-v1.json`, made by
`scripts/gen_msgsig_vectors.py` (never edited by hand; the phone tests read a byte-identical copy in
`mobile/OrchMobileTests/Fixtures/`). All three pass every section. One exception: Wycheproof cases with a
mixed-order key are marked `either`, because libraries may differ on them. The relay never registers such a key.
The workspace and the phone cannot test for it cheaply. Such a key can only be the sender's own (the person
accepted its fingerprint), so it can at worst make its own messages judged differently, never forge another's.

**Keys.** Ed25519, raw 32-byte public keys (never SPKI). A key is refused (at registration and at Accept) when it is
not 32 bytes, when its y is not below p = 2^255 - 19, or when it is one of the eight small-order points (with either
sign bit). The relay also refuses keys with a torsion part at registration (`registration_key_ok`). A trust store
keeps each full key under one contact; if one key is listed under two, the signed `from` decides (never the order
of the list).
- `key_id` = the first 8 bytes of SHA-256("ed25519" ‖ key) as 16 lowercase hex characters. It only finds the key;
  trust is always the full key.
- Fingerprint (what people compare) = the first 160 bits of the same hash in Crockford base32
  (`0123456789ABCDEFGHJKMNPQRSTVWXYZ`), 8 groups of 4 characters split by spaces. A device computes its own
  fingerprint from its own key, never from the relay.

**What is signed.** The sender writes the message once as UTF-8 JSON bytes (the *signed bytes*) and signs
`"orch-sig-v1" 0x00 <purpose> 0x00 <signed bytes>`, purpose one of `msg`, `report`, `key-rotate`,
`key-withdraw`. Nothing is put into a canonical form: the receiver checks the exact bytes and then reads only them.
Bodies for `report`, `key-rotate` and `key-withdraw` are defined with their tickets. They use the same envelope
and strict reading rules.

**Envelope** (the wire). `POST /v1/messages` takes today's message JSON plus a top-level field `envelope`. The relay
stores the envelope as it came, and the inbox and the phone feed hand it back unchanged:

```
"envelope": {"sig_v": 1, "key_id": "<16 hex>", "signed": "<base64url of the signed bytes>", "sig": "<base64url, 64 bytes>",
             "relay_meta": {…}}   // optional, added by the relay, shown only; no decision ever reads it
```

base64url without padding, unused trailing bits zero. Unknown envelope fields, another `sig_v`, a bad `key_id`, a
signature other than 64 bytes or signed bytes outside 2..262144 bytes → `bad_envelope`. No envelope, or a
missing or empty `sig` → `missing_signature`. The outer `id`, `from`, `type`, `ticket`, `reply_to` and `body`
must equal the signed ones, and so must a string `to`. For a signed group `to`, the outer `to` is one workspace
(`ws_…`, the copy's addressee) and the receiver checks the group. Every signed `files` entry must match the
relay's stored blob (size and sha256). Any difference → `422 signed_mismatch`. Messages the relay makes itself (`refresh-hint`, `webhook`, `control`, subscriber
answers) carry no envelope and come from a closed list in code.

**Strict reading of the signed bytes** (same rules in all three languages, else `bad_json`): valid UTF-8; no BOM;
the first byte is `{` and the last is `}` (no whitespace or anything else around the object); no duplicate keys
(compared after unescaping); no lone surrogates; no raw control characters; numbers are integers only (no
fraction, no exponent, no `-0`, no leading zero) within ±(2^53 - 1); no NaN or Infinity; nesting at most 32 deep.
Two keys of one object that are the same text in another Unicode spelling (equal after NFC) are duplicates too.

**Fields of a `msg`** (unknown fields are refused, never ignored; else `bad_field`):

| Field | Rule |
|---|---|
| `v` | `1` (the integer) |
| `id` | `m_` + 16 (message id, as today) |
| `from` | `ws_…` or `ph_…` (the signer) |
| `to` | `ws_…`, `ph_…`, `phones`, or a group `{"group": "grp_t_…", "host": "ws_…", "members_v": <int ≥ 0>}`; never equal to `from`. Only a workspace sends to phones or a group, and a group message is only `text`, `file` or `question`. A phone sends only to a workspace |
| `type` | `text`, `file`, `question`, `answer`, `delegate`, `start`, `allow` (relay-made types are never signed messages) |
| `created_ms` | integer milliseconds since 1970, > 0 |
| `origin` | `person` or `helper`, set by orch itself from a person's own action (dashboard on this computer, CLI with a terminal, phone). Helpers have no signing command. A phone always signs `person` |
| `body` | an object (the type's own content, as today) |
| `ticket`, `reply_to` | optional, `t_…` and `m_…` |
| `question_id`, `question_sha256` | `answer` only and then required (with `reply_to`): the question's id and the SHA-256 hex of the question's signed bytes. After the checks below the receiver acts on an answer only when both match a question it asked that `from` and that is still open (the receiving code's job, not the format's) |
| `expires_ms` | `allow`, `delegate`, `start` only and then required: `created_ms < expires_ms ≤ created_ms + 3600000`. `allow` also needs `reply_to` |
| `files` | on `text`, `file`, `question`, `answer`; required on `file`: 1 to 20 entries of exactly `{"blob_id": "b_…", "size": <0..100 MiB>, "sha256": "<64 hex>"}`, each blob once. A receiver checks size and hash in quarantine before anything opens the file; a file not listed here is refused |

**Who checks what, in this order** (the code returned is the one the vectors expect):

| Step | Relay (first gate) | Receiver: workspace or phone (the decisive gate) |
|---|---|---|
| 1 | envelope: `bad_envelope`, `missing_signature` | same |
| 2 | a registered key of the caller with that `key_id`, else `unknown_key` | a key a person accepted with that `key_id`, else `unknown_key` (a valid signature from a key not accepted yet is held, never acted on) |
| 3 | signature with the key rule above (`verify_strict` in the relay), else `bad_signature` (never held) | same |
| 4 | strict reading `bad_json`, fields `bad_field` | same |
| 5 | signed `from` = the caller, else `wrong_sender` | signed `from` = the contact whose key verified, else `wrong_sender` |
| 6 | the same id stored with the same signed bytes → `200 duplicate`; with other bytes → `replayed` (409 conflict) | `from` = itself → `from_self`; `to` must be itself, `phones` (on a phone) or a group it is in, else `wrong_to` |
| 7 | (no clock or `to` check, so a phone that was offline can still send) | `created_ms` more than 5 minutes ahead → `future`; `expires_ms` reached → `expired`; no `expires_ms` and older than 30 days → `too_old` |
| 8 | | (from, id) seen → `replayed`; else mark it seen atomically before acting. Seen ids are kept 31 days (longer than a message can stay fresh: 30 days plus the 5 minutes of clock skew) |

Over HTTP the relay answers `422` with the code above (`bad_envelope`, `missing_signature`, `unknown_key`,
`bad_signature`, `bad_json`, `bad_field`), `403 wrong_sender` (as rule 1, sender = caller), `409` for `replayed`, `422 key_withdrawn` /
`422 key_blocked` for a withdrawn or blocked key, and, once the admin turned on "signed only", `422
missing_signature` for a message without an envelope (the key and switch rules are in the key sections that
come with the relay ticket). A group message
is never an allow, an answer to a permission question or a start. A held person action is never run by itself on
Accept.
