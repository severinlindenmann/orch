//! Webhooks: created by workspaces, called by the outside world, delivered as `webhook` messages.
use crate::error::*;
use crate::state::{AppState, WebhookLimit};
use crate::store;
use crate::util::*;
use crate::{api::parse_body, auth};
use axum::body::Bytes;
use axum::extract::{Path, Query, State};
use axum::http::{header, HeaderMap, Method, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::Json;
use rusqlite::{params, OptionalExtension};
use serde_json::{json, Map, Value};
use std::collections::HashMap;

const MAX_PAYLOAD: usize = 1024 * 1024;

pub async fn create(
    State(app): State<AppState>,
    h: HeaderMap,
    body: Bytes,
) -> Res<(StatusCode, Json<Value>)> {
    let v = parse_body(&body)?;
    let mode = v["mode"].as_str().unwrap_or("");
    if mode != "once" && mode != "permanent" {
        return Err(invalid("`mode` must be once or permanent."));
    }
    let ticket = v["ticket"].as_str();
    if let Some(t) = ticket {
        let ok = t.len() >= 8
            && t.len() <= 18
            && t.starts_with("t_")
            && t[2..]
                .bytes()
                .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit());
        if !ok {
            return Err(invalid("`ticket` must look like t_7k3f9q."));
        }
    }
    let c = app.db.lock().unwrap();
    let me = auth::workspace(&c, &h)?;
    let id = rand_id("wh_", 10);
    let token = rand_token("whk_", 16);
    c.execute(
        "INSERT INTO webhooks(id,workspace,mode,ticket,token_hash,created_at) VALUES(?1,?2,?3,?4,?5,?6)",
        params![id, me, mode, ticket, token_hash(&token), now()],
    )?;
    let url = format!("{}/webhook/{id}?token={token}", app.cfg.public_url);
    Ok((StatusCode::CREATED, Json(json!({"id": id, "url": url}))))
}

pub fn row_json(r: &rusqlite::Row, with_ws: bool) -> rusqlite::Result<Value> {
    let last: Option<i64> = r.get(5)?;
    let mut o = json!({"id": r.get::<_, String>(0)?, "mode": r.get::<_, String>(2)?,
        "ticket": r.get::<_, Option<String>>(3)?, "created_at": fmt_time(r.get(4)?),
        "last_call_at": last.map(fmt_time)});
    if with_ws {
        o["workspace"] = r.get::<_, String>(1)?.into();
    }
    Ok(o)
}

pub const COLS: &str = "id,workspace,mode,ticket,created_at,last_call_at";

pub async fn list(State(app): State<AppState>, h: HeaderMap) -> Res<Json<Value>> {
    let c = app.db.lock().unwrap();
    let me = auth::workspace(&c, &h)?;
    let items: Vec<Value> = c
        .prepare(&format!(
            "SELECT {COLS} FROM webhooks WHERE workspace=?1 ORDER BY created_at DESC, id"
        ))?
        .query_map([me], |r| row_json(r, false))?
        .collect::<Result<_, _>>()?;
    Ok(Json(json!({"items": items, "next": null})))
}

pub async fn remove(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
) -> Res<StatusCode> {
    let c = app.db.lock().unwrap();
    let me = auth::workspace(&c, &h)?;
    let n = c.execute(
        "DELETE FROM webhooks WHERE id=?1 AND workspace=?2",
        params![id, me],
    )?;
    if n == 0 {
        return Err(not_found("No such webhook."));
    }
    Ok(StatusCode::NO_CONTENT)
}

/// GET/POST/PUT /webhook/<id>?token=whk_...
pub async fn call(
    State(app): State<AppState>,
    method: Method,
    Path(id): Path<String>,
    Query(q): Query<HashMap<String, String>>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    let (err, secs) = match deliver(app, method, id, q, headers, body) {
        Ok(Ok(s)) => return s.into_response(),
        Err(e) => return e.into_response(),
        Ok(Err(WebhookLimit::Calls(s))) => (webhook_limited(false), s),
        Ok(Err(WebhookLimit::Bytes(s))) => (webhook_limited(true), s),
    };
    let mut r = err.into_response();
    r.headers_mut().insert(header::RETRY_AFTER, secs.into());
    r
}

fn deliver(
    app: AppState,
    method: Method,
    id: String,
    mut q: HashMap<String, String>,
    headers: HeaderMap,
    body: Bytes,
) -> Res<Result<StatusCode, WebhookLimit>> {
    let token = q.remove("token").unwrap_or_default();
    if body.len() > MAX_PAYLOAD {
        return Err(too_large("The body can be at most 1 MB."));
    }
    let mut kept = Map::new();
    for (k, v) in headers.iter() {
        let k = k.as_str();
        if matches!(k, "x-github-event" | "x-github-delivery" | "user-agent")
            || k.starts_with("x-orch-")
        {
            kept.insert(k.to_string(), v.to_str().unwrap_or("").into());
        }
    }
    let content_type = headers
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let wh_body = json!({"webhook_id": id, "method": method.as_str(), "content_type": content_type,
        "headers": kept, "query": q, "payload": String::from_utf8_lossy(&body)});

    let mut c = app.db.lock().unwrap();
    let row: Option<(String, String, Option<String>, String)> = c
        .query_row(
            "SELECT workspace,mode,ticket,token_hash FROM webhooks WHERE id=?1",
            [&id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
        )
        .optional()?;
    let Some((ws, mode, ticket, hash)) = row else {
        return Err(not_found("No such webhook."));
    };
    if !ct_eq(&hash, &token_hash(&token)) {
        return Err(unauthorized());
    }
    // Counted only after the token check and before anything is stored or a `once` webhook is used up.
    if let Err(limit) = app.webhook_admit(&id, body.len() as u64, now()) {
        return Ok(Err(limit));
    }
    // One transaction: a `once` webhook is used up in the same step that stores the message.
    let tx = c.transaction()?;
    let n = tx.execute(
        "UPDATE webhooks SET last_call_at=?2, used=1 WHERE id=?1 AND (mode='permanent' OR used=0)",
        params![id, now()],
    )?;
    if n == 0 {
        return Err(gone("This webhook was already used."));
    }
    let from = format!("webhook:{id}");
    store::system_message(
        &tx,
        &app.key,
        &from,
        &ws,
        "webhook",
        ticket.as_deref(),
        None,
        wh_body,
    )?;
    let _ = mode;
    tx.commit()?;
    drop(c);
    app.notify.notify_waiters();
    Ok(Ok(StatusCode::ACCEPTED))
}
