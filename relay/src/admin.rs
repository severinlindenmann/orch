//! Admin listener: portal + `/admin/api`. Reached over the private network only; admin token required.
use crate::api::parse_body;
use crate::error::*;
use crate::state::AppState;
use crate::store::{self, msg_from_row, msg_json, MSG_COLS};
use crate::util::*;
use crate::{auth, shared};
use axum::body::Bytes;
use axum::extract::{DefaultBodyLimit, Path, Query, State};
use axum::http::{header, HeaderMap, StatusCode};
use axum::response::{Html, IntoResponse};
use axum::routing::{delete, get, post, put};
use axum::{Json, Router};
use rusqlite::{params, params_from_iter, Connection};
use serde_json::{json, Value};
use std::collections::{BTreeMap, HashMap};

pub fn router(app: AppState) -> Router {
    Router::new()
        .route("/health", get(|| async { "ok" }))
        .route(
            "/admin",
            get(|| async { Html(include_str!("../web/portal.html")) }),
        )
        .route(
            "/admin/style.css",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/css; charset=utf-8")],
                    include_str!("../web/style.css"),
                )
            }),
        )
        .route("/admin/api/workspaces", get(list_ws).post(add_ws))
        .route(
            "/admin/api/workspaces/:id",
            axum::routing::patch(edit_ws).delete(del_ws),
        )
        .route("/admin/api/workspaces/:id/token", post(new_token))
        .route(
            "/admin/api/workspaces/:id/profile/approve",
            post(approve_profile),
        )
        .route(
            "/admin/api/workspaces/:id/profile/reject",
            post(reject_profile),
        )
        .route("/admin/api/rules", get(get_rules).put(put_rules))
        .route("/admin/api/messages", get(messages))
        .route("/admin/api/allows", get(allows))
        .route("/admin/api/shared", get(get_shared))
        .route("/admin/api/shared/assign/:ws", put(assign))
        .route(
            "/admin/api/shared/:kind/:name",
            put(put_shared).delete(del_shared),
        )
        .route(
            "/admin/api/voice",
            get(get_voice).put(put_voice).delete(del_voice),
        )
        .route("/admin/api/webhooks", get(webhooks))
        .route("/admin/api/webhooks/:id", delete(del_webhook))
        .route("/admin/api/phones", get(list_phones).post(add_phone))
        .route(
            "/admin/api/phones/:id",
            axum::routing::patch(edit_phone).delete(del_phone),
        )
        .fallback(|uri: axum::http::Uri| async move {
            if uri.path().starts_with("/admin/api/") {
                return not_found("No such route.").into_response();
            }
            (
                StatusCode::NOT_FOUND,
                Html(include_str!("../web/not-available.html")),
            )
                .into_response()
        })
        .layer(DefaultBodyLimit::max(21 * 1024 * 1024))
        .with_state(app)
}

fn guard(app: &AppState, h: &HeaderMap) -> Res<()> {
    auth::admin(app, h)
}

fn parse_tags(v: &Value) -> Res<Vec<String>> {
    let Some(a) = v.as_array() else {
        return Err(invalid("`tags` must be a list."));
    };
    store::valid_tags(a).map_err(invalid)
}

fn parse_description(v: &Value) -> Res<String> {
    store::valid_description(v.as_str().unwrap_or("")).map_err(invalid)
}

pub fn prompt(public: &str, ws: &str, token: &str) -> String {
    format!(
        "Connect this workspace to orch-relay. Run in the project folder:\n  orch addon add relay --yes\n  orch relay connect {public} --workspace {ws} --token {token}\nIf orch is not installed yet:\n  macOS/Linux: curl -fsSL {public}/onboarding.sh | sh -s -- --workspace {ws} --token {token}\n  Windows: & ([scriptblock]::Create((irm {public}/onboarding.ps1))) -Workspace {ws} -Token {token}\nThen describe this workspace in one sentence and 2-4 tags: orch relay profile --description \"...\" --tags a,b"
    )
}

// ---------- workspaces ----------

