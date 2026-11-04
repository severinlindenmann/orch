//! Apps: deploy a bundle, run it as a child process (runner.rs), serve and proxy /a/<name>/.
use crate::db::{self, AppRow, Workspace};
use crate::err::{ApiError, ApiResult};
use crate::runner::{run_step, Spec};
use crate::{util, State};
use axum::body::{Body, Bytes};
use axum::extract::{Path, Request, State as St};
use axum::http::{header, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use serde::Deserialize;
use serde_json::{json, Value};
use std::path::{Path as FsPath, PathBuf};
use std::time::{Duration, Instant};

#[derive(Deserialize, Debug)]
pub struct Manifest {
    pub name: String,
    #[serde(default)]
    pub about: String,
    pub stack: String,
    pub start: Option<String>,
    pub health: Option<String>,
    pub test: Option<String>,
    #[serde(default = "none")]
    pub store: String,
    #[serde(default)]
    pub public: bool,
}
fn none() -> String {
    "none".into()
}

fn parse_manifest(dir: &FsPath) -> ApiResult<Manifest> {
    let text = std::fs::read_to_string(dir.join("app.toml"))
        .map_err(|_| ApiError::invalid("The bundle has no app.toml at its top level."))?;
    let m: Manifest = toml::from_str(&text)
        .map_err(|e| ApiError::invalid(format!("app.toml is not valid: {}", e.message())))?;
    let bad = |s: &str| Err(ApiError::invalid(format!("app.toml: {s}")));
    if !util::valid_app_name(&m.name) {
        return bad("name must be 2-40 characters: a-z, 0-9 and -.");
    }
    if !["static", "python", "node"].contains(&m.stack.as_str()) {
        return bad("stack must be static, python or node.");
    }
    if !["none", "json", "markdown", "sqlite"].contains(&m.store.as_str()) {
        return bad("store must be none, json, markdown or sqlite.");
    }
    if m.stack == "static" {
        if m.start.is_some() || m.health.is_some() {
            return bad("static apps must not have start or health.");
        }
    } else if m.start.as_deref().unwrap_or("").is_empty()
        || m.health.as_deref().unwrap_or("").is_empty()
    {
        return bad("python and node apps need start and health.");
    }
    if let Some(h) = &m.health {
        if !h.starts_with('/') {
            return bad("health must be a path starting with /.");
        }
    }
    Ok(m)
}

/// Unpacks the .tar.gz into `dir`; returns the folder that holds app.toml.
fn extract(bytes: &[u8], dir: &FsPath) -> ApiResult<PathBuf> {
    std::fs::create_dir_all(dir)?;
    let gz = flate2::read::GzDecoder::new(bytes);
    let mut ar = tar::Archive::new(gz);
    let (mut total, mut count) = (0u64, 0u32);
    let bad = || ApiError::invalid("The bundle is not a valid .tar.gz.");
    for e in ar.entries().map_err(|_| bad())? {
        let mut e = e.map_err(|_| bad())?;
        let t = e.header().entry_type();
        if t.is_symlink() || t.is_hard_link() {
            return Err(ApiError::invalid("The bundle must not contain links."));
        }
        total += e.size();
        count += 1;
        if total > 500 * 1024 * 1024 || count > 50_000 {
            return Err(ApiError::too_large("The unpacked bundle is too large."));
        }
        if !e.unpack_in(dir).map_err(|_| bad())? {
            return Err(ApiError::invalid("The bundle has an unsafe path."));
        }
    }
    if dir.join("app.toml").is_file() {
        return Ok(dir.to_path_buf());
    }
    let subs: Vec<_> = std::fs::read_dir(dir)?
        .filter_map(|e| e.ok())
        .filter(|e| e.path().is_dir())
        .collect();
    if subs.len() == 1 && subs[0].path().join("app.toml").is_file() {
        return Ok(subs[0].path());
    }
    Err(ApiError::invalid(
        "The bundle has no app.toml at its top level.",
    ))
}

/// First path component below the app root = the version folder to delete.
fn version_root(root: &FsPath, code_dir: &FsPath) -> Option<PathBuf> {
    let rel = code_dir.strip_prefix(root).ok()?;
    Some(root.join(rel.components().next()?.as_os_str()))
}

fn choose_port(st: &State) -> ApiResult<u16> {
    let mut used = st.runner.used_ports();
    for a in db::all_apps(&st.db.lock().unwrap())? {
        used.insert(a.port);
    }
    (st.cfg.port_lo..=st.cfg.port_hi)
        .find(|p| !used.contains(p) && std::net::TcpListener::bind(("127.0.0.1", *p)).is_ok())
        .ok_or_else(|| ApiError::internal("no free app port"))
}

async fn health_ok(st: &State, port: u16, path: &str) -> bool {
    let req = axum::http::Request::get(format!("http://127.0.0.1:{port}{path}"))
        .body(Body::empty())
        .unwrap();
    match tokio::time::timeout(Duration::from_secs(2), st.http.request(req)).await {
        Ok(Ok(r)) => r.status() == StatusCode::OK,
        _ => false,
    }
}

/// Starts the process under `key` and waits for the health check. Err = log tail.
async fn start_and_check(
    st: &State,
    key: &str,
    name: &str,
    dir: &FsPath,
    m: &Manifest,
    port: u16,
) -> Result<(), String> {
    let spec = Spec {
        dir: dir.to_path_buf(),
        start: m.start.clone().unwrap_or_default(),
        port,
        base_path: format!("/a/{name}"),
        data_dir: st.cfg.app_data_dir(name),
        store: m.store.clone(),
        log: st.cfg.log_path(name),
    };
    st.runner.spawn(key, &spec).map_err(|e| e.to_string())?;
    let deadline = Instant::now() + Duration::from_secs(st.cfg.health_secs);
    let path = m.health.clone().unwrap_or_else(|| "/".into());
    loop {
        if !st.runner.is_alive(key) {
            break;
        }
        if health_ok(st, port, &path).await {
            return Ok(());
        }
        if Instant::now() > deadline {
            break;
        }
        tokio::time::sleep(Duration::from_millis(150)).await;
    }
    st.runner.stop(key).await;
    let log = std::fs::read_to_string(st.cfg.log_path(name)).unwrap_or_default();
    Err(util::tail(&log, 4000))
}

pub async fn deploy(
    st: &State,
    w: &Workspace,
    name: &str,
    bytes: Bytes,
    expires_at: Option<String>,
    new_token: bool,
) -> ApiResult<Value> {
    let _g = st.app_lock.lock().await;
    let existing = db::get_app(&st.db.lock().unwrap(), name)?;
    if existing.as_ref().is_some_and(|e| e.workspace != w.id) {
        return Err(ApiError::conflict("This app name is already taken."));
    }
    let root = st.cfg.app_root(name);
    let vroot = root.join(format!("v{}", util::rand_id(8)));
    let r = deploy_inner(
        st,
        w,
        name,
        bytes,
        expires_at,
        new_token,
        existing.as_ref(),
        &vroot,
    )
    .await;
    if r.is_err() {
        let _ = std::fs::remove_dir_all(&vroot);
        st.runner.stop(&format!("{name}~new")).await;
    }
    r
}

#[allow(clippy::too_many_arguments)]
async fn deploy_inner(
    st: &State,
    w: &Workspace,
    name: &str,
    bytes: Bytes,
    expires_at: Option<String>,
    new_token: bool,
    existing: Option<&AppRow>,
    vroot: &FsPath,
) -> ApiResult<Value> {
    let v2 = vroot.to_path_buf();
    let dir = tokio::task::spawn_blocking(move || extract(&bytes, &v2))
        .await
        .map_err(ApiError::internal)??;
    let m = parse_manifest(&dir)?;
    if m.name != name {
        return Err(ApiError::invalid(
            "The name in app.toml does not match the name in the URL.",
        ));
    }
    if m.public && !w.rights.public {
        return Err(ApiError::forbidden(
            "This workspace may not make public apps.",
        ));
    }
    let base = format!("/a/{name}");
    let data_dir = st.cfg.app_data_dir(name);
    let test_port = choose_port(st)?;
    // build
    let build = match m.stack.as_str() {
        "python" if dir.join("requirements.txt").is_file() => {
            Some("uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt")
        }
        "node" if dir.join("package.json").is_file() => Some("npm ci --omit=dev"),
        _ => None,
    };
    if let Some(b) = build {
        let (ok, out) = run_step(
            b,
            &dir,
            test_port,
            &base,
            &dir.join(".test-data"),
            &m.store,
            st.cfg.build_secs,
        )
        .await;
        if !ok {
            return Err(ApiError::new(
                422,
                "test_failed",
                "Installing the app's requirements failed. The old version is still running.",
            )
            .with_output(util::tail(&out, 4000)));
        }
    }
    // test
    if let Some(t) = &m.test {
        let td = dir.join(".test-data");
        let (ok, out) = run_step(t, &dir, test_port, &base, &td, &m.store, st.cfg.test_secs).await;
        let _ = std::fs::remove_dir_all(&td);
        if !ok {
            return Err(ApiError::new(
                422,
                "test_failed",
                "The app's test failed. The old version is still running.",
            )
            .with_output(util::tail(&out, 4000)));
        }
    }
    // start the new version next to the old one
    let mut port = 0;
    if m.stack != "static" {
        port = choose_port(st)?;
        if let Err(out) = start_and_check(st, &format!("{name}~new"), name, &dir, &m, port).await {
            return Err(ApiError::new(
                422,
                "health_failed",
                "The app did not answer its health check. The old version is still running.",
            )
            .with_output(out));
        }
    }
    std::fs::create_dir_all(&data_dir)?;
    // switch
    st.runner.stop(name).await;
    st.runner.rename(&format!("{name}~new"), name);
    let mut view_token = None;
    let mut hash = existing.and_then(|e| e.view_token_hash.clone());
    if !m.public && (hash.is_none() || new_token) {
        let t = util::rand_token("apv_", 16);
        hash = Some(util::sha256_hex(&t));
        view_token = Some(t);
    }
    if m.public {
        hash = None;
    }
    let row = AppRow {
        name: name.into(),
        workspace: w.id.clone(),
        about: m.about.clone(),
        stack: m.stack.clone(),
        store: m.store.clone(),
        public: m.public,
        health: m.health.clone().unwrap_or_default(),
        status: "running".into(),
        port,
        code_dir: dir.to_string_lossy().into(),
        view_token_hash: hash,
        expires_at: expires_at.clone(),
        updated_at: util::now(),
    };
    db::put_app(&st.db.lock().unwrap(), &row, &util::now())?;
    if let Some(old) = existing {
        let root = st.cfg.app_root(name);
        if let Some(v) = version_root(&root, FsPath::new(&old.code_dir)) {
            if v != vroot {
                let _ = std::fs::remove_dir_all(v);
            }
        }
    }
    Ok(json!({
        "name": name,
        "url": format!("{}/a/{}", st.cfg.public_url, name),
        "status": "running",
        "expires_at": expires_at,
        "view_token": view_token,
    }))
}

pub fn status_of(st: &State, a: &AppRow) -> &'static str {
    if a.status == "stopped" {
        "stopped"
    } else if a.stack == "static" || st.runner.is_alive(&a.name) {
        "running"
    } else {
        "failed"
    }
}

