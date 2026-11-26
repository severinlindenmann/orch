//! The relay's first gate for what a phone sends (ORCH-1204; contracts/msgsig.md). `POST /v1/phone/send` may carry
//! an `envelope`: the phone's signature over the message it wrote itself. The relay checks it against the key the
//! phone sent when it was paired, makes sure the request says exactly what the signed bytes say (so the relay
//! stores the person's own words), keeps the signed message id, and hands the envelope to the workspace unchanged.
//! The workspace checks it again itself (the decisive gate) and never trusts the relay for it.
//!
//! Without an envelope the old path stays until the hard cut turns on "signed only" (ORCH-1205).
use crate::error::*;
use crate::msgsig::{self, RelayOutcome, SigError};
use axum::http::StatusCode;
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

pub fn init(c: &Connection) {
    // Shared with the workspace gate (ORCH-1201): sha256 of the signed bytes, for duplicates and replays.
    let _ = c.execute("ALTER TABLE messages ADD COLUMN sig_digest TEXT", []);
}

pub enum Gate {
    /// No envelope: the old path.
    Unsigned,
    /// Signed and new: store the message under `id` with `envelope`, then `mark` it with `digest`.
    Signed {
        id: String,
        envelope: Value,
        digest: String,
    },
    /// The same signed bytes again (a retry): answer with the stored id.
    Duplicate(String),
}

fn refused(e: SigError) -> ApiError {
    let status = match e {
        SigError::WrongSender => StatusCode::FORBIDDEN,
        SigError::Replayed => StatusCode::CONFLICT,
        _ => StatusCode::UNPROCESSABLE_ENTITY,
    };
    ApiError {
        status,
        code: e.code(),
        message: format!("The message signature was refused ({}).", e.code()),
    }
}

fn mismatch(what: &str) -> ApiError {
    ApiError {
        status: StatusCode::UNPROCESSABLE_ENTITY,
        code: "signed_mismatch",
        message: format!("The request does not say what the signed message says ({what})."),
    }
}

fn same(outer: Option<&str>, signed: &Map<String, Value>, k: &str) -> bool {
    outer == signed.get(k).and_then(Value::as_str)
}

/// Check the `envelope` the send request carried (taken out before the schema check). `body` is the message body the relay built from
/// the request, `blobs` the files the request names. The caller keeps its own checks (schema, pairing, limits).
#[allow(clippy::too_many_arguments)]
pub fn check(
    c: &Connection,
    pid: &str,
    env: Option<Value>,
    to: &str,
    ticket: Option<&str>,
    reply_to: Option<&str>,
    body: &Value,
    blobs: &[String],
) -> Res<Gate> {
    let Some(env) = env else {
        // the hard cut covers the phone too: once "signed only" is on, no unsigned send (a read error refuses)
        if crate::signgate::require_signed(c)? {
            return Err(refused(SigError::MissingSignature));
        }
        return Ok(Gate::Unsigned);
    };
    let key = crate::phonekeys::raw_key(c, pid).ok_or_else(|| refused(SigError::UnknownKey))?;
    let read_err = std::cell::RefCell::new(None);
    let lookup = |id: &str| -> Option<String> { crate::msgsig::stored_digest(c, id, &read_err) };
    let (outcome, ver) = msgsig::relay_check(&env, pid, &[key], lookup).map_err(refused)?;
    // a read error is never "not seen before" (fail closed)
    if let Some(e) = read_err.into_inner() {
        return Err(e.into());
    }
    let m = &ver.msg;
    let id = m["id"].as_str().unwrap_or_default().to_string();
    // A retry must say the same as the signed bytes too (checked before it is answered as a duplicate).
    if m.get("type").and_then(Value::as_str) != Some("text") {
        return Err(mismatch("type"));
    }
    if m.get("origin").and_then(Value::as_str) != Some("person") {
        return Err(mismatch("origin"));
    }
    if !same(Some(to), m, "to") {
        return Err(mismatch("to"));
    }
    if !same(ticket, m, "ticket") {
        return Err(mismatch("ticket"));
    }
    if !same(reply_to, m, "reply_to") {
        return Err(mismatch("reply_to"));
    }
    if m.get("body") != Some(body) {
        return Err(mismatch("body"));
    }
    if matches!(outcome, RelayOutcome::Duplicate) {
        return Ok(Gate::Duplicate(id));
    }
    // Every file the request names is listed in the signed bytes with the stored size and hash, and nothing else.
    let signed_files: Vec<&Value> = m
        .get("files")
        .and_then(Value::as_array)
        .map(|a| a.iter().collect())
        .unwrap_or_default();
    if signed_files.len() != blobs.len() {
        return Err(mismatch("files"));
    }
    // one to one: a file named twice ([A, A] against signed [A, B]) never passes
    let named: std::collections::HashSet<&str> = blobs.iter().map(String::as_str).collect();
    if named.len() != blobs.len() {
        return Err(mismatch("files"));
    }
    for b in blobs {
        let stored: Option<(i64, String)> = c
            .query_row(
                "SELECT size, sha256 FROM blobs WHERE id=?1 AND uploader=?2",
                [b, pid],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        let ok = stored.is_some_and(|(size, sha)| {
            signed_files.iter().any(|f| {
                f["blob_id"].as_str() == Some(b.as_str())
                    && f["size"].as_i64() == Some(size)
                    && f["sha256"].as_str() == Some(sha.as_str())
            })
        });
        if !ok {
            return Err(mismatch("files"));
        }
    }
    let digest = hex::encode(Sha256::digest(&ver.signed));
    Ok(Gate::Signed {
        id,
        envelope: env,
        digest,
    })
}

pub fn mark(c: &Connection, id: &str, digest: &str) -> rusqlite::Result<()> {
    c.execute(
        "UPDATE messages SET sig_digest=?2 WHERE id=?1",
        params![id, digest],
    )?;
    Ok(())
}
