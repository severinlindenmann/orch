//! Phone API (`/v1/phone/*`) and push for new questions.
use crate::api::parse_body;
use crate::auth;
use crate::error::*;
use crate::state::AppState;
use crate::store::{self, msg_from_row, msg_json, MSG_COLS};
use crate::util::*;
use axum::body::Bytes;
use axum::extract::{DefaultBodyLimit, Query, State};
use axum::http::{HeaderMap, StatusCode};
use axum::routing::{get, patch, post};
use axum::{Json, Router};
use rusqlite::{params, OptionalExtension};
use serde_json::{json, Value};
use std::collections::HashMap;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/v1/phone/pair", post(pair))
        .route("/v1/phone/push", post(register_push))
        .route("/v1/phone/workspaces", get(workspaces))
        .route(
            "/v1/phone/workspaces/:id",
            patch(patch_workspace).delete(delete_workspace),
        )
        .route("/v1/phone/groups/:host/:id", patch(patch_group))
        .route("/v1/phone/questions", get(questions))
        .route("/v1/phone/answer", post(answer))
        .route("/v1/phone/send", post(send))
        .route("/v1/phone/control", post(control))
        .route("/v1/phone/messages", get(messages))
        .route("/v1/phone/updates", get(updates))
        .route(
            "/v1/phone/blobs",
            post(upload_blob).layer(DefaultBodyLimit::disable()),
        )
        .route("/v1/phone/blobs/:id", get(blob))
        .route("/v1/phone/speech/:id", get(speech))
        .route(
            "/v1/phone/settings",
            get(get_settings).patch(patch_settings),
        )
        .route("/v1/phone/invitations/redeem", post(redeem))
        // Lane R2 (speech, transcribe) adds its routes below this line.
        .route("/v1/phone/signout", post(signout))
        .route(
            "/v1/phone/transcribe",
            post(crate::transcribe::phone)
                .layer(DefaultBodyLimit::max(crate::transcribe::MAX_AUDIO + 1024)),
        )
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
        "UPDATE phones SET token_hash=?2, last_seen=?3, paired_at=?3 WHERE id=?1",
        params![pid, token_hash(&token), now()],
    )?;
    if let Some(n) = v["name"].as_str().and_then(store::clean_phone_name) {
        tx.execute("UPDATE phones SET name=?2 WHERE id=?1", params![pid, n])?;
    }
    tx.commit()?;
    let list: String = c.query_row("SELECT workspaces FROM phones WHERE id=?1", [&pid], |r| {
        r.get(0)
    })?;
    // Its workspaces now list this phone (refresh) and may send to it.
    store::bump_and_hint(&c, &app.key, &store::parse_ws_list(&list))?;
    let ws: Vec<Value> = store::parse_ws_list(&list)
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

/// Open questions for phone `pid`: sent to `phones` or to this phone, by a workspace on its list.
fn open_questions(
    c: &rusqlite::Connection,
    pid: &str,
    ws: &[String],
) -> rusqlite::Result<Vec<store::Msg>> {
    let list = serde_json::to_string(ws).unwrap_or("[]".into());
    let mut st = c.prepare(OPEN_QUESTIONS_SQL)?;
    let rows = st
        .query_map(params![pid, list], msg_from_row)?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(rows)
}

/// Open questions to `phones` or to one phone (?1) from the workspaces in the JSON list (?2). One index-driven
/// branch per case, joined from `json_each`: no scan of the whole messages table.
pub const OPEN_QUESTIONS_SQL: &str = "SELECT seq,id,from_addr,to_addr,type,created_at,ticket,reply_to,payload,acked_at FROM (
        SELECT m.* FROM json_each(?2) j CROSS JOIN messages m
          WHERE m.type='question' AND m.to_addr='phones' AND m.from_addr=j.value
        UNION ALL
        SELECT m.* FROM json_each(?2) j CROSS JOIN messages m
          WHERE m.type='question' AND m.to_addr=?1 AND m.from_addr=j.value
     ) m WHERE NOT EXISTS (SELECT 1 FROM messages a WHERE a.reply_to=m.id AND a.type='answer') ORDER BY seq DESC";

/// Texts for a phone: ?1 phone id, ?2 cursor, ?3 JSON workspace list, ?4 paired-at, ?5 limit.
pub const MESSAGES_SQL: &str = "SELECT seq,id,from_addr,to_addr,type,created_at,ticket,reply_to,payload,acked_at FROM (
        SELECT m.* FROM json_each(?3) j CROSS JOIN messages m
          WHERE m.type='text' AND m.to_addr='phones' AND m.from_addr=j.value AND m.stored_at>=?4 AND m.seq<?2
        UNION ALL
        SELECT m.* FROM json_each(?3) j CROSS JOIN messages m
          WHERE m.type='text' AND m.to_addr=?1 AND m.from_addr=j.value AND m.seq<?2
        UNION ALL
        SELECT m.* FROM json_each(?3) j CROSS JOIN messages m
          WHERE m.type='text' AND m.from_addr=?1 AND m.to_addr=j.value AND m.seq<?2
     ) ORDER BY seq DESC LIMIT ?5";

