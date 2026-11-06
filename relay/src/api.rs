//! Public listener: workspace API, public routes. Phone routes are in phone.rs.
use crate::error::*;
use crate::state::AppState;
use crate::store::{self, msg_from_row, msg_json, MSG_COLS};
use crate::util::*;
use crate::{auth, crypto, rules};
use axum::body::{Body, Bytes};
use axum::extract::{DefaultBodyLimit, Path, Query, State};
use axum::http::{header, HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{delete, get, post};
use axum::{Json, Router};
use futures_util::StreamExt;
use rusqlite::{params, OptionalExtension};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::time::{Duration, Instant};

pub const MAX_BLOB: usize = 100 * 1024 * 1024;
const MAX_JSON: usize = 2 * 1024 * 1024;

pub fn router(app: AppState) -> Router {
    Router::new()
        .route("/health", get(|| async { "ok" }))
        .route("/onboarding.sh", get(crate::onboarding::sh))
        .route("/onboarding.ps1", get(crate::onboarding::ps1))
        .route(
            "/webhook/:id",
            get(crate::webhooks::call)
                .post(crate::webhooks::call)
                .put(crate::webhooks::call),
        )
        .route("/", get(root_page))
        .route("/v1/whoami", get(whoami))
        .route("/v1/me", axum::routing::patch(patch_me))
        .route("/v1/messages", post(post_message))
        .route("/v1/inbox", get(inbox))
        .route("/v1/inbox/ack", post(ack))
        .route(
            "/v1/blobs",
            post(post_blob).layer(DefaultBodyLimit::max(MAX_BLOB + 1024)),
        )
        .route("/v1/blobs/:id", get(get_blob))
        .route(
            "/v1/webhooks",
            post(crate::webhooks::create).get(crate::webhooks::list),
        )
        .route("/v1/webhooks/:id", delete(crate::webhooks::remove))
        .route("/v1/refresh", get(refresh))
        .route(
            "/v1/transcribe",
            post(crate::transcribe::workspace)
                .layer(DefaultBodyLimit::max(crate::transcribe::MAX_AUDIO + 1024)),
        )
        .merge(crate::phone::router())
        .merge(icon_routes())
        .fallback(not_found_page)
        .layer(DefaultBodyLimit::max(MAX_JSON))
        .with_state(app)
}

pub fn parse_body(b: &Bytes) -> Res<Value> {
    serde_json::from_slice(b).map_err(|e| invalid(format!("Body is not valid JSON: {e}")))
}

fn whoami_body(c: &rusqlite::Connection, id: &str) -> Res<Value> {
    let mut card = c.query_row(
        &format!("SELECT {} FROM workspaces WHERE id=?1", store::WS_CARD_COLS),
        [id],
        store::ws_card,
    )?;
    let phones: Vec<String> = c
        .prepare("SELECT workspaces FROM phones WHERE token_hash IS NOT NULL")?
        .query_map([], |r| r.get::<_, String>(0))?
        .collect::<Result<_, _>>()?;
    let n = phones
        .iter()
        .filter(|w| store::parse_list(w).contains(&id.to_string()))
        .count();
    let o = card.as_object_mut().unwrap();
    o.remove("online");
    o.remove("last_seen");
    o.remove("description_by");
    o.remove("tags_by");
    o.insert("pending".into(), store::pending(c, id));
    o.insert("phones".into(), n.into());
    Ok(card)
}

async fn whoami(State(app): State<AppState>, h: HeaderMap) -> Res<Json<Value>> {
    let c = app.db.lock().unwrap();
    let id = auth::workspace(&c, &h)?;
    Ok(Json(whoami_body(&c, &id)?))
}

/// `PATCH /v1/me`: a workspace proposes a new description and/or tags. Nothing changes until the owner approves
/// in the admin panel; one pending change per workspace, a new one replaces it.
async fn patch_me(
    State(app): State<AppState>,
    h: HeaderMap,
    body: Bytes,
) -> Res<(StatusCode, Json<Value>)> {
    let v = parse_body(&body)?;
    let c = app.db.lock().unwrap();
    let me = auth::workspace(&c, &h)?;
    let desc = match v.get("description") {
        None => None,
        Some(d) => Some(
            d.as_str()
                .ok_or_else(|| invalid("`description` must be text."))
                .and_then(|d| store::valid_description(d).map_err(invalid))?,
        ),
    };
    let tags = match v.get("tags") {
        None => None,
        Some(t) => Some(
            t.as_array()
                .ok_or_else(|| invalid("`tags` must be a list."))
                .and_then(|a| store::valid_tags(a).map_err(invalid))?,
        ),
    };
    if desc.is_none() && tags.is_none() {
        return Err(invalid("Send a `description` and/or `tags`."));
    }
    // A proposal that matches what is already in use changes nothing: answer 200 and store no pending change.
    let (cur_desc, cur_tags): (String, String) = c.query_row(
        "SELECT description,tags FROM workspaces WHERE id=?1",
        [&me],
        |r| Ok((r.get(0)?, r.get(1)?)),
    )?;
    let same_desc = desc.as_ref().is_none_or(|d| *d == cur_desc);
    let same_tags = tags
        .as_ref()
        .is_none_or(|t| *t == store::parse_list(&cur_tags));
    if same_desc && same_tags {
        let mut out = whoami_body(&c, &me)?;
        out["status"] = "unchanged".into();
        return Ok((StatusCode::OK, Json(out)));
    }
    // Only these fields, and only while the token that authenticated this call is still current.
    let cur = auth::bearer(&h).map(token_hash).unwrap_or_default();
    let n = c.execute(
        "UPDATE workspaces SET pending_description=?3, pending_tags=?4, pending_at=?5, pending_rev=?6 WHERE id=?1 AND token_hash=?2",
        params![
            me,
            cur,
            desc,
            tags.as_ref().map(|t| serde_json::to_string(t).unwrap()),
            now(),
            rand_id("", 12)
        ],
    )?;
    if n == 0 {
        return Err(unauthorized());
    }
    let mut out = whoami_body(&c, &me)?;
    out["status"] = "pending".into();
    Ok((StatusCode::ACCEPTED, Json(out)))
}

const NOT_AVAILABLE: &str = include_str!("../web/not-available.html");

/// The relay's orch logo (violet: dashboard green, publish blue, relay violet) as tab icon and iOS home-screen icon.
/// Served on the public and the admin listener.
pub fn icon_routes<S: Clone + Send + Sync + 'static>() -> Router<S> {
    let svg = || async {
        (
            [
                (header::CONTENT_TYPE, "image/svg+xml"),
                (header::CACHE_CONTROL, "public, max-age=86400"),
            ],
            include_str!("../web/favicon.svg"),
        )
    };
    let png = || async {
        (
            [
                (header::CONTENT_TYPE, "image/png"),
                (header::CACHE_CONTROL, "public, max-age=86400"),
            ],
            &include_bytes!("../web/apple-touch-icon.png")[..],
        )
    };
    Router::new()
        .route("/favicon.svg", get(svg))
        .route("/favicon.ico", get(svg))
        .route("/apple-touch-icon.png", get(png))
}