async fn list_ws(State(app): State<AppState>, h: HeaderMap) -> Res<Json<Value>> {
    guard(&app, &h)?;
    let c = app.db.lock().unwrap();
    let mut items: Vec<Value> = c
        .prepare(&format!(
            "SELECT {} FROM workspaces ORDER BY name",
            store::WS_CARD_COLS
        ))?
        .query_map([], store::ws_card)?
        .collect::<Result<_, _>>()?;
    for w in items.iter_mut() {
        let n: i64 = c.query_row(
            "SELECT COUNT(*) FROM messages WHERE to_addr=?1 AND acked_at IS NULL",
            [w["id"].as_str().unwrap()],
            |r| r.get(0),
        )?;
        w["unread"] = n.into();
        w["pending"] = store::pending(&c, w["id"].as_str().unwrap());
    }
    Ok(Json(json!({"items": items, "next": null})))
}

async fn add_ws(
    State(app): State<AppState>,
    h: HeaderMap,
    body: Bytes,
) -> Res<(StatusCode, Json<Value>)> {
    guard(&app, &h)?;
    let v = parse_body(&body)?;
    let name = v["name"].as_str().unwrap_or("").trim();
    if name.is_empty() || name.chars().count() > 80 {
        return Err(invalid("Give the workspace a name (up to 80 characters)."));
    }
    let tags = parse_tags(&v["tags"]).or_else(|_| {
        if v["tags"].is_null() {
            Ok(vec![])
        } else {
            Err(invalid("`tags` must be a list."))
        }
    })?;
    let desc = parse_description(&v["description"])?;
    let id = rand_id("ws_", 10);
    let token = rand_token("orn_", 32);
    app.db.lock().unwrap().execute(
        "INSERT INTO workspaces(id,name,description,tags,token_hash,created_at,description_by,tags_by) VALUES(?1,?2,?3,?4,?5,?6,'admin','admin')",
        params![id, name, desc, serde_json::to_string(&tags).unwrap(), token_hash(&token), now()],
    )?;
    let p = prompt(&app.cfg.public_url, &id, &token);
    Ok((
        StatusCode::CREATED,
        Json(json!({"id": id, "token": token, "prompt": p})),
    ))
}

async fn edit_ws(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
    body: Bytes,
) -> Res<StatusCode> {
    guard(&app, &h)?;
    let v = parse_body(&body)?;
    let c = app.db.lock().unwrap();
    if !store::ws_exists(&c, &id) {
        return Err(not_found("No such workspace."));
    }
    if let Some(n) = v.get("name") {
        let n = n.as_str().unwrap_or("").trim();
        if n.is_empty() {
            return Err(invalid("The name must not be empty."));
        }
        c.execute("UPDATE workspaces SET name=?2 WHERE id=?1", params![id, n])?;
    }
    if let Some(d) = v.get("description") {
        c.execute(
            "UPDATE workspaces SET description=?2, description_by='admin' WHERE id=?1",
            params![id, parse_description(d)?],
        )?;
    }
    if let Some(t) = v.get("tags") {
        let t = parse_tags(t)?;
        c.execute(
            "UPDATE workspaces SET tags=?2, tags_by='admin' WHERE id=?1",
            params![id, serde_json::to_string(&t).unwrap()],
        )?;
    }
    let rel = store::related(&c, &id);
    store::bump_and_hint(&c, &app.key, &rel)?;
    drop(c);
    app.notify.notify_waiters();
    Ok(StatusCode::OK)
}

/// The `rev` of the proposal the owner looked at; approve/reject only act on exactly that one.
fn proposal_rev(body: &Bytes) -> Res<String> {
    let v = parse_body(body)?;
    v["rev"]
        .as_str()
        .map(String::from)
        .ok_or_else(|| invalid("Send the `rev` of the change you reviewed."))
}

fn stale_or_none(c: &Connection, id: &str) -> ApiError {
    if store::pending(c, id).is_null() {
        not_found("There is no change to review.")
    } else {
        conflict("This change was replaced, review again.")
    }
}

