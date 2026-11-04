//! Embedded pages and scripts, and the tiny markdown renderer for static apps.
use crate::util::esc;
use crate::State;
use axum::extract::State as St;
use axum::http::{header, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};

pub const FILE_HTML: &str = include_str!("../web/file.html");
pub const PORTAL_HTML: &str = include_str!("../web/portal.html");
pub const PORTAL_JS: &str = include_str!("../web/portal.js");
const FILE_JS: &str = include_str!("../web/file.js");
const STYLE_CSS: &str = include_str!("../web/style.css");
const ONBOARDING_SH: &str = include_str!("../onboarding/onboarding.sh");
const ONBOARDING_PS1: &str = include_str!("../onboarding/onboarding.ps1");

pub fn style() -> &'static str {
    STYLE_CSS
}

pub async fn file_js() -> impl IntoResponse {
    (
        [(header::CONTENT_TYPE, "text/javascript; charset=utf-8")],
        FILE_JS,
    )
}

pub async fn style_css() -> impl IntoResponse {
    (
        [(header::CONTENT_TYPE, "text/css; charset=utf-8")],
        STYLE_CSS,
    )
}

fn script(st: &State, t: &str) -> String {
    t.replace("__PUBLISH_URL__", &st.cfg.public_url)
        .replace("__INSTALL_URL__", &st.cfg.install_url)
        .replace("__INSTALL_REF__", &st.cfg.install_ref)
}

pub async fn onboarding_sh(St(st): St<State>) -> impl IntoResponse {
    (
        [(header::CONTENT_TYPE, "text/x-shellscript; charset=utf-8")],
        script(&st, ONBOARDING_SH),
    )
}

pub async fn onboarding_ps1(St(st): St<State>) -> impl IntoResponse {
    (
        [(header::CONTENT_TYPE, "text/plain; charset=utf-8")],
        script(&st, ONBOARDING_PS1),
    )
}

fn inline(s: &str) -> String {
    let e = esc(s);
    let mut out = String::new();
    for (i, part) in e.split('`').enumerate() {
        if i % 2 == 1 {
            out.push_str(&format!("<code>{part}</code>"));
            continue;
        }
        let mut t = String::new();
        for (j, b) in part.split("**").enumerate() {
            if j % 2 == 1 {
                t.push_str(&format!("<strong>{b}</strong>"));
            } else {
                t.push_str(&links(b));
            }
        }
        out.push_str(&t);
    }
    out
}

fn links(s: &str) -> String {
    let mut out = String::new();
    let mut rest = s;
    while let Some(a) = rest.find('[') {
        let after = &rest[a + 1..];
        if let Some(b) = after.find("](") {
            if let Some(c) = after[b + 2..].find(')') {
                let text = &after[..b];
                let url = &after[b + 2..b + 2 + c];
                out.push_str(&rest[..a]);
                if url.starts_with("http://")
                    || url.starts_with("https://")
                    || url.starts_with('/')
                    || url.starts_with('#')
                    || !url.contains(':')
                {
                    out.push_str(&format!("<a href=\"{url}\">{text}</a>"));
                } else {
                    out.push_str(text);
                }
                rest = &after[b + 2 + c + 1..];
                continue;
            }
        }
        out.push_str(&rest[..=a]);
        rest = after;
    }
    out.push_str(rest);
    out
}

