//! Shared config: skills, MCP servers, credentials, assigned per workspace.
use crate::crypto::{self, Key};
use crate::error::*;
use crate::store;
use base64::engine::general_purpose::STANDARD as B64;
use base64::Engine;
use rusqlite::{params, Connection};
use serde_json::{json, Map, Value};
use std::io::Read;
use std::path::Component;

pub const KINDS: [&str; 3] = ["skills", "mcp", "credentials"];
const MAX_UNPACKED: u64 = 20 * 1024 * 1024;

pub fn aad(kind: &str, name: &str) -> String {
    match kind {
        "skills" => format!("skill:{name}"),
        "mcp" => format!("mcp:{name}"),
        "skillhead" => format!("skillhead:{name}"),
        _ => name.to_string(),
    }
}

pub fn valid_name(kind: &str, n: &str) -> bool {
    let ok = |c: char| c.is_ascii_alphanumeric() || c == '_' || c == '-' || c == '.';
    !n.is_empty() && n.len() <= 64 && n.chars().all(ok) && (kind != "skills" || !n.starts_with('.'))
}

/// Open one sealed item (null when it cannot be opened).
pub fn open_item(key: &Key, kind: &str, name: &str, blob: &[u8]) -> Value {
    dec(key, kind, name, blob)
}

fn dec(key: &Key, kind: &str, name: &str, blob: &[u8]) -> Value {
    crypto::open(key, &aad(kind, name), blob)
        .and_then(|b| serde_json::from_slice(&b).ok())
        .unwrap_or(Value::Null)
}

/// `GET /v1/refresh`: everything assigned to `me` plus the workspace directory.
pub fn snapshot(c: &Connection, key: &Key, me: &str) -> rusqlite::Result<Value> {
    let mut skills = vec![];
    for r in c
        .prepare("SELECT s.name,s.version,s.files,s.head FROM skills s JOIN assign a ON a.kind='skills' AND a.name=s.name WHERE a.ws=?1 ORDER BY s.name")?
        .query_map([me], |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?, r.get::<_, Vec<u8>>(2)?, r.get::<_, Option<Vec<u8>>>(3)?)))?
    {
        let (n, v, f, h) = r?;
        let files = dec(key, "skills", &n, &f);
        let header = match h {
            Some(h) => dec(key, "skillhead", &n, &h),
            None => skill_header(&files),
        };
        skills.push(json!({"name": n, "version": v, "shown_version": shown_version(&header, v),
            "header": header, "files": files}));
    }
    let mut mcp = Map::new();
    for r in c
        .prepare("SELECT m.name,m.config FROM mcp m JOIN assign a ON a.kind='mcp' AND a.name=m.name WHERE a.ws=?1")?
        .query_map([me], |r| Ok((r.get::<_, String>(0)?, r.get::<_, Vec<u8>>(1)?)))?
    {
        let (n, b) = r?;
        let v = dec(key, "mcp", &n, &b);
        mcp.insert(n, v);
    }
    let mut creds = Map::new();
    for r in c
        .prepare("SELECT m.name,m.value FROM creds m JOIN assign a ON a.kind='credentials' AND a.name=m.name WHERE a.ws=?1")?
        .query_map([me], |r| Ok((r.get::<_, String>(0)?, r.get::<_, Vec<u8>>(1)?)))?
    {
        let (n, b) = r?;
        let v = dec(key, "credentials", &n, &b);
        creds.insert(n, v);
    }
    Ok(
        json!({"version": store::version(c), "skills": skills, "mcp": mcp, "credentials": creds,
        "workspaces": store::directory(c, me)?}),
    )
}