pub fn app_json(st: &State, a: &AppRow) -> Value {
    json!({
        "name": a.name, "stack": a.stack, "store": a.store, "public": a.public,
        "status": status_of(st, a), "url": format!("{}/a/{}", st.cfg.public_url, a.name),
        "expires_at": a.expires_at, "updated_at": a.updated_at,
    })
}

/// (re)starts the stored version of an app. Caller holds app_lock.
async fn start_existing(st: &State, a: &AppRow) -> &'static str {
    st.runner.stop(&a.name).await;
    let mut row = a.clone();
    row.status = "running".into();
    if a.stack != "static" {
        let dir = PathBuf::from(&a.code_dir);
        let ok = match (parse_manifest(&dir), choose_port(st)) {
            (Ok(m), Ok(port)) => {
                row.port = port;
                start_and_check(st, &a.name, &a.name, &dir, &m, port)
                    .await
                    .is_ok()
            }
            _ => false,
        };
        if !ok {
            let _ = db::put_app(&st.db.lock().unwrap(), &row, &util::now());
            return "failed";
        }
    }
    row.updated_at = util::now();
    let _ = db::put_app(&st.db.lock().unwrap(), &row, &util::now());
    "running"
}

pub async fn restart(st: &State, name: &str) -> ApiResult<Value> {
    let _g = st.app_lock.lock().await;
    let a = db::get_app(&st.db.lock().unwrap(), name)?
        .ok_or_else(|| ApiError::not_found("No such app."))?;
    let status = start_existing(st, &a).await;
    Ok(json!({"name": name, "status": status}))
}

