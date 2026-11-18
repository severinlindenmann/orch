//! The notebook: the small orch app on the person's notebook (contracts/relay-api.md "Notebook").
//!
//! One notebook belongs to exactly one workspace; the admin adds it on the relay admin page and the notebook redeems
//! the one-time code. The workspace sends `ask`s (POST /v1/messages, `to: nb_…`, type `notebook`); they wait in the
//! relay (encrypted at rest like every message) until the notebook fetches and acks them, so nothing is lost while
//! the notebook sleeps. The notebook answers with `reply` and reports its ways in with `status`
//! (POST /v1/notebook/send); those wait in the workspace inbox as usual. Text only: no blobs on any notebook route.
//! Every route takes the notebook and its workspace from the token, never from the body.
use crate::api::parse_body;
use crate::error::*;
use crate::state::AppState;
use crate::store::{self, msg_from_row, msg_json, open_payload, MSG_COLS};
use crate::util::*;
use crate::{auth, rules};
use axum::body::Bytes;
use axum::extract::{DefaultBodyLimit, Query, State};
use axum::http::{HeaderMap, StatusCode};
use axum::routing::{get, post};
use axum::{Json, Router};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::time::{Duration, Instant};
use time::format_description::well_known::Rfc3339;
use time::OffsetDateTime;

/// Body limit on every notebook route (a reply is at most 64 KB of text).
pub const MAX_BODY: usize = 256 * 1024;
/// Asks waiting for one notebook at most; more are refused.
pub const MAX_WAITING: i64 = 100;
/// Messages per minute in each direction (workspace → its notebook, notebook → its workspace).
pub const PER_MINUTE: i64 = 60;
/// Longest an ask may wait for the notebook.
pub const MAX_ASK_SECS: i64 = 7 * 24 * 3600;
/// Open long-polls per notebook.
pub const MAX_POLLS: u32 = 2;
/// Asks handed out per poll.
const POLL_LIMIT: i64 = 20;
/// Ids per ack.
const MAX_ACK: usize = 100;
/// How long a pairing code works.
pub const CODE_SECS: i64 = 24 * 3600;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/v1/notebook/pair", post(pair))
        .route("/v1/notebook/requests", get(requests))
        .route("/v1/notebook/ack", post(ack))
        .route("/v1/notebook/send", post(send))
        .route("/v1/notebooks", get(list_for_workspace))
        .layer(DefaultBodyLimit::max(MAX_BODY))
}

fn parse_time(s: &str) -> Option<i64> {
    OffsetDateTime::parse(s, &Rfc3339)
        .ok()
        .map(|t| t.unix_timestamp())
}

fn rate_limited_msg(m: &str) -> ApiError {
    ApiError {
        status: StatusCode::TOO_MANY_REQUESTS,
        code: "rate_limited",
        message: m.into(),
    }
}

/// The notebook of workspace `ws`: (id, paired).
pub fn of_workspace(c: &Connection, ws: &str) -> rusqlite::Result<Option<(String, bool)>> {
    c.query_row(
        "SELECT id, token_hash IS NOT NULL FROM notebooks WHERE workspace=?1",
        [ws],
        |r| Ok((r.get(0)?, r.get(1)?)),
    )
    .optional()
}

fn count(c: &Connection, sql: &str, p: impl rusqlite::Params) -> rusqlite::Result<i64> {
    c.query_row(sql, p, |r| r.get(0))
}