/// Unpack a skill `.tar.gz` into `{relative path: base64}`. A single top folder is stripped. Needs SKILL.md.
pub fn unpack_skill(data: &[u8]) -> Res<Value> {
    let gz = flate2::read::GzDecoder::new(data).take(MAX_UNPACKED + 1);
    let mut ar = tar::Archive::new(gz);
    let mut files: Vec<(Vec<String>, Vec<u8>)> = vec![];
    let mut total = 0u64;
    let entries = ar.entries().map_err(|_| invalid("Not a valid .tar.gz."))?;
    for e in entries {
        let mut e = e.map_err(|_| invalid("Not a valid .tar.gz."))?;
        if !e.header().entry_type().is_file() {
            continue;
        }
        let path = e
            .path()
            .map_err(|_| invalid("Bad path in archive."))?
            .into_owned();
        let mut parts = vec![];
        for c in path.components() {
            match c {
                Component::Normal(p) => parts.push(p.to_string_lossy().to_string()),
                Component::CurDir => {}
                _ => {
                    return Err(invalid(
                        "Archive paths must be relative and inside the folder.",
                    ))
                }
            }
        }
        if parts.is_empty() {
            continue;
        }
        let mut buf = vec![];
        e.read_to_end(&mut buf)
            .map_err(|_| invalid("Not a valid .tar.gz."))?;
        total += buf.len() as u64;
        if total > MAX_UNPACKED || files.len() > 500 {
            return Err(too_large("The skill is too big."));
        }
        files.push((parts, buf));
    }
    if !files.is_empty()
        && !files
            .iter()
            .any(|(p, _)| p.len() == 1 && p[0] == "SKILL.md")
        && files
            .iter()
            .all(|(p, _)| p.len() > 1 && p[0] == files[0].0[0])
    {
        for f in files.iter_mut() {
            f.0.remove(0);
        }
    }
    if !files
        .iter()
        .any(|(p, _)| p.len() == 1 && p[0] == "SKILL.md")
    {
        return Err(invalid("The skill folder needs a SKILL.md."));
    }
    let mut out = Map::new();
    for (p, b) in files {
        out.insert(p.join("/"), B64.encode(b).into());
    }
    Ok(Value::Object(out))
}

pub fn put_item(
    c: &Connection,
    key: &Key,
    kind: &str,
    name: &str,
    value: &Value,
) -> rusqlite::Result<i64> {
    let blob = crypto::seal(key, &aad(kind, name), &serde_json::to_vec(value).unwrap());
    let mut ver = 0;
    match kind {
        "skills" => {
            let head = crypto::seal(
                key,
                &aad("skillhead", name),
                &serde_json::to_vec(&skill_header(value)).unwrap(),
            );
            ver = c
                .query_row("SELECT version FROM skills WHERE name=?1", [name], |r| {
                    r.get::<_, i64>(0)
                })
                .unwrap_or(0)
                + 1;
            c.execute(
                "INSERT INTO skills(name,version,files,head) VALUES(?1,?2,?3,?4) ON CONFLICT(name) DO UPDATE SET version=?2, files=?3, head=?4",
                params![name, ver, blob, head],
            )?;
        }
        "mcp" => {
            c.execute(
                "INSERT INTO mcp(name,config) VALUES(?1,?2) ON CONFLICT(name) DO UPDATE SET config=?2",
                params![name, blob],
            )?;
        }
        _ => {
            c.execute(
                "INSERT INTO creds(name,value) VALUES(?1,?2) ON CONFLICT(name) DO UPDATE SET value=?2",
                params![name, blob],
            )?;
        }
    }
    Ok(ver)
}

pub fn table(kind: &str) -> &'static str {
    match kind {
        "skills" => "skills",
        "mcp" => "mcp",
        _ => "creds",
    }
}

pub fn assigned_ws(c: &Connection, kind: &str, name: &str) -> Vec<String> {
    c.prepare("SELECT ws FROM assign WHERE kind=?1 AND name=?2")
        .and_then(|mut s| s.query_map(params![kind, name], |r| r.get(0))?.collect())
        .unwrap_or_default()
}

// ---------- skill header (the frontmatter of SKILL.md) ----------
//
// A restricted reader for the flat skill header (skill format, ORCH-531): top-level `key: value` lines and one
// `metadata:` map of text values. Anything fancier (nested maps, lists, anchors) is skipped, never an error:
// the header only feeds labels and the platform check, the files stay as the admin uploaded them.

const HEAD_MAX: usize = 16 * 1024;
const VALUE_MAX: usize = 1024;
const META_MAX: usize = 64;

/// The version people see: `metadata.version` when the skill sets one, else the relay's own counter.
pub fn shown_version(header: &Value, counter: i64) -> String {
    match header["metadata"]["version"].as_str() {
        Some(v) if !v.is_empty() => v.to_string(),
        _ => counter.to_string(),
    }
}

fn head_key_ok(k: &str) -> bool {
    !k.is_empty()
        && k.len() <= 64
        && k.chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
}

