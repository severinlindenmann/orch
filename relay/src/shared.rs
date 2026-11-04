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
        _ => name.to_string(),
    }
}

pub fn valid_name(kind: &str, n: &str) -> bool {
    let ok = |c: char| c.is_ascii_alphanumeric() || c == '_' || c == '-' || c == '.';
    !n.is_empty() && n.len() <= 64 && n.chars().all(ok) && (kind != "skills" || !n.starts_with('.'))
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
        .prepare("SELECT s.name,s.version,s.files FROM skills s JOIN assign a ON a.kind='skills' AND a.name=s.name WHERE a.ws=?1 ORDER BY s.name")?
        .query_map([me], |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?, r.get::<_, Vec<u8>>(2)?)))?
    {
        let (n, v, f) = r?;
        skills.push(json!({"name": n, "version": v, "files": dec(key, "skills", &n, &f)}));
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
            ver = c
                .query_row("SELECT version FROM skills WHERE name=?1", [name], |r| {
                    r.get::<_, i64>(0)
                })
                .unwrap_or(0)
                + 1;
            c.execute(
                "INSERT INTO skills(name,version,files) VALUES(?1,?2,?3) ON CONFLICT(name) DO UPDATE SET version=?2, files=?3",
                params![name, ver, blob],
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
