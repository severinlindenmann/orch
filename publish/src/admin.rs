//! Admin API and portal. Own listener (private network only); admin token required.
use crate::api::Q;
use crate::db::{self, Rights, Workspace};
use crate::err::{ApiError, ApiResult};
use crate::{apps, files, util, web, State};
use axum::body::Bytes;
use axum::extract::{Path, Query, State as St};
use axum::http::{header, HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{delete, get, patch, post};
use axum::{Json, Router};
use serde::Deserialize;
use serde_json::{json, Value};

pub fn router(st: State) -> Router {
    Router::new()
        .route(
            "/",
            get(|| async { axum::response::Redirect::to("/admin") }),
        )
        .route("/admin", get(portal))
        .route("/admin/", get(portal))
        .route("/admin/style.css", get(css))
        .route("/admin/portal.js", get(js))
        .route("/admin/kit.js", get(kit_js))
        .route("/_/favicon.svg", get(web::favicon_svg))
        .route("/_/apple-touch-icon.png", get(web::touch_icon))
        .route("/admin/api/workspaces", get(ws_list).post(ws_create))
        .route(
            "/admin/api/workspaces/:id",
            patch(ws_patch).delete(ws_delete),
        )
        .route("/admin/api/workspaces/:id/token", post(ws_token))
        .route(
            "/admin/api/workspaces/:id/profile/approve",
            post(profile_approve),
        )
        .route(
            "/admin/api/workspaces/:id/profile/reject",
            post(profile_reject),
        )
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

async fn portal(St(st): St<State>) -> Response {
    page_headers(
        (
            [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
            web::PORTAL_HTML.replace("__PUBLISH_URL__", &util::esc(&st.cfg.public_url)),
        )
            .into_response(),
    )
}
async fn css() -> impl IntoResponse {
    (
        [(header::CONTENT_TYPE, "text/css; charset=utf-8")],
        include_str!("../web/admin.css"),
    )
}
async fn kit_js() -> impl IntoResponse {
    (
        [(header::CONTENT_TYPE, "text/javascript; charset=utf-8")],
        include_str!("../web/admin-kit.js"),
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

pub fn prompt(st: &State, w: &Workspace, token: &str) -> String {
    let (u, id) = (&st.cfg.public_url, &w.id);
    // The admin already typed a description: do not ask the agent to describe itself.
    let describe = if w.description_by == "admin" && !w.description.is_empty() {
        ""
    } else {
        "Then describe this workspace in one sentence and 2-4 tags:\n  orch publish profile --description \"...\" --tags a,b\n"
    };
    format!(
        "Connect this project to orch publish. Run in the project folder:\n  orch addon add publish --yes\n  orch publish connect {u} --workspace {id} --token {token}\nIf orch is not installed yet, run this instead:\n  macOS/Linux: curl -fsSL {u}/onboarding.sh | sh -s -- --workspace {id} --token {token}\n  Windows:     & ([scriptblock]::Create((irm {u}/onboarding.ps1))) -Workspace {id} -Token {token}\n{describe}"
    )
}

fn ws_json(w: &Workspace) -> Value {
    json!({"id": w.id, "name": w.name, "description": w.description, "tags": w.tags, "rights": w.rights,
        "description_by": w.description_by, "tags_by": w.tags_by, "pending": db::Pending::json(&w.pending),
        "icon": w.icon, "color": w.color, "look_by": w.look_by, "show_on_shared_pages": w.show_on_shared_pages})
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

fn clean_tags(t: Vec<String>) -> ApiResult<Vec<String>> {
    util::valid_tags(&t).map_err(ApiError::invalid)
}

fn clean_description(d: &str) -> ApiResult<String> {
    util::valid_description(d).map_err(ApiError::invalid)
}

async fn ws_create(St(st): St<State>, h: HeaderMap, body: Bytes) -> ApiResult<Response> {
    check(&st, &h)?;
    let raw: Value = serde_json::from_slice(&body).map_err(|e| ApiError::invalid(e.to_string()))?;
    let b: NewWs =
        serde_json::from_value(raw.clone()).map_err(|e| ApiError::invalid(e.to_string()))?;
    let lk = crate::look::parse(&raw)?;
    if b.name.trim().is_empty() || b.name.len() > 60 {
        return Err(ApiError::invalid("The name must be 1-60 characters."));
    }
    let token = util::rand_token("orp_", 32);
    let w = Workspace {
        id: format!("ws_{}", util::rand_id(10)),
        name: b.name.trim().into(),
        description: clean_description(&b.description)?,
        tags: clean_tags(b.tags)?,
        rights: b.rights.unwrap_or(Rights {
            files: true,
            apps: true,
            permanent: false,
            public: false,
        }),
        token_hash: util::sha256_hex(&token),
        description_by: "admin".into(),
        tags_by: "admin".into(),
        pending: None,
        icon: lk.icon.flatten(),
        color: lk.color.flatten(),
        look_by: None,
        show_on_shared_pages: true,
    };
    let w = Workspace {
        look_by: (w.icon.is_some() || w.color.is_some()).then(|| "admin".to_string()),
        ..w
    };
    db::insert_workspace(&st.db.lock().unwrap(), &w, &util::now())?;
    let p = prompt(&st, &w, &token);
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
    body: Bytes,
) -> ApiResult<Json<Value>> {
    check(&st, &h)?;
    let raw: Value = serde_json::from_slice(&body).map_err(|e| ApiError::invalid(e.to_string()))?;
    let b: PatchWs =
        serde_json::from_value(raw.clone()).map_err(|e| ApiError::invalid(e.to_string()))?;
    let lk = crate::look::parse(&raw)?;
    // Check and set under one transaction: a refused look stores nothing from this body.
    let mut c = st.db.lock().unwrap();
    let tx = c.transaction()?;
    let mut w =
        db::get_workspace(&tx, &id)?.ok_or_else(|| ApiError::not_found("No such workspace."))?;
    if lk.has_look() {
        crate::look::admin_allowed(&w.look_by)?;
    }
    if let Some(n) = b.name {
        if n.trim().is_empty() || n.len() > 60 {
            return Err(ApiError::invalid("The name must be 1-60 characters."));
        }
        w.name = n.trim().into();
    }
    if let Some(d) = b.description {
        w.description = clean_description(&d)?;
        w.description_by = "admin".into();
    }
    if let Some(t) = b.tags {
        w.tags = clean_tags(t)?;
        w.tags_by = "admin".into();
    }
    if let Some(r) = b.rights {
        w.rights = r;
    }
    db::update_workspace(&tx, &w)?;
    crate::look::apply(&tx, &id, &lk, "admin")?;
    tx.commit()?;
    let w = db::get_workspace(&c, &id)?.ok_or_else(|| ApiError::not_found("No such workspace."))?;
    Ok(Json(ws_json(&w)))
}

/// The `rev` of the proposal the owner looked at; approve/reject only act on exactly that one.
#[derive(Deserialize)]
struct Rev {
    rev: String,
}

fn stale_or_none(st: &State, id: &str) -> ApiError {
    match db::get_workspace(&st.db.lock().unwrap(), id) {
        Ok(Some(w)) if w.pending.is_some() => {
            ApiError::new(409, "conflict", "This change was replaced, review again.")
        }
        _ => ApiError::not_found("There is no change to review."),
    }
}

/// Owner approves the workspace's proposed description/tags: they become live.
async fn profile_approve(
    St(st): St<State>,
    h: HeaderMap,
    Path(id): Path<String>,
    Json(b): Json<Rev>,
) -> ApiResult<Json<Value>> {
    check(&st, &h)?;
    if db::approve_pending(&st.db.lock().unwrap(), &id, &b.rev)? == 0 {
        return Err(stale_or_none(&st, &id));
    }
    Ok(Json(ws_json(&get_ws(&st, &id)?)))
}

/// Owner rejects it: the old values stay, the proposal is dropped.
async fn profile_reject(
    St(st): St<State>,
    h: HeaderMap,
    Path(id): Path<String>,
    Json(b): Json<Rev>,
) -> ApiResult<StatusCode> {
    check(&st, &h)?;
    if db::reject_pending(&st.db.lock().unwrap(), &id, &b.rev)? == 0 {
        return Err(stale_or_none(&st, &id));
    }
    Ok(StatusCode::NO_CONTENT)
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
    let c = st.db.lock().unwrap();
    db::update_workspace(&c, &w)?;
    db::clear_pending(&c, &id)?;
    Ok(Json(
        json!({"token": token, "prompt": prompt(&st, &w, &token)}),
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
        .map(|f| json!({"id": f.id, "workspace": f.workspace, "size": f.size, "created_at": f.created_at, "expires_at": f.expires_at}))
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
