//! The relay's gate for signed messages (ORCH-1201, design note ORCH-1027 sections 4.1 and 9 A2/B/C).
//!
//! - `POST /v1/messages` with an `envelope` is checked against the sender's registered key (`msgsig::relay_check`):
//!   a wrong, missing or changed signature is refused (422 with the contract code), the same id with other bytes
//!   is refused (409 `replayed`), the same bytes again is the usual 200 duplicate. The outer message must say the
//!   same as the signed bytes. The envelope is stored and handed to the receiver unchanged.
//! - Without an envelope the message is refused once the relay admin turned on `require_signed` (the hard cut,
//!   choice C); until then it goes through as before.
//! - A key change is a statement signed by the old key (and by the new key, to show the workspace holds it); it is
//!   held until the relay admin approves it on the admin page. Without the old key (a lost computer) the request
//!   is signed by the new key only and shown as such. Relay approval is a speed bump against a stolen token, never
//!   proof: receivers decide trust themselves.
//! - A workspace withdraws its own key with a statement signed by it; the relay admin can block a key. Both are
//!   final for that key: messages and key changes signed by it are refused, and no replacement is offered from it.
//!
//! Relay-made messages (`store::insert_relay_msg` and friends) never pass this gate: they are a closed list of
//! types in code and carry no envelope.
use crate::error::*;
use crate::msgsig::{self, RelayOutcome, SigError};
use crate::signkeys;
use crate::state::AppState;
use crate::util::*;
use axum::body::Bytes;
use axum::extract::{Path, State};
use axum::http::{HeaderMap, StatusCode};
use axum::Json;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};

/// Setting key: when present, messages without an envelope are refused.
const REQUIRE_KEY: &str = "require_signed";

pub fn init(c: &Connection) -> rusqlite::Result<()> {
    c.execute_batch(
        "CREATE TABLE IF NOT EXISTS sign_key_ended(ws TEXT NOT NULL, public_key TEXT NOT NULL, key_id TEXT NOT NULL,
            state TEXT NOT NULL, at INTEGER NOT NULL, PRIMARY KEY(ws, public_key));
        CREATE TABLE IF NOT EXISTS sign_key_change(ws TEXT PRIMARY KEY, new_key TEXT NOT NULL, kind TEXT NOT NULL,
            old_key TEXT, requested_at INTEGER NOT NULL);",
    )?;
    let _ = c.execute("ALTER TABLE messages ADD COLUMN sig_digest TEXT", []);
    Ok(())
}

// ------------------------------------------------------------------ the switch

pub fn require_signed(c: &Connection) -> bool {
    c.query_row("SELECT 1 FROM settings WHERE k=?1", [REQUIRE_KEY], |_| {
        Ok(())
    })
    .optional()
    .ok()
    .flatten()
    .is_some()
}

pub fn set_require_signed(c: &Connection, on: bool) -> rusqlite::Result<()> {
    if on {
        c.execute(
            "INSERT OR REPLACE INTO settings(k, v) VALUES(?1, x'31')",
            [REQUIRE_KEY],
        )?;
    } else {
        c.execute("DELETE FROM settings WHERE k=?1", [REQUIRE_KEY])?;
    }
    Ok(())
}

// ------------------------------------------------------------------ key state

fn sig_err(status: StatusCode, code: &'static str, m: impl Into<String>) -> ApiError {
    ApiError {
        status,
        code,
        message: m.into(),
    }
}

fn refused(e: SigError) -> ApiError {
    let (status, msg) = match e {
        SigError::Replayed => (
            StatusCode::CONFLICT,
            "This message id was already used for another message.",
        ),
        SigError::MissingSignature => (
            StatusCode::UNPROCESSABLE_ENTITY,
            "The message is not signed.",
        ),
        SigError::UnknownKey => (
            StatusCode::UNPROCESSABLE_ENTITY,
            "The message is signed with a key the relay does not know for this workspace.",
        ),
        SigError::BadSignature => (
            StatusCode::UNPROCESSABLE_ENTITY,
            "The signature does not match the message.",
        ),
        SigError::WrongSender => (
            StatusCode::UNPROCESSABLE_ENTITY,
            "The signed sender is not this workspace.",
        ),
        _ => (
            StatusCode::UNPROCESSABLE_ENTITY,
            "The signed message is not in the signed message format.",
        ),
    };
    sig_err(status, e.code(), msg)
}

