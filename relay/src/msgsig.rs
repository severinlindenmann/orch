//! Signed messages v1 (contracts/relay-api.md "Signed messages", vectors/msgsig-v1.json).
//!
//! The relay is the first gate: it checks the envelope, the sender's registered key, the signature, the strict
//! reading of the signed bytes, the field rules and that the signed `from` is the caller. Freshness and `to` are
//! the receiver's job (the workspace and the phone). Wiring into the routes is a later ticket; this module is
//! pure and runs the shared vectors.

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use ed25519_dalek::{Signature, VerifyingKey};
use serde_json::{Map, Number, Value};
use sha2::{Digest, Sha256};
use unicode_normalization::UnicodeNormalization;

pub const SIG_TAG: &[u8] = b"orch-sig-v1";
pub const PURPOSES: [&str; 4] = ["msg", "report", "key-rotate", "key-withdraw"];
pub const MAX_SIGNED_BYTES: usize = 262_144;
pub const MAX_DEPTH: usize = 32;
pub const MAX_SAFE_INT: i64 = (1 << 53) - 1;
pub const MAX_EXPIRY_MS: i64 = 60 * 60 * 1000;
pub const MAX_FILE_SIZE: i64 = 100 * 1024 * 1024;
pub const MAX_FILES: usize = 20;
const TYPES: [&str; 7] = [
    "text", "file", "question", "answer", "delegate", "start", "allow",
];
const EXPIRING: [&str; 3] = ["allow", "delegate", "start"];
const FILE_TYPES: [&str; 4] = ["text", "file", "question", "answer"];
const GROUP_TYPES: [&str; 3] = ["text", "file", "question"];
const CROCKFORD: &[u8; 32] = b"0123456789ABCDEFGHJKMNPQRSTVWXYZ";