/// A small subset of markdown: headings, lists, code blocks, paragraphs, **bold**, `code`, links.
pub fn markdown_page(title: &str, md: &str) -> String {
    let mut body = String::new();
    let (mut in_code, mut in_list, mut para) = (false, false, Vec::<String>::new());
    fn flush(body: &mut String, para: &mut Vec<String>) {
        if !para.is_empty() {
            body.push_str(&format!("<p>{}</p>\n", para.join(" ")));
            para.clear();
        }
    }
    for line in md.lines() {
        if line.trim_start().starts_with("```") {
            flush(&mut body, &mut para);
            if in_list {
                body.push_str("</ul>\n");
                in_list = false;
            }
            body.push_str(if in_code { "</pre>\n" } else { "<pre>" });
            in_code = !in_code;
            continue;
        }
        if in_code {
            body.push_str(&esc(line));
            body.push('\n');
            continue;
        }
        let t = line.trim();
        let item = t.strip_prefix("- ").or_else(|| t.strip_prefix("* "));
        if let Some(i) = item {
            flush(&mut body, &mut para);
            if !in_list {
                body.push_str("<ul>\n");
                in_list = true;
            }
            body.push_str(&format!("<li>{}</li>\n", inline(i)));
            continue;
        }
        if in_list {
            body.push_str("</ul>\n");
            in_list = false;
        }
        let level = t.chars().take_while(|c| *c == '#').count();
        if (1..=6).contains(&level) && t[level..].starts_with(' ') {
            flush(&mut body, &mut para);
            body.push_str(&format!(
                "<h{level}>{}</h{level}>\n",
                inline(t[level..].trim())
            ));
        } else if t.is_empty() {
            flush(&mut body, &mut para);
        } else {
            para.push(inline(t));
        }
    }
    flush(&mut body, &mut para);
    if in_list {
        body.push_str("</ul>\n");
    }
    if in_code {
        body.push_str("</pre>\n");
    }
    format!(
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{}</title><link rel=\"stylesheet\" href=\"/_/style.css\"></head><body class=\"public\"><div class=\"shell\"><main class=\"content\"><article class=\"card pad\">{body}</article></main></div></body></html>",
        esc(title)
    )
}

const LOGO: &str = r##"<svg viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="20" fill="none" stroke="#e8eaed" stroke-width="6"/><circle cx="32" cy="32" r="6" fill="#2fc6a3"/><circle cx="47" cy="17" r="7" fill="#2fc6a3" stroke="#0a0c0f" stroke-width="3"/></svg>"##;

/// Icon names: "lock", "offline", "clock", "link". Inline SVG, also used by file.js.
pub fn icon(name: &str) -> &'static str {
    match name {
        "lock" => {
            r#"<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>"#
        }
        "offline" => {
            r#"<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v8"/><path d="M6.3 6.7a8 8 0 1 0 11.4 0"/></svg>"#
        }
        "clock" => {
            r#"<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/></svg>"#
        }
        _ => {
            r#"<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/></svg>"#
        }
    }
}

/// A small dark card page (errors and states). `retry` adds a "Try again" button that reloads the page.
pub fn notice(status: u16, icon_name: &str, title: &str, msg: &str, retry: bool) -> Response {
    let button = if retry {
        "<a class=\"button primary\" href=\"\">Try again</a>"
    } else {
        ""
    };
    let html = format!(
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><meta name=\"color-scheme\" content=\"dark\"><meta name=\"referrer\" content=\"no-referrer\"><title>{t} · orch</title><link rel=\"stylesheet\" href=\"/_/style.css\"></head><body class=\"public\"><div class=\"shell\"><main class=\"content\"><header class=\"public-brand\"><a class=\"brand\" href=\"/\">{LOGO}orch</a></header><section class=\"card public-card\"><div class=\"file-icon\">{ic}</div><h1>{t}</h1><p>{m}</p>{button}</section></main></div></body></html>",
        t = esc(title),
        m = esc(msg),
        ic = icon(icon_name),
    );
    let mut r = (
        StatusCode::from_u16(status).unwrap(),
        [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
        html,
    )
        .into_response();
    let h = r.headers_mut();
    h.insert("x-frame-options", HeaderValue::from_static("DENY"));
    h.insert("referrer-policy", HeaderValue::from_static("no-referrer"));
    h.insert("cache-control", HeaderValue::from_static("no-store"));
    h.insert(
        "content-security-policy",
        HeaderValue::from_static(crate::files::CSP),
    );
    r
}

/// Anything that is not a route: root, wrong links.
pub async fn not_found() -> Response {
    notice(
        404,
        "link",
        "This page isn\u{2019}t available",
        "Check the link or ask the sender for a new one.",
        false,
    )
}