/// Owner approves the workspace's proposed description/tags: they become live and everyone gets a refresh-hint.
async fn approve_profile(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
    body: Bytes,
) -> Res<Json<Value>> {
    guard(&app, &h)?;
    let rev = proposal_rev(&body)?;
    let c = app.db.lock().unwrap();
    let n = c.execute(
        "UPDATE workspaces SET
           description_by=CASE WHEN pending_description IS NULL THEN description_by ELSE 'workspace' END,
           tags_by=CASE WHEN pending_tags IS NULL THEN tags_by ELSE 'workspace' END,
           description=COALESCE(pending_description,description), tags=COALESCE(pending_tags,tags),
           pending_description=NULL, pending_tags=NULL, pending_at=NULL, pending_rev=NULL
         WHERE id=?1 AND pending_rev=?2",
        params![id, rev],
    )?;
    if n == 0 {
        return Err(stale_or_none(&c, &id));
    }
    let rel = store::related(&c, &id);
    store::bump_and_hint(&c, &app.key, &rel)?;
    let card = c.query_row(
        &format!("SELECT {} FROM workspaces WHERE id=?1", store::WS_CARD_COLS),
        [&id],
        store::ws_card,
    )?;
    drop(c);
    app.notify.notify_waiters();
    Ok(Json(card))
}

/// Owner rejects it: the old values stay, the proposal is dropped.
async fn reject_profile(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
    body: Bytes,
) -> Res<StatusCode> {
    guard(&app, &h)?;
    let rev = proposal_rev(&body)?;
    let c = app.db.lock().unwrap();
    let n = c.execute(
        "UPDATE workspaces SET pending_description=NULL, pending_tags=NULL, pending_at=NULL, pending_rev=NULL WHERE id=?1 AND pending_rev=?2",
        params![id, rev],
    )?;
    if n == 0 {
        return Err(stale_or_none(&c, &id));
    }
    Ok(StatusCode::NO_CONTENT)
}

async fn new_token(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
) -> Res<Json<Value>> {
    guard(&app, &h)?;
    let token = rand_token("orn_", 32);
    let n = app.db.lock().unwrap().execute(
        "UPDATE workspaces SET token_hash=?2, pending_description=NULL, pending_tags=NULL, pending_at=NULL, pending_rev=NULL WHERE id=?1",
        params![id, token_hash(&token)],
    )?;
    if n == 0 {
        return Err(not_found("No such workspace."));
    }
    let p = prompt(&app.cfg.public_url, &id, &token);
    Ok(Json(json!({"token": token, "prompt": p})))
}

async fn del_ws(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
) -> Res<StatusCode> {
    guard(&app, &h)?;
    let c = app.db.lock().unwrap();
    if !store::ws_exists(&c, &id) {
        return Err(not_found("No such workspace."));
    }
    let rel: Vec<String> = store::related(&c, &id)
        .into_iter()
        .filter(|w| w != &id)
        .collect();
    for sql in [
        "DELETE FROM workspaces WHERE id=?1",
        "DELETE FROM rules WHERE from_id=?1 OR to_id=?1",
        "DELETE FROM assign WHERE ws=?1",
        "DELETE FROM webhooks WHERE workspace=?1",
    ] {
        c.execute(sql, [&id])?;
    }
    let phones: Vec<(String, String)> = c
        .prepare("SELECT id,workspaces FROM phones")?
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .collect::<Result<_, _>>()?;
    for (pid, ws) in phones {
        let mut l = store::parse_list(&ws);
        if l.contains(&id) {
            l.retain(|w| w != &id);
            c.execute(
                "UPDATE phones SET workspaces=?2 WHERE id=?1",
                params![pid, serde_json::to_string(&l).unwrap()],
            )?;
        }
    }
    store::bump_and_hint(&c, &app.key, &rel)?;
    drop(c);
    app.notify.notify_waiters();
    Ok(StatusCode::NO_CONTENT)
}

// ---------- rules ----------

fn all_rules(c: &Connection) -> rusqlite::Result<BTreeMap<(String, String), [bool; 4]>> {
    let mut m = BTreeMap::new();
    for r in c
        .prepare("SELECT from_id,to_id,text,files,delegate,start FROM rules")?
        .query_map([], |r| {
            Ok((
                (r.get(0)?, r.get(1)?),
                [r.get(2)?, r.get(3)?, r.get(4)?, r.get(5)?],
            ))
        })?
    {
        let (k, v) = r?;
        m.insert(k, v);
    }
    Ok(m)
}

