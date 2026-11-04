use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use rand::{rngs::OsRng, Rng, RngCore};
use sha2::{Digest, Sha256};
use subtle::ConstantTimeEq;

pub fn now() -> String {
    chrono::Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string()
}

pub fn in_days(days: i64) -> String {
    (chrono::Utc::now() + chrono::Duration::days(days))
        .format("%Y-%m-%dT%H:%M:%SZ")
        .to_string()
}

/// lowercase letters and digits
pub fn rand_id(n: usize) -> String {
    const A: &[u8] = b"abcdefghijklmnopqrstuvwxyz0123456789";
    (0..n)
        .map(|_| A[OsRng.gen_range(0..A.len())] as char)
        .collect()
}

/// `<prefix>` + base64url of `bytes` random bytes (32 bytes = 43 chars, 16 bytes = 22 chars)
pub fn rand_token(prefix: &str, bytes: usize) -> String {
    let mut b = vec![0u8; bytes];
    OsRng.fill_bytes(&mut b);
    format!("{prefix}{}", URL_SAFE_NO_PAD.encode(b))
}

pub fn sha256_hex(s: &str) -> String {
    let d = Sha256::digest(s.as_bytes());
    d.iter().map(|b| format!("{b:02x}")).collect()
}

pub fn ct_eq(a: &str, b: &str) -> bool {
    a.as_bytes().ct_eq(b.as_bytes()).into()
}

pub fn valid_app_name(n: &str) -> bool {
    (2..=40).contains(&n.len())
        && n.chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
}

pub fn esc(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

/// last `n` bytes of a string, on a char boundary
pub fn tail(s: &str, n: usize) -> String {
    if s.len() <= n {
        return s.to_string();
    }
    let mut i = s.len() - n;
    while !s.is_char_boundary(i) {
        i += 1;
    }
    s[i..].to_string()
}
