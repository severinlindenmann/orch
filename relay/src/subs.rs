//! Subscribers (relay-api.md "Subscribers"): other systems that read what a phone would see from the workspaces in
//! their scope, by pull (`/v1/sub/<token>/events`, a Server-Sent Events stream) or push (subs_push.rs). New tables
//! only: the events are a read view over the stored `messages`, like `/v1/phone/updates`.
use crate::api::parse_body;
use crate::error::*;
use crate::state::AppState;
use crate::store::{self, msg_from_row, Msg, MSG_COLS};
use crate::subs_push::{self, Deliver};
use crate::util::*;
use crate::{auth, crypto, groups};
use axum::body::Bytes;
use axum::extract::{Path, Query, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::sse::{Event, KeepAlive, Sse};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};
use std::convert::Infallible;
use std::sync::{Arc, Mutex, RwLock};
use std::time::Duration;

/// What a subscriber may receive, in this order.
pub const KINDS: [&str; 4] = ["updates", "questions", "results", "files"];
/// Calls a minute per subscriber (every route, opening a stream included).
pub const RATE_PER_MIN: u32 = 60;
/// Open streams per subscriber.
pub const MAX_STREAMS: u32 = 2;
/// Log entries kept per subscriber, and for how long.
const LOG_KEEP: i64 = 200;
const LOG_SECS: i64 = 30 * 24 * 3600;
/// Most stored messages looked at for one page of events.
const MAX_SCAN: usize = 2000;
const MAX_ANSWER: usize = 2000;

pub fn init(c: &Connection) -> rusqlite::Result<()> {
    c.execute_batch(
        "CREATE TABLE IF NOT EXISTS subscribers(id TEXT PRIMARY KEY, name TEXT NOT NULL, workspaces TEXT NOT NULL,
            groups TEXT NOT NULL, kinds TEXT NOT NULL, can_answer INTEGER NOT NULL, can_download INTEGER NOT NULL,
            token_hash TEXT NOT NULL, created_at INTEGER NOT NULL, last_seen INTEGER,
            push_url TEXT, push_secret BLOB, push_state TEXT, push_cursor INTEGER, push_fails INTEGER NOT NULL DEFAULT 0,
            push_next_at INTEGER, push_last_ok INTEGER);
        CREATE UNIQUE INDEX IF NOT EXISTS subscribers_token ON subscribers(token_hash);
        CREATE TABLE IF NOT EXISTS sub_log(n INTEGER PRIMARY KEY AUTOINCREMENT, sub TEXT NOT NULL, at INTEGER NOT NULL,
            what TEXT NOT NULL, event TEXT, result TEXT NOT NULL, ok INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS sub_log_sub ON sub_log(sub, n);",
    )
}

/// Drop log entries older than 30 days.
pub fn purge(c: &Connection, at: i64) -> rusqlite::Result<usize> {
    c.execute("DELETE FROM sub_log WHERE at<?1", [at - LOG_SECS])
}

// ---------- in-memory state: open streams, rate limits, push rounds ----------

pub struct Live {
    streams: Mutex<HashMap<String, u32>>,
    rate: Mutex<HashMap<String, (i64, u32)>>,
    pub(crate) pushing: Mutex<HashSet<String>>,
    deliver: RwLock<Arc<dyn Deliver>>,
}

impl Default for Live {
    fn default() -> Self {
        Live {
            streams: Mutex::default(),
            rate: Mutex::default(),
            pushing: Mutex::default(),
            deliver: RwLock::new(Arc::new(subs_push::Https)),
        }
    }
}

impl Live {
    /// Replace the push transport (tests use a fake receiver; the real one checks addresses on every request).
    pub fn set_deliver(&self, d: Arc<dyn Deliver>) {
        *self.deliver.write().unwrap() = d;
    }
    pub fn deliver(&self) -> Arc<dyn Deliver> {
        self.deliver.read().unwrap().clone()
    }
    pub fn streams_of(&self, id: &str) -> u32 {
        *self.streams.lock().unwrap().get(id).unwrap_or(&0)
    }
    /// One call in the current minute window; false when the subscriber used up its 60.
    fn allow(&self, id: &str, now: i64) -> bool {
        let mut m = self.rate.lock().unwrap();
        let e = m.entry(id.to_string()).or_insert((now, 0));
        if now - e.0 >= 60 {
            *e = (now, 0);
        }
        if e.1 >= RATE_PER_MIN {
            return false;
        }
        e.1 += 1;
        true
    }
}

/// An open stream; dropping it frees the slot.
struct StreamSlot {
    app: AppState,
    id: String,
}

impl Drop for StreamSlot {
    fn drop(&mut self) {
        let mut m = self.app.subs.streams.lock().unwrap();
        if let Some(n) = m.get_mut(&self.id) {
            *n = n.saturating_sub(1);
            if *n == 0 {
                m.remove(&self.id);
            }
        }
    }
}

fn too_many_streams() -> ApiError {
    ApiError {
        status: StatusCode::TOO_MANY_REQUESTS,
        code: "too_many_streams",
        message: format!(
            "This subscriber already has {MAX_STREAMS} open live streams. Close one first."
        ),
    }
}