async fn workspaces(State(app): State<AppState>, h: HeaderMap) -> Res<Json<Value>> {
    let c = app.db.lock().unwrap();
    let (pid, _, ws) = auth::phone(&c, &h)?;
    let open = open_questions(&c, &pid, &ws)?;
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
            crate::look::add_to(&c, &mut card, false);
            card["open_questions"] = open.iter().filter(|m| &m.from == w).count().into();
            card["muted_until"] = store::muted_until(&c, &pid, w);
            card["mobile_mode"] = store::mobile_mode(&c, w);
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
    let (pid, _, ws) = auth::phone(&c, &h)?;
    let rows: Vec<store::Msg> = open_questions(&c, &pid, &ws)?
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

/// `GET /v1/phone/messages`: text messages between this phone and the workspaces on its list, newest first:
/// what workspaces sent to this phone or to `phones`, and what this phone sent.
async fn messages(
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
    let (pid, _, ws) = auth::phone(&c, &h)?;
    // Filter by sender/peer and time in SQL (indexed); broadcasts only from after this phone paired (L3).
    let since: i64 = c.query_row(
        "SELECT COALESCE(paired_at, created_at) FROM phones WHERE id=?1",
        [&pid],
        |r| r.get(0),
    )?;
    let list = serde_json::to_string(&ws).unwrap_or("[]".into());
    let mut st = c.prepare(MESSAGES_SQL)?;
    let mut rows: Vec<crate::store::Msg> = st
        .query_map(
            params![pid, after, list, since, limit as i64 + 1],
            msg_from_row,
        )?
        .collect::<Result<_, _>>()?;
    let more = rows.len() > limit;
    rows.truncate(limit);
    let items: Vec<Value> = rows
        .iter()
        .map(|m| {
            let own = m.from == pid;
            let peer = if own { &m.to } else { &m.from };
            // Receipts exist on the phone's own texts only.
            let client_id = if own {
                store::open_payload(&app.key, m).0["client_id"].clone()
            } else {
                Value::Null
            };
            let delivered_at = match (own, m.acked_at) {
                (true, Some(t)) => Value::from(fmt_time(t)),
                _ => Value::Null,
            };
            json!({"message": msg_json(&app.key, m), "workspace_name": store::ws_name(&c, peer),
                "delivered_at": delivered_at, "client_id": client_id})
        })
        .collect();
    let next = if more {
        rows.last().map(|m| encode_cursor(m.seq))
    } else {
        None
    };
    Ok(Json(json!({"items": items, "next": next})))
}

/// Work-update texts for a phone, newest first (?1 phone id, ?2 JSON workspace list, ?3 paired-at, ?4 ticket or NULL,
/// ?5 seq cursor, ?6 batch size). The same messages table as `MESSAGES_SQL`, only what workspaces sent.
/// Most rows opened (decrypted) for one `/v1/phone/updates` request.
const MAX_SCAN: usize = 2000;

const UPDATES_SQL: &str =
    "SELECT seq,id,from_addr,to_addr,type,created_at,ticket,reply_to,payload,acked_at FROM (
        SELECT m.* FROM json_each(?2) j CROSS JOIN messages m
          WHERE m.type='text' AND m.to_addr='phones' AND m.from_addr=j.value AND m.stored_at>=?3
            AND (?4 IS NULL OR m.ticket=?4) AND m.seq<?5
        UNION ALL
        SELECT m.* FROM json_each(?2) j CROSS JOIN messages m
          WHERE m.type='text' AND m.to_addr=?1 AND m.from_addr=j.value
            AND (?4 IS NULL OR m.ticket=?4) AND m.seq<?5
     ) ORDER BY seq DESC LIMIT ?6";

/// `GET /v1/phone/updates`: a read view over the stored texts that carry `body.update` (relay-api.md). Nothing is written.
async fn updates(
    State(app): State<AppState>,
    h: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Res<Json<Value>> {
    let limit = q
        .get("limit")
        .and_then(|l| l.parse::<usize>().ok())
        .unwrap_or(50)
        .clamp(1, 100);
    let workspace = q.get("workspace").filter(|w| !w.is_empty());
    let ticket = q.get("ticket").filter(|t| !t.is_empty());
    let after = q.get("after").filter(|a| !a.is_empty());
    if ticket.is_some() && workspace.is_none() {
        return Err(invalid("`ticket` needs `workspace`."));
    }
    let c = app.db.lock().unwrap();
    let (pid, _, ws) = auth::phone(&c, &h)?;
    // A workspace that is not on the list answers like an unknown one: an empty list.
    let list: Vec<String> = match workspace {
        Some(w) if ws.contains(w) => vec![w.clone()],
        Some(_) => vec![],
        None => ws,
    };
    let bad_after = || invalid("`after` is not an update of this ticket.");
    if list.is_empty() {
        return if after.is_some() && ticket.is_some() {
            Err(bad_after())
        } else {
            Ok(Json(json!({"items": [], "next": null})))
        };
    }
    let since: i64 = c.query_row(
        "SELECT COALESCE(paired_at, created_at) FROM phones WHERE id=?1",
        [&pid],
        |r| r.get(0),
    )?;
    let list_json = serde_json::to_string(&list).unwrap_or("[]".into());
    // Walk the filtered view newest first, in batches, and keep the texts with `body.update`.
    let mut st = c.prepare(UPDATES_SQL)?;
    let mut cursor = i64::MAX;
    if let (Some(a), Some(t), Some(w)) = (after, ticket, workspace) {
        // `after` must be an update of this ticket in this phone's view; its seq is the cursor (no walking).
        let m: Option<store::Msg> = c
            .query_row(
                &format!("SELECT {MSG_COLS} FROM messages WHERE id=?1 AND type='text' AND ticket=?2 AND from_addr=?3 AND ((to_addr='phones' AND stored_at>=?5) OR to_addr=?4)"),
                params![a, t, w, pid, since],
                msg_from_row,
            )
            .optional()?;
        match m {
            Some(m) if store::open_payload(&app.key, &m).0["update"].is_object() => cursor = m.seq,
            _ => return Err(bad_after()),
        }
    }
    let mut scanned = 0usize;
    let mut out: Vec<(store::Msg, Value)> = vec![];
    let mut seen = std::collections::HashSet::new();
    let mut more = false;
    let mut titles: Vec<Option<String>> = vec![];
    // grouped: the newest ticket_view of each ticket (a newer update without one keeps the last snapshot)
    let mut views: Vec<Value> = vec![];
    let mut extra = 0;
    'scan: loop {
        let rows: Vec<store::Msg> = st
            .query_map(
                params![pid, list_json, since, ticket, cursor, 200i64],
                msg_from_row,
            )?
            .collect::<Result<_, _>>()?;
        let Some(last) = rows.last() else { break };
        cursor = last.seq;
        for m in rows {
            // Hard cap on rows opened per request, whatever was found.
            scanned += 1;
            if scanned > MAX_SCAN {
                more = ticket.is_some() && !out.is_empty();
                break 'scan;
            }
            let (body, top) = store::open_payload(&app.key, &m);
            // General receipts (ack/working without a ticket) are not part of this per-ticket view.
            if !body["update"].is_object() || m.ticket.is_none() {
                continue;
            }
            let mut body = body;
            // the ticket's display key (message `key`, e.g. DM1-12) rides along for the item
            body["__key"] = top
                .get("key")
                .and_then(crate::rules::ticket_key)
                .map(Value::from)
                .unwrap_or(Value::Null);
            if ticket.is_some() {
                if out.len() == limit {
                    more = true;
                    break 'scan;
                }
                out.push((m, body));
            } else {
                // Grouped: the newest update per (workspace, ticket); its title falls back to the newest
                // titled update of that ticket (looked for in a bounded number of older rows).
                let key = (m.from.clone(), m.ticket.clone());
                if seen.insert(key.clone()) {
                    if out.len() < limit {
                        out.push((m, body));
                    }
                } else if let Some(i) = out
                    .iter()
                    .position(|(o, _)| (o.from.clone(), o.ticket.clone()) == key)
                {
                    if titles[i].is_none() {
                        titles[i] = body["update"]["title"].as_str().map(String::from);
                    }
                    if views[i].is_null() {
                        views[i] = body["ticket_view"].clone();
                    }
                }
                if titles.len() < out.len() {
                    titles.push(
                        out.last()
                            .and_then(|(_, b)| b["update"]["title"].as_str().map(String::from)),
                    );
                    views.push(
                        out.last()
                            .map_or(Value::Null, |(_, b)| b["ticket_view"].clone()),
                    );
                }
                if out.len() == limit {
                    extra += 1;
                    if extra > 1000
                        || (titles.iter().all(|t| t.is_some())
                            && views.iter().all(|v| !v.is_null()))
                    {
                        break 'scan;
                    }
                }
            }
        }
    }
    let next = if more {
        out.last().map(|(m, _)| Value::from(m.id.clone()))
    } else {
        None
    };
    let items: Vec<Value> = out
        .iter()
        .enumerate()
        .map(|(i, (m, b))| {
            let u = &b["update"];
            json!({"id": m.id, "workspace": m.from, "workspace_name": store::ws_name(&c, &m.from),
                "ticket": m.ticket, "key": b["__key"], "kind": u["kind"],
                "title": if ticket.is_some() { u["title"].clone() } else { titles.get(i).cloned().flatten().into() }, "text": b["text"],
                "reply_to": m.reply_to, "at": m.created_at,
                "ticket_view": if ticket.is_some() { b["ticket_view"].clone() } else { views.get(i).cloned().unwrap_or(Value::Null) }})
        })
        .collect();
    Ok(Json(json!({"items": items, "next": next})))
}