/// A refusal; `code()` is the contract's code.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SigError {
    BadEnvelope(&'static str),
    MissingSignature,
    UnknownKey,
    BadSignature,
    BadJson(&'static str),
    BadField(&'static str),
    WrongSender,
    Replayed,
}

impl SigError {
    pub fn code(&self) -> &'static str {
        match self {
            SigError::BadEnvelope(_) => "bad_envelope",
            SigError::MissingSignature => "missing_signature",
            SigError::UnknownKey => "unknown_key",
            SigError::BadSignature => "bad_signature",
            SigError::BadJson(_) => "bad_json",
            SigError::BadField(_) => "bad_field",
            SigError::WrongSender => "wrong_sender",
            SigError::Replayed => "replayed",
        }
    }
}

// ------------------------------------------------------------------ keys

fn key_hash(pub_key: &[u8]) -> [u8; 32] {
    let mut h = Sha256::new();
    h.update(b"ed25519");
    h.update(pub_key);
    h.finalize().into()
}

/// 16 hex characters; only an index, never the trust decision.
pub fn key_id(pub_key: &[u8]) -> String {
    hex::encode(&key_hash(pub_key)[..8])
}

/// First 160 bits of the key hash, Crockford base32, 8 groups of 4.
pub fn fingerprint(pub_key: &[u8]) -> String {
    let h = key_hash(pub_key);
    let mut bits: u128 = 0;
    let mut out = String::new();
    let mut nbits = 0;
    for b in &h[..20] {
        bits = (bits << 8) | *b as u128;
        nbits += 8;
        while nbits >= 5 {
            nbits -= 5;
            out.push(CROCKFORD[((bits >> nbits) & 31) as usize] as char);
        }
    }
    out.as_bytes()
        .chunks(4)
        .map(|c| std::str::from_utf8(c).unwrap())
        .collect::<Vec<_>>()
        .join(" ")
}

/// y (low 255 bits, little endian) of the small-order points: 0, 1, p-1 and the two order-8 values.
const SMALL_ORDER_Y: [[u8; 32]; 5] = [
    [0; 32],
    {
        let mut a = [0u8; 32];
        a[0] = 1;
        a
    },
    [
        0xec, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
        0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
        0xff, 0x7f,
    ],
    [
        0xc7, 0x17, 0x6a, 0x70, 0x3d, 0x4d, 0xd8, 0x4f, 0xba, 0x3c, 0x0b, 0x76, 0x0d, 0x10, 0x67,
        0x0f, 0x2a, 0x20, 0x53, 0xfa, 0x2c, 0x39, 0xcc, 0xc6, 0x4e, 0xc7, 0xfd, 0x77, 0x92, 0xac,
        0x03, 0x7a,
    ],
    [
        0x26, 0xe8, 0x95, 0x8f, 0xc2, 0xb2, 0x27, 0xb0, 0x45, 0xc3, 0xf4, 0x89, 0xf2, 0xef, 0x98,
        0xf0, 0xd5, 0xdf, 0xac, 0x05, 0xd3, 0xc6, 0x33, 0x39, 0xb1, 0x38, 0x02, 0x88, 0x6d, 0x53,
        0xfc, 0x05,
    ],
];

/// The same key rule as the workspace and the phone: 32 bytes, canonical y (< p), not a small-order point.
pub fn public_key_ok(pub_key: &[u8]) -> bool {
    let Ok(k) = <[u8; 32]>::try_from(pub_key) else {
        return false;
    };
    let mut y = k;
    y[31] &= 0x7f;
    // y < p = 2^255 - 19: compare little-endian against p
    let mut p = [0xffu8; 32];
    p[0] = 0xed;
    p[31] = 0x7f;
    let mut lt = false;
    for i in (0..32).rev() {
        if y[i] != p[i] {
            lt = y[i] < p[i];
            break;
        }
    }
    lt && !SMALL_ORDER_Y.contains(&y)
}

/// Registration (relay only): the key rule above, a point on the curve, and no torsion part.
pub fn registration_key_ok(pub_key: &[u8]) -> bool {
    if !public_key_ok(pub_key) {
        return false;
    }
    let Ok(vk) = VerifyingKey::from_bytes(pub_key.try_into().unwrap()) else {
        return false;
    };
    !vk.is_weak() && vk.to_edwards().is_torsion_free()
}

pub fn verify_raw(pub_key: &[u8], data: &[u8], sig: &[u8]) -> bool {
    if !public_key_ok(pub_key) || sig.len() != 64 {
        return false;
    }
    let Ok(vk) = VerifyingKey::from_bytes(pub_key.try_into().unwrap()) else {
        return false;
    };
    let s = Signature::from_bytes(sig.try_into().unwrap());
    vk.verify_strict(data, &s).is_ok()
}

pub fn signature_input(purpose: &str, signed: &[u8]) -> Vec<u8> {
    assert!(PURPOSES.contains(&purpose), "unknown purpose");
    let mut v = Vec::with_capacity(SIG_TAG.len() + purpose.len() + 2 + signed.len());
    v.extend_from_slice(SIG_TAG);
    v.push(0);
    v.extend_from_slice(purpose.as_bytes());
    v.push(0);
    v.extend_from_slice(signed);
    v
}

// ------------------------------------------------------------------ base64url, strict

pub fn b64url_decode_strict(s: &str) -> Option<Vec<u8>> {
    if !s
        .bytes()
        .all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_')
        || s.len() % 4 == 1
    {
        return None;
    }
    let raw = URL_SAFE_NO_PAD.decode(s).ok()?;
    (URL_SAFE_NO_PAD.encode(&raw) == s).then_some(raw)
}

// ------------------------------------------------------------------ strict JSON

struct Reader<'a> {
    s: &'a [u8],
    t: &'a str,
    i: usize,
}

type R<T> = Result<T, &'static str>;

