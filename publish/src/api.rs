//! Workspace API (/v1/...): auth and thin handlers; the work is in files.rs and apps.rs.
use crate::db::{self, Workspace};
use crate::err::{ApiError, ApiResult};
use crate::{apps, files, util, State};
use axum::body::{Body, Bytes};
use axum::extract::{Path, Query, State as St};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Deserialize, Default)]
pub struct Q {
    pub days: Option<i64>,
    pub permanent: Option<String>,
    pub new_token: Option<String>,
    pub limit: Option<usize>,
    pub after: Option<String>,
}

impl Q {
    pub fn is_permanent(&self) -> bool {
        matches!(self.permanent.as_deref(), Some("1") | Some("true"))
    }
    pub fn want_new_token(&self) -> bool {
        matches!(self.new_token.as_deref(), Some("1") | Some("true"))
    }
    /// (limit, cursor) for list endpoints: default 50, max 100
    pub fn paging(&self) -> ApiResult<(usize, Option<i64>)> {
        let limit = self.limit.unwrap_or(50).clamp(1, 100);
        let after = db::decode_cursor(self.after.as_deref())
            .map_err(|_| ApiError::invalid("The cursor in ?after= is not valid."))?;
        Ok((limit, after))
    }
}

pub fn auth(st: &State, h: &HeaderMap) -> ApiResult<Workspace> {
    let id = h.get("x-orch-workspace").and_then(|v| v.to_str().ok());
    let tok = h
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.strip_prefix("Bearer "));
    let (Some(id), Some(tok)) = (id, tok) else {
        return Err(ApiError::unauthorized());
    };
    let ws = db::get_workspace(&st.db.lock().unwrap(), id)?;
    let hash = util::sha256_hex(tok);
    match ws {
        Some(w) if util::ct_eq(&hash, &w.token_hash) => Ok(w),
        _ => Err(ApiError::unauthorized()),
    }
}

fn who_json(st: &State, w: &Workspace) -> Value {
    json!({
        "id": w.id, "name": w.name, "description": w.description, "tags": w.tags, "rights": w.rights,
        "max_file_mb": st.cfg.max_file_mb, "default_days": st.cfg.default_days, "max_days": st.cfg.max_days,
    })
}

pub async fn whoami(St(st): St<State>, h: HeaderMap) -> ApiResult<Json<Value>> {
    let w = auth(&st, &h)?;
    Ok(Json(who_json(&st, &w)))
}

#[derive(Deserialize)]
pub struct MeBody {
    description: Option<String>,
    tags: Option<Vec<String>>,
}

/// PATCH /v1/me: a workspace changes its own description and tags.
pub async fn me_patch(St(st): St<State>, h: HeaderMap, body: Bytes) -> ApiResult<Json<Value>> {
    let mut w = auth(&st, &h)?;
    let b: MeBody = serde_json::from_slice(&body).map_err(|_| {
        ApiError::invalid(
            "The body must be JSON like {\"description\": \"...\", \"tags\": [\"a\"]}.",
        )
    })?;
    if let Some(d) = b.description {
        if d.chars().count() > 280 {
            return Err(ApiError::invalid(
                "The description is at most 280 characters.",
            ));
        }
        w.description = d.trim().to_string();
    }
    if let Some(t) = b.tags {
        let t: Vec<String> = t
            .into_iter()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();
        if t.len() > 8 || t.iter().any(|s| s.chars().count() > 24) {
            return Err(ApiError::invalid(
                "Use at most 8 tags, each at most 24 characters.",
            ));
        }
        w.tags = t;
    }
    db::update_workspace(&st.db.lock().unwrap(), &w)?;
    Ok(Json(who_json(&st, &w)))
}

pub async fn files_post(
    St(st): St<State>,
    h: HeaderMap,
    Query(q): Query<Q>,
    body: Body,
) -> ApiResult<Response> {
    let w = auth(&st, &h)?;
    if !w.rights.files {
        return Err(ApiError::forbidden("This workspace may not upload files."));
    }
    let expires = expiry(&st, &w, &q, "files")?;
    let bytes: Bytes = axum::body::to_bytes(body, st.cfg.max_blob_bytes())
        .await
        .map_err(|_| {
            ApiError::too_large(format!(
                "The file is larger than {} MB.",
                st.cfg.max_file_mb
            ))
        })?;
    let v = files::upload(&st, &w, bytes, expires)?;
    Ok((StatusCode::CREATED, Json(v)).into_response())
}