fn sub_rate_limited() -> ApiError {
    ApiError {
        status: StatusCode::TOO_MANY_REQUESTS,
        code: "rate_limited",
        message: format!("Too many calls. A subscriber may call {RATE_PER_MIN} times a minute."),
    }
}

// ---------- the subscriber row ----------

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Kinds {
    pub updates: bool,
    pub questions: bool,
    pub results: bool,
    pub files: bool,
}

impl Kinds {
    fn json(&self) -> Value {
        json!({"updates": self.updates, "questions": self.questions, "results": self.results, "files": self.files})
    }
    fn parse(s: &str) -> Kinds {
        let v: Value = serde_json::from_str(s).unwrap_or(Value::Null);
        let b = |k: &str| v[k].as_bool().unwrap_or(false);
        Kinds {
            updates: b("updates"),
            questions: b("questions"),
            results: b("results"),
            files: b("files"),
        }
    }
}

pub struct Sub {
    pub id: String,
    pub name: String,
    pub workspaces: Vec<String>,
    pub groups: Vec<String>,
    pub kinds: Kinds,
    pub can_answer: bool,
    pub can_download: bool,
    pub created_at: i64,
    pub token_hash: String,
}

const SUB_COLS: &str =
    "id,name,workspaces,groups,kinds,can_answer,can_download,created_at,token_hash";

fn sub_from_row(r: &rusqlite::Row) -> rusqlite::Result<Sub> {
    Ok(Sub {
        id: r.get(0)?,
        name: r.get(1)?,
        workspaces: store::parse_ws_list(&r.get::<_, String>(2)?),
        groups: store::parse_ws_list(&r.get::<_, String>(3)?),
        kinds: Kinds::parse(&r.get::<_, String>(4)?),
        can_answer: r.get(5)?,
        can_download: r.get(6)?,
        created_at: r.get(7)?,
        token_hash: r.get(8)?,
    })
}

pub fn load(c: &Connection, id: &str) -> rusqlite::Result<Option<Sub>> {
    c.query_row(
        &format!("SELECT {SUB_COLS} FROM subscribers WHERE id=?1"),
        [id],
        sub_from_row,
    )
    .optional()
}

/// The workspaces a subscriber sees now: its own list plus the current members of its groups (existing ones only).
pub fn scope(c: &Connection, s: &Sub) -> Vec<String> {
    let mut out: Vec<String> = s
        .workspaces
        .iter()
        .filter(|w| store::ws_exists(c, w))
        .cloned()
        .collect();
    for g in &s.groups {
        for w in groups::members(c, g).unwrap_or_default() {
            if !out.contains(&w) {
                out.push(w);
            }
        }
    }
    out
}

/// Append to the subscriber's activity log and keep only the newest entries.
pub fn log(c: &Connection, sub: &str, what: &str, event: Option<&str>, result: &str, ok: bool) {
    let _ = c.execute(
        "INSERT INTO sub_log(sub,at,what,event,result,ok) VALUES(?1,?2,?3,?4,?5,?6)",
        params![sub, now(), what, event, result, ok],
    );
    let _ = c.execute(
        "DELETE FROM sub_log WHERE sub=?1 AND n<=(SELECT n FROM sub_log WHERE sub=?1 ORDER BY n DESC LIMIT 1 OFFSET ?2)",
        params![sub, LOG_KEEP],
    );
}

/// The subscriber behind a public call: the token from the path, or with `-` from `Authorization: Bearer`.
/// Marks it seen and counts the call against its rate limit.
fn authed(app: &AppState, c: &Connection, h: &HeaderMap, path_token: &str) -> Res<Sub> {
    let tok = if path_token == "-" {
        auth::bearer(h).unwrap_or("")
    } else {
        path_token
    };
    if !tok.starts_with("sub_") {
        return Err(unauthorized());
    }
    let s = c
        .query_row(
            &format!("SELECT {SUB_COLS} FROM subscribers WHERE token_hash=?1"),
            [token_hash(tok)],
            sub_from_row,
        )
        .optional()?
        .ok_or_else(unauthorized)?;
    if !app.subs.allow(&s.id, now()) {
        return Err(sub_rate_limited());
    }
    c.execute(
        "UPDATE subscribers SET last_seen=?2 WHERE id=?1",
        params![s.id, now()],
    )?;
    Ok(s)
}

// ---------- the event view ----------

/// Candidate messages for a subscriber, oldest first: ?1 JSON scope list, ?2 seq cursor, ?3 created-at, ?4 batch.
/// Texts and questions workspaces in scope sent to `phones`, and the answers to those questions.
const EVENTS_SQL: &str = "SELECT seq,id,from_addr,to_addr,type,created_at,ticket,reply_to,payload,acked_at FROM (
        SELECT m.* FROM json_each(?1) j CROSS JOIN messages m
          WHERE m.type='text' AND m.to_addr='phones' AND m.from_addr=j.value AND m.seq>?2 AND m.stored_at>=?3
        UNION ALL
        SELECT m.* FROM json_each(?1) j CROSS JOIN messages m
          WHERE m.type='question' AND m.to_addr='phones' AND m.from_addr=j.value AND m.seq>?2 AND m.stored_at>=?3
        UNION ALL
        SELECT m.* FROM json_each(?1) j CROSS JOIN messages m
          WHERE m.type='answer' AND m.to_addr=j.value AND m.seq>?2 AND m.stored_at>=?3
            AND EXISTS(SELECT 1 FROM messages q WHERE q.id=m.reply_to AND q.type='question' AND q.to_addr='phones'
                       AND q.from_addr=j.value AND q.stored_at>=?3)
     ) ORDER BY seq LIMIT ?4";