impl<'a> Reader<'a> {
    fn ws(&mut self) {
        while self.i < self.s.len() && matches!(self.s[self.i], b' ' | b'\t' | b'\n' | b'\r') {
            self.i += 1;
        }
    }
    fn peek(&self) -> Option<u8> {
        self.s.get(self.i).copied()
    }
    fn value(&mut self, depth: usize) -> R<Value> {
        self.ws();
        match self.peek().ok_or("end of text")? {
            b'{' => self.obj(depth + 1),
            b'[' => self.arr(depth + 1),
            b'"' => Ok(Value::String(self.string()?)),
            b'-' | b'0'..=b'9' => self.number(),
            _ => {
                for (w, v) in [
                    ("true", Value::Bool(true)),
                    ("false", Value::Bool(false)),
                    ("null", Value::Null),
                ] {
                    if self.s[self.i..].starts_with(w.as_bytes()) {
                        self.i += w.len();
                        return Ok(v);
                    }
                }
                Err("unexpected character")
            }
        }
    }
    fn obj(&mut self, depth: usize) -> R<Value> {
        if depth > MAX_DEPTH {
            return Err("too deep");
        }
        self.i += 1;
        let mut out = Map::new();
        let mut seen_keys = std::collections::HashSet::new();
        self.ws();
        if self.peek() == Some(b'}') {
            self.i += 1;
            return Ok(Value::Object(out));
        }
        loop {
            self.ws();
            if self.peek() != Some(b'"') {
                return Err("key expected");
            }
            let k = self.string()?;
            // keys that are the same text in another Unicode spelling count as the same key (all three languages)
            if !seen_keys.insert(k.nfc().collect::<String>()) {
                return Err("duplicate key");
            }
            self.ws();
            if self.peek() != Some(b':') {
                return Err("colon expected");
            }
            self.i += 1;
            let v = self.value(depth)?;
            out.insert(k, v);
            self.ws();
            match self.peek() {
                Some(b',') => self.i += 1,
                Some(b'}') => {
                    self.i += 1;
                    return Ok(Value::Object(out));
                }
                _ => return Err("comma or } expected"),
            }
        }
    }
    fn arr(&mut self, depth: usize) -> R<Value> {
        if depth > MAX_DEPTH {
            return Err("too deep");
        }
        self.i += 1;
        let mut out = Vec::new();
        self.ws();
        if self.peek() == Some(b']') {
            self.i += 1;
            return Ok(Value::Array(out));
        }
        loop {
            out.push(self.value(depth)?);
            self.ws();
            match self.peek() {
                Some(b',') => self.i += 1,
                Some(b']') => {
                    self.i += 1;
                    return Ok(Value::Array(out));
                }
                _ => return Err("comma or ] expected"),
            }
        }
    }
    fn hex4(&mut self) -> R<u32> {
        let h = self.s.get(self.i..self.i + 4).ok_or("bad \\u escape")?;
        let t = std::str::from_utf8(h).map_err(|_| "bad \\u escape")?;
        if !t.bytes().all(|c| c.is_ascii_hexdigit()) {
            return Err("bad \\u escape");
        }
        self.i += 4;
        Ok(u32::from_str_radix(t, 16).unwrap())
    }
    fn string(&mut self) -> R<String> {
        self.i += 1;
        let mut out = String::new();
        loop {
            let c = self.peek().ok_or("unterminated string")?;
            match c {
                b'"' => {
                    self.i += 1;
                    return Ok(out);
                }
                b'\\' => {
                    self.i += 1;
                    let e = self.peek().ok_or("bad escape")?;
                    self.i += 1;
                    match e {
                        b'"' => out.push('"'),
                        b'\\' => out.push('\\'),
                        b'/' => out.push('/'),
                        b'b' => out.push('\u{8}'),
                        b'f' => out.push('\u{c}'),
                        b'n' => out.push('\n'),
                        b'r' => out.push('\r'),
                        b't' => out.push('\t'),
                        b'u' => {
                            let mut cp = self.hex4()?;
                            if (0xD800..=0xDBFF).contains(&cp) {
                                if !self.s[self.i..].starts_with(b"\\u") {
                                    return Err("lone surrogate");
                                }
                                self.i += 2;
                                let lo = self.hex4()?;
                                if !(0xDC00..=0xDFFF).contains(&lo) {
                                    return Err("lone surrogate");
                                }
                                cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                            } else if (0xDC00..=0xDFFF).contains(&cp) {
                                return Err("lone surrogate");
                            }
                            out.push(char::from_u32(cp).ok_or("bad code point")?);
                        }
                        _ => return Err("bad escape"),
                    }
                }
                0x00..=0x1f => return Err("control character in string"),
                _ => {
                    // the whole input is valid UTF-8 already; copy one character
                    let ch = self.t[self.i..].chars().next().ok_or("bad text")?;
                    out.push(ch);
                    self.i += ch.len_utf8();
                }
            }
        }
    }
    fn number(&mut self) -> R<Value> {
        let start = self.i;
        if self.peek() == Some(b'-') {
            self.i += 1;
        }
        match self.peek() {
            Some(b'0') => self.i += 1,
            Some(b'1'..=b'9') => {
                while matches!(self.peek(), Some(b'0'..=b'9')) {
                    self.i += 1;
                }
            }
            _ => return Err("bad number"),
        }
        if matches!(self.peek(), Some(b'.' | b'e' | b'E')) {
            return Err("only integers");
        }
        let t = std::str::from_utf8(&self.s[start..self.i]).unwrap();
        if t == "-0" {
            return Err("-0");
        }
        if t.trim_start_matches('-').len() > 16 {
            return Err("integer too large");
        }
        let n: i64 = t.parse().map_err(|_| "bad number")?;
        if n.abs() > MAX_SAFE_INT {
            return Err("integer too large");
        }
        Ok(Value::Number(Number::from(n)))
    }
}

