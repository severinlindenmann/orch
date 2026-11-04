use base64::engine::general_purpose::URL_SAFE_NO_PAD as B64URL;
use base64::Engine;
use rand::{Rng, RngCore};
use sha2::{Digest, Sha256};
use subtle::ConstantTimeEq;
use time::format_description::well_known::Rfc3339;
use time::OffsetDateTime;

pub fn now() -> i64 {
    OffsetDateTime::now_utc().unix_timestamp()
}

pub fn fmt_time(t: i64) -> String {
    OffsetDateTime::from_unix_timestamp(t)
        .unwrap_or(OffsetDateTime::UNIX_EPOCH)
        .format(&Rfc3339)
        .unwrap_or_default()
}

/// `prefix` + `n` random lowercase letters/digits (ids).
pub fn rand_id(prefix: &str, n: usize) -> String {
    const CH: &[u8] = b"abcdefghijklmnopqrstuvwxyz0123456789";
    let mut rng = rand::rngs::OsRng;
    let s: String = (0..n)
        .map(|_| CH[rng.gen_range(0..CH.len())] as char)
        .collect();
    format!("{prefix}{s}")
}

/// `prefix` + base64url of `bytes` random bytes (tokens: 32 -> 43 chars, 16 -> 22 chars).
pub fn rand_token(prefix: &str, bytes: usize) -> String {
    let mut b = vec![0u8; bytes];
    rand::rngs::OsRng.fill_bytes(&mut b);
    format!("{prefix}{}", B64URL.encode(b))
}

pub fn sha256_hex(data: &[u8]) -> String {
    hex::encode(Sha256::digest(data))
}

pub fn token_hash(token: &str) -> String {
    sha256_hex(token.as_bytes())
}

pub fn ct_eq(a: &str, b: &str) -> bool {
    a.as_bytes().ct_eq(b.as_bytes()).into()
}

pub fn encode_cursor(seq: i64) -> String {
    B64URL.encode(seq.to_string())
}

pub fn decode_cursor(c: &str) -> Option<i64> {
    let b = B64URL.decode(c).ok()?;
    String::from_utf8(b).ok()?.parse().ok()
}

pub fn valid_id(s: &str, prefix: &str, n: usize) -> bool {
    s.len() == prefix.len() + n
        && s.starts_with(prefix)
        && s[prefix.len()..]
            .bytes()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit())
}
