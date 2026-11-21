//! Signing keys of phones (ORCH-1204, design note ORCH-1027 sections 2 and 5): the phone makes its own Ed25519 key
//! in its keychain and sends the public half when it redeems the pairing code the relay admin made ("Add phone").
//! The admin's pairing is the anchor: a new pairing replaces the key (the workspaces then see a new key without
//! the old one and must accept the phone again). There is no other way to set it: a phone paired before keys gets
//! one by a new pairing, so a stolen phone token alone can never bind a key.
//!
//! The relay shows the key to the phone's workspaces (directory `phones[].signing_key`) as a HINT only: a
//! workspace trusts it only after a person accepted its fingerprint. The private key never comes here.
use crate::error::*;
use crate::signkeys::{key_id, parse_public, ALG};
use crate::util::*;
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};

pub fn init(c: &Connection) {
    for col in ["sign_key TEXT", "sign_key_at INTEGER"] {
        let _ = c.execute(&format!("ALTER TABLE phones ADD COLUMN {col}"), []);
    }
}

/// The key a pairing request carries, checked before anything is written. `None` when it sent none (an older
/// app); a bad key refuses the whole pairing so the code stays unused.
pub fn from_pair_request(v: &Value) -> Res<Option<String>> {
    match v.get("public_key") {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(s)) => {
            parse_public(s).map_err(invalid)?;
            Ok(Some(s.clone()))
        }
        Some(_) => Err(invalid("`public_key` must be a string.")),
    }
}

/// Store the key of a pairing (inside the pairing's transaction). A pairing without a key clears the old one: the
/// new install has no key the workspaces could check.
pub fn set_on_pair(c: &Connection, pid: &str, key: Option<&str>) -> rusqlite::Result<()> {
    c.execute(
        "UPDATE phones SET sign_key=?2, sign_key_at=CASE WHEN ?2 IS NULL THEN NULL ELSE ?3 END WHERE id=?1",
        params![pid, key, now()],
    )?;
    Ok(())
}

/// `{alg, public_key, key_id, registered_at}` of a phone, or `null` when it has none.
pub fn info(c: &Connection, pid: &str) -> Value {
    let row: Option<(Option<String>, Option<i64>)> = c
        .query_row(
            "SELECT sign_key, sign_key_at FROM phones WHERE id=?1",
            [pid],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()
        .unwrap_or(None);
    match row {
        Some((Some(k), at)) => match parse_public(&k) {
            Ok(raw) => json!({"alg": ALG, "public_key": k, "key_id": key_id(&raw),
                "registered_at": at.map(fmt_time)}),
            Err(_) => Value::Null,
        },
        _ => Value::Null,
    }
}

/// Adds the phone's key to its directory card (`phones[].signing_key`).
pub fn add_to_card(c: &Connection, card: &mut Value) {
    let id = card["id"].as_str().unwrap_or_default().to_string();
    card["signing_key"] = info(c, &id);
}

/// Adds a workspace's registered key to the phone's workspace item (`signing_key`, a hint the phone shows with
/// Accept; the phone trusts it only after the person accepted the fingerprint).
pub fn add_workspace_key(c: &Connection, card: &mut Value) {
    let id = card["id"].as_str().unwrap_or_default().to_string();
    card["signing_key"] = crate::signkeys::info(c, &id);
}

/// The phone's registered raw key, for the signature check of what it sends.
pub fn raw_key(c: &Connection, pid: &str) -> Option<[u8; 32]> {
    let k: Option<String> = c
        .query_row("SELECT sign_key FROM phones WHERE id=?1", [pid], |r| r.get(0))
        .optional()
        .ok()
        .flatten()
        .flatten();
    k.and_then(|k| parse_public(&k).ok())
}
