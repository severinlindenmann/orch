//! Shared problem reports (contracts/relay-api.md "Problems"). A report archive is one blob; the text fields and the
//! summary are sealed with the master key. Workspaces the admin lets pick problems up (`problem_readers`) list, read,
//! download and take them; the admin sees and changes all of them.
use crate::api::parse_body;
use crate::crypto::{self, Key};
use crate::error::*;
use crate::state::AppState;
use crate::util::*;
use crate::{auth, store};
use axum::body::Bytes;
use axum::extract::{Path, Query, State};
use axum::http::{header, HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post, put};
use axum::{Json, Router};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Map, Value};
use std::collections::HashMap;
use std::path::Path as FsPath;

pub const MAX_ARCHIVE: i64 = 50 * 1024 * 1024;
const PER_DAY: i64 = 20;
const COLS: &str = "id,ref,from_ws,from_name,created_at,shared_at,status,taken_by,taken_by_name,files,attachments,size,sha256,data";

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/v1/problems", post(share).get(list))
        .route("/v1/problems/:id", get(read))
        .route("/v1/problems/:id/file", get(file))
        .route("/v1/problems/:id/status", post(set_status))
}

pub fn admin_router() -> Router<AppState> {
    Router::new()
        .route("/admin/api/problems", get(admin_list))
        .route("/admin/api/problems/readers", put(put_readers))
        .route(
            "/admin/api/problems/:id",
            get(admin_read).patch(admin_patch).delete(admin_delete),
        )
        .route("/admin/api/problems/:id/file", get(admin_file))
}

fn aad(id: &str) -> String {
    format!("problem:{id}")
}

/// Delete problems shared before `cutoff` together with their archives.
pub fn purge(c: &Connection, data_dir: &FsPath, cutoff: i64) -> rusqlite::Result<usize> {
    let rows: Vec<(String, String)> = c
        .prepare("SELECT id,blob_id FROM problems WHERE shared_at<?1")?
        .query_map([cutoff], |r| Ok((r.get(0)?, r.get(1)?)))?
        .collect::<Result<_, _>>()?;
    for (id, blob) in &rows {
        drop_row(c, data_dir, id, blob)?;
    }
    Ok(rows.len())
}

fn drop_row(c: &Connection, data_dir: &FsPath, id: &str, blob: &str) -> rusqlite::Result<()> {
    let _ = std::fs::remove_file(data_dir.join("blobs").join(blob));
    c.execute("DELETE FROM blobs WHERE id=?1", [blob])?;
    c.execute("DELETE FROM problems WHERE id=?1", [id])?;
    Ok(())
}

fn text(v: &Value, k: &str, max: usize) -> Res<String> {
    match &v[k] {
        Value::Null => Ok(String::new()),
        Value::String(s) if s.chars().count() <= max => Ok(s.clone()),
        _ => Err(invalid(format!(
            "`{k}` must be text of at most {max} characters."
        ))),
    }
}

fn opt_text(v: &Value, k: &str, max: usize) -> Res<Option<String>> {
    Ok(Some(text(v, k, max)?).filter(|s| !s.is_empty()))
}

fn valid_ref(r: &str) -> bool {
    let b = r.as_bytes();
    r.len() <= 80
        && r.len() > 12
        && r.starts_with("r-")
        && b[2..6].iter().all(u8::is_ascii_digit)
        && b[6] == b'-'
        && b[7..11].iter().all(u8::is_ascii_digit)
        && b[11] == b'-'
        && b.iter()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'-' | b'_' | b'.'))
}

fn count(v: &Value, k: &str, lo: i64, hi: i64) -> Res<i64> {
    match v[k].as_i64() {
        Some(n) if (lo..=hi).contains(&n) => Ok(n),
        None if v[k].is_null() && lo == 0 => Ok(0),
        _ => Err(invalid(format!(
            "`{k}` must be a number from {lo} to {hi}."
        ))),
    }
}

fn require_reader(c: &Connection, me: &str) -> Res<()> {
    let ok: bool = c.query_row(
        "SELECT EXISTS(SELECT 1 FROM problem_readers WHERE ws=?1)",
        [me],
        |r| r.get(0),
    )?;
    if ok {
        Ok(())
    } else {
        Err(forbidden(
            "The admin has not let this workspace pick up problems.",
        ))
    }
}

