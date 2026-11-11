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
        .replace('\'', "&#39;")
}

/// Ends a tag name.
fn name_delim(c: u8) -> bool {
    matches!(c, b'>' | b'/' | b' ' | b'\t' | b'\n' | b'\r' | b'\x0c')
}

/// Elements whose content is text, not markup (raw text / RCDATA).
const RAW_TEXT: [&[u8]; 9] = [
    b"script",
    b"style",
    b"textarea",
    b"title",
    b"xmp",
    b"iframe",
    b"noembed",
    b"noframes",
    b"noscript",
];

fn find_bytes(h: &[u8], pat: &[u8]) -> Option<usize> {
    h.windows(pat.len()).position(|w| w == pat)
}

/// End (exclusive) of the comment whose body starts at `b` (just after `<!--`): the first `-->` or
/// `--!>`. `<!-->` and `<!--->` close right away.
fn comment_end(h: &[u8], b: usize) -> Option<usize> {
    if h[b..].starts_with(b">") {
        return Some(b + 1);
    }
    if h[b..].starts_with(b"->") {
        return Some(b + 2);
    }
    let mut k = b;
    loop {
        let d = k + find_bytes(&h[k..], b"--")?;
        if h[d + 2..].starts_with(b">") {
            return Some(d + 3);
        }
        if h[d + 2..].starts_with(b"!>") {
            return Some(d + 4);
        }
        k = d + 1;
    }
}

/// Start (`<`) of the `</script` that ends script content starting at `i`. Follows the HTML script
/// data escaped / double-escaped states: after `<!--`, a `<script` hides the next `</script` until
/// `-->`. A script that never ends gives `None`.
fn script_end(h: &[u8], mut i: usize) -> Option<usize> {
    let script_at = |k: usize| {
        k + 6 < h.len() && h[k..k + 6].eq_ignore_ascii_case(b"script") && name_delim(h[k + 6])
    };
    // 0: script data, 1: escaped, 2: double escaped; `dashes`: run of `-` in the escaped states
    let mut st = 0u8;
    let mut dashes = 0usize;
    while i < h.len() {
        let c = h[i];
        if st == 0 {
            if h[i..].starts_with(b"<!--") {
                (st, dashes, i) = (1, 2, i + 4);
                continue;
            }
            if c == b'<' && h.get(i + 1) == Some(&b'/') && script_at(i + 2) {
                return Some(i);
            }
        } else if c == b'-' {
            dashes += 1;
            i += 1;
            continue;
        } else if c == b'>' && dashes >= 2 {
            st = 0;
        } else if c == b'<' && h.get(i + 1) == Some(&b'/') && script_at(i + 2) {
            if st == 1 {
                return Some(i);
            }
            (st, dashes, i) = (1, 0, i + 8);
            continue;
        } else if c == b'<' && st == 1 && script_at(i + 1) {
            (st, dashes, i) = (2, 0, i + 7);
            continue;
        }
        dashes = 0;
        i += 1;
    }
    None
}