/// Lifetime from `?days=` / `?permanent=1`, checked against the workspace rights.
pub fn expiry(st: &State, w: &Workspace, q: &Q, what: &str) -> ApiResult<Option<String>> {
    if q.is_permanent() {
        if !w.rights.permanent {
            return Err(ApiError::forbidden(format!(
                "This workspace may not make permanent {what}."
            )));
        }
        return Ok(None);
    }
    let days = q.days.unwrap_or(st.cfg.default_days);
    if days < 1 || days > st.cfg.max_days {
        return Err(ApiError::invalid(format!(
            "days must be between 1 and {}.",
            st.cfg.max_days
        )));
    }
    Ok(Some(util::in_days(days)))
}

pub async fn files_list(
    St(st): St<State>,
    h: HeaderMap,
    Query(q): Query<Q>,
) -> ApiResult<Json<Value>> {
    let w = auth(&st, &h)?;
    let (limit, after) = q.paging()?;
    let (rows, next) = db::list_files(&st.db.lock().unwrap(), Some(&w.id), limit, after)?;
    let items: Vec<Value> = rows
        .iter()
        .map(|f| json!({"id": f.id, "size": f.size, "created_at": f.created_at, "expires_at": f.expires_at}))
        .collect();
    Ok(Json(json!({"items": items, "next": next})))
}

pub async fn files_delete(
    St(st): St<State>,
    h: HeaderMap,
    Path(id): Path<String>,
) -> ApiResult<StatusCode> {
    let w = auth(&st, &h)?;
    let f = db::get_file(&st.db.lock().unwrap(), &id)?;
    match f {
        Some(f) if f.workspace == w.id => {
            files::remove(&st, &id);
            Ok(StatusCode::NO_CONTENT)
        }
        _ => Err(ApiError::not_found("No such file.")),
    }
}

pub async fn apps_put(
    St(st): St<State>,
    h: HeaderMap,
    Path(name): Path<String>,
    Query(q): Query<Q>,
    body: Body,
) -> ApiResult<Json<Value>> {
    let w = auth(&st, &h)?;
    if !w.rights.apps {
        return Err(ApiError::forbidden("This workspace may not publish apps."));
    }
    if !util::valid_app_name(&name) {
        return Err(ApiError::invalid(
            "The app name must be 2-40 characters: a-z, 0-9 and -.",
        ));
    }
    let expires = expiry(&st, &w, &q, "apps")?;
    let bytes = axum::body::to_bytes(body, 100 * 1024 * 1024)
        .await
        .map_err(|_| ApiError::too_large("The app bundle is larger than 100 MB."))?;
    apps::deploy(&st, &w, &name, bytes, expires, q.want_new_token())
        .await
        .map(Json)
}

pub async fn apps_list(
    St(st): St<State>,
    h: HeaderMap,
    Query(q): Query<Q>,
) -> ApiResult<Json<Value>> {
    let w = auth(&st, &h)?;
    let (limit, after) = q.paging()?;
    let (rows, next) = db::list_apps(&st.db.lock().unwrap(), Some(&w.id), limit, after)?;
    let items: Vec<Value> = rows.iter().map(|a| apps::app_json(&st, a)).collect();
    Ok(Json(json!({"items": items, "next": next})))
}

fn own_app(st: &State, w: &Workspace, name: &str) -> ApiResult<()> {
    match db::get_app(&st.db.lock().unwrap(), name)? {
        Some(a) if a.workspace == w.id => Ok(()),
        _ => Err(ApiError::not_found("No such app.")),
    }
}

pub async fn apps_restart(
    St(st): St<State>,
    h: HeaderMap,
    Path(name): Path<String>,
) -> ApiResult<Json<Value>> {
    let w = auth(&st, &h)?;
    own_app(&st, &w, &name)?;
    apps::restart(&st, &name).await.map(Json)
}

pub async fn apps_stop(
    St(st): St<State>,
    h: HeaderMap,
    Path(name): Path<String>,
) -> ApiResult<Json<Value>> {
    let w = auth(&st, &h)?;
    own_app(&st, &w, &name)?;
    apps::stop(&st, &name).await.map(Json)
}

pub async fn apps_delete(
    St(st): St<State>,
    h: HeaderMap,
    Path(name): Path<String>,
) -> ApiResult<StatusCode> {
    let w = auth(&st, &h)?;
    own_app(&st, &w, &name)?;
    let _g = st.app_lock.lock().await;
    apps::remove(&st, &name).await;
    Ok(StatusCode::NO_CONTENT)
}