fn rules_json(m: &BTreeMap<(String, String), [bool; 4]>) -> Value {
    let v: Vec<Value> = m
        .iter()
        .map(|((f, t), x)| json!({"from": f, "to": t, "text": x[0], "files": x[1], "delegate": x[2], "start": x[3]}))
        .collect();
    json!({"rules": v})
}

async fn get_rules(State(app): State<AppState>, h: HeaderMap) -> Res<Json<Value>> {
    guard(&app, &h)?;
    let c = app.db.lock().unwrap();
    Ok(Json(rules_json(&all_rules(&c)?)))
}

async fn put_rules(State(app): State<AppState>, h: HeaderMap, body: Bytes) -> Res<Json<Value>> {
    guard(&app, &h)?;
    let v = parse_body(&body)?;
    let list = v["rules"]
        .as_array()
        .ok_or_else(|| invalid("`rules` must be a list."))?;
    let c = app.db.lock().unwrap();
    let mut new = BTreeMap::new();
    for r in list {
        let (f, t) = (
            r["from"].as_str().unwrap_or(""),
            r["to"].as_str().unwrap_or(""),
        );
        if !store::ws_exists(&c, f) || !store::ws_exists(&c, t) {
            return Err(invalid("Every rule needs two existing workspaces."));
        }
        let b = |k: &str| r[k].as_bool().unwrap_or(false);
        new.insert(
            (f.to_string(), t.to_string()),
            [b("text"), b("files"), b("delegate"), b("start")],
        );
    }
    let old = all_rules(&c)?;
    c.execute("DELETE FROM rules", [])?;
    for ((f, t), x) in &new {
        c.execute(
            "INSERT INTO rules(from_id,to_id,text,files,delegate,start) VALUES(?1,?2,?3,?4,?5,?6)",
            params![f, t, x[0], x[1], x[2], x[3]],
        )?;
    }
    let mut affected = vec![];
    for k in old.keys().chain(new.keys()) {
        if old.get(k) != new.get(k) {
            affected.push(k.0.clone());
            affected.push(k.1.clone());
        }
    }
    if !affected.is_empty() {
        store::bump_and_hint(&c, &app.key, &affected)?;
    }
    drop(c);
    app.notify.notify_waiters();
    Ok(Json(rules_json(&new)))
}

// ---------- messages, allows ----------

fn page_params(q: &HashMap<String, String>) -> (i64, i64) {
    (
        q.get("limit")
            .and_then(|l| l.parse().ok())
            .unwrap_or(50)
            .clamp(1, 100),
        q.get("after")
            .and_then(|c| decode_cursor(c))
            .unwrap_or(i64::MAX),
    )
}

fn query_msgs(
    c: &Connection,
    filter: &str,
    args: Vec<String>,
    limit: i64,
    after: i64,
) -> Res<(Vec<store::Msg>, Option<String>)> {
    let sql = format!(
        "SELECT {MSG_COLS} FROM messages WHERE seq<?1 {filter} ORDER BY seq DESC LIMIT {}",
        limit + 1
    );
    let mut all = vec![after.to_string()];
    all.extend(args);
    let mut rows: Vec<store::Msg> = c
        .prepare(&sql)?
        .query_map(
            params_from_iter(all.iter().enumerate().map(|(i, a)| {
                if i == 0 {
                    rusqlite::types::Value::Integer(after)
                } else {
                    rusqlite::types::Value::Text(a.clone())
                }
            })),
            msg_from_row,
        )?
        .collect::<Result<_, _>>()?;
    let next = if rows.len() as i64 > limit {
        rows.truncate(limit as usize);
        rows.last().map(|m| encode_cursor(m.seq))
    } else {
        None
    };
    Ok((rows, next))
}

