//! Files: the server only ever holds the encrypted blob (crypto.md, OPF1).
use crate::db::{self, FileRow, Workspace};
use crate::err::{ApiError, ApiResult};
use crate::{util, web, State};
use axum::body::Bytes;
use axum::extract::{Path, State as St};
use axum::http::{header, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use serde_json::{json, Value};

/// File page: no inline script or eval; previews use blob: URLs made by file.js (img, media, the PDF frame) and the
/// sandboxed /_/frame.html for HTML pages.
pub const CSP: &str = "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data: blob: https:; media-src blob:; frame-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";

fn blob_path(st: &State, id: &str) -> std::path::PathBuf {
    st.cfg.blobs_dir().join(id)
}

pub fn upload(
    st: &State,
    w: &Workspace,
    blob: Bytes,
    expires_at: Option<String>,
) -> ApiResult<Value> {
    if blob.len() < 32 || &blob[0..4] != b"OPF1" {
        return Err(ApiError::invalid(
            "The body is not an encrypted orch file (it must start with OPF1 and be at least 32 bytes).",
        ));
    }
    let id = format!("f_{}", util::rand_id(16));
    std::fs::write(blob_path(st, &id), &blob)?;
    let row = FileRow {
        id: id.clone(),
        workspace: w.id.clone(),
        size: blob.len() as i64,
        created_at: util::now(),
        expires_at: expires_at.clone(),
    };
    if let Err(e) = db::insert_file(&st.db.lock().unwrap(), &row) {
        let _ = std::fs::remove_file(blob_path(st, &id));
        return Err(e.into());
    }
    Ok(json!({
        "id": id,
        "url": format!("{}/f/{}", st.cfg.public_url, id),
        "size": row.size,
        "expires_at": expires_at,
    }))
}

/// Deletes the row and the blob.
pub fn remove(st: &State, id: &str) {
    let _ = db::delete_file(&st.db.lock().unwrap(), id);
    let _ = std::fs::remove_file(blob_path(st, id));
}

fn state_of(st: &State, id: &str) -> ApiResult<FileRow> {
    let f = db::get_file(&st.db.lock().unwrap(), id)?
        .ok_or_else(|| ApiError::not_found("No such file."))?;
    if f.expires_at
        .as_deref()
        .is_some_and(|e| e <= util::now().as_str())
    {
        return Err(ApiError::gone("This link has expired."));
    }
    Ok(f)
}

/// GET /f/<id>: the small page; its JS fetches the blob and decrypts in the browser.
pub async fn page(St(st): St<State>, Path(id): Path<String>) -> Response {
    let status = match state_of(&st, &id) {
        Ok(_) => StatusCode::OK,
        Err(e) => e.status,
    };
    let mut r = (
        status,
        [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
        web::FILE_HTML,
    )
        .into_response();
    let h = r.headers_mut();
    h.insert("x-frame-options", HeaderValue::from_static("DENY"));
    h.insert("referrer-policy", HeaderValue::from_static("no-referrer"));
    h.insert("content-security-policy", HeaderValue::from_static(CSP));
    h.insert("cache-control", HeaderValue::from_static("no-store"));
    r
}

/// GET /f/<id>/blob
pub async fn blob(St(st): St<State>, Path(id): Path<String>) -> ApiResult<Response> {
    let row = state_of(&st, &id)?;
    let file = tokio::fs::File::open(blob_path(&st, &id))
        .await
        .map_err(|_| ApiError::not_found("No such file."))?;
    let len = file.metadata().await.map(|m| m.len()).ok();
    let mut r = (
        [
            (header::CONTENT_TYPE, "application/octet-stream"),
            (header::CACHE_CONTROL, "no-store"),
            (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
        ],
        axum::body::Body::from_stream(tokio_util::io::ReaderStream::new(file)),
    )
        .into_response();
    if let Some(n) = len {
        r.headers_mut().insert(header::CONTENT_LENGTH, n.into());
    }
    // the page shows "N days left"; absent = permanent
    if let Some(v) = row.expires_at.and_then(|e| HeaderValue::from_str(&e).ok()) {
        r.headers_mut().insert("x-orch-expires-at", v);
    }
    Ok(r)
}
