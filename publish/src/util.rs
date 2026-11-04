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

/// Allowed in a description: letters, marks, numbers, punctuation, symbols and ordinary spaces
/// (Unicode categories L, M, N, P, S, Zs). Control, format (bidi, zero-width), line and paragraph separators are not.
fn good_char(c: char) -> bool {
    use unicode_general_category::GeneralCategory as G;
    !matches!(
        unicode_general_category::get_general_category(c),
        G::Control
            | G::Format
            | G::Surrogate
            | G::PrivateUse
            | G::Unassigned
            | G::LineSeparator
            | G::ParagraphSeparator
    ) && !default_ignorable(c)
}

/// Default_Ignorable_Code_Point (invisible: variation selectors, fillers, ...) plus the braille blank.
fn default_ignorable(c: char) -> bool {
    matches!(c as u32,
        0x00AD | 0x034F | 0x061C | 0x115F..=0x1160 | 0x17B4..=0x17B5 | 0x180B..=0x180F
        | 0x200B..=0x200F | 0x202A..=0x202E | 0x2060..=0x206F | 0x2800 | 0x3164
        | 0xFE00..=0xFE0F | 0xFEFF | 0xFFA0 | 0xFFF0..=0xFFF8 | 0x1BCA0..=0x1BCA3
        | 0x1D173..=0x1D17A | 0xE0000..=0xE0FFF)
}

/// More than 2 combining marks in a row on one base character ("zalgo").
fn too_many_marks(d: &str) -> bool {
    use unicode_general_category::GeneralCategory as G;
    let mut run = 0;
    for c in d.chars() {
        if matches!(
            unicode_general_category::get_general_category(c),
            G::NonspacingMark | G::SpacingMark | G::EnclosingMark
        ) {
            run += 1;
            if run > 2 {
                return true;
            }
        } else {
            run = 0;
        }
    }
    false
}

/// Plain one-line text, up to 280 characters (own or admin-written).
pub fn valid_description(d: &str) -> Result<String, &'static str> {
    use unicode_normalization::UnicodeNormalization;
    let d: String = d.trim().nfc().collect();
    if d.chars().count() > 280 {
        return Err("The description is at most 280 characters.");
    }
    if !d.chars().all(good_char) {
        return Err("The description must be plain text on one line (letters, numbers, punctuation and symbols only).");
    }
    if too_many_marks(&d) {
        return Err("The description has too many stacked accents or marks.");
    }
    Ok(d)
}

/// At most 8 tags, each 1-24 characters of lowercase letters, digits and hyphens.
pub fn valid_tags(t: &[String]) -> Result<Vec<String>, &'static str> {
    if t.len() > 8 {
        return Err("Use at most 8 tags.");
    }
    t.iter()
        .map(|s| s.trim())
        .map(|s| {
            let ok = (1..=24).contains(&s.len())
                && s.bytes()
                    .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-');
            if ok {
                Ok(s.to_string())
            } else {
                Err("Each tag is 1 to 24 characters: lowercase letters, digits and hyphens.")
            }
        })
        .collect()
}