async fn messages(
    State(app): State<AppState>,
    h: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Res<Json<Value>> {
    guard(&app, &h)?;
    let (limit, after) = page_params(&q);
    let (mut filter, mut args) = (String::new(), vec![]);
    if let Some(w) = q.get("workspace").filter(|w| !w.is_empty()) {
        filter += " AND (from_addr=?2 OR to_addr=?2)";
        args.push(w.clone());
    }
    if let Some(t) = q.get("type").filter(|t| !t.is_empty()) {
        filter += &format!(" AND type=?{}", args.len() + 2);
        args.push(t.clone());
    }
    let c = app.db.lock().unwrap();
    let (rows, next) = query_msgs(&c, &filter, args, limit, after)?;
    let items: Vec<Value> = rows
        .iter()
        .map(|m| {
            let mut j = msg_json(&app.key, m);
            j["acked"] = m.acked.into();
            j
        })
        .collect();
    Ok(Json(json!({"items": items, "next": next})))
}

async fn allows(
    State(app): State<AppState>,
    h: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Res<Json<Value>> {
    guard(&app, &h)?;
    let (limit, after) = page_params(&q);
    let c = app.db.lock().unwrap();
    let (rows, next) = query_msgs(&c, " AND type='allow'", vec![], limit, after)?;
    let items: Vec<Value> = rows
        .iter()
        .map(|m| {
            let (b, _) = store::open_payload(&app.key, m);
            json!({"from": m.from, "to": m.to, "kind": b["kind"], "key": b.get("key").cloned().unwrap_or(Value::Null),
                "mode": b["mode"], "created_at": m.created_at})
        })
        .collect();
    Ok(Json(json!({"items": items, "next": next})))
}

// ---------- shared config ----------

async fn get_shared(State(app): State<AppState>, h: HeaderMap) -> Res<Json<Value>> {
    guard(&app, &h)?;
    let c = app.db.lock().unwrap();
    let names = |sql: &str| -> rusqlite::Result<Vec<String>> {
        c.prepare(sql)?.query_map([], |r| r.get(0))?.collect()
    };
    let skills: Vec<Value> = c
        .prepare("SELECT name,version FROM skills ORDER BY name")?
        .query_map([], |r| {
            Ok(json!({"name": r.get::<_, String>(0)?, "version": r.get::<_, i64>(1)?}))
        })?
        .collect::<Result<_, _>>()?;
    let mut assign: BTreeMap<String, Value> = BTreeMap::new();
    for r in c
        .prepare("SELECT ws,kind,name FROM assign ORDER BY name")?
        .query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
            ))
        })?
    {
        let (ws, kind, name) = r?;
        let e = assign
            .entry(ws)
            .or_insert(json!({"skills": [], "mcp": [], "credentials": []}));
        e[&kind].as_array_mut().unwrap().push(name.into());
    }
    Ok(Json(
        json!({"version": store::version(&c), "skills": skills,
        "mcp": names("SELECT name FROM mcp ORDER BY name")?, "credentials": names("SELECT name FROM creds ORDER BY name")?,
        "assign": assign}),
    ))
}

async fn put_shared(
    State(app): State<AppState>,
    h: HeaderMap,
    Path((kind, name)): Path<(String, String)>,
    body: Bytes,
) -> Res<Json<Value>> {
    guard(&app, &h)?;
    if !shared::KINDS.contains(&kind.as_str()) || !shared::valid_name(&kind, &name) {
        return Err(invalid("Unknown kind or bad name."));
    }
    let (value, ret_version) = match kind.as_str() {
        "skills" => (shared::unpack_skill(&body)?, true),
        "mcp" => {
            let v = parse_body(&body)?;
            if !v["config"].is_object() {
                return Err(invalid("`config` must be an object."));
            }
            (v["config"].clone(), false)
        }
        _ => {
            let v = parse_body(&body)?;
            let val = v["value"]
                .as_str()
                .ok_or_else(|| invalid("`value` must be text."))?;
            (Value::String(val.to_string()), false)
        }
    };
    let c = app.db.lock().unwrap();
    let ver = shared::put_item(&c, &app.key, &kind, &name, &value)?;
    let affected = shared::assigned_ws(&c, &kind, &name);
    store::bump_and_hint(&c, &app.key, &affected)?;
    drop(c);
    app.notify.notify_waiters();
    Ok(Json(if ret_version {
        json!({"name": name, "version": ver})
    } else {
        Value::Null
    }))
}