/// `GET /v1/phone/blobs/<id>`: a proof file named in a `body.ticket_view` of a text that a workspace on this phone's
/// list sent to it or to `phones` (same filter as `/v1/phone/messages`), uploaded by that workspace. Else 404.
async fn blob(
    State(app): State<AppState>,
    h: HeaderMap,
    axum::extract::Path(id): axum::extract::Path<String>,
) -> Res<axum::response::Response> {
    use axum::response::IntoResponse;
    let none = || not_found("No such file.");
    if !valid_id(&id, "b_", 16) {
        return Err(none());
    }
    {
        let c = app.db.lock().unwrap();
        let (pid, _, ws) = auth::phone(&c, &h)?;
        let since: i64 = c.query_row(
            "SELECT COALESCE(paired_at, created_at) FROM phones WHERE id=?1",
            [&pid],
            |r| r.get(0),
        )?;
        let ok: bool = c.query_row(
            "SELECT EXISTS(SELECT 1 FROM blobs WHERE id=?1 AND uploader=?4)
             OR EXISTS(SELECT 1 FROM view_blobs v JOIN messages m ON m.id=v.msg_id JOIN blobs b ON b.id=v.blob_id
               WHERE v.blob_id=?1 AND m.type='text' AND b.uploader=m.from_addr
                 AND m.from_addr IN (SELECT value FROM json_each(?2))
                 AND ((m.to_addr='phones' AND m.stored_at>=?3) OR m.to_addr=?4))",
            params![id, serde_json::to_string(&ws).unwrap_or("[]".into()), since, pid],
            |r| r.get(0),
        )?;
        if !ok {
            return Err(none());
        }
    }
    let raw = tokio::fs::read(app.blob_path(&id))
        .await
        .map_err(|_| none())?;
    let plain = crate::crypto::open(&app.key, &id, &raw)
        .ok_or_else(|| internal("blob does not decrypt"))?;
    Ok((
        [
            (axum::http::header::CONTENT_TYPE, "application/octet-stream"),
            (axum::http::header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
            (axum::http::header::CONTENT_DISPOSITION, "attachment"),
        ],
        plain,
    )
        .into_response())
}

// ---------- phone app v3 ----------

const MSG_SCHEMA_ID: &str = "https://orch.severin.io/contracts/message.schema.json";
const PHONE_SCHEMA_ID: &str = "https://orch.severin.io/contracts/phone-api.schema.json";
const DEFS: [&str; 7] = [
    "heartbeat_request",
    "control_request",
    "send_request",
    "answer_request",
    "settings_patch_request",
    "group_mute_request",
    "workspace_patch_request",
];

/// Request bodies are checked against `phone-api.schema.json` (the contract), one `$defs` entry each.
fn schemas() -> &'static HashMap<&'static str, jsonschema::JSONSchema> {
    static S: std::sync::OnceLock<HashMap<&'static str, jsonschema::JSONSchema>> =
        std::sync::OnceLock::new();
    S.get_or_init(|| {
        let msg: Value = serde_json::from_str(include_str!("../../contracts/message.schema.json"))
            .expect("message schema");
        let phone: Value =
            serde_json::from_str(include_str!("../../contracts/phone-api.schema.json"))
                .expect("phone schema");
        DEFS.iter()
            .map(|d| {
                let root = json!({"$ref": format!("{PHONE_SCHEMA_ID}#/$defs/{d}")});
                let s = jsonschema::JSONSchema::options()
                    .should_validate_formats(true)
                    .with_document(MSG_SCHEMA_ID.into(), msg.clone())
                    .with_document(PHONE_SCHEMA_ID.into(), phone.clone())
                    .compile(&root)
                    .expect("compile phone schema");
                (*d, s)
            })
            .collect()
    })
}

pub(crate) fn check(def: &str, v: &Value) -> Res<()> {
    match schemas()[def].validate(v) {
        Ok(()) => Ok(()),
        Err(errs) => Err(invalid(
            errs.take(3)
                .map(|e| format!("{} ({})", e, e.instance_path))
                .collect::<Vec<_>>()
                .join("; "),
        )),
    }
}

/// The id of the message this phone already stored under `client_id` (one namespace across send and answer).
fn client_dup(c: &rusqlite::Connection, pid: &str, cid: &str) -> rusqlite::Result<Option<String>> {
    c.query_row(
        "SELECT msg_id FROM phone_client_ids WHERE phone=?1 AND client_id=?2",
        [pid, cid],
        |r| r.get(0),
    )
    .optional()
}

fn remember_client_id(
    c: &rusqlite::Connection,
    pid: &str,
    cid: &str,
    msg_id: &str,
) -> rusqlite::Result<()> {
    c.execute(
        "INSERT INTO phone_client_ids(phone,client_id,msg_id) VALUES(?1,?2,?3)",
        [pid, cid, msg_id],
    )?;
    Ok(())
}

async fn answer(
    State(app): State<AppState>,
    h: HeaderMap,
    body: Bytes,
) -> Res<(StatusCode, Json<Value>)> {
    let v = parse_body(&body)?;
    let (id, cid) = {
        let c = app.db.lock().unwrap();
        let (pid, name, ws) = auth::phone(&c, &h)?;
        // A retry of the same client_id is a duplicate, checked before the 409 and whatever the body says.
        if let Some(cid) = v["client_id"].as_str() {
            if let Some(old) = client_dup(&c, &pid, cid)? {
                return Ok((
                    StatusCode::OK,
                    Json(json!({"id": old, "client_id": cid, "duplicate": true})),
                ));
            }
        }
        check("answer_request", &v)?;
        let qid = v["question_message_id"].as_str().unwrap_or("");
        let text = v["answer"].as_str().unwrap_or("");
        let cid = v["client_id"].as_str().map(String::from);
        let q = store::get_msg(&c, qid)?
            .filter(|q| {
                q.typ == "question" && (q.to == "phones" || q.to == pid) && ws.contains(&q.from)
            })
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
        let (qb, qextra) = store::open_payload(&app.key, &q);
        let tx = c.unchecked_transaction()?;
        let mut abody = json!({"question_id": qb["question_id"], "answer": text, "answered_by": format!("human:{name}")});
        if let Some(cid) = &cid {
            abody["client_id"] = cid.clone().into();
        }
        let m = store::system_message_with_key(
            qextra.get("key").and_then(crate::rules::ticket_key),
            &c,
            &app.key,
            &pid,
            &q.from,
            "answer",
            q.ticket.as_deref(),
            Some(qid),
            abody,
        )?;
        let id = m["id"].as_str().unwrap().to_string();
        if let Some(cid) = &cid {
            remember_client_id(&c, &pid, cid, &id)?;
        }
        tx.commit()?;
        (id, cid)
    };
    app.notify.notify_waiters();
    Ok((
        StatusCode::CREATED,
        Json(json!({"id": id, "client_id": cid})),
    ))
}

/// Blob ids a send request names, with the size an attachment claims: attachments, `voice.blob_id`, pins' `voice_blob_id`.
fn named_blobs(v: &Value) -> Vec<(String, Option<i64>)> {
    let mut out = vec![];
    for a in v["attachments"].as_array().into_iter().flatten() {
        if let Some(b) = a["blob_id"].as_str() {
            out.push((b.to_string(), Some(a["size"].as_i64().unwrap_or(-1))));
        }
    }
    if let Some(b) = v["voice"]["blob_id"].as_str() {
        out.push((b.to_string(), None));
    }
    for p in v["feedback"]["pins"].as_array().into_iter().flatten() {
        if let Some(b) = p["voice_blob_id"].as_str() {
            out.push((b.to_string(), None));
        }
    }
    out
}

async fn send(
    State(app): State<AppState>,
    h: HeaderMap,
    body: Bytes,
) -> Res<(StatusCode, Json<Value>)> {
    let v = parse_body(&body)?;
    let id = {
        let c = app.db.lock().unwrap();
        let (pid, _, ws) = auth::phone(&c, &h)?;
        if let Some(cid) = v["client_id"].as_str() {
            if let Some(old) = client_dup(&c, &pid, cid)? {
                return Ok((
                    StatusCode::OK,
                    Json(json!({"id": old, "client_id": cid, "duplicate": true})),
                ));
            }
        }
        check("send_request", &v)?;
        let to = v["to"].as_str().unwrap_or("");
        let cid = v["client_id"].as_str();
        if !ws.iter().any(|w| w == to) || !store::ws_exists(&c, to) {
            return Err(not_allowed("This phone may not send to that workspace."));
        }
        let ticket = v["ticket"].as_str();
        let reply_to = v["reply_to"].as_str();
        if let Some(r) = reply_to {
            // Only a text of this phone's own conversation with that workspace (the /v1/phone/messages view).
            let since: i64 = c.query_row(
                "SELECT COALESCE(paired_at, created_at) FROM phones WHERE id=?1",
                [&pid],
                |r| r.get(0),
            )?;
            let ok: bool = c.query_row(
                "SELECT EXISTS(SELECT 1 FROM messages WHERE id=?1 AND type='text' AND (
                    (from_addr=?2 AND to_addr=?3) OR (from_addr=?3 AND (to_addr=?2 OR (to_addr='phones' AND stored_at>=?4)))))",
                params![r, pid, to, since],
                |r| r.get(0),
            )?;
            if !ok {
                return Err(invalid(
                    "`reply_to` must be a text of your conversation with this workspace.",
                ));
            }
        }
        // Every file must be an upload of this phone (another phone's or an unknown id answers the same 404).
        let blobs = named_blobs(&v);
        for (b, size) in &blobs {
            let stored: Option<i64> = c
                .query_row(
                    "SELECT size FROM blobs WHERE id=?1 AND uploader=?2",
                    [b, &pid],
                    |r| r.get(0),
                )
                .optional()?;
            match (stored, size) {
                (None, _) => {
                    return Err(not_found("Upload the file first (POST /v1/phone/blobs)."))
                }
                (Some(n), Some(claimed)) if n != *claimed => {
                    return Err(invalid(
                        "An attachment's size does not match the uploaded file.",
                    ))
                }
                _ => {}
            }
        }
        let mut b = serde_json::Map::new();
        if let Some(cid) = cid {
            b.insert("client_id".into(), cid.into());
        }
        if v["general"] == true {
            b.insert("general".into(), true.into());
        }
        for k in ["text", "attachments", "voice", "location", "feedback"] {
            if !v[k].is_null() {
                b.insert(k.into(), v[k].clone());
            }
        }
        let body = Value::Object(b);
        // Same schema check as workspace messages.
        let mut cand = json!({"schema": "orch.msg/1", "id": rand_id("m_", 16), "from": pid, "to": to,
            "type": "text", "created_at": fmt_time(now()), "body": body});
        if let Some(t) = ticket {
            cand["ticket"] = t.into();
        }
        if let Some(r) = reply_to {
            cand["reply_to"] = r.into();
        }
        crate::rules::validate_schema(&cand).map_err(invalid)?;
        let tx = c.unchecked_transaction()?;
        let m = store::system_message(&c, &app.key, &pid, to, "text", ticket, reply_to, body)?;
        let id = m["id"].as_str().unwrap().to_string();
        if let Some(cid) = cid {
            remember_client_id(&c, &pid, cid, &id)?;
        }
        // The workspace named in this text may read these files (GET /v1/blobs/<id>).
        for (b, _) in &blobs {
            c.execute(
                "INSERT OR IGNORE INTO phone_blobs(blob_id,msg_id) VALUES(?1,?2)",
                [b, &id],
            )?;
        }
        tx.commit()?;
        id
    };
    app.notify.notify_waiters();
    let cid = v["client_id"].clone();
    Ok((
        StatusCode::CREATED,
        Json(json!({"id": id, "client_id": cid})),
    ))
}