/// The signed bytes as one JSON object, read strictly (same rules as workspace/src/orch/msgsig.py).
pub fn read_strict_json(data: &[u8]) -> R<Map<String, Value>> {
    if data.len() > MAX_SIGNED_BYTES {
        return Err("too large");
    }
    if data.first() != Some(&b'{') || data.last() != Some(&b'}') {
        return Err("must be one object with nothing around it");
    }
    let t = std::str::from_utf8(data).map_err(|_| "invalid UTF-8")?;
    let mut r = Reader { s: data, t, i: 0 };
    let v = r.value(0)?;
    if r.i != data.len() {
        return Err("trailing bytes");
    }
    match v {
        Value::Object(m) => Ok(m),
        _ => Err("not an object"),
    }
}

// ------------------------------------------------------------------ fields

fn re_id(s: &str, prefix: &str, min: usize, max: usize, lower_hex_only: bool) -> bool {
    let Some(rest) = s.strip_prefix(prefix) else {
        return false;
    };
    (min..=max).contains(&rest.len())
        && rest.bytes().all(|c| {
            if lower_hex_only {
                c.is_ascii_digit() || (b'a'..=b'f').contains(&c)
            } else {
                c.is_ascii_digit() || c.is_ascii_lowercase()
            }
        })
}
fn is_ws(s: &str) -> bool {
    re_id(s, "ws_", 10, 10, false)
}
fn is_ph(s: &str) -> bool {
    re_id(s, "ph_", 10, 10, false)
}
fn is_msg_id(s: &str) -> bool {
    re_id(s, "m_", 16, 16, false)
}
fn is_hex64(s: &str) -> bool {
    re_id(s, "", 64, 64, true)
}
fn is_int(v: &Value) -> Option<i64> {
    v.as_i64()
}
fn str_of<'a>(m: &'a Map<String, Value>, k: &str) -> Option<&'a str> {
    m.get(k).and_then(|v| v.as_str())
}

const TOP_FIELDS: [&str; 14] = [
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
];