fn head_value(raw: &str) -> Option<String> {
    let v = raw.trim();
    let out = if let Some(inner) = v.strip_prefix('"') {
        let inner = inner.strip_suffix('"')?;
        inner.replace("\\\"", "\"").replace("\\\\", "\\")
    } else if let Some(inner) = v.strip_prefix('\'') {
        inner.strip_suffix('\'')?.replace("''", "'")
    } else {
        if v.starts_with(['[', '{', '&', '*', '!', '|', '>']) {
            return None;
        }
        match v.find(" #") {
            Some(i) => v[..i].trim_end().to_string(),
            None => v.to_string(),
        }
    };
    let out: String = out.chars().filter(|c| !c.is_control()).collect();
    (out.chars().count() <= VALUE_MAX).then_some(out)
}

/// The parsed header of a skill's `SKILL.md` (files as `{path: base64}`): `{"name", "description",
/// "metadata": {key: text}}`, only what was readable. `{}` when there is no header.
pub fn skill_header(files: &Value) -> Value {
    let text = files["SKILL.md"]
        .as_str()
        .and_then(|b| B64.decode(b).ok())
        .and_then(|b| String::from_utf8(b).ok())
        .unwrap_or_default();
    let mut lines = text.lines();
    if lines.next().map(str::trim_end) != Some("---") {
        return json!({});
    }
    let mut out = Map::new();
    let mut meta = Map::new();
    let mut in_meta = false;
    let mut meta_indent = 0;
    let mut size = 0;
    for line in lines {
        size += line.len() + 1;
        if size > HEAD_MAX || line.trim_end() == "---" {
            break;
        }
        if line.trim().is_empty() || line.trim_start().starts_with('#') {
            continue;
        }
        let indent = line.len() - line.trim_start().len();
        let Some((k, v)) = line.trim().split_once(':') else {
            continue;
        };
        let k = k.trim();
        if indent == 0 {
            in_meta = k == "metadata" && v.trim().is_empty();
            meta_indent = 0;
            if !in_meta && matches!(k, "name" | "description") {
                if let Some(v) = head_value(v) {
                    out.insert(k.to_string(), v.into());
                }
            }
        } else if in_meta && head_key_ok(k) && meta.len() < META_MAX {
            // only the first level of metadata: a deeper line belongs to a nested map, which is skipped
            if meta_indent == 0 {
                meta_indent = indent;
            }
            if indent != meta_indent || v.trim().is_empty() {
                continue;
            }
            if let Some(v) = head_value(v) {
                meta.insert(k.to_string(), v.into());
            }
        }
    }
    if !meta.is_empty() {
        out.insert("metadata".into(), Value::Object(meta));
    }
    Value::Object(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn head(text: &str) -> Value {
        skill_header(&json!({"SKILL.md": B64.encode(text)}))
    }

    #[test]
    fn reads_the_flat_header() {
        let h = head(
            "---\nname: github\ndescription: \"GitHub work. Use when a PR: \\\"x\\\"\"\nlicense: MIT\n\
             metadata:\n  version: \"1.2.0\"\n  owner: Severin # who\n  status: 'draft'\n  platforms: \"macos, windows\"\n\
             ---\nbody: not header\n",
        );
        assert_eq!(h["name"], "github");
        assert_eq!(h["description"], "GitHub work. Use when a PR: \"x\"");
        assert_eq!(
            h["metadata"],
            json!({"version": "1.2.0", "owner": "Severin", "status": "draft", "platforms": "macos, windows"})
        );
        assert!(h.get("license").is_none() && h.get("body").is_none());
        assert_eq!(shown_version(&h, 7), "1.2.0");
    }

    #[test]
    fn skips_what_it_cannot_read() {
        assert_eq!(head("no header\nname: x\n"), json!({}));
        assert_eq!(skill_header(&json!({})), json!({}));
        assert_eq!(skill_header(&Value::Null), json!({}));
        let h = head(
            "---\nname: x\nmetadata:\n  nested:\n    deep: a\n  list: [a, b]\n  bad key!: v\n  ok: \"v\"\n\
             status: draft\n---\n",
        );
        // nested and list values, bad keys and top-level extras are left out; metadata ends at the next top-level key
        assert_eq!(h, json!({"name": "x", "metadata": {"ok": "v"}}));
        assert_eq!(shown_version(&h, 3), "3");
        let long = format!("---\nmetadata:\n  owner: {}\n---\n", "a".repeat(2000));
        assert_eq!(head(&long), json!({}));
    }
}