/// Largest phone upload: 25 MB.
pub const MAX_PHONE_BLOB: usize = 25 * 1024 * 1024;
/// Most bytes one phone may upload in 24 hours: 1 GB.
const PHONE_UPLOAD_DAY: i64 = 1024 * 1024 * 1024;
/// Slowest average upload speed (bytes per second) allowed after the grace time (else 408).
const MIN_UPLOAD_BPS: f64 = 16.0 * 1024.0;
/// Whole body at most this long (else 408).
const UPLOAD_TOTAL: std::time::Duration = std::time::Duration::from_secs(300);

/// The phone's one upload in flight; freed when the request ends, however it ends.
struct UploadSlot {
    app: AppState,
    pid: String,
}

impl Drop for UploadSlot {
    fn drop(&mut self) {
        self.app.upload_inflight.lock().unwrap().remove(&self.pid);
    }
}

/// `POST /v1/phone/blobs`: raw bytes, stored like workspace blobs (encrypted), uploader = this phone.
async fn upload_blob(
    State(app): State<AppState>,
    h: HeaderMap,
    body: axum::body::Body,
) -> Res<(StatusCode, Json<Value>)> {
    use futures_util::StreamExt;
    use sha2::{Digest, Sha256};
    // Authenticate before reading a single body byte.
    let pid = {
        let c = app.db.lock().unwrap();
        auth::phone(&c, &h)?.0
    };
    let too_big = || too_large("Files can be at most 25 MB.");
    let announced = h
        .get(axum::http::header::CONTENT_LENGTH)
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.parse::<usize>().ok());
    if announced.is_some_and(|n| n > MAX_PHONE_BLOB) {
        return Err(too_big());
    }
    // One upload at a time per phone, and a daily budget that counts what is in flight: the check and the
    // reservation happen together under the database lock, before a body byte is read.
    let _slot = {
        let c = app.db.lock().unwrap();
        let used: i64 = c.query_row(
            "SELECT COALESCE(SUM(size),0) FROM blobs WHERE uploader=?1 AND created_at>?2",
            params![pid, now() - 86400],
            |r| r.get(0),
        )?;
        let want = announced.unwrap_or(MAX_PHONE_BLOB) as i64;
        let mut live = app.upload_inflight.lock().unwrap();
        if live.contains_key(&pid) || used + want > PHONE_UPLOAD_DAY {
            return Err(ApiError {
                status: StatusCode::TOO_MANY_REQUESTS,
                code: "rate_limited",
                message: "Too many uploads. Try again later.".into(),
            });
        }
        live.insert(pid.clone(), want);
        UploadSlot {
            app: app.clone(),
            pid: pid.clone(),
        }
    };
    // A few uploads in flight per relay (memory); do not wait for ever.
    let _permit = tokio::time::timeout(app.upload_wait(), app.upload_slots.acquire())
        .await
        .map_err(|_| ApiError {
            status: StatusCode::SERVICE_UNAVAILABLE,
            code: "busy",
            message: "The relay is busy. Try again in a moment.".into(),
        })?
        .map_err(internal)?;
    let mut buf: Vec<u8> = Vec::new();
    let mut hasher = Sha256::new();
    let mut stream = body.into_data_stream();
    let started = std::time::Instant::now();
    let timeout = || ApiError {
        status: StatusCode::REQUEST_TIMEOUT,
        code: "request_timeout",
        message: "The upload took too long.".into(),
    };
    loop {
        let left = UPLOAD_TOTAL.saturating_sub(started.elapsed());
        let next = tokio::time::timeout(left.min(app.upload_idle()), stream.next())
            .await
            .map_err(|_| timeout())?;
        let Some(chunk) = next else { break };
        let chunk = chunk.map_err(|_| invalid("Upload was interrupted."))?;
        // too slow on average (below 16 KB/s once past the grace time): free the slot
        let age = started.elapsed();
        if age
            >= std::time::Duration::from_millis(
                app.upload_grace_ms
                    .load(std::sync::atomic::Ordering::Relaxed),
            )
            && ((buf.len() + chunk.len()) as f64) < MIN_UPLOAD_BPS * age.as_secs_f64()
        {
            return Err(timeout());
        }
        if buf.len() + chunk.len() > MAX_PHONE_BLOB {
            return Err(too_big());
        }
        hasher.update(&chunk);
        buf.extend_from_slice(&chunk);
    }
    if buf.is_empty() {
        return Err(invalid("The file is empty."));
    }
    let size = buf.len();
    let sha = hex::encode(hasher.finalize());
    let id = rand_id("b_", 16);
    crate::crypto::seal_in_place(&app.key, &id, &mut buf);
    if let Err(e) = tokio::fs::write(app.blob_path(&id), &buf).await {
        let _ = tokio::fs::remove_file(app.blob_path(&id)).await;
        return Err(internal(e));
    }
    drop(buf);
    let ins = app.db.lock().unwrap().execute(
        "INSERT INTO blobs(id,uploader,size,sha256,created_at) VALUES(?1,?2,?3,?4,?5)",
        params![id, pid, size as i64, sha, now()],
    );
    if let Err(e) = ins {
        let _ = tokio::fs::remove_file(app.blob_path(&id)).await;
        return Err(e.into());
    }
    Ok((
        StatusCode::CREATED,
        Json(json!({"blob_id": id, "size": size, "sha256": sha})),
    ))
}