pub async fn stop(st: &State, name: &str) -> ApiResult<Value> {
    let _g = st.app_lock.lock().await;
    let mut a = db::get_app(&st.db.lock().unwrap(), name)?
        .ok_or_else(|| ApiError::not_found("No such app."))?;
    st.runner.stop(name).await;
    a.status = "stopped".into();
    db::put_app(&st.db.lock().unwrap(), &a, &util::now())?;
    Ok(json!({"name": name, "status": "stopped"}))
}

/// Stops and deletes an app with its code and data. Caller holds app_lock.
pub async fn remove(st: &State, name: &str) {
    st.runner.stop(name).await;
    let _ = std::fs::remove_dir_all(st.cfg.app_root(name));
    let _ = std::fs::remove_file(st.cfg.log_path(name));
    let _ = db::delete_app(&st.db.lock().unwrap(), name);
}

pub async fn resume_all(st: &State) {
    let apps = db::all_apps(&st.db.lock().unwrap()).unwrap_or_default();
    for a in apps
        .into_iter()
        .filter(|a| a.status == "running" && a.stack != "static")
    {
        let _g = st.app_lock.lock().await;
        start_existing(st, &a).await;
    }
}

// ---- public /a/<name>/...

fn text(status: u16, body: &str) -> Response {
    (
        StatusCode::from_u16(status).unwrap(),
        [(header::CONTENT_TYPE, "text/plain; charset=utf-8")],
        body.to_string(),
    )
        .into_response()
}