fn current_key(c: &Connection, ws: &str) -> rusqlite::Result<Option<String>> {
    Ok(
        c.query_row("SELECT sign_key FROM workspaces WHERE id=?1", [ws], |r| {
            r.get::<_, Option<String>>(0)
        })
        .optional()?
        .flatten(),
    )
}

/// `withdrawn` / `blocked` / `replaced` when the key no longer counts, else None.
fn ended(c: &Connection, ws: &str, key: &str) -> Option<String> {
    c.query_row(
        "SELECT state FROM sign_key_ended WHERE ws=?1 AND public_key=?2",
        params![ws, key],
        |r| r.get(0),
    )
    .optional()
    .ok()
    .flatten()
}

fn end_key(c: &Connection, ws: &str, key: &str, state: &str) -> rusqlite::Result<()> {
    let kid = signkeys::parse_public(key)
        .map(|r| signkeys::key_id(&r))
        .unwrap_or_default();
    c.execute(
        "INSERT INTO sign_key_ended(ws, public_key, key_id, state, at) VALUES(?1,?2,?3,?4,?5)
         ON CONFLICT(ws, public_key) DO UPDATE SET state=excluded.state, at=excluded.at",
        params![ws, key, kid, state, now()],
    )?;
    // a pending change signed by a key that just ended loses its proof: drop it
    c.execute(
        "DELETE FROM sign_key_change WHERE ws=?1 AND old_key=?2",
        params![ws, key],
    )?;
    Ok(())
}

/// The key a message from `ws` must be signed with, or why there is none.
fn usable_key(c: &Connection, ws: &str) -> Res<[u8; 32]> {
    let Some(k) = current_key(c, ws)? else {
        return Err(sig_err(
            StatusCode::UNPROCESSABLE_ENTITY,
            "unknown_key",
            "This workspace has no signing key at the relay yet.",
        ));
    };
    match ended(c, ws, &k).as_deref() {
        Some("withdrawn") => {
            return Err(sig_err(
                StatusCode::UNPROCESSABLE_ENTITY,
                "key_withdrawn",
                "This workspace's signing key was withdrawn. A new key needs the relay admin's approval.",
            ))
        }
        Some(_) => {
            return Err(sig_err(
                StatusCode::UNPROCESSABLE_ENTITY,
                "key_blocked",
                "The relay admin blocked this workspace's signing key.",
            ))
        }
        None => {}
    }
    signkeys::parse_public(&k).map_err(|_| {
        sig_err(
            StatusCode::UNPROCESSABLE_ENTITY,
            "unknown_key",
            "This workspace's stored signing key is not usable.",
        )
    })
}

/// `{state, pending_change}` shown next to `signing_key` in whoami and the directory (a hint, like the key).
pub fn state_info(c: &Connection, ws: &str) -> Value {
    let Ok(Some(k)) = current_key(c, ws) else {
        return Value::Null;
    };
    let state = ended(c, ws, &k).unwrap_or_else(|| "active".into());
    let pending: Option<String> = c
        .query_row(
            "SELECT new_key FROM sign_key_change WHERE ws=?1",
            [ws],
            |r| r.get(0),
        )
        .optional()
        .ok()
        .flatten();
    json!({"state": state, "pending_change": pending.is_some()})
}

// ------------------------------------------------------------------ the message gate