async fn get_settings(State(app): State<AppState>, h: HeaderMap) -> Res<Json<Value>> {
    let c = app.db.lock().unwrap();
    let (pid, ..) = auth::phone(&c, &h)?;
    Ok(Json(store::phone_settings(&c, &pid)))
}

async fn patch_settings(
    State(app): State<AppState>,
    h: HeaderMap,
    body: Bytes,
) -> Res<Json<Value>> {
    let v = parse_body(&body)?;
    let c = app.db.lock().unwrap();
    let (pid, ..) = auth::phone(&c, &h)?;
    check("settings_patch_request", &v)?;
    // parse before any write: a bad time must not leave the other fields half saved
    let mute_all = v.get("mute_all_until").map(mute_until).transpose()?;
    c.execute(
        "INSERT OR IGNORE INTO phone_settings(phone) VALUES(?1)",
        [&pid],
    )?;
    if let Some(s) = v["speak"].as_str() {
        c.execute(
            "UPDATE phone_settings SET speak=?2 WHERE phone=?1",
            params![pid, s],
        )?;
    }
    if let Some(b) = v["swiss_german"].as_bool() {
        c.execute(
            "UPDATE phone_settings SET swiss_german=?2 WHERE phone=?1",
            params![pid, b],
        )?;
    }
    if let Some(n) = v["tts_cap_usd"].as_f64() {
        c.execute(
            "UPDATE phone_settings SET tts_cap_usd=?2 WHERE phone=?1",
            params![pid, n],
        )?;
    }
    if let Some(m) = mute_all {
        match m {
            Some(u) => c.execute(
                "INSERT INTO phone_mute_all(phone,until) VALUES(?1,?2) ON CONFLICT(phone) DO UPDATE SET until=?2",
                params![pid, u],
            )?,
            None => c.execute("DELETE FROM phone_mute_all WHERE phone=?1", [&pid])?,
        };
    }
    Ok(Json(store::phone_settings(&c, &pid)))
}