async fn del_shared(
    State(app): State<AppState>,
    h: HeaderMap,
    Path((kind, name)): Path<(String, String)>,
) -> Res<StatusCode> {
    guard(&app, &h)?;
    if !shared::KINDS.contains(&kind.as_str()) {
        return Err(invalid("Unknown kind."));
    }
    let c = app.db.lock().unwrap();
    let affected = shared::assigned_ws(&c, &kind, &name);
    let n = c.execute(
        &format!("DELETE FROM {} WHERE name=?1", shared::table(&kind)),
        [&name],
    )?;
    if n == 0 {
        return Err(not_found("No such item."));
    }
    c.execute(
        "DELETE FROM assign WHERE kind=?1 AND name=?2",
        params![kind, name],
    )?;
    store::bump_and_hint(&c, &app.key, &affected)?;
    drop(c);
    app.notify.notify_waiters();
    Ok(StatusCode::NO_CONTENT)
}

async fn assign(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(ws): Path<String>,
    body: Bytes,
) -> Res<StatusCode> {
    guard(&app, &h)?;
    let v = parse_body(&body)?;
    let c = app.db.lock().unwrap();
    if !store::ws_exists(&c, &ws) {
        return Err(not_found("No such workspace."));
    }
    let mut want = vec![];
    for kind in shared::KINDS {
        for n in v[kind].as_array().cloned().unwrap_or_default() {
            let n = n.as_str().unwrap_or("").to_string();
            let exists: bool = c.query_row(
                &format!(
                    "SELECT EXISTS(SELECT 1 FROM {} WHERE name=?1)",
                    shared::table(kind)
                ),
                [&n],
                |r| r.get(0),
            )?;
            if !exists {
                return Err(invalid(format!("{n} does not exist.")));
            }
            want.push((kind, n));
        }
    }
    c.execute("DELETE FROM assign WHERE ws=?1", [&ws])?;
    for (k, n) in want {
        c.execute(
            "INSERT OR IGNORE INTO assign(ws,kind,name) VALUES(?1,?2,?3)",
            params![ws, k, n],
        )?;
    }
    store::bump_and_hint(&c, &app.key, &[ws])?;
    drop(c);
    app.notify.notify_waiters();
    Ok(StatusCode::OK)
}

// ---------- webhooks ----------

async fn get_voice(State(app): State<AppState>, h: HeaderMap) -> Res<Json<Value>> {
    guard(&app, &h)?;
    let c = app.db.lock().unwrap();
    Ok(Json(
        json!({"deepgram": crate::transcribe::status(&c, &app.key)}),
    ))
}

async fn put_voice(State(app): State<AppState>, h: HeaderMap, body: Bytes) -> Res<Json<Value>> {
    guard(&app, &h)?;
    let v = parse_body(&body)?;
    let k = v["deepgram_key"].as_str().unwrap_or("").trim();
    if k.len() < 8 || k.len() > 200 || !k.chars().all(|c| c.is_ascii_graphic()) {
        return Err(invalid("`deepgram_key` must be the Deepgram API key."));
    }
    let c = app.db.lock().unwrap();
    crate::transcribe::set_key(&c, &app.key, k)?;
    Ok(Json(
        json!({"deepgram": crate::transcribe::status(&c, &app.key)}),
    ))
}

async fn del_voice(State(app): State<AppState>, h: HeaderMap) -> Res<StatusCode> {
    guard(&app, &h)?;
    let c = app.db.lock().unwrap();
    crate::transcribe::remove_key(&c)?;
    Ok(StatusCode::NO_CONTENT)
}

async fn webhooks(State(app): State<AppState>, h: HeaderMap) -> Res<Json<Value>> {
    guard(&app, &h)?;
    let c = app.db.lock().unwrap();
    let items: Vec<Value> = c
        .prepare(&format!(
            "SELECT {} FROM webhooks ORDER BY created_at DESC, id",
            crate::webhooks::COLS
        ))?
        .query_map([], |r| crate::webhooks::row_json(r, true))?
        .collect::<Result<_, _>>()?;
    Ok(Json(json!({"items": items, "next": null})))
}

async fn del_webhook(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
) -> Res<StatusCode> {
    guard(&app, &h)?;
    let n = app
        .db
        .lock()
        .unwrap()
        .execute("DELETE FROM webhooks WHERE id=?1", [id])?;
    if n == 0 {
        return Err(not_found("No such webhook."));
    }
    Ok(StatusCode::NO_CONTENT)
}

// ---------- phones ----------