fn page(status: StatusCode) -> Response {
    (
        status,
        [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
        NOT_AVAILABLE,
    )
        .into_response()
}

async fn root_page() -> Response {
    page(StatusCode::OK)
}

/// Unknown paths: the API answers JSON, everything else a friendly dark page.
async fn not_found_page(uri: axum::http::Uri) -> Response {
    if uri.path().starts_with("/v1/") {
        return not_found("No such route.").into_response();
    }
    page(StatusCode::NOT_FOUND)
}

async fn post_message(
    State(app): State<AppState>,
    h: HeaderMap,
    body: Bytes,
) -> Res<(StatusCode, Json<Value>)> {
    let mut msg = parse_body(&body)?;
    rules::clean_ticket_key(&mut msg);
    let (stored, push) = {
        let c = app.db.lock().unwrap();
        let me = auth::workspace(&c, &h)?;
        if msg["from"].as_str() != Some(&me) {
            return Err(forbidden("`from` must be the authenticated workspace."));
        }
        rules::validate_schema(&msg).map_err(invalid)?;
        rules::check_update_title(&msg).map_err(invalid)?;
        let id = msg["id"].as_str().unwrap_or("").to_string();
        let digest = sha256_hex(&serde_json::to_vec(&msg).unwrap());
        let old: Option<(String, String)> = c
            .query_row(
                "SELECT digest,from_addr FROM messages WHERE id=?1",
                [&id],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        if let Some((d, f)) = old {
            if d == digest && f == me {
                return Ok((StatusCode::OK, Json(json!({"id": id, "duplicate": true}))));
            }
            return Err(conflict(
                "This message id was already used for another message.",
            ));
        }
        let stored = rules::authorize(&c, &app.key, &me, msg)?;
        store::insert_message(&c, &app.key, &stored, &digest)?;
        let to = stored["to"].as_str().unwrap_or("");
        let push = matches!(stored["type"].as_str(), Some("question" | "text"))
            && (to == "phones" || to.starts_with("ph_"));
        (stored, push)
    };
    app.notify.notify_waiters();
    if push {
        crate::phone::push_message(&app, &stored).await;
    }
    Ok((StatusCode::CREATED, Json(json!({"id": stored["id"]}))))
}

async fn inbox(
    State(app): State<AppState>,
    h: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Res<Json<Value>> {
    let wait = q
        .get("wait")
        .and_then(|w| w.parse::<u64>().ok())
        .unwrap_or(0)
        .min(30);
    let limit = q
        .get("limit")
        .and_then(|w| w.parse::<i64>().ok())
        .unwrap_or(100)
        .clamp(1, 100);
    let after = q.get("after").and_then(|c| decode_cursor(c)).unwrap_or(0);
    let deadline = Instant::now() + Duration::from_secs(wait);
    loop {
        let notified = app.notify.notified();
        tokio::pin!(notified);
        notified.as_mut().enable();
        let (items, last) = {
            let c = app.db.lock().unwrap();
            let me = auth::workspace(&c, &h)?;
            let mut st = c.prepare(&format!(
                "SELECT {MSG_COLS} FROM messages WHERE to_addr=?1 AND acked_at IS NULL AND seq>?2 ORDER BY seq LIMIT ?3"
            ))?;
            let rows: Vec<store::Msg> = st
                .query_map(params![me, after, limit], msg_from_row)?
                .collect::<Result<_, _>>()?;
            let last = rows.last().map(|m| m.seq);
            (
                rows.iter()
                    .map(|m| msg_json(&app.key, m))
                    .collect::<Vec<_>>(),
                last,
            )
        };
        if !items.is_empty() || Instant::now() >= deadline {
            let next = if items.len() as i64 == limit {
                last.map(encode_cursor)
            } else {
                None
            };
            return Ok(Json(json!({"items": items, "next": next})));
        }
        tokio::select! {
            _ = &mut notified => {}
            _ = tokio::time::sleep_until(deadline.into()) => {}
        }
    }
}

async fn ack(State(app): State<AppState>, h: HeaderMap, body: Bytes) -> Res<StatusCode> {
    let v = parse_body(&body)?;
    let ids = v["ids"]
        .as_array()
        .ok_or_else(|| invalid("`ids` must be a list."))?;
    let c = app.db.lock().unwrap();
    let me = auth::workspace(&c, &h)?;
    for id in ids.iter().filter_map(Value::as_str) {
        c.execute(
            "UPDATE messages SET acked_at=?3 WHERE id=?1 AND to_addr=?2 AND acked_at IS NULL",
            params![id, me, now()],
        )?;
    }
    Ok(StatusCode::NO_CONTENT)
}

async fn post_blob(
    State(app): State<AppState>,
    h: HeaderMap,
    body: Body,
) -> Res<(StatusCode, Json<Value>)> {
    // Authenticate before reading a single body byte.
    let me = {
        let c = app.db.lock().unwrap();
        auth::workspace(&c, &h)?
    };
    if let Some(n) = h
        .get(header::CONTENT_LENGTH)
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.parse::<usize>().ok())
    {
        if n > MAX_BLOB {
            return Err(too_large("Files can be at most 100 MB."));
        }
    }
    // Stream the body; the cap is enforced while streaming. The buffer is sealed in place.
    let mut buf: Vec<u8> = Vec::new();
    let mut hasher = Sha256::new();
    let mut stream = body.into_data_stream();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|_| invalid("Upload was interrupted."))?;
        if buf.len() + chunk.len() > MAX_BLOB {
            return Err(too_large("Files can be at most 100 MB."));
        }
        hasher.update(&chunk);
        buf.extend_from_slice(&chunk);
    }
    let size = buf.len();
    let sha = hex::encode(hasher.finalize());
    let id = rand_id("b_", 16);
    crypto::seal_in_place(&app.key, &id, &mut buf);
    tokio::fs::write(app.blob_path(&id), &buf)
        .await
        .map_err(internal)?;
    drop(buf);
    app.db.lock().unwrap().execute(
        "INSERT INTO blobs(id,uploader,size,sha256,created_at) VALUES(?1,?2,?3,?4,?5)",
        params![id, me, size as i64, sha, now()],
    )?;
    Ok((
        StatusCode::CREATED,
        Json(json!({"blob_id": id, "size": size, "sha256": sha})),
    ))
}