pub struct Page {
    /// (seq, event)
    pub items: Vec<(i64, Value)>,
    /// The seq of the last stored message looked at (the cursor for the next read).
    pub last_seq: i64,
    /// The id of that message (`next` for the client).
    pub last_id: Option<String>,
    /// True when the page is full or the scan limit was hit: there may be more now.
    pub more: bool,
}

/// One page of events after `after` (a seq), at most `limit`.
pub fn read_events(
    c: &Connection,
    key: &crypto::Key,
    s: &Sub,
    after: i64,
    limit: usize,
) -> rusqlite::Result<Page> {
    let mut page = Page {
        items: vec![],
        last_seq: after,
        last_id: None,
        more: false,
    };
    let sc = scope(c, s);
    if sc.is_empty() {
        return Ok(page);
    }
    let list = serde_json::to_string(&sc).unwrap_or("[]".into());
    let mut st = c.prepare(EVENTS_SQL)?;
    let mut scanned = 0usize;
    loop {
        let rows: Vec<Msg> = st
            .query_map(
                params![list, page.last_seq, s.created_at, 200i64],
                msg_from_row,
            )?
            .collect::<Result<_, _>>()?;
        if rows.is_empty() {
            return Ok(page);
        }
        for m in rows {
            scanned += 1;
            page.last_seq = m.seq;
            page.last_id = Some(m.id.clone());
            if let Some(e) = event_of(c, key, &m, s)? {
                page.items.push((m.seq, e));
                if page.items.len() >= limit {
                    page.more = true;
                    return Ok(page);
                }
            }
            if scanned >= MAX_SCAN {
                page.more = true;
                return Ok(page);
            }
        }
    }
}

fn ws_json(c: &Connection, id: &str) -> Value {
    json!({"id": id, "name": store::ws_name(c, id).unwrap_or_default()})
}

/// "human:Anna's iPhone" / "agent:Bot (system)" -> the display name.
fn display_by(v: &Value) -> String {
    let s = v.as_str().unwrap_or("");
    s.strip_prefix("human:")
        .or_else(|| s.strip_prefix("agent:"))
        .unwrap_or(s)
        .to_string()
}

/// The subscriber's copy of a `body.ticket_view`: no checklist, no history; files only when Files is on.
fn view_subset(tv: &Value, files: bool) -> Value {
    if !tv.is_object() {
        return Value::Null;
    }
    let att = tv["attachments"].as_array().cloned().unwrap_or_default();
    let links: Vec<Value> = att
        .iter()
        .filter(|a| a["url"].is_string())
        .map(|a| json!({"kind": a["kind"], "title": a["title"], "url": a["url"]}))
        .collect();
    let file_list: Vec<Value> = if files {
        att.iter()
            .filter(|a| a["blob_id"].is_string())
            .map(|a| json!({"name": a["name"], "size": a["size"], "blob_id": a["blob_id"]}))
            .collect()
    } else {
        vec![]
    };
    json!({"title": tv["title"], "status": tv["status"], "agent": tv.get("agent").cloned().unwrap_or(Value::Null),
        "summary": tv.get("summary").cloned().unwrap_or(Value::Null), "done": tv["done"], "total": tv["total"],
        "links": links, "files": file_list})
}

fn first_answer(c: &Connection, qid: &str) -> rusqlite::Result<Option<Msg>> {
    c.query_row(
        &format!("SELECT {MSG_COLS} FROM messages WHERE reply_to=?1 AND type='answer' ORDER BY seq LIMIT 1"),
        [qid],
        msg_from_row,
    )
    .optional()
}