/// What the gate decided for one `POST /v1/messages`.
pub enum Gate {
    /// No envelope and the switch is off: the old path.
    Unsigned,
    /// Signed and new: store `envelope` with the message and `digest` (sha256 hex of the signed bytes).
    Signed { envelope: Value, digest: String },
    /// The same signed bytes again.
    Duplicate,
}

fn same(outer: &Value, signed: &Map<String, Value>, k: &str) -> bool {
    let o = outer.get(k).filter(|v| !v.is_null());
    let s = signed.get(k).filter(|v| !v.is_null());
    o == s
}

/// Take the `envelope` out of `msg` (from the authenticated workspace `me`) and check it. The caller keeps doing
/// its own checks (schema, rules) on the rest of `msg`.
pub fn check(c: &Connection, me: &str, msg: &mut Value) -> Res<Gate> {
    let env = msg.as_object_mut().and_then(|o| o.remove("envelope"));
    let Some(env) = env else {
        if require_signed(c) {
            return Err(refused(SigError::MissingSignature));
        }
        return Ok(Gate::Unsigned);
    };
    let key = usable_key(c, me)?;
    let lookup = |id: &str| -> Option<String> {
        c.query_row(
            "SELECT COALESCE(sig_digest, '') FROM messages WHERE id=?1",
            [id],
            |r| r.get(0),
        )
        .optional()
        .ok()
        .flatten()
    };
    let (outcome, v) = msgsig::relay_check(&env, me, &[key], lookup).map_err(refused)?;
    // the outer message must say what the signed bytes say (receivers read only the envelope)
    let to_ok = match v.msg.get("to") {
        Some(Value::String(_)) => same(msg, &v.msg, "to"),
        // a group message: the receiver checks the group; the relay delivers to one workspace
        Some(Value::Object(_)) => msg["to"].as_str().is_some_and(|t| t.starts_with("ws_")),
        _ => false,
    };
    let fields_ok = ["id", "from", "type", "ticket", "reply_to", "body"]
        .iter()
        .all(|k| same(msg, &v.msg, k));
    if !(to_ok && fields_ok) {
        return Err(sig_err(
            StatusCode::UNPROCESSABLE_ENTITY,
            "signed_mismatch",
            "The message says something other than its signed bytes.",
        ));
    }
    check_files(c, &v.msg)?;
    if outcome == RelayOutcome::Duplicate {
        return Ok(Gate::Duplicate);
    }
    Ok(Gate::Signed {
        envelope: env,
        digest: hex::encode(Sha256::digest(&v.signed)),
    })
}

/// Every signed file must be the blob the relay holds: same size and hash.
fn check_files(c: &Connection, m: &Map<String, Value>) -> Res<()> {
    for f in m
        .get("files")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let id = f["blob_id"].as_str().unwrap_or("");
        let row: Option<(i64, String)> = c
            .query_row("SELECT size, sha256 FROM blobs WHERE id=?1", [id], |r| {
                Ok((r.get(0)?, r.get(1)?))
            })
            .optional()?;
        let ok = row.is_some_and(|(size, sha)| {
            Some(size) == f["size"].as_i64()
                && f["sha256"]
                    .as_str()
                    .is_some_and(|h| h.eq_ignore_ascii_case(&sha))
        });
        if !ok {
            return Err(sig_err(
                StatusCode::UNPROCESSABLE_ENTITY,
                "signed_mismatch",
                "A signed file is not the file the relay holds.",
            ));
        }
    }
    Ok(())
}

/// Store the signed bytes' digest next to the message just inserted.
pub fn mark(c: &Connection, id: &str, digest: &str) -> rusqlite::Result<()> {
    c.execute(
        "UPDATE messages SET sig_digest=?2 WHERE id=?1",
        params![id, digest],
    )?;
    Ok(())
}

// ------------------------------------------------------------------ key statements (workspace side)

fn int_field(m: &Map<String, Value>, k: &str) -> Option<i64> {
    m.get(k)
        .filter(|v| v.is_i64() || v.is_u64())
        .and_then(Value::as_i64)
}