/// Walk the real tags of `h` in order: comments, `<!...>`/`<?...>`, attribute values and raw-text
/// element contents are skipped. Calls `f(start, end, name, is_end_tag, self_closing)` and stops
/// when it returns true. Linear time; a truncated tag, comment or raw-text element ends the walk
/// (`None`), and so does `<plaintext>` (the rest is text).
fn scan(h: &[u8], mut f: impl FnMut(usize, usize, &[u8], bool, bool) -> bool) -> Option<()> {
    let mut i = 0;
    while let Some(p) = h[i..].iter().position(|&c| c == b'<') {
        let s = i + p;
        let rest = &h[s + 1..];
        let letter = |k: usize| rest.get(k).is_some_and(|c| c.is_ascii_alphabetic());
        if rest.starts_with(b"!--") {
            i = comment_end(h, s + 4)?;
        } else if letter(0) || (rest.first() == Some(&b'/') && letter(1)) {
            let is_end = rest[0] == b'/';
            let n0 = s + 1 + usize::from(is_end);
            let n1 = n0
                + h[n0..]
                    .iter()
                    .position(|&c| name_delim(c))
                    .unwrap_or(h.len() - n0);
            let (e, sc) = tag_close(h, s)?;
            let name = &h[n0..n1];
            if f(s, e, name, is_end, sc) {
                return Some(());
            }
            i = e;
            let is = |t: &[u8]| !is_end && name.eq_ignore_ascii_case(t);
            if is(b"plaintext") {
                return None;
            } else if is(b"script") {
                i = script_end(h, i)?;
            } else if RAW_TEXT.iter().any(|r| is(r)) {
                // content runs to the matching `</name`
                loop {
                    let p = i + find_bytes(&h[i..], b"</")?;
                    let n = p + 2 + name.len();
                    if n < h.len() && h[p + 2..n].eq_ignore_ascii_case(name) && name_delim(h[n]) {
                        i = p;
                        break;
                    }
                    i = p + 2;
                }
            }
        } else if matches!(rest.first(), Some(b'!' | b'/' | b'?')) {
            // doctype or bogus comment: up to the next `>`
            i = s + 2 + rest.iter().position(|&c| c == b'>')?;
        } else {
            i = s + 1; // a lone `<` is text
        }
    }
    Some(())
}

/// Start (`<`) of the first real `<tag ...>` start tag (ASCII case-insensitive), see `scan`.
fn find_tag(h: &[u8], tag: &str) -> Option<usize> {
    let mut at = None;
    let _ = scan(h, |s, _, name, is_end, _| {
        let hit = !is_end && name.eq_ignore_ascii_case(tag.as_bytes());
        if hit {
            at = Some(s);
        }
        hit
    });
    at
}

/// Whether the page has a real document `<title>` anywhere (browsers use the first one, even
/// after `</head>` or in `<body>`): an HTML one, not inside `<svg>`/`<math>` or `<template>`.
fn has_title(h: &[u8]) -> bool {
    let mut hidden = 0usize;
    let mut found = false;
    let _ = scan(h, |_, _, name, is_end, sc| {
        let is = |t: &[u8]| name.eq_ignore_ascii_case(t);
        if is(b"svg") || is(b"math") || is(b"template") {
            if is_end {
                hidden = hidden.saturating_sub(1);
            } else if !sc || is(b"template") {
                hidden += 1;
            }
            false
        } else {
            found = hidden == 0 && !is_end && is(b"title");
            found
        }
    });
    found
}

/// End (exclusive) of the tag that starts at `start`, see `tag_close`.
fn tag_end(h: &[u8], start: usize) -> Option<usize> {
    tag_close(h, start).map(|(e, _)| e)
}

