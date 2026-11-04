//! Phone API (`/v1/phone/*`) and push for new questions.
use crate::api::parse_body;
use crate::auth;
use crate::error::*;
use crate::state::AppState;
use crate::store::{self, msg_from_row, msg_json, MSG_COLS};
use crate::util::*;
use axum::body::Bytes;
use axum::extract::{Query, State};
use axum::http::{HeaderMap, StatusCode};
use axum::routing::{get, post};
use axum::{Json, Router};
use rusqlite::{params, OptionalExtension};
use serde_json::{json, Value};
use std::collections::HashMap;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/v1/phone/pair", post(pair))
        .route("/v1/phone/push", post(register_push))
        .route("/v1/phone/workspaces", get(workspaces))
        .route("/v1/phone/questions", get(questions))
        .route("/v1/phone/answer", post(answer))
        .route("/v1/phone/send", post(send))
        .route("/v1/phone/signout", post(signout))
}

async fn pair(State(app): State<AppState>, body: Bytes) -> Res<(StatusCode, Json<Value>)> {
    let v = parse_body(&body)?;
    let code = v["code"].as_str().unwrap_or("");
    let mut c = app.db.lock().unwrap();
    let row: Option<(String, i64, bool)> = c
        .query_row(
            "SELECT phone_id,expires_at,used FROM pair_codes WHERE hash=?1",
            [token_hash(code)],
            |r| Ok((r.get(0)?, r.get(1)?, r.get::<_, i64>(2)? != 0)),
        )
        .optional()?;
    let Some((pid, exp, used)) = row else {
        return Err(unauthorized());
    };
    if used || exp < now() {
        return Err(gone("This pairing code was already used or has expired."));
    }
    let token = rand_token("orn_", 32);
    let tx = c.transaction()?;
    tx.execute(
        "UPDATE pair_codes SET used=1 WHERE hash=?1",
        [token_hash(code)],
    )?;
    tx.execute(
        "UPDATE phones SET token_hash=?2, last_seen=?3 WHERE id=?1",
        params![pid, token_hash(&token), now()],
    )?;
    if let Some(n) = v["name"].as_str().filter(|n| !n.trim().is_empty()) {
        tx.execute(
            "UPDATE phones SET name=?2 WHERE id=?1",
            params![pid, n.trim()],
        )?;
    }
    tx.commit()?;
    let list: String = c.query_row("SELECT workspaces FROM phones WHERE id=?1", [&pid], |r| {
        r.get(0)
    })?;
    let ws: Vec<Value> = store::parse_list(&list)
        .iter()
        .filter_map(|w| store::ws_name(&c, w).map(|n| json!({"id": w, "name": n})))
        .collect();
    Ok((
        StatusCode::CREATED,
        Json(json!({"phone_id": pid, "token": token, "workspaces": ws})),
    ))
}

async fn register_push(State(app): State<AppState>, h: HeaderMap, body: Bytes) -> Res<StatusCode> {
    let v = parse_body(&body)?;
    let t = v["apns_token"].as_str().unwrap_or("");
    if t.is_empty() || !t.bytes().all(|c| c.is_ascii_hexdigit()) {
        return Err(invalid("`apns_token` must be a hex string."));
    }
    let c = app.db.lock().unwrap();
    let (pid, ..) = auth::phone(&c, &h)?;
    c.execute(
        "UPDATE phones SET apns_token=?2, sandbox=?3 WHERE id=?1",
        params![pid, t, v["sandbox"].as_bool().unwrap_or(false)],
    )?;
    Ok(StatusCode::NO_CONTENT)
}

fn open_questions(c: &rusqlite::Connection, ws: &[String]) -> rusqlite::Result<Vec<store::Msg>> {
    let mut st = c.prepare(&format!(
        "SELECT {MSG_COLS} FROM messages m WHERE type='question' AND to_addr='phones'
         AND NOT EXISTS (SELECT 1 FROM messages a WHERE a.reply_to=m.id AND a.type='answer') ORDER BY seq DESC"
    ))?;
    let rows = st
        .query_map([], msg_from_row)?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(rows.into_iter().filter(|m| ws.contains(&m.from)).collect())
}

async fn workspaces(State(app): State<AppState>, h: HeaderMap) -> Res<Json<Value>> {
    let c = app.db.lock().unwrap();
    let (_, _, ws) = auth::phone(&c, &h)?;
    let open = open_questions(&c, &ws)?;
    let mut items = vec![];
    for w in &ws {
        let card = c
            .query_row(
                &format!("SELECT {} FROM workspaces WHERE id=?1", store::WS_CARD_COLS),
                [w],
                store::ws_card,
            )
            .optional()?;
        if let Some(mut card) = card {
            card["open_questions"] = open.iter().filter(|m| &m.from == w).count().into();
            items.push(card);
        }
    }
    Ok(Json(json!({"items": items, "next": null})))
}