fn statement_fields(m: &Map<String, Value>, typ: &str, allowed: &[&str]) -> Res<()> {
    if let Some(k) = m.keys().find(|k| !allowed.contains(&k.as_str())) {
        return Err(sig_err(
            StatusCode::UNPROCESSABLE_ENTITY,
            "bad_field",
            format!("Unknown field `{k}` in the signed statement."),
        ));
    }
    if int_field(m, "v") != Some(1)
        || m.get("type").and_then(Value::as_str) != Some(typ)
        || int_field(m, "created_ms").is_none_or(|t| t < 0)
    {
        return Err(sig_err(
            StatusCode::UNPROCESSABLE_ENTITY,
            "bad_field",
            format!("The signed statement must carry v 1, type \"{typ}\", from, key ids and created_ms."),
        ));
    }
    Ok(())
}

/// `POST /v1/me/signing-key/change` `{"envelope": <key-rotate statement>, "new_sig": "<b64url>"}`.
///
/// Statement (signed, purpose `key-rotate`): `{"v":1,"type":"key-rotate","from":<ws>,"old_key_id":<id or null>,
/// "new_public_key":<43 chars>,"created_ms":<int>}`.
/// - Signed by the current key: `old_key_id` is its id and `new_sig` is the new key's signature over the same
///   input (it shows the workspace holds the new key).
/// - Without the old key: `old_key_id` is null, the envelope is signed by the new key and `new_sig` is left out.
///
/// 202 held for the relay admin; a newer request replaces an older pending one.
pub async fn change(
    State(app): State<AppState>,
    h: HeaderMap,
    body: Bytes,
) -> Res<(StatusCode, Json<Value>)> {
    let v = crate::api::parse_body(&body)?;
    let o = v
        .as_object()
        .ok_or_else(|| invalid("Send {\"envelope\": …, \"new_sig\": …}."))?;
    if let Some(k) = o.keys().find(|k| *k != "envelope" && *k != "new_sig") {
        return Err(invalid(format!("Unknown field `{k}`.")));
    }
    let env = o.get("envelope").cloned().unwrap_or(Value::Null);
    let e = msgsig::read_envelope(&env).map_err(refused)?;
    let stmt = msgsig::read_strict_json(&e.signed).map_err(|x| refused(SigError::BadJson(x)))?;
    statement_fields(
        &stmt,
        "key-rotate",
        &[
            "v",
            "type",
            "from",
            "old_key_id",
            "new_public_key",
            "created_ms",
        ],
    )?;
    let new_pk = stmt
        .get("new_public_key")
        .and_then(Value::as_str)
        .ok_or_else(|| invalid("`new_public_key` is missing."))?
        .to_string();
    let new_raw = signkeys::parse_public(&new_pk).map_err(invalid)?;
    if !msgsig::registration_key_ok(&new_raw) {
        return Err(invalid("`new_public_key` is not a usable Ed25519 key."));
    }
    let c = app.db.lock().unwrap();
    let me = crate::auth::workspace(&c, &h)?;
    if stmt.get("from").and_then(Value::as_str) != Some(me.as_str()) {
        return Err(refused(SigError::WrongSender));
    }
    let Some(cur) = current_key(&c, &me)? else {
        return Err(invalid(
            "This workspace has no signing key yet: register it with PUT /v1/me/signing-key.",
        ));
    };
    if cur == new_pk || ended(&c, &me, &new_pk).is_some() {
        return Err(invalid(
            "The new key must be a key this workspace never used before.",
        ));
    }
    let input = msgsig::signature_input("key-rotate", &e.signed);
    let kind =
        match stmt.get("old_key_id") {
            Some(Value::String(old_id)) => {
                let cur_raw = signkeys::parse_public(&cur).map_err(invalid)?;
                if *old_id != signkeys::key_id(&cur_raw) || e.key_id != *old_id {
                    return Err(refused(SigError::UnknownKey));
                }
                if let Some(st) = ended(&c, &me, &cur) {
                    // a withdrawn or blocked key never vouches for a replacement
                    return Err(sig_err(
                    StatusCode::UNPROCESSABLE_ENTITY,
                    if st == "withdrawn" { "key_withdrawn" } else { "key_blocked" },
                    "The old key no longer counts; send the change without it (old_key_id null).",
                ));
                }
                if !msgsig::verify_raw(&cur_raw, &input, &e.sig) {
                    return Err(refused(SigError::BadSignature));
                }
                let ns = o
                    .get("new_sig")
                    .and_then(Value::as_str)
                    .and_then(msgsig::b64url_decode_strict)
                    .ok_or_else(|| refused(SigError::MissingSignature))?;
                if !msgsig::verify_raw(&new_raw, &input, &ns) {
                    return Err(refused(SigError::BadSignature));
                }
                "signed"
            }
            Some(Value::Null) => {
                if o.contains_key("new_sig") {
                    return Err(invalid(
                        "`new_sig` is only for a change signed by the old key.",
                    ));
                }
                if e.key_id != signkeys::key_id(&new_raw)
                    || !msgsig::verify_raw(&new_raw, &input, &e.sig)
                {
                    return Err(refused(SigError::BadSignature));
                }
                "no_old_key"
            }
            _ => return Err(invalid("`old_key_id` must be the old key's id or null.")),
        };
    let old = (kind == "signed").then_some(cur.clone());
    c.execute(
        "INSERT INTO sign_key_change(ws, new_key, kind, old_key, requested_at) VALUES(?1,?2,?3,?4,?5)
         ON CONFLICT(ws) DO UPDATE SET new_key=excluded.new_key, kind=excluded.kind, old_key=excluded.old_key,
           requested_at=excluded.requested_at",
        params![me, new_pk, kind, old, now()],
    )?;
    Ok((
        StatusCode::ACCEPTED,
        Json(json!({"status": "pending", "kind": kind, "key_id": signkeys::key_id(&new_raw)})),
    ))
}