/// Rules for an `ask` a workspace sends (called from rules::authorize). Returns the message to store.
pub fn authorize_ask(c: &Connection, sender: &str, msg: Value) -> Res<Value> {
    let to = msg["to"].as_str().unwrap_or("");
    if !valid_id(to, "nb_", 10) {
        return Err(not_allowed(
            "Notebook messages go to your notebook (nb_…) only.",
        ));
    }
    let nb = msg["body"]["notebook"].clone();
    if nb["kind"] != "ask" {
        return Err(not_allowed("A workspace sends only asks to its notebook."));
    }
    if msg.get("reply_to").is_some() {
        return Err(invalid("An ask is not a reply."));
    }
    match of_workspace(c, sender)? {
        Some((id, paired)) if id == to => {
            if !paired {
                return Err(not_allowed(
                    "Your notebook is not connected yet. Run the line from the relay admin page on the notebook.",
                ));
            }
        }
        // Another workspace's notebook answers exactly like an unknown one.
        _ => {
            return Err(not_found(
                "No notebook with this id. Add the notebook on the relay admin page (Notebooks).",
            ))
        }
    }
    let t = now();
    let exp = nb["expires_at"].as_str().and_then(parse_time).unwrap_or(0);
    if exp <= t || exp > t + MAX_ASK_SECS + 60 {
        return Err(invalid(
            "`expires_at` must be in the future and at most 7 days away.",
        ));
    }
    let waiting = count(
        c,
        "SELECT COUNT(*) FROM messages WHERE to_addr=?1 AND acked_at IS NULL",
        [to],
    )?;
    if waiting >= MAX_WAITING {
        return Err(rate_limited_msg(
            "The notebook has too many waiting requests. Wait until it wakes up.",
        ));
    }
    let recent = count(
        c,
        "SELECT COUNT(*) FROM messages WHERE from_addr=?1 AND to_addr=?2 AND stored_at>?3",
        params![sender, to, t - 60],
    )?;
    if recent >= PER_MINUTE {
        return Err(rate_limited_msg(
            "Too many requests to the notebook. Try again in a minute.",
        ));
    }
    Ok(msg)
}