/// Field rules of a `msg` signed object.
pub fn check_fields(m: &Map<String, Value>) -> Result<(), SigError> {
    use SigError::BadField as B;
    if m.keys().any(|k| !TOP_FIELDS.contains(&k.as_str())) {
        return Err(B("unknown field"));
    }
    for k in [
        "v",
        "id",
        "from",
        "to",
        "type",
        "created_ms",
        "origin",
        "body",
    ] {
        if !m.contains_key(k) {
            return Err(B("missing field"));
        }
    }
    if is_int(&m["v"]) != Some(1) {
        return Err(B("v"));
    }
    if !str_of(m, "id").is_some_and(is_msg_id) {
        return Err(B("id"));
    }
    let from = str_of(m, "from")
        .filter(|f| is_ws(f) || is_ph(f))
        .ok_or(B("from"))?;
    match &m["to"] {
        Value::String(to) => {
            if !(is_ws(to) || is_ph(to) || to == "phones") {
                return Err(B("to"));
            }
            if to == from {
                return Err(B("to equals from"));
            }
            if (to == "phones" || is_ph(to)) && !is_ws(from) {
                return Err(B("only a workspace sends to phones"));
            }
        }
        Value::Object(g) => {
            if g.len() != 3
                || !["group", "host", "members_v"]
                    .iter()
                    .all(|k| g.contains_key(*k))
            {
                return Err(B("to group fields"));
            }
            if !g["group"]
                .as_str()
                .is_some_and(|s| re_id(s, "grp_t_", 6, 16, false))
            {
                return Err(B("to.group"));
            }
            if !g["host"].as_str().is_some_and(is_ws) {
                return Err(B("to.host"));
            }
            if !is_int(&g["members_v"]).is_some_and(|n| n >= 0) {
                return Err(B("to.members_v"));
            }
            if !is_ws(from) {
                return Err(B("only a workspace sends to a group"));
            }
        }
        _ => return Err(B("to")),
    }
    if is_ph(from) && !m["to"].as_str().is_some_and(is_ws) {
        return Err(B("a phone sends only to a workspace"));
    }
    let typ = str_of(m, "type")
        .filter(|t| TYPES.contains(t))
        .ok_or(B("type"))?;
    if m["to"].is_object() && !GROUP_TYPES.contains(&typ) {
        return Err(B("a group message is only text, file or question"));
    }
    let created = is_int(&m["created_ms"])
        .filter(|n| *n > 0)
        .ok_or(B("created_ms"))?;
    let origin = str_of(m, "origin")
        .filter(|o| *o == "person" || *o == "helper")
        .ok_or(B("origin"))?;
    if is_ph(from) && origin != "person" {
        return Err(B("a phone signs only as a person"));
    }
    if !m["body"].is_object() {
        return Err(B("body"));
    }
    if m.contains_key("ticket")
        && !str_of(m, "ticket").is_some_and(|s| re_id(s, "t_", 6, 16, false))
    {
        return Err(B("ticket"));
    }
    if m.contains_key("reply_to") && !str_of(m, "reply_to").is_some_and(is_msg_id) {
        return Err(B("reply_to"));
    }
    if m.contains_key("question_id")
        && !str_of(m, "question_id").is_some_and(|s| {
            (1..=64).contains(&s.len())
                && s.bytes()
                    .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
        })
    {
        return Err(B("question_id"));
    }
    if m.contains_key("question_sha256") && !str_of(m, "question_sha256").is_some_and(is_hex64) {
        return Err(B("question_sha256"));
    }
    if typ == "answer" {
        if !["reply_to", "question_id", "question_sha256"]
            .iter()
            .all(|k| m.contains_key(*k))
        {
            return Err(B("answer fields"));
        }
    } else if m.contains_key("question_sha256") || m.contains_key("question_id") {
        return Err(B("question_id and question_sha256 only on answer"));
    }
    if typ == "allow" && !m.contains_key("reply_to") {
        return Err(B("allow needs reply_to"));
    }
    if EXPIRING.contains(&typ) {
        let e = m
            .get("expires_ms")
            .and_then(is_int)
            .ok_or(B("expires_ms"))?;
        if !(created < e && e <= created + MAX_EXPIRY_MS) {
            return Err(B("expires_ms out of range"));
        }
    } else if m.contains_key("expires_ms") {
        return Err(B("expires_ms only on allow, delegate, start"));
    }
    if let Some(files) = m.get("files") {
        if !FILE_TYPES.contains(&typ) {
            return Err(B("files not allowed on this type"));
        }
        let arr = files
            .as_array()
            .filter(|a| (1..=MAX_FILES).contains(&a.len()))
            .ok_or(B("files"))?;
        let mut seen = std::collections::HashSet::new();
        for f in arr {
            let f = f.as_object().ok_or(B("file fields"))?;
            if f.len() != 3
                || !["blob_id", "size", "sha256"]
                    .iter()
                    .all(|k| f.contains_key(*k))
            {
                return Err(B("file fields"));
            }
            let blob = f["blob_id"]
                .as_str()
                .filter(|s| re_id(s, "b_", 16, 16, false))
                .ok_or(B("file blob_id"))?;
            if !seen.insert(blob) {
                return Err(B("file blob_id"));
            }
            if !is_int(&f["size"]).is_some_and(|n| (0..=MAX_FILE_SIZE).contains(&n)) {
                return Err(B("file size"));
            }
            if !f["sha256"].as_str().is_some_and(is_hex64) {
                return Err(B("file sha256"));
            }
        }
    } else if typ == "file" {
        return Err(B("file needs files"));
    }
    Ok(())
}

// ------------------------------------------------------------------ envelope, verify, relay gate

pub struct Envelope {
    pub key_id: String,
    pub signed: Vec<u8>,
    pub sig: Vec<u8>,
}

