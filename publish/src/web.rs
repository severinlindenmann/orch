//! Embedded pages and scripts, and the tiny markdown renderer for static apps.
use crate::util::esc;
use crate::State;
use axum::extract::State as St;
use axum::http::header;
use axum::response::IntoResponse;

pub const FILE_HTML: &str = include_str!("../web/file.html");
pub const PRIVATE_HTML: &str = include_str!("../web/private.html");
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