/// The event a stored message makes for this subscriber, or `None` when its kinds leave it out.
fn event_of(
    c: &Connection,
    key: &crypto::Key,
    m: &Msg,
    s: &Sub,
) -> rusqlite::Result<Option<Value>> {
    let (body, extra) = store::open_payload(key, m);
    let tkey = extra
        .get("key")
        .and_then(crate::rules::ticket_key)
        .map(Value::from)
        .unwrap_or(Value::Null);
    let base = |typ: &str, ws: &str| json!({"v": 1, "id": m.id, "type": typ, "workspace": ws_json(c, ws), "ticket": m.ticket, "key": tkey, "at": m.created_at});
    let k = s.kinds;
    Ok(match m.typ.as_str() {
        "text" => {
            let u = &body["update"];
            if u.is_object() {
                let raw = u["kind"].as_str().unwrap_or("note");
                let on = match raw {
                    "ack" | "working" | "note" => k.updates,
                    "result" | "failure" | "stopped" => k.results,
                    "question" => k.questions,
                    _ => k.updates,
                };
                if !on {
                    return Ok(None);
                }
                let mut e = base("update", &m.from);
                e["kind"] = (if raw == "ack" { "started" } else { raw }).into();
                e["title"] = u.get("title").cloned().unwrap_or(Value::Null);
                e["text"] = body["text"].as_str().unwrap_or("").into();
                e["ticket_view"] = view_subset(&body["ticket_view"], k.files);
                Some(e)
            } else {
                let mut e = base("text", &m.from);
                e["text"] = body["text"].as_str().unwrap_or("").into();
                Some(e)
            }
        }
        "question" if k.questions => {
            let ans = first_answer(c, &m.id)?;
            let answered = ans.as_ref().map(|a| {
                let (b, _) = store::open_payload(key, a);
                json!({"answer": b["answer"].as_str().unwrap_or(""), "answered_by": display_by(&b["answered_by"])})
            });
            let mut e = base("question", &m.from);
            e["question_id"] = m.id.clone().into();
            e["text"] = body["text"].as_str().unwrap_or("").into();
            e["title"] = body.get("title").cloned().unwrap_or(Value::Null);
            e["options"] = body["options"]
                .as_array()
                .cloned()
                .unwrap_or_default()
                .into();
            e["answerable"] = (s.can_answer && answered.is_none()).into();
            e["answered"] = answered.unwrap_or(Value::Null);
            Some(e)
        }
        "answer" if k.questions => {
            let mut e = base("answered", &m.to);
            e["question_id"] = m.reply_to.clone().into();
            e["answer"] = body["answer"].as_str().unwrap_or("").into();
            e["answered_by"] = display_by(&body["answered_by"]).into();
            Some(e)
        }
        _ => None,
    })
}

/// A short label for the log: "DM1-12 result", "Month-end close question".
pub fn event_label(e: &Value) -> String {
    let who = e["key"]
        .as_str()
        .map(String::from)
        .or_else(|| e["workspace"]["name"].as_str().map(String::from))
        .unwrap_or_default();
    let what = e["kind"].as_str().or(e["type"].as_str()).unwrap_or("");
    format!("{who} {what}").trim().to_string()
}

/// The seq of a stored message (an event id used as a cursor).
fn seq_of(c: &Connection, id: &str) -> Res<i64> {
    c.query_row("SELECT seq FROM messages WHERE id=?1", [id], |r| r.get(0))
        .optional()?
        .ok_or_else(|| invalid("`after` is not a known event."))
}

// ---------- public routes ----------

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/v1/sub/:token/events", get(events))
        .route("/v1/sub/:token/stream", get(stream))
        .route("/v1/sub/:token/files/:blob", get(file))
        .route("/v1/sub/:token/answer", post(answer))
}