async fn get_blob(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
) -> Res<Response> {
    {
        let c = app.db.lock().unwrap();
        let me = auth::workspace(&c, &h)?;
        let ok: bool = c.query_row(
            "SELECT EXISTS(SELECT 1 FROM blobs WHERE id=?1 AND uploader=?2)
             OR EXISTS(SELECT 1 FROM messages WHERE blob_id=?1 AND type='file' AND to_addr=?2)
             OR EXISTS(SELECT 1 FROM phone_blobs pb JOIN messages m ON m.id=pb.msg_id JOIN blobs b ON b.id=pb.blob_id
               WHERE pb.blob_id=?1 AND m.type='text' AND m.to_addr=?2 AND b.uploader=m.from_addr)",
            params![id, me],
            |r| r.get(0),
        )?;
        if !ok {
            return Err(not_found("No such file."));
        }
    }
    let raw = tokio::fs::read(app.blob_path(&id))
        .await
        .map_err(|_| not_found("No such file."))?;
    let plain =
        crypto::open(&app.key, &id, &raw).ok_or_else(|| internal("blob does not decrypt"))?;
    Ok((
        [
            (header::CONTENT_TYPE, "application/octet-stream"),
            (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
            (header::CONTENT_DISPOSITION, "attachment"),
        ],
        plain,
    )
        .into_response())
}

async fn refresh(State(app): State<AppState>, h: HeaderMap) -> Res<Json<Value>> {
    let c = app.db.lock().unwrap();
    let me = auth::workspace(&c, &h)?;
    Ok(Json(crate::shared::snapshot(&c, &app.key, &me)?))
}