/// `POST /v1/me/signing-key/withdraw` `{"envelope": <key-withdraw statement>}`. Statement (signed by the key it
/// withdraws, purpose `key-withdraw`): `{"v":1,"type":"key-withdraw","from":<ws>,"key_id":<id>,"created_ms":<int>}`.
/// 200; from then on messages and key changes signed by that key are refused.
pub async fn withdraw(State(app): State<AppState>, h: HeaderMap, body: Bytes) -> Res<Json<Value>> {
    let v = crate::api::parse_body(&body)?;
    let o = v
        .as_object()
        .ok_or_else(|| invalid("Send {\"envelope\": …}."))?;
    if let Some(k) = o.keys().find(|k| *k != "envelope") {
        return Err(invalid(format!("Unknown field `{k}`.")));
    }
    let env = o.get("envelope").cloned().unwrap_or(Value::Null);
    let c = app.db.lock().unwrap();
    let me = crate::auth::workspace(&c, &h)?;
    let Some(cur) = current_key(&c, &me)? else {
        return Err(refused(SigError::UnknownKey));
    };
    let raw = signkeys::parse_public(&cur).map_err(invalid)?;
    let ver = msgsig::verify(&env, "key-withdraw", &[(me.clone(), raw)]).map_err(refused)?;
    statement_fields(
        &ver.msg,
        "key-withdraw",
        &["v", "type", "from", "key_id", "created_ms"],
    )?;
    if ver.msg.get("from").and_then(Value::as_str) != Some(me.as_str()) {
        return Err(refused(SigError::WrongSender));
    }
    if ver.msg.get("key_id").and_then(Value::as_str) != Some(signkeys::key_id(&raw).as_str()) {
        return Err(invalid(
            "`key_id` must be the id of the key that signs the statement.",
        ));
    }
    if ended(&c, &me, &cur).is_none() {
        end_key(&c, &me, &cur, "withdrawn")?;
    }
    Ok(Json(
        json!({"status": "withdrawn", "key_id": signkeys::key_id(&raw)}),
    ))
}