async fn events(
    State(app): State<AppState>,
    Path(tok): Path<String>,
    h: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Res<Json<Value>> {
    let limit = q
        .get("limit")
        .and_then(|l| l.parse::<usize>().ok())
        .unwrap_or(100)
        .clamp(1, 100);
    let c = app.db.lock().unwrap();
    let s = authed(&app, &c, &h, &tok)?;
    let after = match q.get("after").filter(|a| !a.is_empty()) {
        Some(a) => seq_of(&c, a)?,
        None => 0,
    };
    let page = read_events(&c, &app.key, &s, after, limit)?;
    let n = page.items.len();
    log(
        &c,
        &s.id,
        "events",
        None,
        &format!("{n} event{}", if n == 1 { "" } else { "s" }),
        true,
    );
    let next = if page.more { page.last_id } else { None };
    let items: Vec<Value> = page.items.into_iter().map(|(_, e)| e).collect();
    Ok(Json(json!({"items": items, "next": next})))
}

async fn stream(
    State(app): State<AppState>,
    Path(tok): Path<String>,
    h: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Res<Response> {
    let resume = h
        .get("last-event-id")
        .and_then(|v| v.to_str().ok())
        .map(String::from)
        .or_else(|| q.get("after").cloned())
        .filter(|a| !a.is_empty());
    let (s, start) = {
        let c = app.db.lock().unwrap();
        let s = authed(&app, &c, &h, &tok)?;
        let start = match resume {
            Some(a) => seq_of(&c, &a)?,
            None => c.query_row("SELECT COALESCE(MAX(seq),0) FROM messages", [], |r| {
                r.get(0)
            })?,
        };
        (s, start)
    };
    {
        let mut m = app.subs.streams.lock().unwrap();
        let n = m.entry(s.id.clone()).or_insert(0);
        if *n >= MAX_STREAMS {
            return Err(too_many_streams());
        }
        *n += 1;
    }
    let slot = StreamSlot {
        app: app.clone(),
        id: s.id.clone(),
    };
    {
        let c = app.db.lock().unwrap();
        log(&c, &s.id, "stream", None, "opened", true);
    }
    let (tx, rx) = tokio::sync::mpsc::channel::<Event>(32);
    let task_app = app.clone();
    tokio::spawn(async move {
        let _slot = slot;
        let app = task_app;
        let mut cursor = start;
        loop {
            let notified = app.notify.notified();
            tokio::pin!(notified);
            notified.as_mut().enable();
            let page = {
                let c = app.db.lock().unwrap();
                // Rotated or removed: the stream ends at once. Scope and kinds are read fresh every time.
                let cur = match load(&c, &s.id) {
                    Ok(Some(cur)) if cur.token_hash == s.token_hash => cur,
                    _ => break,
                };
                match read_events(&c, &app.key, &cur, cursor, 100) {
                    Ok(p) => p,
                    Err(e) => {
                        tracing::warn!("subscriber stream: {e}");
                        break;
                    }
                }
            };
            cursor = page.last_seq;
            for (_, e) in page.items {
                let ev = Event::default()
                    .id(e["id"].as_str().unwrap_or(""))
                    .event(e["type"].as_str().unwrap_or("text"))
                    .data(e.to_string());
                if tx.send(ev).await.is_err() {
                    return;
                }
            }
            if page.more {
                continue;
            }
            tokio::select! {
                _ = &mut notified => {}
                _ = tokio::time::sleep(Duration::from_secs(30)) => {}
                _ = tx.closed() => return,
            }
        }
    });
    let body = futures_util::stream::unfold(rx, |mut rx| async move {
        rx.recv().await.map(|e| (Ok::<_, Infallible>(e), rx))
    });
    Ok(Sse::new(body)
        .keep_alive(
            KeepAlive::new()
                .interval(Duration::from_secs(25))
                .text("ping"),
        )
        .into_response())
}

async fn file(
    State(app): State<AppState>,
    Path((tok, id)): Path<(String, String)>,
    h: HeaderMap,
) -> Res<Response> {
    let none = || not_found("No such file.");
    {
        let c = app.db.lock().unwrap();
        let s = authed(&app, &c, &h, &tok)?;
        if !valid_id(&id, "b_", 16) || !s.kinds.files || !s.can_download {
            return Err(none());
        }
        let sc = serde_json::to_string(&scope(&c, &s)).unwrap_or("[]".into());
        let ok: bool = c.query_row(
            "SELECT EXISTS(SELECT 1 FROM view_blobs v JOIN messages m ON m.id=v.msg_id JOIN blobs b ON b.id=v.blob_id
               WHERE v.blob_id=?1 AND m.type='text' AND m.to_addr='phones' AND b.uploader=m.from_addr
                 AND m.from_addr IN (SELECT value FROM json_each(?2)) AND m.stored_at>=?3)",
            params![id, sc, s.created_at],
            |r| r.get(0),
        )?;
        if !ok {
            return Err(none());
        }
        log(&c, &s.id, "file", None, &id, true);
    }
    let raw = tokio::fs::read(app.blob_path(&id))
        .await
        .map_err(|_| none())?;
    let plain =
        crypto::open(&app.key, &id, &raw).ok_or_else(|| internal("blob does not decrypt"))?;
    Ok((
        [(axum::http::header::CONTENT_TYPE, "application/octet-stream")],
        plain,
    )
        .into_response())
}

async fn answer(
    State(app): State<AppState>,
    Path(tok): Path<String>,
    h: HeaderMap,
    body: Bytes,
) -> Res<(StatusCode, Json<Value>)> {
    let id = {
        let c = app.db.lock().unwrap();
        let s = authed(&app, &c, &h, &tok)?;
        // Answering needs Questions on too: a subscriber that does not see questions cannot answer them.
        if !s.can_answer || !s.kinds.questions {
            return Err(not_allowed(
                "This subscriber may only read. In the relay admin, open Subscribers and turn on Can answer questions.",
            ));
        }
        let v = parse_body(&body)?;
        let qid = v["question_id"].as_str().unwrap_or("");
        let text = v["answer"].as_str().unwrap_or("");
        if text.trim().is_empty() || text.chars().count() > MAX_ANSWER {
            return Err(invalid(format!(
                "`answer` must be 1 to {MAX_ANSWER} characters."
            )));
        }
        let sc = scope(&c, &s);
        let q = store::get_msg(&c, qid)?
            .filter(|q| q.typ == "question" && q.to == "phones" && sc.contains(&q.from))
            .ok_or_else(|| not_found("No such question."))?;
        let stored_at: i64 =
            c.query_row("SELECT stored_at FROM messages WHERE id=?1", [qid], |r| {
                r.get(0)
            })?;
        if stored_at < s.created_at {
            return Err(not_found("No such question."));
        }
        // The database lock makes check + insert one step: the first answer wins (phones use the same rule).
        if let Some(p) = first_answer(&c, qid)? {
            let (b, _) = store::open_payload(&app.key, &p);
            return Err(already_answered(format!(
                "This question was already answered: {}.",
                b["answer"].as_str().unwrap_or("")
            )));
        }
        let (qb, qextra) = store::open_payload(&app.key, &q);
        let m = store::system_message_with_key(
            qextra.get("key").and_then(crate::rules::ticket_key),
            &c,
            &app.key,
            &s.id,
            &q.from,
            "answer",
            q.ticket.as_deref(),
            Some(qid),
            json!({"question_id": qb["question_id"], "answer": text, "answered_by": format!("agent:{} (system)", s.name)}),
        )?;
        let label = qextra
            .get("key")
            .and_then(crate::rules::ticket_key)
            .map(|k| format!("{k} question"));
        log(&c, &s.id, "answer", label.as_deref(), "answered", true);
        m["id"].as_str().unwrap_or("").to_string()
    };
    app.notify.notify_waiters();
    Ok((StatusCode::CREATED, Json(json!({"id": id}))))
}

// ---------- admin routes ----------

pub fn admin_router() -> Router<AppState> {
    Router::new()
        .route("/admin/api/subscribers", get(list).post(create))
        .route(
            "/admin/api/subscribers/:id",
            axum::routing::patch(edit).delete(remove),
        )
        .route("/admin/api/subscribers/:id/token", post(rotate))
        .route("/admin/api/subscribers/:id/push/retry", post(retry))
        .route("/admin/api/subscribers/:id/push/test", post(test))
        .route("/admin/api/subscribers/:id/log", get(get_log))
}

/// The admin's view of one subscriber (relay-api.md).
fn card(app: &AppState, c: &Connection, id: &str) -> Res<Value> {
    let row = c
        .query_row(
            "SELECT id,name,workspaces,groups,kinds,can_answer,can_download,created_at,last_seen,push_url,push_state,
                push_fails,push_next_at,push_last_ok FROM subscribers WHERE id=?1",
            [id],
            |r| {
                let push_url: Option<String> = r.get(9)?;
                let push = match push_url {
                    Some(u) => json!({"url": u, "state": r.get::<_, Option<String>>(10)?.unwrap_or("ok".into()),
                        "fails": r.get::<_, i64>(11)?, "next_try_at": r.get::<_, Option<i64>>(12)?.map(fmt_time),
                        "last_ok_at": r.get::<_, Option<i64>>(13)?.map(fmt_time)}),
                    None => Value::Null,
                };
                Ok(json!({"id": r.get::<_, String>(0)?, "name": r.get::<_, String>(1)?,
                    "workspaces": store::parse_ws_list(&r.get::<_, String>(2)?),
                    "groups": store::parse_ws_list(&r.get::<_, String>(3)?),
                    "kinds": Kinds::parse(&r.get::<_, String>(4)?).json(),
                    "can_answer": r.get::<_, bool>(5)?, "can_download": r.get::<_, bool>(6)?,
                    "created_at": fmt_time(r.get(7)?), "last_seen": r.get::<_, Option<i64>>(8)?.map(fmt_time),
                    "push": push}))
            },
        )
        .optional()?;
    let mut v = row.ok_or_else(|| not_found("No such subscriber."))?;
    // A removed workspace or group drops out of the lists (it is not in the scope either).
    let ws: Vec<Value> = v["workspaces"]
        .as_array()
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .filter(|w| store::ws_exists(c, w.as_str().unwrap_or("")))
        .collect();
    let gs: Vec<Value> = v["groups"]
        .as_array()
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .filter(|g| groups::exists(c, g.as_str().unwrap_or("")))
        .collect();
    v["workspaces"] = ws.into();
    v["groups"] = gs.into();
    v["streams"] = app.subs.streams_of(id).into();
    Ok(v)
}

async fn list(State(app): State<AppState>, h: HeaderMap) -> Res<Json<Value>> {
    auth::admin(&app, &h)?;
    let c = app.db.lock().unwrap();
    let ids: Vec<String> = c
        .prepare("SELECT id FROM subscribers ORDER BY name COLLATE NOCASE, id")?
        .query_map([], |r| r.get(0))?
        .collect::<Result<_, _>>()?;
    let items: Vec<Value> = ids.iter().map(|i| card(&app, &c, i)).collect::<Res<_>>()?;
    Ok(Json(json!({"items": items, "next": null})))
}

fn check_name(v: &Value) -> Res<String> {
    let n = store::valid_description(v.as_str().unwrap_or("")).map_err(invalid)?;
    if n.is_empty() || n.chars().count() > 40 {
        return Err(invalid("Give the subscriber a name (up to 40 characters)."));
    }
    Ok(n)
}

fn check_list(c: &Connection, v: &Value, what: &str) -> Res<Vec<String>> {
    if v.is_null() {
        return Ok(vec![]);
    }
    let a = v
        .as_array()
        .ok_or_else(|| invalid(format!("`{what}` must be a list.")))?;
    let mut out: Vec<String> = vec![];
    for x in a {
        let x = x.as_str().unwrap_or("");
        let ok = if what == "groups" {
            groups::exists(c, x)
        } else {
            store::ws_exists(c, x)
        };
        if !ok {
            return Err(invalid(if what == "groups" {
                "One of the groups does not exist.".to_string()
            } else {
                "One of the workspaces does not exist.".to_string()
            }));
        }
        if !out.iter().any(|o| o == x) {
            out.push(x.to_string());
        }
    }
    Ok(out)
}

fn check_kinds(v: &Value, base: Kinds) -> Res<Kinds> {
    if v.is_null() {
        return Ok(base);
    }
    if !v.is_object() {
        return Err(invalid("`kinds` must be an object."));
    }
    let f = |k: &str, d: bool| -> Res<bool> {
        match v.get(k) {
            None => Ok(d),
            Some(Value::Bool(b)) => Ok(*b),
            _ => Err(invalid(format!("`kinds.{k}` must be true or false."))),
        }
    };
    Ok(Kinds {
        updates: f("updates", base.updates)?,
        questions: f("questions", base.questions)?,
        results: f("results", base.results)?,
        files: f("files", base.files)?,
    })
}

fn check_flag(v: &Value, k: &str, d: bool) -> Res<bool> {
    match v.get(k) {
        None | Some(Value::Null) => Ok(d),
        Some(Value::Bool(b)) => Ok(*b),
        _ => Err(invalid(format!("`{k}` must be true or false."))),
    }
}

fn need_questions(k: Kinds, can_answer: bool) -> Res<()> {
    if can_answer && !k.questions {
        return Err(invalid("Can answer questions needs Questions turned on."));
    }
    Ok(())
}

fn need_scope(ws: &[String], gs: &[String]) -> Res<()> {
    if ws.is_empty() && gs.is_empty() {
        return Err(invalid("Pick at least one group or workspace."));
    }
    Ok(())
}

fn max_seq(c: &Connection) -> rusqlite::Result<i64> {
    c.query_row("SELECT COALESCE(MAX(seq),0) FROM messages", [], |r| {
        r.get(0)
    })
}

fn link(app: &AppState, token: &str) -> String {
    format!("{}/v1/sub/{token}", app.cfg.public_url)
}

fn new_push_secret(app: &AppState, id: &str) -> (String, Vec<u8>) {
    let secret = rand_token("whsec_", 32);
    let sealed = crypto::seal(&app.key, id, secret.as_bytes());
    (secret, sealed)
}

async fn create(
    State(app): State<AppState>,
    h: HeaderMap,
    body: Bytes,
) -> Res<(StatusCode, Json<Value>)> {
    auth::admin(&app, &h)?;
    let v = parse_body(&body)?;
    let name = check_name(&v["name"])?;
    let push_url = match &v["push_url"] {
        Value::Null => None,
        Value::String(u) if u.trim().is_empty() => None,
        Value::String(u) => Some(subs_push::check_url(u.trim()).map_err(invalid)?.to_string()),
        _ => return Err(invalid("`push_url` must be text.")),
    };
    let c = app.db.lock().unwrap();
    let ws = check_list(&c, &v["workspaces"], "workspaces")?;
    let gs = check_list(&c, &v["groups"], "groups")?;
    need_scope(&ws, &gs)?;
    let kinds = check_kinds(
        &v["kinds"],
        Kinds {
            updates: false,
            questions: true,
            results: true,
            files: false,
        },
    )?;
    let can_answer = check_flag(&v, "can_answer", false)?;
    let can_download = check_flag(&v, "can_download", false)?;
    need_questions(kinds, can_answer)?;
    let id = rand_id("sub_", 10);
    let token = rand_token("sub_", 32);
    let (secret, sealed) = match push_url {
        Some(_) => {
            let (s, b) = new_push_secret(&app, &id);
            (Some(s), Some(b))
        }
        None => (None, None),
    };
    c.execute(
        "INSERT INTO subscribers(id,name,workspaces,groups,kinds,can_answer,can_download,token_hash,created_at,
            push_url,push_secret,push_state,push_cursor) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13)",
        params![
            id,
            name,
            serde_json::to_string(&ws).unwrap(),
            serde_json::to_string(&gs).unwrap(),
            kinds.json().to_string(),
            can_answer,
            can_download,
            token_hash(&token),
            now(),
            push_url,
            sealed,
            push_url.as_ref().map(|_| "ok"),
            push_url.as_ref().map(|_| max_seq(&c)).transpose()?
        ],
    )?;
    log(&c, &id, "created", None, "by Admin", true);
    let sub = card(&app, &c, &id)?;
    Ok((
        StatusCode::CREATED,
        Json(
            json!({"subscriber": sub, "token": token, "link": link(&app, &token), "push_secret": secret}),
        ),
    ))
}