fn problem(key: &Key, r: &rusqlite::Row, with_summary: bool) -> rusqlite::Result<Value> {
    let id: String = r.get(0)?;
    let data: Vec<u8> = r.get(13)?;
    let d: Value = crypto::open(key, &aad(&id), &data)
        .and_then(|b| serde_json::from_slice(&b).ok())
        .unwrap_or(Value::Null);
    let mut o = Map::new();
    o.insert("id".into(), id.into());
    o.insert("ref".into(), r.get::<_, String>(1)?.into());
    o.insert("from".into(), r.get::<_, String>(2)?.into());
    o.insert("from_name".into(), r.get::<_, String>(3)?.into());
    o.insert("shared_at".into(), fmt_time(r.get(5)?).into());
    o.insert("created_at".into(), r.get::<_, String>(4)?.into());
    o.insert("status".into(), r.get::<_, String>(6)?.into());
    o.insert("taken_by".into(), r.get::<_, Option<String>>(7)?.into());
    o.insert(
        "taken_by_name".into(),
        r.get::<_, Option<String>>(8)?.into(),
    );
    let scope = &d["scope"];
    o.insert(
        "scope".into(),
        json!({"ticket": scope["ticket"], "addon": scope["addon"]}),
    );
    for k in ["note", "expected", "more"] {
        o.insert(k.into(), d[k].as_str().unwrap_or("").into());
    }
    o.insert(
        "problems".into(),
        d["problems"].as_array().cloned().unwrap_or_default().into(),
    );
    o.insert("files".into(), r.get::<_, i64>(9)?.into());
    o.insert("attachments".into(), r.get::<_, i64>(10)?.into());
    o.insert("size".into(), r.get::<_, i64>(11)?.into());
    o.insert("sha256".into(), r.get::<_, String>(12)?.into());
    o.insert("orch_version".into(), d["orch_version"].clone());
    o.insert("os".into(), d["os"].clone());
    if with_summary {
        o.insert("summary".into(), d["summary"].as_str().unwrap_or("").into());
    }
    Ok(Value::Object(o))
}

fn one(c: &Connection, key: &Key, id: &str, with_summary: bool) -> Res<Value> {
    c.query_row(
        &format!("SELECT {COLS} FROM problems WHERE id=?1"),
        [id],
        |r| problem(key, r, with_summary),
    )
    .optional()?
    .ok_or_else(|| not_found("No such problem."))
}

fn many(c: &Connection, key: &Key, status: Option<&str>, limit: i64) -> Res<Vec<Value>> {
    let mut st = c.prepare(&format!(
        "SELECT {COLS} FROM problems WHERE (?1 IS NULL OR status=?1) ORDER BY shared_at DESC, rowid DESC LIMIT ?2"
    ))?;
    let rows = st
        .query_map(params![status, limit], |r| problem(key, r, false))?
        .collect::<Result<_, _>>()?;
    Ok(rows)
}

async fn share(
    State(app): State<AppState>,
    h: HeaderMap,
    body: Bytes,
) -> Res<(StatusCode, Json<Value>)> {
    let v = parse_body(&body)?;
    let c = app.db.lock().unwrap();
    let me = auth::workspace(&c, &h)?;
    let rf = v["ref"].as_str().unwrap_or("");
    if !valid_ref(rf) {
        return Err(invalid(
            "`ref` must look like r-0102-1530-ticket (a problem report, not an incident).",
        ));
    }
    let created_at = text(&v, "created_at", 40)?;
    if created_at.is_empty() {
        return Err(invalid("`created_at` is needed."));
    }
    let scope = &v["scope"];
    let ticket = opt_text(scope, "ticket", 40)?;
    let addon = opt_text(scope, "addon", 80)?;
    let (note, expected, more) = (
        text(&v, "note", 600)?,
        text(&v, "expected", 600)?,
        text(&v, "more", 4000)?,
    );
    let summary = text(&v, "summary", 20000)?;
    if summary.is_empty() {
        return Err(invalid("`summary` is needed."));
    }
    let mut checks = vec![];
    if !v["problems"].is_null() {
        let a = v["problems"]
            .as_array()
            .filter(|a| a.len() <= 20)
            .ok_or_else(|| invalid("`problems` must be a list of at most 20 names."))?;
        for n in a {
            match n.as_str() {
                Some(s) if s.chars().count() <= 60 => checks.push(s.to_string()),
                _ => {
                    return Err(invalid(
                        "Each name in `problems` must be text of at most 60 characters.",
                    ))
                }
            }
        }
    }
    let files = count(&v, "files", 1, 2000)?;
    let attachments = count(&v, "attachments", 0, 10)?;
    let (orch_version, os) = (opt_text(&v, "orch_version", 40)?, opt_text(&v, "os", 80)?);
    let size = v["size"]
        .as_i64()
        .ok_or_else(|| invalid("`size` is needed."))?;
    let sha = v["sha256"].as_str().unwrap_or("");
    let blob_id = v["blob_id"].as_str().unwrap_or("");

    // A retried send answers with the stored problem and changes nothing.
    let old: Option<String> = c
        .query_row(
            "SELECT id FROM problems WHERE from_ws=?1 AND ref=?2",
            params![me, rf],
            |r| r.get(0),
        )
        .optional()?;
    if let Some(id) = old {
        return Ok((StatusCode::OK, Json(json!({"id": id}))));
    }
    let blob: Option<(i64, String)> = c
        .query_row(
            "SELECT size,sha256 FROM blobs WHERE id=?1 AND uploader=?2",
            params![blob_id, me],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    let Some((bsize, bsha)) = blob else {
        return Err(not_found(
            "The report file was not found. Upload it again, then share the problem.",
        ));
    };
    if bsize > MAX_ARCHIVE {
        return Err(too_large("A problem report can be at most 50 MB."));
    }
    if bsize != size || !bsha.eq_ignore_ascii_case(sha) {
        return Err(invalid(
            "The report file does not match its size or checksum. Upload it again.",
        ));
    }
    let today: i64 = c.query_row(
        "SELECT COUNT(*) FROM problems WHERE from_ws=?1 AND shared_at>?2",
        params![me, now() - 86400],
        |r| r.get(0),
    )?;
    if today >= PER_DAY {
        return Err(problem_limited());
    }
    let id = rand_id("pb_", 16);
    let data = json!({"scope": {"ticket": ticket, "addon": addon}, "note": note, "expected": expected, "more": more,
        "problems": checks, "summary": summary, "orch_version": orch_version, "os": os});
    let sealed = crypto::seal(&app.key, &aad(&id), &serde_json::to_vec(&data).unwrap());
    let from_name = store::ws_name(&c, &me).unwrap_or_default();
    c.execute(
        "INSERT INTO problems(id,ref,from_ws,from_name,created_at,shared_at,blob_id,files,attachments,size,sha256,data)
         VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12)",
        params![id, rf, me, from_name, created_at, now(), blob_id, files, attachments, bsize, bsha, sealed],
    )?;
    Ok((StatusCode::CREATED, Json(json!({"id": id}))))
}