/// A `muted_until` / `mute_all_until` value: a future UTC time, `"forever"`, or off (`null`, a past time).
fn mute_until(v: &Value) -> Res<Option<i64>> {
    Ok(match v {
        Value::String(s) if s == "forever" => Some(store::MUTE_FOREVER),
        Value::String(s) => {
            let t = time::OffsetDateTime::parse(s, &time::format_description::well_known::Rfc3339)
                .map_err(|_| {
                    invalid("A mute time must be a UTC time like 2026-11-06T22:00:00Z.")
                })?;
            Some(t.unix_timestamp()).filter(|t| *t > now())
        }
        _ => None,
    })
}

/// Most active group mutes one phone may hold.
const MAX_GROUP_MUTES: usize = 100;

/// `PATCH /v1/phone/groups/<host ws>/<grp id>`: mute or unmute one group for this phone (no push while muted).
async fn patch_group(
    State(app): State<AppState>,
    h: HeaderMap,
    axum::extract::Path((host, gid)): axum::extract::Path<(String, String)>,
    body: Bytes,
) -> Res<Json<Value>> {
    let c = app.db.lock().unwrap();
    let (pid, _, ws) = auth::phone(&c, &h)?;
    let v = parse_body(&body)?;
    check("group_mute_request", &v)?;
    if !valid_group_id(&gid) {
        return Err(invalid("Not a group id."));
    }
    let until = mute_until(&v["muted_until"])?;
    // Unmuting is allowed for any host (also one that left the list); muting needs a host on the list.
    if until.is_some() && !ws.contains(&host) {
        return Err(not_found("Not found."));
    }
    store::purge_group_mutes(&c, &pid);
    match until {
        Some(u) => {
            let known = !store::group_muted_until(&c, &pid, &host, &gid).is_null();
            if !known && store::group_mutes(&c, &pid).len() >= MAX_GROUP_MUTES {
                return Err(invalid("Too many muted groups (at most 100)."));
            }
            c.execute(
                "INSERT INTO phone_group_mutes(phone,host,grp,until) VALUES(?1,?2,?3,?4) ON CONFLICT(phone,host,grp) DO UPDATE SET until=?4",
                params![pid, host, gid, u],
            )?
        }
        None => c.execute(
            "DELETE FROM phone_group_mutes WHERE phone=?1 AND host=?2 AND grp=?3",
            params![pid, host, gid],
        )?,
    };
    Ok(Json(
        json!({"host": host, "id": gid, "muted_until": store::group_muted_until(&c, &pid, &host, &gid)}),
    ))
}

/// `grp_t_` + 6..16 lowercase letters or digits (chat-groups.schema.json).
fn valid_group_id(id: &str) -> bool {
    id.strip_prefix("grp_t_").is_some_and(|r| {
        (6..=16).contains(&r.len())
            && r.bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit())
    })
}

/// `PATCH /v1/phone/workspaces/<ws>`: mute or unmute a workspace for this phone (no push while muted).
async fn patch_workspace(
    State(app): State<AppState>,
    h: HeaderMap,
    axum::extract::Path(wsid): axum::extract::Path<String>,
    body: Bytes,
) -> Res<Json<Value>> {
    let v = parse_body(&body)?;
    let c = app.db.lock().unwrap();
    let (pid, _, ws) = auth::phone(&c, &h)?;
    if !ws.contains(&wsid) {
        return Err(not_found("No such workspace."));
    }
    check("workspace_patch_request", &v)?;
    let until = mute_until(&v["muted_until"])?;
    match until {
        Some(u) => c.execute(
            "INSERT INTO phone_mutes(phone,ws,until) VALUES(?1,?2,?3) ON CONFLICT(phone,ws) DO UPDATE SET until=?3",
            params![pid, wsid, u],
        )?,
        None => c.execute(
            "DELETE FROM phone_mutes WHERE phone=?1 AND ws=?2",
            params![pid, wsid],
        )?,
    };
    let mut card = c.query_row(
        &format!("SELECT {} FROM workspaces WHERE id=?1", store::WS_CARD_COLS),
        [&wsid],
        store::ws_card,
    )?;
    crate::look::add_to(&c, &mut card, false);
    card["open_questions"] = open_questions(&c, &pid, &ws)?
        .iter()
        .filter(|m| m.from == wsid)
        .count()
        .into();
    card["muted_until"] = store::muted_until(&c, &pid, &wsid);
    card["mobile_mode"] = store::mobile_mode(&c, &wsid);
    Ok(Json(card))
}