async fn edit(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
    body: Bytes,
) -> Res<Json<Value>> {
    auth::admin(&app, &h)?;
    let v = parse_body(&body)?;
    let mut c = app.db.lock().unwrap();
    let cur = load(&c, &id)?.ok_or_else(|| not_found("No such subscriber."))?;
    let name = match v.get("name") {
        Some(n) => check_name(n)?,
        None => cur.name.clone(),
    };
    let ws = match v.get("workspaces") {
        Some(x) => check_list(&c, x, "workspaces")?,
        None => cur.workspaces.clone(),
    };
    let gs = match v.get("groups") {
        Some(x) => check_list(&c, x, "groups")?,
        None => cur.groups.clone(),
    };
    need_scope(&ws, &gs)?;
    let kinds = check_kinds(v.get("kinds").unwrap_or(&Value::Null), cur.kinds)?;
    let can_answer = check_flag(&v, "can_answer", cur.can_answer)?;
    let can_download = check_flag(&v, "can_download", cur.can_download)?;
    need_questions(kinds, can_answer)?;
    let old_url: Option<String> =
        c.query_row("SELECT push_url FROM subscribers WHERE id=?1", [&id], |r| {
            r.get(0)
        })?;
    let tx = c.transaction()?;
    tx.execute(
        "UPDATE subscribers SET name=?2, workspaces=?3, groups=?4, kinds=?5, can_answer=?6, can_download=?7 WHERE id=?1",
        params![
            id,
            name,
            serde_json::to_string(&ws).unwrap(),
            serde_json::to_string(&gs).unwrap(),
            kinds.json().to_string(),
            can_answer,
            can_download
        ],
    )?;
    let mut secret = None;
    if let Some(p) = v.get("push_url") {
        let new_url = match p {
            Value::Null => None,
            Value::String(u) if u.trim().is_empty() => None,
            Value::String(u) => Some(subs_push::check_url(u.trim()).map_err(invalid)?.to_string()),
            _ => return Err(invalid("`push_url` must be text or null.")),
        };
        match (&old_url, &new_url) {
            (_, None) => {
                tx.execute(
                    "UPDATE subscribers SET push_url=NULL, push_secret=NULL, push_state=NULL, push_cursor=NULL,
                        push_fails=0, push_next_at=NULL, push_last_ok=NULL WHERE id=?1",
                    [&id],
                )?;
            }
            (None, Some(u)) => {
                let (s, sealed) = new_push_secret(&app, &id);
                tx.execute(
                    "UPDATE subscribers SET push_url=?2, push_secret=?3, push_state='ok', push_cursor=?4, push_fails=0,
                        push_next_at=NULL WHERE id=?1",
                    params![id, u, sealed, max_seq(&tx)?],
                )?;
                secret = Some(s);
            }
            (Some(o), Some(u)) if o != u => {
                tx.execute(
                    "UPDATE subscribers SET push_url=?2, push_state='ok', push_fails=0, push_next_at=NULL WHERE id=?1",
                    params![id, u],
                )?;
            }
            _ => {}
        }
    }
    log(&tx, &id, "changed", None, "by Admin", true);
    tx.commit()?;
    let sub = card(&app, &c, &id)?;
    drop(c);
    app.notify.notify_waiters();
    Ok(Json(json!({"subscriber": sub, "push_secret": secret})))
}