async fn questions(
    State(app): State<AppState>,
    h: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Res<Json<Value>> {
    let limit = q
        .get("limit")
        .and_then(|l| l.parse::<usize>().ok())
        .unwrap_or(50)
        .clamp(1, 100);
    let after = q
        .get("after")
        .and_then(|c| decode_cursor(c))
        .unwrap_or(i64::MAX);
    let c = app.db.lock().unwrap();
    let (_, _, ws) = auth::phone(&c, &h)?;
    let rows: Vec<store::Msg> = open_questions(&c, &ws)?
        .into_iter()
        .filter(|m| m.seq < after)
        .collect();
    let more = rows.len() > limit;
    let rows = &rows[..rows.len().min(limit)];
    let items: Vec<Value> = rows
        .iter()
        .map(|m| json!({"message": msg_json(&app.key, m), "workspace_name": store::ws_name(&c, &m.from)}))
        .collect();
    let next = if more {
        rows.last().map(|m| encode_cursor(m.seq))
    } else {
        None
    };
    Ok(Json(json!({"items": items, "next": next})))
}

async fn answer(
    State(app): State<AppState>,
    h: HeaderMap,
    body: Bytes,
) -> Res<(StatusCode, Json<Value>)> {
    let v = parse_body(&body)?;
    let qid = v["question_message_id"].as_str().unwrap_or("");
    let text = v["answer"].as_str().unwrap_or("");
    if text.is_empty() {
        return Err(invalid("`answer` must not be empty."));
    }
    let id = {
        let c = app.db.lock().unwrap();
        let (pid, name, ws) = auth::phone(&c, &h)?;
        let q = store::get_msg(&c, qid)?
            .filter(|q| q.typ == "question" && q.to == "phones" && ws.contains(&q.from))
            .ok_or_else(|| not_found("No such question."))?;
        // The database lock makes check + insert one step: the first answer wins.
        let prev = c
            .query_row(
                &format!("SELECT {MSG_COLS} FROM messages WHERE reply_to=?1 AND type='answer' ORDER BY seq LIMIT 1"),
                [qid],
                msg_from_row,
            )
            .optional()?;
        if let Some(p) = prev {
            let (b, _) = store::open_payload(&app.key, &p);
            return Err(already_answered(format!(
                "This question was already answered: {}.",
                b["answer"].as_str().unwrap_or("")
            )));
        }
        let (qb, _) = store::open_payload(&app.key, &q);
        let m = store::system_message(
            &c,
            &app.key,
            &pid,
            &q.from,
            "answer",
            q.ticket.as_deref(),
            Some(qid),
            json!({"question_id": qb["question_id"], "answer": text, "answered_by": format!("human:{name}")}),
        )?;
        m["id"].as_str().unwrap().to_string()
    };
    app.notify.notify_waiters();
    Ok((StatusCode::CREATED, Json(json!({"id": id}))))
}

async fn send(
    State(app): State<AppState>,
    h: HeaderMap,
    body: Bytes,
) -> Res<(StatusCode, Json<Value>)> {
    let v = parse_body(&body)?;
    let to = v["to"].as_str().unwrap_or("");
    let text = v["text"].as_str().unwrap_or("");
    if text.is_empty() || text.len() > 20000 {
        return Err(invalid("`text` must be 1 to 20000 characters."));
    }
    let ticket = v["ticket"].as_str();
    if ticket.is_some_and(|t| !(t.starts_with("t_") && (8..=18).contains(&t.len()))) {
        return Err(invalid("`ticket` must look like t_7k3f9q."));
    }
    let id = {
        let c = app.db.lock().unwrap();
        let (pid, _, ws) = auth::phone(&c, &h)?;
        if !ws.iter().any(|w| w == to) || !store::ws_exists(&c, to) {
            return Err(not_allowed("This phone may not send to that workspace."));
        }
        let m = store::system_message(
            &c,
            &app.key,
            &pid,
            to,
            "text",
            ticket,
            None,
            json!({"text": text}),
        )?;
        m["id"].as_str().unwrap().to_string()
    };
    app.notify.notify_waiters();
    Ok((StatusCode::CREATED, Json(json!({"id": id}))))
}

async fn signout(State(app): State<AppState>, h: HeaderMap) -> Res<StatusCode> {
    let c = app.db.lock().unwrap();
    let (pid, ..) = auth::phone(&c, &h)?;
    c.execute(
        "UPDATE phones SET token_hash=NULL, apns_token=NULL WHERE id=?1",
        [pid],
    )?;
    Ok(StatusCode::NO_CONTENT)
}

/// Push a new question to every phone that may reach the asking workspace.
pub async fn push_question(app: &AppState, q: &Value) {
    let targets: Vec<(bool, String)> = {
        let c = app.db.lock().unwrap();
        let mut st = match c.prepare(
            "SELECT sandbox,apns_token,workspaces FROM phones WHERE apns_token IS NOT NULL AND token_hash IS NOT NULL",
        ) {
            Ok(s) => s,
            Err(_) => return,
        };
        let rows = st
            .query_map([], |r| {
                Ok((
                    r.get::<_, i64>(0)? != 0,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                ))
            })
            .map(|r| r.flatten().collect::<Vec<_>>())
            .unwrap_or_default();
        let from = q["from"].as_str().unwrap_or("").to_string();
        rows.into_iter()
            .filter(|(_, _, w)| store::parse_list(w).contains(&from))
            .map(|(s, t, _)| (s, t))
            .collect()
    };
    if targets.is_empty() {
        return;
    }
    let name = {
        let c = app.db.lock().unwrap();
        store::ws_name(&c, q["from"].as_str().unwrap_or("")).unwrap_or_default()
    };
    let text: String = q["body"]["text"]
        .as_str()
        .unwrap_or("")
        .chars()
        .take(120)
        .collect();
    let payload = json!({"aps": {"alert": {"title": name, "body": text}, "sound": "default"},
        "message_id": q["id"], "workspace": q["from"]});
    for (sandbox, token) in targets {
        if let Err(e) = app.pusher.send(sandbox, &token, &payload).await {
            tracing::warn!("push failed: {e}");
        }
    }
}