/// `DELETE /v1/phone/workspaces/<ws>`: drop the workspace from this phone's list.
async fn delete_workspace(
    State(app): State<AppState>,
    h: HeaderMap,
    axum::extract::Path(wsid): axum::extract::Path<String>,
) -> Res<StatusCode> {
    let c = app.db.lock().unwrap();
    let (pid, _, ws) = auth::phone(&c, &h)?;
    if !ws.contains(&wsid) {
        return Err(not_found("No such workspace."));
    }
    let rest: Vec<&String> = ws.iter().filter(|w| **w != wsid).collect();
    c.execute(
        "UPDATE phones SET workspaces=?2 WHERE id=?1",
        params![pid, serde_json::to_string(&rest).unwrap_or("[]".into())],
    )?;
    c.execute(
        "DELETE FROM phone_mutes WHERE phone=?1 AND ws=?2",
        params![pid, wsid],
    )?;
    store::forget_group_mutes_of(&c, &pid, &wsid);
    // The workspace can no longer reach this phone: it refreshes its phone list.
    store::bump_and_hint(&c, &app.key, std::slice::from_ref(&wsid))?;
    Ok(StatusCode::NO_CONTENT)
}

/// Redeem calls allowed per phone and minute.
const REDEEM_PER_MINUTE: u32 = 10;

/// `POST /v1/phone/invitations/redeem`: an invitation link adds its workspaces to this (paired) phone's list.
async fn redeem(State(app): State<AppState>, h: HeaderMap, body: Bytes) -> Res<Json<Value>> {
    let v = parse_body(&body)?;
    let c = app.db.lock().unwrap();
    let (pid, _, ws) = auth::phone(&c, &h)?;
    {
        let t = now();
        let mut m = app.redeem_rate.lock().unwrap();
        let e = m.entry(pid.clone()).or_insert((t, 0));
        if t - e.0 >= 60 {
            *e = (t, 0);
        }
        e.1 += 1;
        if e.1 > REDEEM_PER_MINUTE {
            return Err(ApiError {
                status: StatusCode::TOO_MANY_REQUESTS,
                code: "rate_limited",
                message: "Too many tries. Try again in a minute.".into(),
            });
        }
    }
    let code = v["code"]
        .as_str()
        .filter(|c| c.starts_with("pc_"))
        .ok_or_else(|| invalid("`code` is the code from the invitation link (pc_…)."))?;
    let row: Option<(String, i64, bool)> = c
        .query_row(
            "SELECT phone_id,expires_at,used FROM pair_codes WHERE hash=?1",
            [token_hash(code)],
            |r| Ok((r.get(0)?, r.get(1)?, r.get::<_, i64>(2)? != 0)),
        )
        .optional()?;
    let Some((inv, exp, used)) = row else {
        return Err(not_found("No such invitation."));
    };
    if used || exp < now() {
        return Err(gone("This invitation was already used or has expired."));
    }
    // The invitation is the unpaired phone entry the admin made. A paired phone is not an invitation.
    let inv_ws: Option<String> = c
        .query_row(
            "SELECT workspaces FROM phones WHERE id=?1 AND token_hash IS NULL",
            [&inv],
            |r| r.get(0),
        )
        .optional()?;
    let Some(inv_ws) = inv_ws.filter(|_| inv != pid) else {
        return Err(gone("This invitation was already used or has expired."));
    };
    let wanted: Vec<String> = store::parse_ws_list(&inv_ws)
        .into_iter()
        .filter(|w| store::ws_exists(&c, w))
        .collect();
    let added: Vec<String> = wanted.iter().filter(|w| !ws.contains(w)).cloned().collect();
    let mut list = ws.clone();
    list.extend(added.iter().cloned());
    let tx = c.unchecked_transaction()?;
    for w in &added {
        store::forget_group_mutes_of(&c, &pid, w);
        c.execute(
            "DELETE FROM phone_mutes WHERE phone=?1 AND ws=?2",
            params![pid, w],
        )?;
    }
    c.execute(
        "UPDATE phones SET workspaces=?2 WHERE id=?1",
        params![pid, serde_json::to_string(&list).unwrap_or("[]".into())],
    )?;
    c.execute(
        "DELETE FROM phones WHERE id=?1 AND token_hash IS NULL",
        [&inv],
    )?;
    c.execute(
        "UPDATE pair_codes SET used=1 WHERE hash=?1",
        [token_hash(code)],
    )?;
    if !added.is_empty() {
        store::bump_and_hint(&c, &app.key, &added)?;
    }
    tx.commit()?;
    let out: Vec<Value> = wanted
        .iter()
        .filter_map(|w| store::ws_name(&c, w).map(|n| json!({"id": w, "name": n})))
        .collect();
    Ok(Json(json!({"workspaces": out})))
}

async fn signout(State(app): State<AppState>, h: HeaderMap) -> Res<StatusCode> {
    let c = app.db.lock().unwrap();
    let (pid, _, ws) = auth::phone(&c, &h)?;
    c.execute(
        "UPDATE phones SET token_hash=NULL, apns_token=NULL WHERE id=?1",
        [&pid],
    )?;
    store::forget_phone_mutes(&c, &pid);
    // Its workspaces no longer list this phone.
    store::bump_and_hint(&c, &app.key, &ws)?;
    Ok(StatusCode::NO_CONTENT)
}