async fn remove(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
) -> Res<StatusCode> {
    auth::admin(&app, &h)?;
    {
        let c = app.db.lock().unwrap();
        let n = c.execute("DELETE FROM subscribers WHERE id=?1", [&id])?;
        if n == 0 {
            return Err(not_found("No such subscriber."));
        }
        c.execute("DELETE FROM sub_log WHERE sub=?1", [&id])?;
    }
    app.notify.notify_waiters();
    Ok(StatusCode::NO_CONTENT)
}

async fn rotate(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
) -> Res<Json<Value>> {
    auth::admin(&app, &h)?;
    let token = rand_token("sub_", 32);
    {
        let c = app.db.lock().unwrap();
        let n = c.execute(
            "UPDATE subscribers SET token_hash=?2 WHERE id=?1",
            params![id, token_hash(&token)],
        )?;
        if n == 0 {
            return Err(not_found("No such subscriber."));
        }
        log(&c, &id, "rotated", None, "by Admin", true);
    }
    app.notify.notify_waiters();
    Ok(Json(json!({"token": token, "link": link(&app, &token)})))
}

fn push_on(c: &Connection, id: &str) -> Res<()> {
    let url: Option<Option<String>> = c
        .query_row("SELECT push_url FROM subscribers WHERE id=?1", [id], |r| {
            r.get(0)
        })
        .optional()?;
    match url {
        None => Err(not_found("No such subscriber.")),
        Some(None) => Err(invalid(
            "Push is off for this subscriber. Add your https address first.",
        )),
        Some(Some(_)) => Ok(()),
    }
}