pub fn read_envelope(env: &Value) -> Result<Envelope, SigError> {
    use SigError::BadEnvelope as E;
    let e = match env {
        Value::Null => return Err(SigError::MissingSignature),
        Value::Object(o) => o,
        _ => return Err(E("not an object")),
    };
    if e.keys()
        .any(|k| !["sig_v", "key_id", "signed", "sig", "relay_meta"].contains(&k.as_str()))
    {
        return Err(E("unknown field"));
    }
    if e.get("sig_v").and_then(|v| v.as_i64()) != Some(1) {
        return Err(E("sig_v"));
    }
    if e.get("relay_meta").is_some_and(|v| !v.is_object()) {
        return Err(E("relay_meta"));
    }
    match e.get("sig") {
        None | Some(Value::Null) => return Err(SigError::MissingSignature),
        Some(Value::String(s)) if s.is_empty() => return Err(SigError::MissingSignature),
        _ => {}
    }
    let kid = e
        .get("key_id")
        .and_then(|v| v.as_str())
        .filter(|s| {
            s.len() == 16
                && s.bytes()
                    .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
        })
        .ok_or(E("key_id"))?;
    let signed = e
        .get("signed")
        .and_then(|v| v.as_str())
        .and_then(b64url_decode_strict)
        .ok_or(E("signed"))?;
    let sig = e
        .get("sig")
        .and_then(|v| v.as_str())
        .and_then(b64url_decode_strict)
        .ok_or(E("sig"))?;
    if !(2..=MAX_SIGNED_BYTES).contains(&signed.len()) {
        return Err(E("signed size"));
    }
    if sig.len() != 64 {
        return Err(E("sig size"));
    }
    Ok(Envelope {
        key_id: kid.to_string(),
        signed,
        sig,
    })
}

/// What verify returns: the owner whose key verified, the signed object and the exact signed bytes.
pub struct Verified {
    pub owner: String,
    pub msg: Map<String, Value>,
    pub signed: Vec<u8>,
}

/// Envelope + trusted keys (owner, raw key) -> the verified message. Checks, in this order: envelope, key,
/// signature, strict JSON, fields, signed `from` == key owner.
pub fn verify(
    env: &Value,
    purpose: &str,
    keys: &[(String, [u8; 32])],
) -> Result<Verified, SigError> {
    let e = read_envelope(env)?;
    let cands: Vec<_> = keys.iter().filter(|(_, k)| key_id(k) == e.key_id).collect();
    if cands.is_empty() {
        return Err(SigError::UnknownKey);
    }
    let data = signature_input(purpose, &e.signed);
    // every owner of a key that verified; the signed `from` must be one of them, so the order of the keys
    // never changes the answer
    let owners: std::collections::BTreeSet<&String> = cands
        .iter()
        .filter(|(_, k)| verify_raw(k, &data, &e.sig))
        .map(|(o, _)| o)
        .collect();
    let first = owners
        .iter()
        .next()
        .ok_or(SigError::BadSignature)?
        .to_string();
    let m = read_strict_json(&e.signed).map_err(SigError::BadJson)?;
    let mut owner = first;
    if purpose == "msg" {
        check_fields(&m)?;
        let from = m["from"].as_str().unwrap_or_default().to_string();
        if !owners.contains(&from) {
            return Err(SigError::WrongSender);
        }
        owner = from;
    }
    Ok(Verified {
        owner,
        msg: m,
        signed: e.signed,
    })
}

#[derive(Debug, PartialEq, Eq)]
pub enum RelayOutcome {
    New,
    Duplicate,
}

/// The relay's gate for a `msg` from the authenticated `caller`. `seen(id)` returns the sha256 hex of the signed
/// bytes already stored under that message id (any sender), or None. Same bytes -> Duplicate (200 duplicate),
/// other bytes -> Replayed (409 conflict).
pub fn relay_check(
    env: &Value,
    caller: &str,
    registered: &[[u8; 32]],
    seen: impl FnOnce(&str) -> Option<String>,
) -> Result<(RelayOutcome, Verified), SigError> {
    let keys: Vec<_> = registered
        .iter()
        .map(|k| (caller.to_string(), *k))
        .collect();
    let v = verify(env, "msg", &keys)?;
    let h = hex::encode(Sha256::digest(&v.signed));
    match seen(v.msg["id"].as_str().unwrap()) {
        None => Ok((RelayOutcome::New, v)),
        Some(old) if old == h => Ok((RelayOutcome::Duplicate, v)),
        Some(_) => Err(SigError::Replayed),
    }
}