fn private_page() -> Response {
    let mut r = (
        StatusCode::UNAUTHORIZED,
        [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
        crate::web::PRIVATE_HTML,
    )
        .into_response();
    r.headers_mut().insert(
        "content-security-policy",
        HeaderValue::from_static(crate::files::CSP),
    );
    r
}

pub async fn serve_root(St(st): St<State>, Path(name): Path<String>, req: Request) -> Response {
    handle(st, name, String::new(), req).await
}

pub async fn serve(
    St(st): St<State>,
    Path((name, rest)): Path<(String, String)>,
    req: Request,
) -> Response {
    handle(st, name, rest, req).await
}

fn cookie_name(name: &str) -> String {
    format!("orch_app_{name}")
}

fn cookie_value(req: &Request, cname: &str) -> Option<String> {
    for h in req.headers().get_all(header::COOKIE) {
        for part in h.to_str().unwrap_or("").split(';') {
            if let Some((k, v)) = part.trim().split_once('=') {
                if k == cname {
                    return Some(v.to_string());
                }
            }
        }
    }
    None
}

async fn handle(st: State, name: String, rest: String, req: Request) -> Response {
    let app = match db::get_app(&st.db.lock().unwrap(), &name) {
        Ok(Some(a)) => a,
        _ => return text(404, "No such app."),
    };
    let query = req.uri().query().unwrap_or("").to_string();
    if !req.uri().path().ends_with('/') && rest.is_empty() {
        let loc = format!(
            "/a/{name}/{}",
            if query.is_empty() {
                String::new()
            } else {
                format!("?{query}")
            }
        );
        return (StatusCode::PERMANENT_REDIRECT, [(header::LOCATION, loc)]).into_response();
    }
    if app
        .expires_at
        .as_deref()
        .is_some_and(|e| e <= util::now().as_str())
    {
        return text(410, "This app has expired.");
    }
    if !app.public {
        let ok = |t: &str| {
            app.view_token_hash
                .as_deref()
                .is_some_and(|h| util::ct_eq(&util::sha256_hex(t), h))
        };
        let qtoken = query
            .split('&')
            .find_map(|p| p.strip_prefix("token="))
            .map(str::to_string);
        if let Some(t) = qtoken {
            if !ok(&t) {
                return private_page();
            }
            let rest_q: Vec<&str> = query
                .split('&')
                .filter(|p| !p.starts_with("token=") && !p.is_empty())
                .collect();
            let loc = format!(
                "/a/{name}/{rest}{}",
                if rest_q.is_empty() {
                    String::new()
                } else {
                    format!("?{}", rest_q.join("&"))
                }
            );
            let secure = if st.cfg.public_url.starts_with("https") {
                "; Secure"
            } else {
                ""
            };
            let cookie = format!(
                "{}={t}; HttpOnly; SameSite=Lax; Path=/a/{name}/{secure}",
                cookie_name(&name)
            );
            return (
                StatusCode::FOUND,
                [(header::LOCATION, loc), (header::SET_COOKIE, cookie)],
            )
                .into_response();
        }
        match cookie_value(&req, &cookie_name(&name)) {
            Some(c) if ok(&c) => {}
            _ => return private_page(),
        }
    }
    if app.status == "stopped" {
        return text(503, "This app is stopped.");
    }
    if app.stack == "static" {
        return serve_static(&app, &rest);
    }
    proxy(&st, &app, &rest, &query, req).await
}

async fn proxy(st: &State, app: &AppRow, rest: &str, query: &str, req: Request) -> Response {
    if !st.runner.is_alive(&app.name) {
        return text(503, "This app is not running.");
    }
    let uri = format!(
        "http://127.0.0.1:{}/{}{}",
        app.port,
        rest,
        if query.is_empty() {
            String::new()
        } else {
            format!("?{query}")
        }
    );
    let (parts, body) = req.into_parts();
    let mut b = axum::http::Request::builder().method(parts.method).uri(uri);
    for (k, v) in parts.headers.iter() {
        let n = k.as_str();
        if k == header::HOST
            || k == header::COOKIE
            || k == header::AUTHORIZATION
            || n.starts_with("x-orch-")
        {
            continue;
        }
        b = b.header(k, v);
    }
    // keep the app's own cookies; drop orch ones (private-app tokens, admin)
    let others: Vec<String> = parts
        .headers
        .get_all(header::COOKIE)
        .iter()
        .flat_map(|h| {
            h.to_str()
                .unwrap_or("")
                .split(';')
                .map(|s| s.trim().to_string())
                .collect::<Vec<_>>()
        })
        .filter(|c| !c.is_empty() && !c.starts_with("orch_app_") && !c.starts_with("orch_admin="))
        .collect();
    if !others.is_empty() {
        b = b.header(header::COOKIE, others.join("; "));
    }
    let Ok(r) = b.body(body) else {
        return text(400, "Bad request.");
    };
    match st.http.request(r).await {
        Ok(resp) => {
            let mut resp = resp.map(Body::new);
            resp.headers_mut().remove("service-worker-allowed");
            resp
        }
        Err(_) => text(502, "The app did not answer."),
    }
}

fn content_type(p: &FsPath) -> &'static str {
    match p.extension().and_then(|e| e.to_str()).unwrap_or("") {
        "html" | "htm" | "md" => "text/html; charset=utf-8",
        "css" => "text/css; charset=utf-8",
        "js" | "mjs" => "text/javascript; charset=utf-8",
        "json" => "application/json",
        "txt" | "csv" => "text/plain; charset=utf-8",
        "svg" => "image/svg+xml",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "webp" => "image/webp",
        "ico" => "image/x-icon",
        "pdf" => "application/pdf",
        "woff2" => "font/woff2",
        "wasm" => "application/wasm",
        _ => "application/octet-stream",
    }
}

fn serve_static(app: &AppRow, rest: &str) -> Response {
    let root = PathBuf::from(&app.code_dir);
    let mut p = root.clone();
    for c in rest.split('/').filter(|c| !c.is_empty()) {
        if c == ".." || c.starts_with('.') {
            return text(404, "Not found.");
        }
        p.push(c);
    }
    if p.is_dir() {
        let h = p.join("index.html");
        p = if h.is_file() { h } else { p.join("index.md") };
    }
    if p == root.join("app.toml") || !p.is_file() {
        return text(404, "Not found.");
    }
    let Ok(bytes) = std::fs::read(&p) else {
        return text(404, "Not found.");
    };
    if p.extension().is_some_and(|e| e == "md") {
        let html = crate::web::markdown_page(&app.name, &String::from_utf8_lossy(&bytes));
        return ([(header::CONTENT_TYPE, "text/html; charset=utf-8")], html).into_response();
    }
    (
        [
            (header::CONTENT_TYPE, content_type(&p)),
            (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
        ],
        bytes,
    )
        .into_response()
}
