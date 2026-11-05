//! SQLite schema and the small helpers every module shares.
use crate::crypto::{self, Key};
use crate::util::*;
use rusqlite::{params, Connection, OptionalExtension, Row};
use serde_json::{json, Map, Value};
use std::path::Path;

pub const RETENTION_SECS: i64 = 90 * 24 * 3600;
pub const ONLINE_SECS: i64 = 120;

pub fn init(c: &Connection) -> rusqlite::Result<()> {
    c.execute_batch(
        "PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
        INSERT OR IGNORE INTO meta(k,v) VALUES('version','1');
        CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
            tags TEXT NOT NULL, token_hash TEXT NOT NULL, created_at INTEGER NOT NULL, last_seen INTEGER,
            description_by TEXT NOT NULL DEFAULT 'workspace', tags_by TEXT NOT NULL DEFAULT 'workspace',
            pending_description TEXT, pending_tags TEXT, pending_at INTEGER, pending_rev TEXT);
        CREATE TABLE IF NOT EXISTS phones(id TEXT PRIMARY KEY, name TEXT NOT NULL, workspaces TEXT NOT NULL,
            token_hash TEXT, apns_token TEXT, sandbox INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, last_seen INTEGER);
        CREATE TABLE IF NOT EXISTS pair_codes(hash TEXT PRIMARY KEY, phone_id TEXT NOT NULL, expires_at INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS rules(from_id TEXT NOT NULL, to_id TEXT NOT NULL, text INTEGER NOT NULL, files INTEGER NOT NULL,
            delegate INTEGER NOT NULL, start INTEGER NOT NULL, PRIMARY KEY(from_id,to_id));
        CREATE TABLE IF NOT EXISTS messages(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, from_addr TEXT NOT NULL,
            to_addr TEXT NOT NULL, type TEXT NOT NULL, created_at TEXT NOT NULL, ticket TEXT, reply_to TEXT, blob_id TEXT,
            digest TEXT NOT NULL, payload BLOB NOT NULL, stored_at INTEGER NOT NULL, acked_at INTEGER);
        CREATE INDEX IF NOT EXISTS msg_to ON messages(to_addr, acked_at);
        CREATE INDEX IF NOT EXISTS msg_reply ON messages(reply_to);
        DROP INDEX IF EXISTS msg_text_to;
        DROP INDEX IF EXISTS msg_text_from;
        CREATE INDEX IF NOT EXISTS msg_type_to_from ON messages(type, to_addr, from_addr, seq);
        CREATE INDEX IF NOT EXISTS msg_type_from_to ON messages(type, from_addr, to_addr, seq);
        CREATE TABLE IF NOT EXISTS blobs(id TEXT PRIMARY KEY, uploader TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL, created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS webhooks(id TEXT PRIMARY KEY, workspace TEXT NOT NULL, mode TEXT NOT NULL, ticket TEXT,
            token_hash TEXT NOT NULL, created_at INTEGER NOT NULL, last_call_at INTEGER, used INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS skills(name TEXT PRIMARY KEY, version INTEGER NOT NULL, files BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS mcp(name TEXT PRIMARY KEY, config BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS creds(name TEXT PRIMARY KEY, value BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS assign(ws TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY(ws,kind,name));",
    )?;
    // Older databases: add the profile columns (ignore "duplicate column"). Existing rows count as written by the workspace.
    for col in [
        "description_by TEXT NOT NULL DEFAULT 'workspace'",
        "tags_by TEXT NOT NULL DEFAULT 'workspace'",
        "pending_description TEXT",
        "pending_tags TEXT",
        "pending_at INTEGER",
        "pending_rev TEXT",
    ] {
        let _ = c.execute(&format!("ALTER TABLE workspaces ADD COLUMN {col}"), []);
    }
    // When the phone paired (L3): broadcasts to `phones` from before are not shown to it.
    let _ = c.execute("ALTER TABLE phones ADD COLUMN paired_at INTEGER", []);
    Ok(())
}

pub fn version(c: &Connection) -> i64 {
    c.query_row("SELECT v FROM meta WHERE k='version'", [], |r| {
        r.get::<_, String>(0)
    })
    .ok()
    .and_then(|v| v.parse().ok())
    .unwrap_or(1)
}

pub fn bump_version(c: &Connection) -> rusqlite::Result<i64> {
    let v = version(c) + 1;
    c.execute("UPDATE meta SET v=?1 WHERE k='version'", [v.to_string()])?;
    Ok(v)
}

// ---------- messages ----------

pub struct Msg {
    pub seq: i64,
    pub id: String,
    pub from: String,
    pub to: String,
    pub typ: String,
    pub created_at: String,
    pub ticket: Option<String>,
    pub reply_to: Option<String>,
    pub payload: Vec<u8>,
    pub acked: bool,
}

pub const MSG_COLS: &str =
    "seq,id,from_addr,to_addr,type,created_at,ticket,reply_to,payload,acked_at";

pub fn msg_from_row(r: &Row) -> rusqlite::Result<Msg> {
    Ok(Msg {
        seq: r.get(0)?,
        id: r.get(1)?,
        from: r.get(2)?,
        to: r.get(3)?,
        typ: r.get(4)?,
        created_at: r.get(5)?,
        ticket: r.get(6)?,
        reply_to: r.get(7)?,
        payload: r.get(8)?,
        acked: r.get::<_, Option<i64>>(9)?.is_some(),
    })
}

pub fn get_msg(c: &Connection, id: &str) -> rusqlite::Result<Option<Msg>> {
    c.query_row(
        &format!("SELECT {MSG_COLS} FROM messages WHERE id=?1"),
        [id],
        msg_from_row,
    )
    .optional()
}

/// The encrypted part of a message: `{body, extra}` (extra = unknown top-level fields, kept).
pub fn open_payload(key: &Key, m: &Msg) -> (Value, Map<String, Value>) {
    let v: Value = crypto::open(key, &m.id, &m.payload)
        .and_then(|b| serde_json::from_slice(&b).ok())
        .unwrap_or(json!({"body": {}, "extra": {}}));
    (
        v["body"].clone(),
        v["extra"].as_object().cloned().unwrap_or_default(),
    )
}

pub fn msg_json(key: &Key, m: &Msg) -> Value {
    let (body, extra) = open_payload(key, m);
    let mut o = extra;
    o.insert("schema".into(), "orch.msg/1".into());
    o.insert("id".into(), m.id.clone().into());
    o.insert("from".into(), m.from.clone().into());
    o.insert("to".into(), m.to.clone().into());
    o.insert("type".into(), m.typ.clone().into());
    o.insert("created_at".into(), m.created_at.clone().into());
    if let Some(t) = &m.ticket {
        o.insert("ticket".into(), t.clone().into());
    }
    if let Some(t) = &m.reply_to {
        o.insert("reply_to".into(), t.clone().into());
    }
    o.insert("body".into(), body);
    Value::Object(o)
}

const KNOWN: [&str; 9] = [
    "schema",
    "id",
    "from",
    "to",
    "type",
    "created_at",
    "ticket",
    "reply_to",
    "body",
];

/// Store a full message (already validated). `digest` identifies the submitted content for duplicate checks.
pub fn insert_message(
    c: &Connection,
    key: &Key,
    msg: &Value,
    digest: &str,
) -> rusqlite::Result<()> {
    let s = |k: &str| msg[k].as_str().map(str::to_string);
    let id = s("id").unwrap_or_default();
    let extra: Map<String, Value> = msg
        .as_object()
        .map(|o| {
            o.iter()
                .filter(|(k, _)| !KNOWN.contains(&k.as_str()))
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect()
        })
        .unwrap_or_default();
    let payload = crypto::seal(
        key,
        &id,
        &serde_json::to_vec(&json!({"body": msg["body"], "extra": extra})).unwrap(),
    );
    let blob_id = if msg["type"] == "file" {
        msg["body"]["blob_id"].as_str().map(str::to_string)
    } else {
        None
    };
    c.execute(
        "INSERT INTO messages(id,from_addr,to_addr,type,created_at,ticket,reply_to,blob_id,digest,payload,stored_at)
         VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)",
        params![
            id,
            s("from"),
            s("to"),
            s("type"),
            s("created_at"),
            s("ticket"),
            s("reply_to"),
            blob_id,
            digest,
            payload,
            now()
        ],
    )?;
    Ok(())
}

#[allow(clippy::too_many_arguments)]
/// A message made by the relay itself (answer, phone text, webhook, refresh-hint).
pub fn system_message(
    c: &Connection,
    key: &Key,
    from: &str,
    to: &str,
    typ: &str,
    ticket: Option<&str>,
    reply_to: Option<&str>,
    body: Value,
) -> rusqlite::Result<Value> {
    let mut m = json!({"schema": "orch.msg/1", "id": rand_id("m_", 16), "from": from, "to": to,
        "type": typ, "created_at": fmt_time(now()), "body": body});
    if let Some(t) = ticket {
        m["ticket"] = t.into();
    }
    if let Some(t) = reply_to {
        m["reply_to"] = t.into();
    }
    insert_message(c, key, &m, "")?;
    Ok(m)
}

// ---------- workspaces ----------

pub fn online(last_seen: Option<i64>) -> bool {
    last_seen.is_some_and(|t| now() - t < ONLINE_SECS)
}

pub fn ws_name(c: &Connection, id: &str) -> Option<String> {
    c.query_row("SELECT name FROM workspaces WHERE id=?1", [id], |r| {
        r.get(0)
    })
    .ok()
}

pub fn ws_exists(c: &Connection, id: &str) -> bool {
    ws_name(c, id).is_some()
}

/// A phone's workspace list without repeats (first one wins), also for rows saved before the admin API deduped.
pub fn parse_ws_list(s: &str) -> Vec<String> {
    let mut l = parse_list(s);
    let mut seen = std::collections::HashSet::new();
    l.retain(|w| seen.insert(w.clone()));
    l
}

pub fn parse_list(s: &str) -> Vec<String> {
    serde_json::from_str(s).unwrap_or_default()
}

/// `{id,name,description,tags,online,last_seen}` for one workspace.
pub fn ws_card(r: &Row) -> rusqlite::Result<Value> {
    let last: Option<i64> = r.get(4)?;
    Ok(
        json!({"id": r.get::<_, String>(0)?, "name": r.get::<_, String>(1)?,
        "description": r.get::<_, String>(2)?, "tags": parse_list(&r.get::<_, String>(3)?),
        "online": online(last), "last_seen": last.map(fmt_time),
        "description_by": r.get::<_, String>(5)?, "tags_by": r.get::<_, String>(6)?}),
    )
}

pub const WS_CARD_COLS: &str = "id,name,description,tags,last_seen,description_by,tags_by";

/// The change a workspace proposed for its own profile, or `null`. Only the proposed fields are set.
pub fn pending(c: &Connection, id: &str) -> Value {
    c.query_row(
        "SELECT pending_description,pending_tags,pending_at,pending_rev FROM workspaces WHERE id=?1",
        [id],
        |r| {
            let (d, t, at, rev): (Option<String>, Option<String>, Option<i64>, Option<String>) =
                (r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?);
            Ok(match at {
                Some(at) => {
                    json!({"description": d, "tags": t.map(|t| parse_list(&t)), "at": fmt_time(at), "rev": rev})
                }
                None => Value::Null,
            })
        },
    )
    .unwrap_or(Value::Null)
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

/// Description of a workspace (admin- or self-written): plain one-line text (NFC-normalised), up to 280 characters.
pub fn valid_description(d: &str) -> Result<String, &'static str> {
    use unicode_normalization::UnicodeNormalization;
    let d: String = d.trim().nfc().collect();
    if d.chars().count() > 280 {
        return Err("The description can be up to 280 characters.");
    }
    if !d.chars().all(good_char) {
        return Err("The description must be plain text on one line (letters, numbers, punctuation and symbols only).");
    }
    if too_many_marks(&d) {
        return Err("The description has too many stacked accents or marks.");
    }
    Ok(d)
}

/// Display name a phone gives at pairing: NFC, trimmed, characters outside the description allowlist dropped,
/// at most 60 characters. `None` when nothing is left (the admin's label stays).
pub fn clean_phone_name(n: &str) -> Option<String> {
    use unicode_normalization::UnicodeNormalization;
    let n: String = n.nfc().filter(|c| good_char(*c)).collect();
    let n: String = n.trim().chars().take(60).collect();
    let n = n.trim().to_string();
    (!n.is_empty()).then_some(n)
}

/// Tag: lowercase letters, digits and hyphens, 1 to 24 characters.
pub fn valid_tag(t: &str) -> bool {
    (1..=24).contains(&t.len())
        && t.bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
}

pub fn valid_tags(a: &[Value]) -> Result<Vec<String>, &'static str> {
    if a.len() > 8 {
        return Err("Use at most 8 tags.");
    }
    a.iter()
        .map(|t| match t.as_str() {
            Some(t) if valid_tag(t.trim()) => Ok(t.trim().to_string()),
            _ => Err("Each tag is 1 to 24 characters: lowercase letters, digits and hyphens."),
        })
        .collect()
}

pub fn rule_flags(c: &Connection, from: &str, to: &str) -> Option<[bool; 4]> {
    c.query_row(
        "SELECT text,files,delegate,start FROM rules WHERE from_id=?1 AND to_id=?2",
        [from, to],
        |r| Ok([r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?]),
    )
    .optional()
    .ok()
    .flatten()
}

fn can(f: Option<[bool; 4]>) -> Value {
    let f = f.unwrap_or([false; 4]);
    json!({"text": f[0], "files": f[1], "delegate": f[2], "start": f[3]})
}

/// workspaces.schema.json: every workspace with a pair rule to or from `me`.
pub fn directory(c: &Connection, me: &str) -> rusqlite::Result<Value> {
    let mut st = c.prepare(&format!(
        "SELECT {WS_CARD_COLS} FROM workspaces WHERE id!=?1 AND (
           id IN (SELECT to_id FROM rules WHERE from_id=?1) OR id IN (SELECT from_id FROM rules WHERE to_id=?1))
         ORDER BY name"
    ))?;
    let cards: Vec<Value> = st.query_map([me], ws_card)?.collect::<Result<_, _>>()?;
    let items: Vec<Value> = cards
        .into_iter()
        .map(|mut w| {
            let id = w["id"].as_str().unwrap().to_string();
            w["can_send"] = can(rule_flags(c, me, &id));
            w["accepts_from"] = can(rule_flags(c, &id, me));
            w
        })
        .collect();
    Ok(
        json!({"schema": "orch.workspaces/1", "self": me, "updated_at": fmt_time(now()), "workspaces": items,
            "phones": phones_of(c, me)?}),
    )
}

/// Paired phones (signed in) whose list holds workspace `ws`: `[{id, name, online, last_seen}]` by name.
/// The admin's phone pairing is the rule: these phones may reach `ws` and `ws` may send text/questions to them.
pub fn phones_of(c: &Connection, ws: &str) -> rusqlite::Result<Vec<Value>> {
    let mut st = c.prepare(
        "SELECT id,name,workspaces,last_seen FROM phones WHERE token_hash IS NOT NULL ORDER BY name, id",
    )?;
    let rows = st.query_map([], |r| {
        Ok((
            r.get::<_, String>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
            r.get::<_, Option<i64>>(3)?,
        ))
    })?;
    let mut out = vec![];
    for row in rows {
        let (id, name, list, last) = row?;
        if parse_list(&list).iter().any(|w| w == ws) {
            out.push(json!({"id": id, "name": name, "online": online(last), "last_seen": last.map(fmt_time)}));
        }
    }
    Ok(out)
}

/// True when phone `pid` is paired (signed in) and may reach workspace `ws`.
pub fn phone_reaches(c: &Connection, pid: &str, ws: &str) -> bool {
    phones_of(c, ws).is_ok_and(|p| p.iter().any(|x| x["id"] == pid))
}

/// The workspaces in a phone's list (empty when there is no such phone).
pub fn phone_workspaces(c: &Connection, pid: &str) -> Vec<String> {
    c.query_row("SELECT workspaces FROM phones WHERE id=?1", [pid], |r| {
        r.get::<_, String>(0)
    })
    .optional()
    .ok()
    .flatten()
    .map(|l| parse_list(&l))
    .unwrap_or_default()
}

/// `me` plus every workspace connected to it by a pair rule.
pub fn related(c: &Connection, me: &str) -> Vec<String> {
    let mut v = vec![me.to_string()];
    if let Ok(mut st) = c.prepare(
        "SELECT to_id FROM rules WHERE from_id=?1 UNION SELECT from_id FROM rules WHERE to_id=?1",
    ) {
        if let Ok(rows) = st.query_map([me], |r| r.get::<_, String>(0)) {
            v.extend(rows.flatten());
        }
    }
    v
}

/// Raise `version` by 1 and send one refresh-hint to each existing workspace in `ws` (replacing an unread one).
pub fn bump_and_hint(c: &Connection, key: &Key, ws: &[String]) -> rusqlite::Result<i64> {
    let v = bump_version(c)?;
    let mut seen = std::collections::HashSet::new();
    for w in ws {
        if !seen.insert(w.clone()) || !ws_exists(c, w) {
            continue;
        }
        c.execute(
            "DELETE FROM messages WHERE to_addr=?1 AND type='refresh-hint' AND acked_at IS NULL",
            [w],
        )?;
        system_message(
            c,
            key,
            "admin",
            w,
            "refresh-hint",
            None,
            None,
            json!({"version": v}),
        )?;
    }
    Ok(v)
}

/// Delete messages and blobs older than 90 days.
pub fn purge(c: &Connection, data_dir: &Path, at: i64) -> rusqlite::Result<(usize, usize)> {
    let cutoff = at - RETENTION_SECS;
    let m = c.execute("DELETE FROM messages WHERE stored_at<?1", [cutoff])?;
    let mut st = c.prepare("SELECT id FROM blobs WHERE created_at<?1")?;
    let ids: Vec<String> = st
        .query_map([cutoff], |r| r.get(0))?
        .collect::<Result<_, _>>()?;
    for id in &ids {
        let _ = std::fs::remove_file(data_dir.join("blobs").join(id));
        c.execute("DELETE FROM blobs WHERE id=?1", [id])?;
    }
    c.execute("DELETE FROM pair_codes WHERE expires_at<?1", [at - 86400])?;
    Ok((m, ids.len()))
}