// ------------------------------------------------------------------ admin

fn key_card(pk: &str) -> Value {
    match signkeys::parse_public(pk) {
        Ok(raw) => json!({"public_key": pk, "key_id": signkeys::key_id(&raw),
            "fingerprint": msgsig::fingerprint(&raw)}),
        Err(_) => json!({"public_key": pk, "key_id": null, "fingerprint": null}),
    }
}

/// `GET /admin/api/signing-keys`: the switch and, per workspace, its key, its state, a pending change and the keys
/// that ended.
pub async fn admin_list(State(app): State<AppState>, h: HeaderMap) -> Res<Json<Value>> {
    crate::auth::admin(&app, &h)?;
    let c = app.db.lock().unwrap();
    let mut st = c.prepare(
        "SELECT id, name, sign_key, sign_key_at FROM workspaces ORDER BY name COLLATE NOCASE",
    )?;
    let rows: Vec<(String, String, Option<String>, Option<i64>)> = st
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))?
        .collect::<Result<_, _>>()?;
    let mut out = vec![];
    for (id, name, key, at) in rows {
        let current = key.as_deref().map(|k| {
            let mut card = key_card(k);
            card["state"] = ended(&c, &id, k).unwrap_or_else(|| "active".into()).into();
            card["registered_at"] = at.map(fmt_time).into();
            card
        });
        let pending: Option<Value> = c
            .query_row(
                "SELECT new_key, kind, requested_at FROM sign_key_change WHERE ws=?1",
                [&id],
                |r| {
                    let mut card = key_card(&r.get::<_, String>(0)?);
                    card["kind"] = r.get::<_, String>(1)?.into();
                    card["requested_at"] = fmt_time(r.get(2)?).into();
                    Ok(card)
                },
            )
            .optional()?;
        let mut hs = c.prepare(
            "SELECT public_key, state, at FROM sign_key_ended WHERE ws=?1 AND public_key<>COALESCE(?2,'')
             ORDER BY at DESC LIMIT 20",
        )?;
        let ended_keys: Vec<Value> = hs
            .query_map(params![id, key], |r| {
                let mut card = key_card(&r.get::<_, String>(0)?);
                card["state"] = r.get::<_, String>(1)?.into();
                card["at"] = fmt_time(r.get(2)?).into();
                Ok(card)
            })?
            .collect::<Result<_, _>>()?;
        out.push(
            json!({"workspace": id, "name": name, "key": current, "pending": pending,
            "ended": ended_keys}),
        );
    }
    Ok(Json(
        json!({"require_signed": require_signed(&c), "workspaces": out}),
    ))
}

fn key_id_in(body: &Bytes) -> Res<String> {
    let v = crate::api::parse_body(body)?;
    v["key_id"]
        .as_str()
        .filter(|s| s.len() == 16)
        .map(str::to_string)
        .ok_or_else(|| invalid("Send {\"key_id\": \"<the key id shown on the page>\"}."))
}

fn stale() -> ApiError {
    sig_err(
        StatusCode::CONFLICT,
        "stale",
        "This key change is no longer the one waiting. Reload the page.",
    )
}

fn pending_of(c: &Connection, ws: &str) -> rusqlite::Result<Option<(String, String)>> {
    c.query_row(
        "SELECT new_key, kind FROM sign_key_change WHERE ws=?1",
        [ws],
        |r| Ok((r.get(0)?, r.get(1)?)),
    )
    .optional()
}

fn kid_of(pk: &str) -> String {
    signkeys::parse_public(pk)
        .map(|r| signkeys::key_id(&r))
        .unwrap_or_default()
}