async fn retry(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
) -> Res<Json<Value>> {
    auth::admin(&app, &h)?;
    let sub = {
        let c = app.db.lock().unwrap();
        push_on(&c, &id)?;
        c.execute(
            "UPDATE subscribers SET push_state='ok', push_fails=0, push_next_at=NULL WHERE id=?1",
            [&id],
        )?;
        log(&c, &id, "retry", None, "by Admin", true);
        card(&app, &c, &id)?
    };
    app.notify.notify_waiters();
    Ok(Json(sub))
}

async fn test(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
) -> Res<Json<Value>> {
    auth::admin(&app, &h)?;
    {
        let c = app.db.lock().unwrap();
        push_on(&c, &id)?;
    }
    Ok(Json(subs_push::send_test(&app, &id).await?))
}

async fn get_log(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
    Query(q): Query<HashMap<String, String>>,
) -> Res<Json<Value>> {
    auth::admin(&app, &h)?;
    let c = app.db.lock().unwrap();
    if load(&c, &id)?.is_none() {
        return Err(not_found("No such subscriber."));
    }
    let failed = q.get("failed").is_some_and(|f| f == "1" || f == "true");
    let items: Vec<Value> = c
        .prepare(
            "SELECT at,what,event,result,ok FROM sub_log WHERE sub=?1 AND (?2=0 OR ok=0) ORDER BY n DESC LIMIT 200",
        )?
        .query_map(params![id, failed], |r| {
            Ok(json!({"at": fmt_time(r.get(0)?), "what": r.get::<_, String>(1)?,
                "event": r.get::<_, Option<String>>(2)?, "result": r.get::<_, String>(3)?, "ok": r.get::<_, bool>(4)?}))
        })?
        .collect::<Result<_, _>>()?;
    Ok(Json(json!({"items": items, "next": null})))
}