/// Push a new question or text to the phones it is for: every phone that may reach the sending workspace
/// (`to: phones`) or that one phone (`to: ph_…`). Question pushes carry `message_id` (tap opens the question);
/// text pushes carry `type: "text"` and `text_id` instead.
pub async fn push_message(app: &AppState, q: &Value) {
    let to = q["to"].as_str().unwrap_or("").to_string();
    let from = q["from"].as_str().unwrap_or("").to_string();
    let is_text = q["type"] == "text";
    // Work updates: only result / question / failure / stopped are pushed. ack, working and note stay quiet
    // and do not use up the text budget.
    let update = &q["body"]["update"];
    if is_text
        && update.is_object()
        && !matches!(
            update["kind"].as_str(),
            Some("result" | "question" | "failure" | "stopped")
        )
    {
        return;
    }
    let targets: Vec<(bool, String)> = {
        let c = app.db.lock().unwrap();
        let mut st = match c.prepare(
            "SELECT sandbox,apns_token,workspaces,id FROM phones WHERE apns_token IS NOT NULL AND token_hash IS NOT NULL",
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
                    r.get::<_, String>(3)?,
                ))
            })
            .map(|r| r.flatten().collect::<Vec<_>>())
            .unwrap_or_default();
        let mut budget = app.push_budget.lock().unwrap();
        rows.into_iter()
            .filter(|(_, _, w, id)| {
                store::parse_ws_list(w).contains(&from) && (to == "phones" || &to == id)
            })
            // Muted: no push for anything from that workspace (stored and listed as usual).
            .filter(|(.., id)| !store::push_muted(&c, id, &from, &q["body"]))
            // L2: texts are always stored; only the push is skipped when the budget is used up.
            .filter(|(.., id)| {
                !is_text
                    || budget
                        .entry(format!("{from}|{id}"))
                        .or_default()
                        .allow(crate::util::now())
            })
            .map(|(s, t, ..)| (s, t))
            .collect()
    };
    if targets.is_empty() {
        return;
    }
    let name = {
        let c = app.db.lock().unwrap();
        store::ws_name(&c, q["from"].as_str().unwrap_or("")).unwrap_or_default()
    };
    let body_text = q["body"]["text"].as_str().unwrap_or("");
    let text = match update["title"].as_str() {
        Some(t) if is_text => format!("{t}: {}", body_text.lines().next().unwrap_or("")),
        _ => body_text.to_string(),
    };
    // "DM1-12 · title": the ticket's display key first when the workspace sent one
    let key = crate::rules::ticket_key(&q["key"]);
    let text: String = match key {
        Some(k) => format!("{k} · {text}"),
        None => text,
    }
    .chars()
    .take(120)
    .collect();
    let mut payload = json!({"aps": {"alert": {"title": name, "body": text}, "sound": "default"},
        "workspace": q["from"]});
    if q["ticket"].is_string() {
        payload["ticket"] = q["ticket"].clone();
        payload["key"] = key.map(Value::from).unwrap_or(Value::Null);
    }
    if q["type"] == "question" {
        payload["message_id"] = q["id"].clone();
    } else {
        payload["type"] = "text".into();
        payload["text_id"] = q["id"].clone();
    }
    send_pushes(app, targets, &payload).await;
}

/// Send one payload to each (sandbox, device token); a dead token is forgotten.
pub async fn send_pushes(app: &AppState, targets: Vec<(bool, String)>, payload: &Value) {
    for (sandbox, token) in targets {
        if let Err(e) = app.pusher.send(sandbox, &token, payload).await {
            tracing::warn!("push failed: {}", e.message);
            if e.dead_token {
                let c = app.db.lock().unwrap();
                let _ = c.execute(
                    "UPDATE phones SET apns_token=NULL WHERE apns_token=?1",
                    [&token],
                );
            }
        }
    }
}

/// `POST /v1/phone/control`: a phone asks a workspace on its list for one thing (`mobile_mode_off`). The relay builds
/// the `control` message itself (`from` = the authenticated phone); nobody else can make this type.
async fn control(
    State(app): State<AppState>,
    h: HeaderMap,
    body: Bytes,
) -> Res<(StatusCode, Json<Value>)> {
    let v = parse_body(&body)?;
    let (id, cid) = {
        let c = app.db.lock().unwrap();
        let (pid, _, ws) = auth::phone(&c, &h)?;
        if let Some(cid) = v["client_id"].as_str() {
            if let Some(old) = client_dup(&c, &pid, cid)? {
                return Ok((
                    StatusCode::OK,
                    Json(json!({"id": old, "client_id": cid, "duplicate": true})),
                ));
            }
        }
        check("control_request", &v)?;
        let to = v["to"].as_str().unwrap_or("");
        if !ws.iter().any(|w| w == to) || !store::ws_exists(&c, to) {
            return Err(not_allowed("This phone may not send to that workspace."));
        }
        let mut b = serde_json::Map::new();
        b.insert("control".into(), v["control"].clone());
        if let Some(cid) = v["client_id"].as_str() {
            b.insert("client_id".into(), cid.into());
        }
        let tx = c.unchecked_transaction()?;
        let m = store::system_message(
            &c,
            &app.key,
            &pid,
            to,
            "control",
            None,
            None,
            Value::Object(b),
        )?;
        let id = m["id"].as_str().unwrap().to_string();
        if let Some(cid) = v["client_id"].as_str() {
            remember_client_id(&c, &pid, cid, &id)?;
        }
        tx.commit()?;
        (id, v["client_id"].clone())
    };
    app.notify.notify_waiters();
    Ok((
        StatusCode::CREATED,
        Json(json!({"id": id, "client_id": cid})),
    ))
}

/// `GET /v1/phone/speech/<message_id>`: the text read aloud as mp3 (see `speech::generate`).
async fn speech(
    State(app): State<AppState>,
    h: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
    axum::extract::Path(id): axum::extract::Path<String>,
) -> Res<axum::response::Response> {
    use axum::response::IntoResponse;
    let (pid, ws, settings) = {
        let c = app.db.lock().unwrap();
        let (pid, _, ws) = auth::phone(&c, &h)?;
        let s = crate::speech::Settings::of(&c, &pid);
        (pid, ws, s)
    };
    let mp3 = crate::speech::generate(
        &app,
        &pid,
        &ws,
        &settings,
        &id,
        q.get("lang").map(String::as_str),
    )
    .await?;
    Ok(([(axum::http::header::CONTENT_TYPE, "audio/mpeg")], mp3).into_response())
}