/// `POST /admin/api/signing-keys/:ws/approve` `{"key_id": <pending new key id>}`: the new key replaces the old one.
pub async fn admin_approve(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(ws): Path<String>,
    body: Bytes,
) -> Res<Json<Value>> {
    crate::auth::admin(&app, &h)?;
    let kid = key_id_in(&body)?;
    let c = app.db.lock().unwrap();
    let Some((new_key, _)) = pending_of(&c, &ws)?.filter(|(k, _)| kid_of(k) == kid) else {
        return Err(stale());
    };
    if ended(&c, &ws, &new_key).is_some() {
        return Err(stale());
    }
    c.execute_batch("SAVEPOINT sign_approve")?;
    let done = (|| -> rusqlite::Result<()> {
        if let Some(old) = current_key(&c, &ws)? {
            if ended(&c, &ws, &old).is_none() {
                end_key(&c, &ws, &old, "replaced")?;
            }
        }
        c.execute(
            "UPDATE workspaces SET sign_key=?2, sign_key_at=?3 WHERE id=?1",
            params![ws, new_key, now()],
        )?;
        c.execute("DELETE FROM sign_key_change WHERE ws=?1", [&ws])?;
        Ok(())
    })();
    match done {
        Ok(()) => c.execute_batch("RELEASE sign_approve")?,
        Err(e) => {
            let _ = c.execute_batch("ROLLBACK TO sign_approve; RELEASE sign_approve");
            return Err(e.into());
        }
    }
    let rel = crate::store::related(&c, &ws);
    crate::store::bump_and_hint(&c, &app.key, &rel)?;
    drop(c);
    app.notify.notify_waiters();
    Ok(Json(json!({"status": "approved", "key_id": kid})))
}

/// `POST /admin/api/signing-keys/:ws/reject` `{"key_id": <pending new key id>}`: the change is dropped.
pub async fn admin_reject(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(ws): Path<String>,
    body: Bytes,
) -> Res<Json<Value>> {
    crate::auth::admin(&app, &h)?;
    let kid = key_id_in(&body)?;
    let c = app.db.lock().unwrap();
    if !pending_of(&c, &ws)?.is_some_and(|(k, _)| kid_of(&k) == kid) {
        return Err(stale());
    }
    c.execute("DELETE FROM sign_key_change WHERE ws=?1", [&ws])?;
    Ok(Json(json!({"status": "rejected", "key_id": kid})))
}

/// `POST /admin/api/signing-keys/:ws/block` `{"key_id": <current key id>}`: the key is refused from now on and
/// never vouches for a replacement. Final for that key.
pub async fn admin_block(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(ws): Path<String>,
    body: Bytes,
) -> Res<Json<Value>> {
    crate::auth::admin(&app, &h)?;
    let kid = key_id_in(&body)?;
    let c = app.db.lock().unwrap();
    let Some(cur) = current_key(&c, &ws)?.filter(|k| kid_of(k) == kid) else {
        return Err(stale());
    };
    if ended(&c, &ws, &cur).is_none() {
        end_key(&c, &ws, &cur, "blocked")?;
    }
    let rel = crate::store::related(&c, &ws);
    crate::store::bump_and_hint(&c, &app.key, &rel)?;
    drop(c);
    app.notify.notify_waiters();
    Ok(Json(json!({"status": "blocked", "key_id": kid})))
}

/// `PUT /admin/api/signing-keys/settings` `{"require_signed": true|false}`.
pub async fn admin_settings(
    State(app): State<AppState>,
    h: HeaderMap,
    body: Bytes,
) -> Res<Json<Value>> {
    crate::auth::admin(&app, &h)?;
    let v = crate::api::parse_body(&body)?;
    let on = v["require_signed"]
        .as_bool()
        .ok_or_else(|| invalid("`require_signed` must be true or false."))?;
    let c = app.db.lock().unwrap();
    set_require_signed(&c, on)?;
    Ok(Json(json!({"require_signed": on})))
}

/// For tests and tools: the base64url form of a raw key.
pub fn b64(raw: &[u8]) -> String {
    URL_SAFE_NO_PAD.encode(raw)
}
