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

/// Find the `<tag` start (ASCII case-insensitive) where the tag name ends right after it.
fn find_tag(h: &[u8], tag: &str) -> Option<usize> {
    let t = tag.as_bytes();
    let mut i = 0;
    while i + 1 + t.len() < h.len() {
        if h[i] == b'<'
            && h[i + 1..i + 1 + t.len()].eq_ignore_ascii_case(t)
            && matches!(
                h[i + 1 + t.len()],
                b'>' | b'/' | b' ' | b'\t' | b'\n' | b'\r'
            )
        {
            return Some(i);
        }
        i += 1;
    }
    None
}

/// End (exclusive) of the tag that starts at `start`, respecting quoted attribute values.
fn tag_end(h: &[u8], start: usize) -> Option<usize> {
    let mut q = 0u8;
    for (i, &c) in h.iter().enumerate().skip(start) {
        match (q, c) {
            (0, b'"' | b'\'') => q = c,
            (0, b'>') => return Some(i + 1),
            (x, y) if x != 0 && x == y => q = 0,
            _ => {}
        }
    }
    None
}

/// Serve-time default for hosted app pages: add `<title>` (the app name, escaped) when the page has
/// none and `lang="en"` on `<html>` when it has no lang. Pages that already have them are untouched.
pub fn with_default_head(bytes: &[u8], app_name: &str) -> Vec<u8> {
    let mut out = bytes.to_vec();
    // lang first (it sits before the head, so offsets of the title insert stay valid after it)
    if let Some(h) = find_tag(&out, "html") {
        if let Some(e) = tag_end(&out, h) {
            let attrs = out[h + 5..e].to_ascii_lowercase();
            let has_lang = attrs.windows(5).enumerate().any(|(i, w)| {
                w[..4] == *b"lang"
                    && (w[4] == b'=' || w[4] == b'>' || w[4].is_ascii_whitespace())
                    && (i == 0
                        || attrs[i - 1].is_ascii_whitespace()
                        || matches!(attrs[i - 1], b'"' | b'\'' | b'/'))
            });
            if !has_lang {
                let at = h + 5;
                out.splice(at..at, b" lang=\"en\"".iter().copied());
            }
        }
    }
    if find_tag(&out, "title").is_none() {
        let t = format!("<title>{}</title>", esc(app_name));
        let at = [("head", true), ("html", true)]
            .iter()
            .find_map(|(tag, _)| find_tag(&out, tag).and_then(|s| tag_end(&out, s)))
            .or_else(|| {
                // fragment page: after a leading doctype if any, else at the very start
                let bom = if out.starts_with(b"\xEF\xBB\xBF") {
                    3
                } else {
                    0
                };
                let lead = bom + out[bom..].iter().position(|c| !c.is_ascii_whitespace())?;
                if out[lead..].len() >= 9 && out[lead..lead + 9].eq_ignore_ascii_case(b"<!doctype")
                {
                    tag_end(&out, lead)
                } else {
                    None
                }
            })
            .unwrap_or(if out.starts_with(b"\xEF\xBB\xBF") {
                3
            } else {
                0
            });
        out.splice(at..at, t.bytes());
    }
    out
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

#[cfg(test)]
mod head_tests {
    use super::with_default_head as f;
    fn s(b: &str) -> String {
        String::from_utf8(f(b.as_bytes(), "my-app")).unwrap()
    }
    #[test]
    fn adds_both() {
        assert_eq!(
            s("<!doctype html><html><head><meta charset=utf-8></head><body>x</body></html>"),
            "<!doctype html><html lang=\"en\"><head><title>my-app</title><meta charset=utf-8></head><body>x</body></html>"
        );
    }
    #[test]
    fn untouched_when_present() {
        let p = "<html LANG='de'><HEAD><TITLE>Mine</TITLE></HEAD></html>";
        assert_eq!(s(p), p);
        let p = "<html lang=\"fr\" class=a><head><title >T</title></head></html>";
        assert_eq!(s(p), p);
    }
    #[test]
    fn lang_lookalike_attr_does_not_count() {
        assert!(s("<html data-lang=\"x\"><head></head></html>").contains(" lang=\"en\" data-lang"));
        assert!(
            s("<html title=\"a>lang=b\"><head></head></html>").contains("<html lang=\"en\" title")
        );
    }
    #[test]
    fn no_panic_on_trailing_tag_and_odd_lang_spacing() {
        for p in ["<html", "x<head", "<!doctype html><html", "<title"] {
            let _ = f(p.as_bytes(), "my-app");
        }
        let p = "<html lang\t=\"de\"><head><title>T</title></head></html>";
        assert_eq!(s(p), p);
        let p = "<html/lang=\"de\"><head><title>T</title></head></html>";
        assert_eq!(s(p), p);
    }
    #[test]
    fn bom_stays_first() {
        let o = f("\u{feff}<!doctype html><h1>".as_bytes(), "my-app");
        assert_eq!(
            String::from_utf8(o).unwrap(),
            "\u{feff}<!doctype html><title>my-app</title><h1>"
        );
    }
    #[test]
    fn fragments() {
        assert_eq!(s("<h1>hi</h1>"), "<title>my-app</title><h1>hi</h1>");
        assert_eq!(
            s("<!DOCTYPE html>\n<h1>hi</h1>"),
            "<!DOCTYPE html><title>my-app</title>\n<h1>hi</h1>"
        );
        assert_eq!(s(""), "<title>my-app</title>");
    }
    #[test]
    fn name_is_escaped() {
        let o = String::from_utf8(f(b"<head></head>", "a\"><script>x</script>&")).unwrap();
        assert_eq!(
            o,
            "<head><title>a&quot;&gt;&lt;script&gt;x&lt;/script&gt;&amp;</title></head>"
        );
    }
}