/// End (exclusive) of the tag that starts at `start` and whether it is self-closing (`/>`), using
/// the HTML attribute states: a quote only opens a value right after `=`, and `=` at the start of
/// an attribute name is part of the name.
fn tag_close(h: &[u8], start: usize) -> Option<(usize, bool)> {
    let mut i = start + 1;
    while i < h.len() && !name_delim(h[i]) {
        i += 1;
    }
    // 0: before attribute name, 1: before value (after `=`), 2: unquoted value,
    // 3: attribute name, 4: after attribute name
    let mut st = 0u8;
    let mut slash = false;
    while i < h.len() {
        let c = h[i];
        if c == b'>' {
            return Some((i + 1, slash));
        }
        slash = c == b'/' && matches!(st, 0 | 3 | 4);
        st = match (st, c) {
            (1, b'"' | b'\'') => {
                i += 1 + h[i + 1..].iter().position(|&x| x == c)?;
                0
            }
            (_, c) if c.is_ascii_whitespace() => match st {
                3 => 4,
                2 => 0,
                s => s,
            },
            (0 | 3 | 4, b'/') => 0,
            (3 | 4, b'=') => 1,
            (0 | 4, _) => 3,
            (1, _) => 2,
            (s, _) => s,
        };
        i += 1;
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
    if !has_title(&out) {
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
    fn find_tag_skips_comments_scripts_and_attr_values() {
        assert_eq!(
            s("<!-- <html> --><html><head></head></html>"),
            "<!-- <html> --><html lang=\"en\"><head><title>my-app</title></head></html>"
        );
        assert_eq!(
            s("<!doctype html><script>x=\"<head><html>\"</script><p>hi"),
            "<!doctype html><title>my-app</title><script>x=\"<head><html>\"</script><p>hi"
        );
        assert_eq!(
            s("<div data-x=\"<head>\"></div>"),
            "<title>my-app</title><div data-x=\"<head>\"></div>"
        );
        assert_eq!(
            s("<html><style>/* <head> */</style><head></head></html>"),
            "<html lang=\"en\"><style>/* <head> */</style><head><title>my-app</title></head></html>"
        );
        assert_eq!(
            s("<!--><head>--><HEAD></HEAD>"),
            "<!--><head><title>my-app</title>--><HEAD></HEAD>"
        );
    }
    #[test]
    fn find_tag_only_real_head_title_counts() {
        for p in [
            "<html lang=en><head></head><body><svg><title>icon</title></svg></body></html>",
            "<html lang=en><head><script>x='<title>'</script></head></html>",
            "<html lang=en><head><!-- <title>T</title> --></head></html>",
            "<html lang=en><head><svg><title>i</title></svg></head></html>",
            "<html lang=en><head><meta content=\"<title>\"></head></html>",
        ] {
            assert_eq!(s(p).matches("<title>my-app</title>").count(), 1, "{p}");
            assert!(
                s(p).starts_with("<html lang=en><head><title>my-app</title>"),
                "{p}"
            );
        }
        // a real title after an svg in head still counts
        let p = "<html lang=en><head><svg/><title>T</title></head></html>";
        assert_eq!(s(p), p);
    }
    #[test]
    fn find_tag_stray_quote_in_html_tag() {
        assert_eq!(
            s("<html a\"b><body title=\"x>y\">hi</body></html>"),
            "<html lang=\"en\" a\"b><title>my-app</title><body title=\"x>y\">hi</body></html>"
        );
        assert_eq!(
            s("<html class=a'b><head></head></html>"),
            "<html lang=\"en\" class=a'b><head><title>my-app</title></head></html>"
        );
        // quoted values still hide a `>`
        assert_eq!(
            s("<html data-x = 'a>b'><head></head></html>"),
            "<html lang=\"en\" data-x = 'a>b'><head><title>my-app</title></head></html>"
        );
    }
    #[test]
    fn find_tag_normal_page() {
        let p = "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n<link rel=stylesheet href=a.css>\n<title>App</title>\n<script src=x.js></script>\n</head>\n<body><h1>Hi</h1></body>\n</html>\n";
        assert_eq!(s(p), p);
        assert_eq!(
            s("<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n</head>\n<body></body>\n</html>"),
            "<!DOCTYPE html>\n<html lang=\"en\">\n<head><title>my-app</title>\n<meta charset=\"utf-8\">\n</head>\n<body></body>\n</html>"
        );
    }
    #[test]
    fn find_tag_truncated_input_no_panic() {
        for p in [
            "<",
            "</",
            "<!",
            "<!-",
            "<!--",
            "<!-- <head>",
            "<?x",
            "<script>",
            "<script><head>",
            "<script></scr",
            "<html a=\"",
            "<html a=\"b><head>",
            "<html a=",
            "<x =",
            "<svg",
            "<head><title",
            "<html><head></he",
            "\u{feff}<",
            "<a/",
        ] {
            let o = String::from_utf8(f(p.as_bytes(), "my-app")).unwrap();
            assert_eq!(o.matches("<title>my-app</title>").count(), 1, "{p}");
        }
        // a complete `<title>` start tag counts even if the element is cut off (browsers use it)
        let p = "<html lang=en><head><title>x</tit";
        assert_eq!(s(p), p);
    }
    #[test]
    fn find_tag_title_outside_head_counts() {
        for p in [
            "<head></head><title>T</title>",
            "<body><title>T</title>",
            "<html lang=en><head><meta charset=utf-8></head><title>Mine</title><body>x</body></html>",
            "<html lang=en><body><title>Mine</title><p>x</p></body></html>",
        ] {
            assert_eq!(s(p), p);
        }
        assert_eq!(
            s("<html><body><title>Mine</title></body></html>"),
            "<html lang=\"en\"><body><title>Mine</title></body></html>"
        );
    }
    #[test]
    fn find_tag_script_escaped_states() {
        // `<!--<script>` keeps the first `</script>` inside the script: `<head>`/`<html>` are JS text
        let p = "<script>x=`<!--<script></script><head>`</script>";
        assert_eq!(s(p), format!("<title>my-app</title>{p}"));
        let p = "<script>x=`<!--<script></script><html>`</script>";
        assert_eq!(s(p), format!("<title>my-app</title>{p}"));
        let p = "<html lang=en><head><script><!--<script></script><title>x</title></script></head>";
        assert!(s(p).starts_with("<html lang=en><head><title>my-app</title><script>"));
        // never-ending script: nothing inside it counts, the insert stays before it
        let p = "<html lang=en><head><script><!--<script></script><title>x</title>";
        assert!(s(p).starts_with("<html lang=en><head><title>my-app</title><script>"));
        // `-->` leaves the escaped states, so a later `</script>` ends the script as usual
        assert_eq!(
            s("<script><!-- x --></script><head></head>"),
            "<script><!-- x --></script><head><title>my-app</title></head>"
        );
        assert_eq!(
            s("<script><!--<script>a</script>--></script><head></head>"),
            "<script><!--<script>a</script>--></script><head><title>my-app</title></head>"
        );
        assert_eq!(
            s("<script><!--></script><head></head>"),
            "<script><!--></script><head><title>my-app</title></head>"
        );
        // escaped (not double-escaped) state still ends at `</script>`
        assert_eq!(
            s("<script><!-- a</script><head></head>"),
            "<script><!-- a</script><head><title>my-app</title></head>"
        );
    }
    #[test]
    fn find_tag_equals_starting_attr_name() {
        // a lone `=` starts the name `="x`, so the first `>` ends the tag
        assert_eq!(s("<head =\"x>\">"), "<head =\"x><title>my-app</title>\">");
        assert_eq!(s("<head ==\"x>\">"), "<head ==\"x>\"><title>my-app</title>");
        assert_eq!(s("<head ==' x>'>"), "<head ==' x>'><title>my-app</title>");
        // the fake title in the value does not count
        assert_eq!(
            s("<head ==\"<title>x</title>\">"),
            "<head ==\"<title>x</title>\"><title>my-app</title>"
        );
        let o = String::from_utf8(f(b"<head></head>", "a' b")).unwrap();
        assert_eq!(o, "<head><title>a&#39; b</title></head>");
    }
    #[test]
    fn find_tag_other_parser_divergences() {
        assert_eq!(
            s("<plaintext><head>"),
            "<title>my-app</title><plaintext><head>"
        );
        let p = "<!-- x --!><title>T</title>";
        assert_eq!(s(p), p);
        assert_eq!(
            s("<!-- x --!><html><head></head>"),
            "<!-- x --!><html lang=\"en\"><head><title>my-app</title></head>"
        );
        assert_eq!(
            s("<html lang=en><head><svg a=/><title>i</title></svg></head></html>"),
            "<html lang=en><head><title>my-app</title><svg a=/><title>i</title></svg></head></html>"
        );
        assert_eq!(
            s("<html lang=en><head><template><title>T</title></template></head></html>"),
            "<html lang=en><head><title>my-app</title><template><title>T</title></template></head></html>"
        );
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
