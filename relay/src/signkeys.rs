//! Signing keys of workspaces (ORCH-1027 design note section 2, ORCH-1200): each workspace makes its own
//! Ed25519 key pair and registers the public half here with `PUT /v1/me/signing-key`. The relay keeps it and
//! shows it in whoami and in the directory as a HINT only: a receiver trusts a key only after a person
//! accepted its fingerprint. The private key never comes here.
//!
//! A key is the raw 32 bytes, base64url without padding (43 characters). Refused: other lengths, a point that
//! is not on the curve, a non-canonical encoding and a small-order (weak) key. A workspace that already has a
//! key cannot replace it here: a key change is a statement signed by the old key (a later ticket), so a stolen
//! relay token alone cannot swap the key.
use crate::error::*;
use crate::state::AppState;
use crate::util::*;
use axum::body::Bytes;
use axum::extract::State;
use axum::http::{HeaderMap, StatusCode};
use axum::Json;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

pub const ALG: &str = "ed25519";

/// The raw key from its wire form, or why it is refused (plain words).
pub fn parse_public(s: &str) -> Result<[u8; 32], &'static str> {
    if s.len() != 43 {
        return Err("`public_key` must be 32 bytes in base64url without padding (43 characters).");
    }
    let raw = URL_SAFE_NO_PAD
        .decode(s)
        .map_err(|_| "`public_key` is not base64url without padding.")?;
    let raw: [u8; 32] = raw
        .try_into()
        .map_err(|_| "`public_key` must be exactly 32 bytes.")?;
    // base64url of 32 bytes leaves 2 spare bits in the last character: they must be zero (one spelling).
    if URL_SAFE_NO_PAD.encode(raw) != s {
        return Err("`public_key` is not written the one canonical way.");
    }
    let vk = ed25519_dalek::VerifyingKey::from_bytes(&raw)
        .map_err(|_| "`public_key` is not a valid Ed25519 key.")?;
    if vk.to_edwards().compress().to_bytes() != raw {
        return Err("`public_key` is not written the one canonical way.");
    }
    if vk.is_weak() {
        return Err("`public_key` is a weak (small-order) key.");
    }
    // the same rule as a key change (msgsig::registration_key_ok): no torsion part, so every library agrees
    if !vk.to_edwards().is_torsion_free() {
        return Err("`public_key` is not a valid Ed25519 key.");
    }
    Ok(raw)
}

/// Key id: the first 16 hex characters of SHA-256("ed25519" + raw key). An index only, never the trust decision.
pub fn key_id(raw: &[u8; 32]) -> String {
    let mut h = Sha256::new();
    h.update(ALG.as_bytes());
    h.update(raw);
    hex::encode(h.finalize())[..16].to_string()
}

/// `{alg, public_key, key_id, registered_at}` of a workspace, or `null` when it has registered none yet.
pub fn info(c: &Connection, ws: &str) -> Value {
    let row: Option<(Option<String>, Option<i64>)> = c
        .query_row(
            "SELECT sign_key, sign_key_at FROM workspaces WHERE id=?1",
            [ws],
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

/// `PUT /v1/me/signing-key` `{"alg": "ed25519", "public_key": "<43 chars>"}` (workspace auth).
/// 201 stored, 200 the same key again (unchanged), 409 `key_exists` for a different key, 422 a bad key.
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
    let raw = parse_public(pk).map_err(invalid)?;
    let c = app.db.lock().unwrap();
    let me = crate::auth::workspace(&c, &h)?;
    let cur: Option<String> =
        c.query_row("SELECT sign_key FROM workspaces WHERE id=?1", [&me], |r| {
            r.get(0)
        })?;
    let out = |status: &str| {
        let mut i = info(&c, &me);
        i["status"] = status.into();
        i
    };
    match cur {
        Some(k) if k == pk => Ok((StatusCode::OK, Json(out("unchanged")))),
        Some(_) => Err(ApiError {
            status: StatusCode::CONFLICT,
            code: "key_exists",
            message: "This workspace already has a signing key. A new key needs a change signed by the old one."
                .into(),
        }),
        None => {
            // Only while the token that authenticated this call is current, and only when still empty.
            let tok = crate::auth::bearer(&h).map(token_hash).unwrap_or_default();
            let n = c.execute(
                "UPDATE workspaces SET sign_key=?3, sign_key_at=?4 WHERE id=?1 AND token_hash=?2 AND sign_key IS NULL",
                params![me, tok, pk, now()],
            )?;
            if n == 0 {
                return Err(unauthorized());
            }
            debug_assert_eq!(key_id(&raw).len(), 16);
            Ok((StatusCode::CREATED, Json(out("stored"))))
        }
    }
}