/// (notebook id, its workspace) of an authenticated notebook call (also marks it seen).
pub fn auth_notebook(c: &Connection, h: &HeaderMap) -> Res<(String, String)> {
    let id = h
        .get("x-orch-notebook")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");
    let Some(tok) = auth::bearer(h) else {
        return Err(unauthorized());
    };
    if !valid_id(id, "nb_", 10) {
        return Err(unauthorized());
    }
    let row: Option<(Option<String>, String)> = c
        .query_row(
            "SELECT token_hash, workspace FROM notebooks WHERE id=?1",
            [id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    match row {
        Some((Some(hh), ws)) if ct_eq(&hh, &token_hash(tok)) => {
            c.execute(
                "UPDATE notebooks SET last_seen=?2 WHERE id=?1",
                params![id, now()],
            )?;
            Ok((id.to_string(), ws))
        }
        _ => Err(unauthorized()),
    }
}

async fn pair(State(app): State<AppState>, body: Bytes) -> Res<(StatusCode, Json<Value>)> {
    let v = parse_body(&body)?;
    let code = v["code"].as_str().unwrap_or("");
    if code.is_empty() || code.len() > 100 {
        return Err(unauthorized());
    }
    let mut c = app.db.lock().unwrap();
    let t = now();
    let token = rand_token("orn_", 32);
    let tx = c.transaction()?;
    let nid: Option<String> = tx
        .query_row(
            "SELECT notebook_id FROM notebook_codes WHERE hash=?1",
            [token_hash(code)],
            |r| r.get(0),
        )
        .optional()?;
    let Some(nid) = nid else {
        return Err(unauthorized());
    };
    // Used once: only the call that flips `used` gets a token, even when two arrive together.
    let n = tx.execute(
        "UPDATE notebook_codes SET used=1 WHERE hash=?1 AND used=0 AND expires_at>=?2",
        params![token_hash(code), t],
    )?;
    if n != 1 {
        return Err(gone(
            "This code was already used or has expired. Make a new one on the relay admin page.",
        ));
    }
    let changed = tx.execute(
        "UPDATE notebooks SET token_hash=?2, paired_at=?3, last_seen=?3 WHERE id=?1",
        params![nid, token_hash(&token), t],
    )?;
    if changed != 1 {
        return Err(gone(
            "This notebook was removed. Make a new code on the relay admin page.",
        ));
    }
    if let Some(name) = v["name"].as_str().and_then(store::clean_phone_name) {
        tx.execute(
            "UPDATE notebooks SET name=?2 WHERE id=?1",
            params![nid, name],
        )?;
    }
    let ws: String = tx.query_row("SELECT workspace FROM notebooks WHERE id=?1", [&nid], |r| {
        r.get(0)
    })?;
    tx.commit()?;
    Ok((
        StatusCode::CREATED,
        Json(json!({"notebook_id": nid, "token": token,
            "workspace": {"id": ws, "name": store::ws_name(&c, &ws).unwrap_or_default()}})),
    ))
}

/// Frees a long-poll slot when the request ends (also on a dropped connection).
struct PollSlot {
    app: AppState,
    id: String,
}

impl Drop for PollSlot {
    fn drop(&mut self) {
        let mut m = self.app.notebook_polls.lock().unwrap();
        if let Some(n) = m.get_mut(&self.id) {
            *n = n.saturating_sub(1);
            if *n == 0 {
                m.remove(&self.id);
            }
        }
    }
}

async fn requests(
    State(app): State<AppState>,
    h: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Res<Json<Value>> {
    let wait = q
        .get("wait")
        .and_then(|w| w.parse::<u64>().ok())
        .unwrap_or(0)
        .min(30);
    let (id, _) = {
        let c = app.db.lock().unwrap();
        auth_notebook(&c, &h)?
    };
    let _slot = {
        let mut m = app.notebook_polls.lock().unwrap();
        let n = m.entry(id.clone()).or_insert(0);
        if *n >= MAX_POLLS {
            return Err(rate_limited_msg(
                "The notebook already waits for requests. Close the other connection.",
            ));
        }
        *n += 1;
        PollSlot {
            app: app.clone(),
            id: id.clone(),
        }
    };
    let deadline = Instant::now() + Duration::from_secs(wait);
    loop {
        let notified = app.notify.notified();
        tokio::pin!(notified);
        notified.as_mut().enable();
        let items = {
            let c = app.db.lock().unwrap();
            // Checked again on every round: a removed notebook gets nothing more.
            let (me, ws) = auth_notebook(&c, &h)?;
            waiting_asks(&c, &app, &me, &ws)?
        };
        if !items.is_empty() || Instant::now() >= deadline {
            return Ok(Json(json!({"items": items})));
        }
        tokio::select! {
            _ = &mut notified => {}
            _ = tokio::time::sleep_until(deadline.into()) => {}
        }
    }
}

/// Unacked asks for notebook `me` from its workspace `ws`; an expired ask is dropped (acked) and never handed out.
fn waiting_asks(c: &Connection, app: &AppState, me: &str, ws: &str) -> Res<Vec<Value>> {
    let mut st = c.prepare(&format!(
        "SELECT {MSG_COLS} FROM messages WHERE to_addr=?1 AND from_addr=?2 AND acked_at IS NULL ORDER BY seq LIMIT ?3"
    ))?;
    let rows: Vec<store::Msg> = st
        .query_map(params![me, ws, POLL_LIMIT], msg_from_row)?
        .collect::<Result<_, _>>()?;
    let t = now();
    let mut out = Vec::new();
    for m in &rows {
        let (body, _) = open_payload(&app.key, m);
        let exp = body["notebook"]["expires_at"]
            .as_str()
            .and_then(parse_time)
            .unwrap_or(0);
        if exp <= t {
            c.execute(
                "UPDATE messages SET acked_at=?2 WHERE id=?1",
                params![m.id, t],
            )?;
            continue;
        }
        out.push(msg_json(&app.key, m));
    }
    Ok(out)
}

async fn ack(State(app): State<AppState>, h: HeaderMap, body: Bytes) -> Res<StatusCode> {
    let v = parse_body(&body)?;
    let ids = v["ids"]
        .as_array()
        .ok_or_else(|| invalid("`ids` must be a list."))?;
    if ids.len() > MAX_ACK {
        return Err(invalid("At most 100 ids per call."));
    }
    let c = app.db.lock().unwrap();
    let (me, _) = auth_notebook(&c, &h)?;
    for id in ids.iter().filter_map(Value::as_str) {
        c.execute(
            "UPDATE messages SET acked_at=?3 WHERE id=?1 AND to_addr=?2 AND acked_at IS NULL",
            params![id, me, now()],
        )?;
    }
    Ok(StatusCode::NO_CONTENT)
}

/// `POST /v1/notebook/send {id, reply_to?, notebook: {kind: reply|status, …}}`: the relay builds the message from the
/// notebook to its own workspace.
async fn send(
    State(app): State<AppState>,
    h: HeaderMap,
    body: Bytes,
) -> Res<(StatusCode, Json<Value>)> {
    let v = parse_body(&body)?;
    let mid = v["id"].as_str().unwrap_or("").to_string();
    if !valid_id(&mid, "m_", 16) {
        return Err(invalid(
            "`id` must be m_ and 16 lowercase letters or digits.",
        ));
    }
    {
        let c = app.db.lock().unwrap();
        let (me, ws) = auth_notebook(&c, &h)?;
        let kind = v["notebook"]["kind"].as_str().unwrap_or("");
        let mut msg = json!({
            "schema": "orch.msg/1", "id": mid, "from": me, "to": ws, "type": "notebook",
            "created_at": fmt_time(now()), "body": {"notebook": v["notebook"].clone()},
        });
        match kind {
            "reply" => {
                let rid = v["reply_to"].as_str().unwrap_or("");
                let q = store::get_msg(&c, rid)?;
                match q {
                    Some(q) if q.typ == "notebook" && q.from == ws && q.to == me => {}
                    _ => return Err(not_allowed("That is not a request for this notebook.")),
                }
                msg["reply_to"] = rid.into();
            }
            "status" => {
                if v.get("reply_to").is_some() {
                    return Err(invalid("A status is not a reply."));
                }
            }
            _ => return Err(invalid("A notebook sends only `reply` or `status`.")),
        }
        rules::validate_schema(&msg).map_err(invalid)?;
        // A resend of the same message (same id and content, created_at aside) is a no-op.
        let mut same = msg.clone();
        same["created_at"] = Value::Null;
        let digest = sha256_hex(&serde_json::to_vec(&same).unwrap());
        let old: Option<(String, String)> = c
            .query_row(
                "SELECT digest,from_addr FROM messages WHERE id=?1",
                [&mid],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        if let Some((d, f)) = old {
            if d == digest && f == me {
                return Ok((StatusCode::OK, Json(json!({"id": mid, "duplicate": true}))));
            }
            return Err(conflict(
                "This message id was already used for another message.",
            ));
        }
        if kind == "reply" {
            let prev = c
                .query_row(
                    "SELECT 1 FROM messages WHERE reply_to=?1 AND from_addr=?2",
                    params![msg["reply_to"].as_str().unwrap_or(""), me],
                    |_| Ok(()),
                )
                .optional()?;
            if prev.is_some() {
                return Err(already_answered("This request was already answered."));
            }
        }
        let recent = count(
            &c,
            "SELECT COUNT(*) FROM messages WHERE from_addr=?1 AND stored_at>?2",
            params![me, now() - 60],
        )?;
        if recent >= PER_MINUTE {
            return Err(rate_limited_msg(
                "Too many messages. Try again in a minute.",
            ));
        }
        if kind == "status" {
            // Only the newest status waits: an older one the workspace has not fetched yet is replaced.
            let old: Option<String> = c
                .query_row("SELECT status_msg FROM notebooks WHERE id=?1", [&me], |r| {
                    r.get(0)
                })
                .optional()?
                .flatten();
            if let Some(old) = old {
                c.execute(
                    "DELETE FROM messages WHERE id=?1 AND from_addr=?2 AND acked_at IS NULL",
                    params![old, me],
                )?;
            }
        }
        store::insert_message(&c, &app.key, &msg, &digest)?;
        if kind == "status" {
            c.execute(
                "UPDATE notebooks SET status_msg=?2 WHERE id=?1",
                params![me, mid],
            )?;
        }
    }
    app.notify.notify_waiters();
    Ok((StatusCode::CREATED, Json(json!({"id": mid}))))
}

/// `GET /v1/notebooks` (workspace auth): this workspace's notebook, at most one.
async fn list_for_workspace(State(app): State<AppState>, h: HeaderMap) -> Res<Json<Value>> {
    let c = app.db.lock().unwrap();
    let me = auth::workspace(&c, &h)?;
    let row: Option<(String, String, bool, Option<i64>)> = c
        .query_row(
            "SELECT id,name,token_hash IS NOT NULL,last_seen FROM notebooks WHERE workspace=?1",
            [&me],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
        )
        .optional()?;
    let items: Vec<Value> = match row {
        Some((id, name, paired, last)) => {
            let waiting = count(
                &c,
                "SELECT COUNT(*) FROM messages WHERE to_addr=?1 AND acked_at IS NULL",
                [&id],
            )?;
            vec![json!({"id": id, "name": name, "paired": paired,
                "last_seen": last.filter(|_| paired).map(fmt_time), "online": paired && store::online(last),
                "waiting": waiting})]
        }
        None => vec![],
    };
    Ok(Json(json!({"items": items})))
}

// ---------- admin (private network only, mounted in admin.rs) ----------

pub fn admin_list(c: &Connection) -> Res<Value> {
    let items: Vec<Value> = c
        .prepare("SELECT id,name,workspace,token_hash IS NOT NULL,last_seen FROM notebooks ORDER BY created_at, id")?
        .query_map([], |r| {
            let last: Option<i64> = r.get(4)?;
            let paired: bool = r.get(3)?;
            Ok(json!({"id": r.get::<_, String>(0)?, "name": r.get::<_, String>(1)?,
                "workspace": r.get::<_, String>(2)?, "paired": paired,
                "online": paired && store::online(last), "last_seen": last.filter(|_| paired).map(fmt_time)}))
        })?
        .collect::<Result<_, _>>()?;
    Ok(json!({"items": items}))
}

/// Adds a notebook for one workspace and returns its one-time code and the line to run on the notebook.
pub fn admin_add(c: &Connection, public_url: &str, v: &Value) -> Res<Value> {
    let name = v["name"].as_str().unwrap_or("").trim();
    if name.is_empty() || name.chars().count() > 100 {
        return Err(invalid("Give the notebook a name."));
    }
    let ws = v["workspace"].as_str().unwrap_or("");
    if !store::ws_exists(c, ws) {
        return Err(invalid("Pick the workspace this notebook belongs to."));
    }
    if of_workspace(c, ws)?.is_some() {
        return Err(conflict(
            "This workspace already has a notebook. Remove it first.",
        ));
    }
    let nid = rand_id("nb_", 10);
    let code = rand_token("nc_", 16);
    c.execute(
        "INSERT INTO notebooks(id,name,workspace,created_at) VALUES(?1,?2,?3,?4)",
        params![nid, name, ws, now()],
    )?;
    c.execute(
        "INSERT INTO notebook_codes(hash,notebook_id,expires_at) VALUES(?1,?2,?3)",
        params![token_hash(&code), nid, now() + CODE_SECS],
    )?;
    Ok(json!({"notebook_id": nid, "code": code,
        "line": format!("orch-notebook connect {public_url} {code}")}))
}

/// Removes a notebook: its token stops working at once, its codes and waiting asks go with it.
pub fn admin_remove(c: &mut Connection, id: &str) -> Res<()> {
    let tx = c.transaction()?;
    let n = tx.execute("DELETE FROM notebooks WHERE id=?1", [id])?;
    if n == 0 {
        return Err(not_found("No such notebook."));
    }
    tx.execute("DELETE FROM notebook_codes WHERE notebook_id=?1", [id])?;
    tx.execute(
        "DELETE FROM messages WHERE to_addr=?1 AND acked_at IS NULL",
        [id],
    )?;
    tx.commit()?;
    Ok(())
}

/// A removed workspace takes its notebook with it.
pub fn forget_workspace(c: &Connection, ws: &str) -> rusqlite::Result<()> {
    let ids: Vec<String> = c
        .prepare("SELECT id FROM notebooks WHERE workspace=?1")?
        .query_map([ws], |r| r.get(0))?
        .collect::<Result<_, _>>()?;
    for id in ids {
        c.execute("DELETE FROM notebook_codes WHERE notebook_id=?1", [&id])?;
        c.execute(
            "DELETE FROM messages WHERE to_addr=?1 AND acked_at IS NULL",
            [&id],
        )?;
        c.execute("DELETE FROM notebooks WHERE id=?1", [&id])?;
    }
    Ok(())
}