fn check_ws_list(c: &Connection, v: &Value) -> Res<Vec<String>> {
    let a = v
        .as_array()
        .ok_or_else(|| invalid("`workspaces` must be a list."))?;
    let mut out = vec![];
    for w in a {
        let w = w.as_str().unwrap_or("");
        if !store::ws_exists(c, w) {
            return Err(invalid(format!("{w} is not a workspace.")));
        }
        out.push(w.to_string());
    }
    Ok(out)
}

async fn list_phones(State(app): State<AppState>, h: HeaderMap) -> Res<Json<Value>> {
    guard(&app, &h)?;
    let c = app.db.lock().unwrap();
    let items: Vec<Value> = c
        .prepare("SELECT id,name,workspaces,token_hash IS NOT NULL,last_seen FROM phones ORDER BY created_at, id")?
        .query_map([], |r| {
            let last: Option<i64> = r.get(4)?;
            Ok(json!({"id": r.get::<_, String>(0)?, "name": r.get::<_, String>(1)?,
                "workspaces": store::parse_list(&r.get::<_, String>(2)?), "paired": r.get::<_, bool>(3)?,
                "online": store::online(last)}))
        })?
        .collect::<Result<_, _>>()?;
    Ok(Json(json!({"items": items, "next": null})))
}

async fn add_phone(
    State(app): State<AppState>,
    h: HeaderMap,
    body: Bytes,
) -> Res<(StatusCode, Json<Value>)> {
    guard(&app, &h)?;
    let v = parse_body(&body)?;
    let name = v["name"].as_str().unwrap_or("").trim();
    if name.is_empty() {
        return Err(invalid("Give the phone a name."));
    }
    let c = app.db.lock().unwrap();
    let ws = check_ws_list(&c, &v["workspaces"])?;
    let pid = rand_id("ph_", 10);
    let code = rand_token("pc_", 16);
    c.execute(
        "INSERT INTO phones(id,name,workspaces,created_at) VALUES(?1,?2,?3,?4)",
        params![pid, name, serde_json::to_string(&ws).unwrap(), now()],
    )?;
    c.execute(
        "INSERT INTO pair_codes(hash,phone_id,expires_at) VALUES(?1,?2,?3)",
        params![token_hash(&code), pid, now() + 24 * 3600],
    )?;
    let enc = percent_encoding::utf8_percent_encode(
        &app.cfg.public_url,
        percent_encoding::NON_ALPHANUMERIC,
    );
    let link = format!("orch://pair?relay={enc}&code={code}");
    let qr = qrcode::QrCode::new(link.as_bytes())
        .map_err(internal)?
        .render::<qrcode::render::svg::Color>()
        .min_dimensions(200, 200)
        .build();
    Ok((
        StatusCode::CREATED,
        Json(json!({"phone_id": pid, "link": link, "qr_svg": qr})),
    ))
}

async fn edit_phone(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
    body: Bytes,
) -> Res<StatusCode> {
    guard(&app, &h)?;
    let v = parse_body(&body)?;
    let c = app.db.lock().unwrap();
    let ws = check_ws_list(&c, &v["workspaces"])?;
    let old = store::phone_workspaces(&c, &id);
    let n = c.execute(
        "UPDATE phones SET workspaces=?2 WHERE id=?1",
        params![id, serde_json::to_string(&ws).unwrap()],
    )?;
    if n == 0 {
        return Err(not_found("No such phone."));
    }
    // Workspaces that gained or lost the phone refresh their phone list.
    let changed: Vec<String> = old
        .iter()
        .filter(|w| !ws.contains(w))
        .chain(ws.iter().filter(|w| !old.contains(w)))
        .cloned()
        .collect();
    if !changed.is_empty() {
        store::bump_and_hint(&c, &app.key, &changed)?;
    }
    Ok(StatusCode::OK)
}

async fn del_phone(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
) -> Res<StatusCode> {
    guard(&app, &h)?;
    let c = app.db.lock().unwrap();
    let old = store::phone_workspaces(&c, &id);
    let n = c.execute("DELETE FROM phones WHERE id=?1", [&id])?;
    c.execute("DELETE FROM pair_codes WHERE phone_id=?1", [&id])?;
    if n == 0 {
        return Err(not_found("No such phone."));
    }
    store::bump_and_hint(&c, &app.key, &old)?;
    Ok(StatusCode::NO_CONTENT)
}
