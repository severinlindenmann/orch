//! Signing keys of phones (ORCH-1204, design note ORCH-1027 sections 2 and 5): the phone makes its own Ed25519 key
//! in its keychain and sends the public half when it redeems the pairing code the relay admin made ("Add phone").
//! The admin's pairing is the anchor: a new pairing replaces the key (the workspaces then see a new key without
//! the old one and must accept the phone again). A phone paired before keys existed may register one key once with
//! `PUT /v1/phone/signing-key`; replacing it needs a new pairing, so a stolen phone token alone cannot swap it.
//!
//! The relay shows the key to the phone's workspaces (directory `phones[].signing_key`) as a HINT only: a
//! workspace trusts it only after a person accepted its fingerprint. The private key never comes here.
use crate::error::*;
use crate::signkeys::{key_id, parse_public, ALG};
use crate::state::AppState;
use crate::util::*;
use axum::body::Bytes;
use axum::extract::State;
use axum::http::{HeaderMap, StatusCode};
use axum::Json;
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

/// `PUT /v1/phone/signing-key` `{"alg": "ed25519", "public_key": "<43 chars>"}` (phone auth): once, for a phone
/// paired before keys existed. 201 stored, 200 the same key again, 409 `key_exists` for another key.
pub async fn put(
    State(app): State<AppState>,
    h: HeaderMap,
    body: Bytes,
) -> Res<(StatusCode, Json<Value>)> {
    let v = crate::api::parse_body(&body)?;
    let o = v
        .as_object()
        .ok_or_else(|| invalid("Send {\"alg\": \"ed25519\", \"public_key\": \"…\"}."))?;
    if let Some(k) = o.keys().find(|k| *k != "alg" && *k != "public_key") {
        return Err(invalid(format!("Unknown field `{k}`.")));
    }
    if o.get("alg").and_then(Value::as_str) != Some(ALG) {
        return Err(invalid("`alg` must be \"ed25519\"."));
    }
    let pk = o
        .get("public_key")
        .and_then(Value::as_str)
        .ok_or_else(|| invalid("`public_key` is missing."))?;
    parse_public(pk).map_err(invalid)?;
    let c = app.db.lock().unwrap();
    let (pid, _, ws) = crate::auth::phone(&c, &h)?;
    let cur: Option<String> =
        c.query_row("SELECT sign_key FROM phones WHERE id=?1", [&pid], |r| r.get(0))?;
    let out = |status: &str| {
        let mut i = info(&c, &pid);
        i["status"] = status.into();
        i
    };
    match cur {
        Some(k) if k == pk => Ok((StatusCode::OK, Json(out("unchanged")))),
        Some(_) => Err(ApiError {
            status: StatusCode::CONFLICT,
            code: "key_exists",
            message: "This phone already has a signing key. A new key needs a new pairing on the relay admin page."
                .into(),
        }),
        None => {
            let tok = crate::auth::bearer(&h).map(token_hash).unwrap_or_default();
            let n = c.execute(
                "UPDATE phones SET sign_key=?3, sign_key_at=?4 WHERE id=?1 AND token_hash=?2 AND sign_key IS NULL",
                params![pid, tok, pk, now()],
            )?;
            if n == 0 {
                return Err(unauthorized());
            }
            // Its workspaces see the new key on their next directory read.
            crate::store::bump_and_hint(&c, &app.key, &ws)?;
            Ok((StatusCode::CREATED, Json(out("stored"))))
        }
    }
}
