//! Admin API and portal. Own listener (private network only); admin token required.
use crate::api::Q;
use crate::db::{self, Rights, Workspace};
use crate::err::{ApiError, ApiResult};
use crate::{apps, files, util, web, State};
use axum::extract::{Path, Query, State as St};
use axum::http::{header, HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{delete, get, patch, post};
use axum::{Json, Router};
use serde::Deserialize;
use serde_json::{json, Value};

pub fn router(st: State) -> Router {
    Router::new()
        .route("/admin", get(portal))
        .route("/admin/", get(portal))
        .route("/admin/style.css", get(css))
        .route("/admin/portal.js", get(js))
        .route("/admin/api/workspaces", get(ws_list).post(ws_create))
        .route(
            "/admin/api/workspaces/:id",
            patch(ws_patch).delete(ws_delete),
        )
        .route("/admin/api/workspaces/:id/token", post(ws_token))
        .route("/admin/api/files", get(files_list))
        .route("/admin/api/files/:id", delete(file_delete))
        .route("/admin/api/apps", get(apps_list))
        .route("/admin/api/apps/:name/restart", post(app_restart))
        .route("/admin/api/apps/:name/stop", post(app_stop))
        .route("/admin/api/apps/:name", delete(app_delete))
        .with_state(st)
}

fn page_headers(mut r: Response) -> Response {
    let h = r.headers_mut();
    h.insert("x-frame-options", "DENY".parse().unwrap());
    h.insert("referrer-policy", "no-referrer".parse().unwrap());
    h.insert(
        "content-security-policy",
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
            .parse()
            .unwrap(),
    );
    r
}

async fn portal() -> Response {
    page_headers(
        (
            [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
            web::PORTAL_HTML,
        )
            .into_response(),
    )
}
async fn css() -> impl IntoResponse {
    (
        [(header::CONTENT_TYPE, "text/css; charset=utf-8")],
        web::style(),
    )
}
async fn js() -> impl IntoResponse {
    (
        [(header::CONTENT_TYPE, "text/javascript; charset=utf-8")],
        web::PORTAL_JS,
    )
}

fn check(st: &State, h: &HeaderMap) -> ApiResult<()> {
    let t = h.get("x-orch-admin").and_then(|v| v.to_str().ok());
    match t {
        Some(t) if !st.cfg.admin_token.is_empty() && util::ct_eq(t, &st.cfg.admin_token) => Ok(()),
        _ => Err(ApiError::new(
            401,
            "unauthorized",
            "Missing or wrong admin token.",
        )),
    }
}

pub fn prompt(st: &State, id: &str, token: &str) -> String {
    let u = &st.cfg.public_url;
    format!(
        "Connect this workspace to orch-publish. Run in the project folder:\n  orch publish connect {u} --workspace {id} --token {token}\nIf orch is not installed yet:\n  macOS/Linux: curl -fsSL {u}/onboarding.sh | sh -s -- --workspace {id} --token {token}\n  Windows:     & ([scriptblock]::Create((irm {u}/onboarding.ps1))) -Workspace {id} -Token {token}\n"
    )
}

fn ws_json(w: &Workspace) -> Value {
    json!({"id": w.id, "name": w.name, "description": w.description, "tags": w.tags, "rights": w.rights})
}

async fn ws_list(St(st): St<State>, h: HeaderMap, Query(q): Query<Q>) -> ApiResult<Json<Value>> {
    check(&st, &h)?;
    let (limit, after) = q.paging()?;
    let (rows, next) = db::list_workspaces(&st.db.lock().unwrap(), limit, after)?;
    let items: Vec<Value> = rows
        .iter()
        .map(|(w, f, a)| {
            let mut v = ws_json(w);
            v["files"] = json!(f);
            v["apps"] = json!(a);
            v
        })
        .collect();
    Ok(Json(json!({"items": items, "next": next})))
}

#[derive(Deserialize)]
struct NewWs {
    name: String,
    #[serde(default)]
    description: String,
    #[serde(default)]
    tags: Vec<String>,
    rights: Option<Rights>,
}

fn clean_tags(t: Vec<String>) -> Vec<String> {
    t.into_iter()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

async fn ws_create(St(st): St<State>, h: HeaderMap, Json(b): Json<NewWs>) -> ApiResult<Response> {
    check(&st, &h)?;
    if b.name.trim().is_empty() || b.name.len() > 60 {
        return Err(ApiError::invalid("The name must be 1-60 characters."));
    }
    let token = util::rand_token("orp_", 32);
    let w = Workspace {
        id: format!("ws_{}", util::rand_id(10)),
        name: b.name.trim().into(),
        description: b.description,
        tags: clean_tags(b.tags),
        rights: b.rights.unwrap_or(Rights {
            files: true,
            apps: true,
            permanent: false,
            public: false,
        }),
        token_hash: util::sha256_hex(&token),
    };
    db::insert_workspace(&st.db.lock().unwrap(), &w, &util::now())?;
    let p = prompt(&st, &w.id, &token);
    Ok((
        StatusCode::CREATED,
        Json(json!({"id": w.id, "token": token, "prompt": p})),
    )
        .into_response())
}

#[derive(Deserialize)]
struct PatchWs {
    name: Option<String>,
    description: Option<String>,
    tags: Option<Vec<String>>,
    rights: Option<Rights>,
}

fn get_ws(st: &State, id: &str) -> ApiResult<Workspace> {
    db::get_workspace(&st.db.lock().unwrap(), id)?
        .ok_or_else(|| ApiError::not_found("No such workspace."))
}

async fn ws_patch(
    St(st): St<State>,
    h: HeaderMap,
    Path(id): Path<String>,
    Json(b): Json<PatchWs>,
) -> ApiResult<Json<Value>> {
    check(&st, &h)?;
    let mut w = get_ws(&st, &id)?;
    if let Some(n) = b.name {
        if n.trim().is_empty() || n.len() > 60 {
            return Err(ApiError::invalid("The name must be 1-60 characters."));
        }
        w.name = n.trim().into();
    }
    if let Some(d) = b.description {
        w.description = d;
    }
    if let Some(t) = b.tags {
        w.tags = clean_tags(t);
    }
    if let Some(r) = b.rights {
        w.rights = r;
    }
    db::update_workspace(&st.db.lock().unwrap(), &w)?;
    Ok(Json(ws_json(&w)))
}

async fn ws_token(
    St(st): St<State>,
    h: HeaderMap,
    Path(id): Path<String>,
) -> ApiResult<Json<Value>> {
    check(&st, &h)?;
    let mut w = get_ws(&st, &id)?;
    let token = util::rand_token("orp_", 32);
    w.token_hash = util::sha256_hex(&token);
    db::update_workspace(&st.db.lock().unwrap(), &w)?;
    Ok(Json(
        json!({"token": token, "prompt": prompt(&st, &id, &token)}),
    ))
}

async fn ws_delete(
    St(st): St<State>,
    h: HeaderMap,
    Path(id): Path<String>,
) -> ApiResult<StatusCode> {
    check(&st, &h)?;
    get_ws(&st, &id)?;
    let (fids, names) = {
        let c = st.db.lock().unwrap();
        let f = db::file_ids_of(&c, &id)?;
        let n: Vec<String> = db::all_apps(&c)?
            .into_iter()
            .filter(|a| a.workspace == id)
            .map(|a| a.name)
            .collect();
        (f, n)
    };
    for f in fids {
        files::remove(&st, &f);
    }
    for n in names {
        let _g = st.app_lock.lock().await;
        apps::remove(&st, &n).await;
    }
    db::delete_workspace(&st.db.lock().unwrap(), &id)?;
    Ok(StatusCode::NO_CONTENT)
}

async fn files_list(St(st): St<State>, h: HeaderMap, Query(q): Query<Q>) -> ApiResult<Json<Value>> {
    check(&st, &h)?;
    let (limit, after) = q.paging()?;
    let (rows, next) = db::list_files(&st.db.lock().unwrap(), None, limit, after)?;
    let items: Vec<Value> = rows
        .iter()
        .map(|f| json!({"id": f.id, "workspace": f.workspace, "size": f.size, "expires_at": f.expires_at}))
        .collect();
    Ok(Json(json!({"items": items, "next": next})))
}

async fn file_delete(
    St(st): St<State>,
    h: HeaderMap,
    Path(id): Path<String>,
) -> ApiResult<StatusCode> {
    check(&st, &h)?;
    db::get_file(&st.db.lock().unwrap(), &id)?
        .ok_or_else(|| ApiError::not_found("No such file."))?;
    files::remove(&st, &id);
    Ok(StatusCode::NO_CONTENT)
}

async fn apps_list(St(st): St<State>, h: HeaderMap, Query(q): Query<Q>) -> ApiResult<Json<Value>> {
    check(&st, &h)?;
    let (limit, after) = q.paging()?;
    let (rows, next) = db::list_apps(&st.db.lock().unwrap(), None, limit, after)?;
    let items: Vec<Value> = rows
        .iter()
        .map(|a| {
            let mut v = apps::app_json(&st, a);
            v["workspace"] = json!(a.workspace);
            v
        })
        .collect();
    Ok(Json(json!({"items": items, "next": next})))
}

fn app_exists(st: &State, name: &str) -> ApiResult<()> {
    db::get_app(&st.db.lock().unwrap(), name)?
        .map(|_| ())
        .ok_or_else(|| ApiError::not_found("No such app."))
}

async fn app_restart(
    St(st): St<State>,
    h: HeaderMap,
    Path(n): Path<String>,
) -> ApiResult<Json<Value>> {
    check(&st, &h)?;
    app_exists(&st, &n)?;
    apps::restart(&st, &n).await.map(Json)
}

async fn app_stop(
    St(st): St<State>,
    h: HeaderMap,
    Path(n): Path<String>,
) -> ApiResult<Json<Value>> {
    check(&st, &h)?;
    app_exists(&st, &n)?;
    apps::stop(&st, &n).await.map(Json)
}

async fn app_delete(
    St(st): St<State>,
    h: HeaderMap,
    Path(n): Path<String>,
) -> ApiResult<StatusCode> {
    check(&st, &h)?;
    app_exists(&st, &n)?;
    let _g = st.app_lock.lock().await;
    apps::remove(&st, &n).await;
    Ok(StatusCode::NO_CONTENT)
}