async fn list(
    State(app): State<AppState>,
    h: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
) -> Res<Json<Value>> {
    let c = app.db.lock().unwrap();
    let me = auth::workspace(&c, &h)?;
    require_reader(&c, &me)?;
    let want = q.get("status").map(String::as_str).unwrap_or("new");
    let status = match want {
        "all" => None,
        "new" | "taken" | "done" => Some(want),
        _ => return Err(invalid("`status` must be new, taken, done or all.")),
    };
    Ok(Json(
        json!({"items": many(&c, &app.key, status, 100)?, "next": null}),
    ))
}

async fn read(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
) -> Res<Json<Value>> {
    let c = app.db.lock().unwrap();
    let me = auth::workspace(&c, &h)?;
    require_reader(&c, &me)?;
    Ok(Json(one(&c, &app.key, &id, true)?))
}

fn archive_headers(name: Option<&str>) -> [(header::HeaderName, String); 3] {
    [
        (header::CONTENT_TYPE, "application/octet-stream".into()),
        (header::X_CONTENT_TYPE_OPTIONS, "nosniff".into()),
        (
            header::CONTENT_DISPOSITION,
            match name {
                Some(n) => format!("attachment; filename=\"{n}.tar\""),
                None => "attachment".into(),
            },
        ),
    ]
}

async fn archive(app: &AppState, id: &str, name: bool) -> Res<Response> {
    let (blob, rf): (String, String) = {
        let c = app.db.lock().unwrap();
        c.query_row("SELECT blob_id,ref FROM problems WHERE id=?1", [id], |r| {
            Ok((r.get(0)?, r.get(1)?))
        })
        .optional()?
        .ok_or_else(|| not_found("No such problem."))?
    };
    let raw = tokio::fs::read(app.blob_path(&blob))
        .await
        .map_err(|_| not_found("The report file is gone."))?;
    let plain =
        crypto::open(&app.key, &blob, &raw).ok_or_else(|| internal("blob does not decrypt"))?;
    Ok((archive_headers(name.then_some(rf.as_str())), plain).into_response())
}

async fn file(State(app): State<AppState>, h: HeaderMap, Path(id): Path<String>) -> Res<Response> {
    {
        let c = app.db.lock().unwrap();
        let me = auth::workspace(&c, &h)?;
        require_reader(&c, &me)?;
    }
    archive(&app, &id, false).await
}

fn status_arg(v: &Value) -> Res<&str> {
    match v["status"].as_str() {
        Some(s @ ("new" | "taken" | "done")) => Ok(s),
        _ => Err(invalid("`status` must be taken, done or new.")),
    }
}

async fn set_status(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
    body: Bytes,
) -> Res<Json<Value>> {
    let v = parse_body(&body)?;
    let want = status_arg(&v)?;
    let mut c = app.db.lock().unwrap();
    let me = auth::workspace(&c, &h)?;
    require_reader(&c, &me)?;
    let tx = c.transaction()?;
    let holder: Option<String> = tx
        .query_row("SELECT taken_by FROM problems WHERE id=?1", [&id], |r| {
            r.get(0)
        })
        .optional()?
        .ok_or_else(|| not_found("No such problem."))?;
    let mine = holder.as_deref() == Some(me.as_str());
    match want {
        "taken" => {
            if holder.is_some() && !mine {
                return Err(conflict("Another workspace already took this problem."));
            }
            let name = store::ws_name(&tx, &me);
            tx.execute(
                "UPDATE problems SET status='taken', taken_by=?2, taken_by_name=?3 WHERE id=?1",
                params![id, me, name],
            )?;
        }
        "done" => {
            if !mine {
                return Err(conflict(
                    "Only the workspace that took this problem can mark it done.",
                ));
            }
            tx.execute("UPDATE problems SET status='done' WHERE id=?1", [&id])?;
        }
        _ => {
            if !mine {
                return Err(conflict(
                    "Only the workspace that took this problem can give it back.",
                ));
            }
            tx.execute(
                "UPDATE problems SET status='new', taken_by=NULL, taken_by_name=NULL WHERE id=?1",
                [&id],
            )?;
        }
    }
    let out = one(&tx, &app.key, &id, false)?;
    tx.commit()?;
    Ok(Json(out))
}

// ---------- admin ----------

fn readers(c: &Connection) -> Res<Vec<String>> {
    Ok(c.prepare("SELECT ws FROM problem_readers ORDER BY ws")?
        .query_map([], |r| r.get(0))?
        .collect::<Result<_, _>>()?)
}

async fn admin_list(State(app): State<AppState>, h: HeaderMap) -> Res<Json<Value>> {
    auth::admin(&app, &h)?;
    let c = app.db.lock().unwrap();
    Ok(Json(
        json!({"items": many(&c, &app.key, None, 500)?, "readers": readers(&c)?}),
    ))
}

async fn put_readers(State(app): State<AppState>, h: HeaderMap, body: Bytes) -> Res<Json<Value>> {
    auth::admin(&app, &h)?;
    let v = parse_body(&body)?;
    let list = v["workspaces"]
        .as_array()
        .ok_or_else(|| invalid("`workspaces` must be a list."))?;
    let mut c = app.db.lock().unwrap();
    let mut ids: Vec<&str> = vec![];
    for w in list {
        match w.as_str() {
            Some(s) if store::ws_exists(&c, s) => ids.push(s),
            _ => return Err(invalid("One of the workspaces does not exist.")),
        }
    }
    let tx = c.transaction()?;
    tx.execute("DELETE FROM problem_readers", [])?;
    for w in ids {
        tx.execute("INSERT OR IGNORE INTO problem_readers(ws) VALUES(?1)", [w])?;
    }
    tx.commit()?;
    Ok(Json(json!({"readers": readers(&c)?})))
}

async fn admin_read(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
) -> Res<Json<Value>> {
    auth::admin(&app, &h)?;
    let c = app.db.lock().unwrap();
    Ok(Json(one(&c, &app.key, &id, true)?))
}

async fn admin_file(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
) -> Res<Response> {
    auth::admin(&app, &h)?;
    archive(&app, &id, true).await
}

async fn admin_patch(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
    body: Bytes,
) -> Res<Json<Value>> {
    auth::admin(&app, &h)?;
    let v = parse_body(&body)?;
    let want = status_arg(&v)?;
    let c = app.db.lock().unwrap();
    let sql = match want {
        "new" => "UPDATE problems SET status='new', taken_by=NULL, taken_by_name=NULL WHERE id=?1",
        "taken" => {
            "UPDATE problems SET status='taken', taken_by=NULL, taken_by_name=NULL WHERE id=?1"
        }
        _ => "UPDATE problems SET status='done' WHERE id=?1",
    };
    if c.execute(sql, [&id])? == 0 {
        return Err(not_found("No such problem."));
    }
    Ok(Json(one(&c, &app.key, &id, false)?))
}

async fn admin_delete(
    State(app): State<AppState>,
    h: HeaderMap,
    Path(id): Path<String>,
) -> Res<StatusCode> {
    auth::admin(&app, &h)?;
    let c = app.db.lock().unwrap();
    let blob: String = c
        .query_row("SELECT blob_id FROM problems WHERE id=?1", [&id], |r| {
            r.get(0)
        })
        .optional()?
        .ok_or_else(|| not_found("No such problem."))?;
    drop_row(&c, &app.cfg.data_dir, &id, &blob)?;
    Ok(StatusCode::NO_CONTENT)
}
