//! Apps: deploy a bundle, run it as a child process (runner.rs), serve and proxy /a/<name>/.
use crate::db::{self, AppRow, Workspace};
use crate::err::{ApiError, ApiResult};
use crate::runner::{container_mode, run_step, Spec, StepCtx};
use crate::{util, State};
use axum::body::{Body, Bytes};
use axum::extract::{Path, Request, State as St};
use axum::http::{header, StatusCode};
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
    let docker_ok = crate::runner::docker_apps_enabled();
    check_manifest(&m, dir, docker_ok)?;
    Ok(m)
}

/// Rules for app.toml; `docker_ok` = container mode AND ORCH_PUBLISH_DOCKER_APPS=1.
fn check_manifest(m: &Manifest, dir: &FsPath, docker_ok: bool) -> ApiResult<()> {
    let bad = |s: &str| Err(ApiError::invalid(format!("app.toml: {s}")));
    if !util::valid_app_name(&m.name) {
        return bad("name must be 2-40 characters: a-z, 0-9 and -, starting and ending with a letter or digit.");
    }
    if !["static", "python", "node", "docker"].contains(&m.stack.as_str()) {
        return bad("stack must be static, python, node or docker.");
    }
    if m.stack == "docker" {
        if !docker_ok {
            return bad("This server doesn't run apps with their own Dockerfile.");
        }
        let Ok(text) = std::fs::read_to_string(dir.join("Dockerfile")) else {
            return bad("docker apps need a Dockerfile at the top of the bundle.");
        };
        if let Err(e) = crate::runner::check_dockerfile(&text) {
            return bad(e);
        }
    }
    if !["none", "json", "markdown", "sqlite"].contains(&m.store.as_str()) {
        return bad("store must be none, json, markdown or sqlite.");
    }
    if m.stack == "static" {
        if m.start.is_some() || m.health.is_some() {
            return bad("static apps must not have start or health.");
        }
    } else if m.stack == "docker" {
        if m.health.as_deref().unwrap_or("").is_empty() {
            return bad("docker apps need health.");
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
    Ok(())
}

/// The node install step: `npm ci` only with a lockfile (it refuses without one), else `npm install`.
fn node_install(dir: &FsPath) -> &'static str {
    if dir.join("package-lock.json").is_file() || dir.join("npm-shrinkwrap.json").is_file() {
        "npm ci --omit=dev"
    } else {
        "npm install --omit=dev --no-audit --no-fund"
    }
}

/// Scratch data folder of the build/test steps of one deploy: next to the version folders, made by the
/// server, never inside the code the build can write to.
fn step_dir(st: &State, name: &str, vroot: &FsPath) -> PathBuf {
    let v = vroot
        .file_name()
        .map(|f| f.to_string_lossy().into_owned())
        .unwrap_or_default();
    st.cfg.app_root(name).join(format!(".step-{v}"))
}

/// Deletes a folder; in container mode the app's uid gets its rights back first.
async fn rm_tree(p: &FsPath) {
    // a link planted by app code is only unlinked, never followed; folders outside our roots are skipped
    if std::fs::symlink_metadata(p).is_ok_and(|m| m.file_type().is_symlink()) {
        let _ = std::fs::remove_file(p);
        return;
    }
    if !p.exists() || !crate::runner::guard_dir(p) {
        return;
    }
    if container_mode() {
        crate::runner::make_deletable(p).await;
    }
    let _ = std::fs::remove_dir_all(p);
}

/// Version folder name of the code in `code_dir` (images are tagged `orch-app-<name>:<vdir>-<random>`).
fn vdir_of(st: &State, name: &str, code_dir: &FsPath) -> Option<String> {
    let v = version_root(&st.cfg.app_root(name), code_dir)?;
    Some(v.file_name()?.to_string_lossy().into_owned())
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
    if std::env::var("ORCH_PUBLISH_SANDBOX").is_ok_and(|v| v == "systemd" || v == "container") {
        crate::runner::prep_perms(dir);
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
    used.extend(st.sleep.reserved_ports.lock().unwrap().iter());
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
    poll_ms: u64,
) -> Result<(), String> {
    let image = if m.stack == "docker" {
        let v = vdir_of(st, name, dir).ok_or("no version folder")?;
        Some(
            crate::runner::ensure_image(name, &v, dir, st.cfg.build_secs)
                .await
                .ok_or("The app's image could not be built.")?,
        )
    } else {
        None
    };
    let spec = Spec {
        stack: m.stack.clone(),
        image,
        dir: dir.to_path_buf(),
        start: m.start.clone().unwrap_or_default(),
        port,
        base_path: format!("/a/{name}"),
        data_dir: st.cfg.app_data_dir(name),
        store: m.store.clone(),
        log: st.cfg.log_path(name),
    };
    st.runner
        .spawn(key, &spec)
        .await
        .map_err(|e| e.to_string())?;
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
        tokio::time::sleep(Duration::from_millis(poll_ms)).await;
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
        if container_mode() {
            if let Some(v) = vdir_of(st, name, &vroot) {
                crate::runner::remove_images(name, Some(&v)).await;
            }
        }
        st.runner.stop(&format!("{name}~new")).await;
        rm_tree(&step_dir(st, name, &vroot)).await;
        rm_tree(&vroot).await;
        if existing.is_none() {
            // a failed first deploy leaves no empty app folder behind (fails harmlessly if not empty)
            let _ = std::fs::remove_dir(&root);
        }
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
    let container = container_mode();
    let build = match m.stack.as_str() {
        "python" if dir.join("requirements.txt").is_file() => Some(if container {
            "python -m venv .venv && .venv/bin/pip install --no-cache-dir -r requirements.txt"
        } else {
            "uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt"
        }),
        // `npm ci` needs a lockfile; the node template (and many small apps) ship package.json only
        "node" if dir.join("package.json").is_file() => Some(node_install(&dir)),
        _ => None,
    };
    let mut image = None;
    if m.stack == "docker" {
        let v = vdir_of(st, name, &dir).ok_or_else(|| ApiError::internal("no version folder"))?;
        let tag = crate::runner::new_image_tag(name, &v);
        let (ok, out) = crate::runner::build_image(&tag, &dir, st.cfg.build_secs).await;
        image = Some(tag);
        if !ok {
            return Err(ApiError::new(
                422,
                "test_failed",
                "Building the app's image failed. The old version is still running.",
            )
            .with_output(util::tail(&out, 4000)));
        }
    }
    if let Some(b) = build {
        let bd = step_dir(st, name, vroot);
        let (ok, out) = run_step(
            b,
            &dir,
            &StepCtx {
                app: name,
                stack: &m.stack,
                image: None,
                writable: true,
                port: test_port,
                base_path: &base,
                data_dir: &bd,
                store: &m.store,
                secs: st.cfg.build_secs,
            },
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
        let td = step_dir(st, name, vroot);
        let ctx = StepCtx {
            app: name,
            stack: &m.stack,
            image: image.as_deref(),
            writable: false,
            port: test_port,
            base_path: &base,
            data_dir: &td,
            store: &m.store,
            secs: st.cfg.test_secs,
        };
        let (ok, out) = run_step(t, &dir, &ctx).await;
        if !ok {
            return Err(ApiError::new(
                422,
                "test_failed",
                "The app's test failed. The old version is still running.",
            )
            .with_output(util::tail(&out, 4000)));
        }
    }
    rm_tree(&step_dir(st, name, vroot)).await;
    // start the new version next to the old one
    let mut port = 0;
    if m.stack != "static" {
        port = choose_port(st)?;
        if let Err(out) =
            start_and_check(st, &format!("{name}~new"), name, &dir, &m, port, 150).await
        {
            return Err(ApiError::new(
                422,
                "health_failed",
                if container_mode() {
                    "The app did not answer its health check. Does the app listen on $HOST (not 127.0.0.1)? The old version is still running."
                } else {
                    "The app did not answer its health check. The old version is still running."
                },
            )
            .with_output(out));
        }
    }
    std::fs::create_dir_all(&data_dir)?;
    // switch
    st.runner.stop(name).await;
    st.runner.rename(&format!("{name}~new"), name);
    st.sleep.sleeping.lock().unwrap().remove(name);
    st.sleep.cooldown.lock().unwrap().remove(name);
    touch(st, name);
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
                if container_mode() && old.stack == "docker" {
                    if let Some(v) = vdir_of(st, name, FsPath::new(&old.code_dir)) {
                        crate::runner::remove_images(name, Some(&v)).await;
                    }
                }
                rm_tree(&v).await;
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
    } else if a.stack == "static" || st.runner.is_alive(&a.name) || is_sleeping(st, &a.name) {
        "running"
    } else {
        "failed"
    }
}

/// Stopped for idleness: the app is available, it starts on the next request.
pub fn is_sleeping(st: &State, name: &str) -> bool {
    st.sleep.sleeping.lock().unwrap().contains(name)
}

/// Static apps are always awake; others while their process runs.
fn is_awake(st: &State, a: &AppRow) -> bool {
    a.status != "stopped" && (a.stack == "static" || st.runner.is_alive(&a.name))
}

pub fn app_json(st: &State, a: &AppRow) -> Value {
    json!({
        "name": a.name, "stack": a.stack, "store": a.store, "public": a.public,
        "status": status_of(st, a), "awake": is_awake(st, a), "url": format!("{}/a/{}", st.cfg.public_url, a.name),
        "expires_at": a.expires_at, "updated_at": a.updated_at,
    })
}

/// (re)starts the stored version of an app. Caller holds app_lock.
async fn start_existing(st: &State, a: &AppRow) -> &'static str {
    st.runner.stop(&a.name).await;
    st.sleep.sleeping.lock().unwrap().remove(&a.name);
    st.sleep.cooldown.lock().unwrap().remove(&a.name);
    touch(st, &a.name);
    if a.stack == "docker" && !crate::runner::docker_apps_enabled() {
        // keep the reason where the owner looks: the app's log
        let _ = std::fs::write(
            st.cfg.log_path(&a.name),
            "This server doesn't run apps with their own Dockerfile.\n",
        );
        let mut row = a.clone();
        row.status = "running".into();
        let _ = db::put_app(&st.db.lock().unwrap(), &row, &util::now());
        return "failed";
    }
    let mut row = a.clone();
    row.status = "running".into();
    if a.stack != "static" {
        let dir = PathBuf::from(&a.code_dir);
        let ok = match (parse_manifest(&dir), choose_port(st)) {
            (Ok(m), Ok(port)) => {
                row.port = port;
                start_and_check(st, &a.name, &a.name, &dir, &m, port, 150)
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
    st.sleep.sleeping.lock().unwrap().remove(name);
    a.status = "stopped".into();
    db::put_app(&st.db.lock().unwrap(), &a, &util::now())?;
    Ok(json!({"name": name, "status": "stopped"}))
}

/// Stops and deletes an app with its code and data. Caller holds app_lock.
pub async fn remove(st: &State, name: &str) {
    // the name feeds a path: only the plain charset (routes also look the app up first)
    if name.is_empty()
        || !name
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
    {
        return;
    }
    st.runner.stop(name).await;
    st.sleep.sleeping.lock().unwrap().remove(name);
    st.sleep.activity.lock().unwrap().remove(name);
    st.sleep.cooldown.lock().unwrap().remove(name);
    st.sleep.wake.lock().unwrap().remove(name);
    if container_mode() {
        crate::runner::remove_images(name, None).await;
    }
    rm_tree(&st.cfg.app_root(name)).await;
    let _ = std::fs::remove_file(st.cfg.log_path(name));
    let _ = db::delete_app(&st.db.lock().unwrap(), name);
}

/// Container mode, before the listeners start: removes leftover step containers and containers of
/// apps that are not in the database (this instance only).
pub async fn startup_sweep(st: &State) {
    if container_mode() {
        let apps = db::all_apps(&st.db.lock().unwrap()).unwrap_or_default();
        let known = apps.iter().map(|a| a.name.clone()).collect();
        crate::runner::sweep_containers(&known).await;
    }
}

pub async fn resume_all(st: &State) {
    let apps = db::all_apps(&st.db.lock().unwrap()).unwrap_or_default();
    for a in apps
        .into_iter()
        .filter(|a| a.status == "running" && a.stack != "static")
    {
        if st.cfg.idle_secs > 0 && (a.stack != "docker" || crate::runner::docker_apps_enabled()) {
            // scale to zero: apps start on their first request (saves memory after a restart)
            st.sleep.sleeping.lock().unwrap().insert(a.name.clone());
            continue;
        }
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
    crate::web::notice(
        401,
        "lock",
        "This app is private",
        "Ask the owner for a new link.",
        false,
    )
}

fn paused_page() -> Response {
    crate::web::notice(
        503,
        "offline",
        "This app is paused",
        "The owner stopped it for now. Ask the owner to start it again.",
        false,
    )
}

fn offline_page() -> Response {
    crate::web::notice(
        503,
        "offline",
        "This app is offline",
        "It is not running right now. Try again in a moment, or ask the owner to start it.",
        true,
    )
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
        _ => {
            return crate::web::notice(
                404,
                "link",
                "This app isn\u{2019}t available",
                "Check the link or ask the sender for a new one.",
                false,
            )
        }
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
        return crate::web::notice(
            410,
            "clock",
            "This app has expired",
            "It is no longer available. Ask the owner to share it again.",
            false,
        );
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
        return paused_page();
    }
    if app.stack == "static" {
        return serve_static(&app, &rest).await;
    }
    proxy(&st, &app, &rest, &query, req).await
}

const HOP_BY_HOP: [&str; 8] = [
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
];

async fn proxy(st: &State, app: &AppRow, rest: &str, query: &str, req: Request) -> Response {
    // WebSockets are not forwarded (the proxy speaks plain HTTP request/response)
    if req.headers().contains_key(header::UPGRADE) {
        return crate::web::notice(
            501,
            "offline",
            "This app can\u{2019}t use WebSockets here.",
            "Plain page loads and live updates over normal requests work.",
            false,
        );
    }
    // count the request first: an app with requests in flight never sleeps (only where apps sleep)
    let guard = (st.cfg.idle_secs > 0).then(|| InFlight::new(st, &app.name));
    let woken;
    let app = if st.cfg.idle_secs > 0 && is_sleeping(st, &app.name) {
        let fresh = match wake(st, &app.name).await {
            Ok(a) => a,
            Err(r) => return *r,
        };
        // the caller was authorized for the OLD row: refuse if access changed meanwhile
        if let Some(r) = access_changed(app, &fresh) {
            return r;
        }
        woken = fresh;
        &woken
    } else {
        app
    };
    // route to the port of THIS app's live process, not the port in a row read before (stale after a
    // redeploy or a wake): a request can never reach another app's process
    let Some(port) = st.runner.live_port(&app.name) else {
        return offline_page();
    };
    let uri = format!(
        "http://127.0.0.1:{}/{}{}",
        port,
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
            || HOP_BY_HOP.contains(&n)
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
            // the request stays in flight until the body is done (SSE, long downloads)
            match guard {
                Some(g) => resp.map(|b| Body::new(Guarded { inner: b, _g: g })),
                None => resp,
            }
        }
        Err(_) => offline_page(),
    }
}

/// Marks an app as used now.
fn touch(st: &State, name: &str) {
    let mut g = st.sleep.activity.lock().unwrap();
    g.entry(name.to_string()).or_insert((Instant::now(), 0)).0 = Instant::now();
}

/// One request in flight to an app; counts down on drop (errors and disconnects too).
struct InFlight {
    st: State,
    name: String,
}

impl InFlight {
    fn new(st: &State, name: &str) -> Self {
        let mut g = st.sleep.activity.lock().unwrap();
        let e = g.entry(name.to_string()).or_insert((Instant::now(), 0));
        e.0 = Instant::now();
        e.1 += 1;
        InFlight {
            st: st.clone(),
            name: name.to_string(),
        }
    }
}

impl Drop for InFlight {
    fn drop(&mut self) {
        let mut g = self.st.sleep.activity.lock().unwrap();
        if let Some(e) = g.get_mut(&self.name) {
            e.0 = Instant::now();
            e.1 = e.1.saturating_sub(1);
        }
    }
}

/// Response body that holds the in-flight guard until it is dropped.
struct Guarded {
    inner: Body,
    _g: InFlight,
}

impl http_body::Body for Guarded {
    type Data = Bytes;
    type Error = axum::Error;
    fn poll_frame(
        mut self: std::pin::Pin<&mut Self>,
        cx: &mut std::task::Context<'_>,
    ) -> std::task::Poll<Option<Result<http_body::Frame<Bytes>, axum::Error>>> {
        std::pin::Pin::new(&mut self.inner).poll_frame(cx)
    }
    fn is_end_stream(&self) -> bool {
        self.inner.is_end_stream()
    }
    fn size_hint(&self) -> http_body::SizeHint {
        self.inner.size_hint()
    }
}

/// Stops apps that got no request for `idle_secs` (container mode). Runs every `sleep_sweep_secs`; tests call it.
pub async fn sleep_sweep(st: &State) {
    let idle = Duration::from_secs(st.cfg.idle_secs);
    if st.cfg.idle_secs == 0 {
        return;
    }
    let apps = db::all_apps(&st.db.lock().unwrap()).unwrap_or_default();
    for a in apps
        .into_iter()
        .filter(|a| a.status == "running" && a.stack != "static")
    {
        let taken;
        let due = |st: &State| -> bool {
            if !st.runner.is_alive(&a.name) {
                return false;
            }
            let mut g = st.sleep.activity.lock().unwrap();
            let e = g.entry(a.name.clone()).or_insert((Instant::now(), 0));
            e.1 == 0 && e.0.elapsed() > idle
        };
        if !due(st) {
            continue;
        }
        {
            let _g = st.app_lock.lock().await;
            // re-check under the lock: stopped, deleted or redeployed meanwhile
            let found = db::get_app(&st.db.lock().unwrap(), &a.name);
            if !matches!(found, Ok(Some(r)) if r.status == "running" && r.stack != "static") {
                continue;
            }
            // decide and mark sleeping in one step: a request that arrives after this wakes the app
            let act = st.sleep.activity.lock().unwrap();
            let Some(e) = act.get(&a.name) else { continue };
            if e.1 != 0 || e.0.elapsed() <= idle || !st.runner.is_alive(&a.name) {
                continue;
            }
            st.sleep.sleeping.lock().unwrap().insert(a.name.clone());
            // take the process out under the locks; the slow stop below hits exactly this handle,
            // never "whatever runs under the name" (a request may have woken a new one by then)
            taken = st.runner.take(&a.name);
        }
        if let Some(p) = taken {
            st.runner.stop_taken(p).await;
        }
        tracing::info!("app {} sleeps (idle)", a.name);
    }
}

fn notice_gone() -> Response {
    crate::web::notice(
        404,
        "link",
        "This app isn\u{2019}t available",
        "Check the link or ask the sender for a new one.",
        false,
    )
}

/// Compares what the request was authorized against with the row now: None = same access.
fn access_changed(old: &AppRow, new: &AppRow) -> Option<Response> {
    if new.status == "stopped" {
        return Some(paused_page());
    }
    if new
        .expires_at
        .as_deref()
        .is_some_and(|e| e <= util::now().as_str())
    {
        return Some(crate::web::notice(
            410,
            "clock",
            "This app has expired",
            "It is no longer available. Ask the owner to share it again.",
            false,
        ));
    }
    if new.workspace != old.workspace
        || new.public != old.public
        || new.view_token_hash != old.view_token_hash
        || new.stack != old.stack
    {
        return Some(private_page());
    }
    None
}

const WAKE_COOLDOWN: Duration = Duration::from_secs(30);

fn wake_503() -> Box<Response> {
    Box::new(crate::web::notice(
        503,
        "offline",
        "This app could not start",
        "Try again in a moment.",
        true,
    ))
}

/// Frees a reserved port when dropped.
struct Reserved {
    st: State,
    port: Option<u16>,
}

impl Drop for Reserved {
    fn drop(&mut self) {
        if let Some(p) = self.port {
            self.st.sleep.reserved_ports.lock().unwrap().remove(&p);
        }
    }
}

/// Starts a sleeping app for a request. One wake per app at a time (others wait for it), at most 4 wakes at once.
/// The global app_lock is only taken briefly (re-check before, commit after), never during the start.
async fn wake(st: &State, name: &str) -> Result<AppRow, Box<Response>> {
    let lock = st
        .sleep
        .wake
        .lock()
        .unwrap()
        .entry(name.to_string())
        .or_default()
        .clone();
    let _w = lock.lock().await;
    let t0 = Instant::now();
    // a failed wake is not retried for 30 s
    if st
        .sleep
        .cooldown
        .lock()
        .unwrap()
        .get(name)
        .is_some_and(|t| t.elapsed() < WAKE_COOLDOWN)
    {
        return Err(wake_503());
    }
    let _slot = st.sleep.wake_slots.acquire().await;
    // a dead leftover entry of an earlier run goes first, outside the global lock (a live process is never touched)
    if is_sleeping(st, name) && !st.runner.is_alive(name) {
        st.runner.stop(name).await;
    }
    let (row, m, port, _reserved) = {
        let _g = st.app_lock.lock().await;
        let found = db::get_app(&st.db.lock().unwrap(), name);
        let row = match found {
            Ok(Some(r)) => r,
            _ => return Err(Box::new(notice_gone())),
        };
        if row.status == "stopped" {
            return Err(Box::new(paused_page()));
        }
        if !is_sleeping(st, name) {
            return Ok(row); // woken by an earlier request, or restarted
        }
        if row.stack == "docker" && !crate::runner::docker_apps_enabled() {
            return Err(wake_fail(st, name, "docker apps are disabled".into()));
        }
        let dir = PathBuf::from(&row.code_dir);
        let Ok(m) = parse_manifest(&dir) else {
            return Err(wake_fail(st, name, "bad manifest".into()));
        };
        let mut reserved = Reserved {
            st: st.clone(),
            port: None,
        };
        // the stored port is reserved by the DB row (choose_port skips it): reuse it
        let port = if row.port != 0 && std::net::TcpListener::bind(("127.0.0.1", row.port)).is_ok()
        {
            row.port
        } else {
            match choose_port(st) {
                Ok(p) => {
                    st.sleep.reserved_ports.lock().unwrap().insert(p);
                    reserved.port = Some(p);
                    p
                }
                Err(_) => return Err(wake_fail(st, name, "no free app port".into())),
            }
        };
        (row, m, port, reserved)
    };
    let dir = PathBuf::from(&row.code_dir);
    let key = format!("{name}~wake");
    if let Err(log) = start_and_check(st, &key, name, &dir, &m, port, 25).await {
        return Err(wake_fail(st, name, log));
    }
    // commit: still the same app, still asleep, not stopped/deleted/redeployed meanwhile
    let _g = st.app_lock.lock().await;
    let found = db::get_app(&st.db.lock().unwrap(), name);
    let mut cur = match found {
        Ok(Some(r)) if r.code_dir == row.code_dir && is_sleeping(st, name) => r,
        Ok(None) => {
            st.runner.stop(&key).await;
            return Err(Box::new(notice_gone()));
        }
        Ok(Some(r)) if r.status == "stopped" => {
            st.runner.stop(&key).await;
            return Err(Box::new(paused_page()));
        }
        // restarted or redeployed by someone else meanwhile: serve theirs if it runs
        Ok(Some(r)) if r.status == "running" && st.runner.is_alive(name) => {
            st.runner.stop(&key).await;
            return Ok(r);
        }
        _ => {
            st.runner.stop(&key).await;
            return Err(wake_503());
        }
    };
    st.runner.rename(&key, name);
    if cur.port != port {
        // fallback port (the stored one was not free); `_reserved` is released after this
        cur.port = port;
        let _ = db::put_app(&st.db.lock().unwrap(), &cur, &cur.updated_at.clone());
    }
    st.sleep.sleeping.lock().unwrap().remove(name);
    st.sleep.cooldown.lock().unwrap().remove(name);
    tracing::info!("app {name} woke in {} ms", t0.elapsed().as_millis());
    Ok(cur)
}

/// Failed wake: log once, start the cooldown. The app stays asleep (not failed).
fn wake_fail(st: &State, name: &str, why: String) -> Box<Response> {
    // the app's output is data: logged as an escaped field, never as raw lines
    tracing::warn!(app = %name, log = ?util::tail(&why, 1500), "app could not wake (no new try for 30 s)");
    st.sleep
        .cooldown
        .lock()
        .unwrap()
        .insert(name.to_string(), Instant::now());
    wake_503()
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

async fn serve_static(app: &AppRow, rest: &str) -> Response {
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
    if p.extension().is_some_and(|e| e == "md") {
        let Ok(bytes) = std::fs::read(&p) else {
            return text(404, "Not found.");
        };
        let html = crate::web::markdown_page(&app.name, &String::from_utf8_lossy(&bytes));
        return ([(header::CONTENT_TYPE, "text/html; charset=utf-8")], html).into_response();
    }
    if p.extension().is_some_and(|e| e == "html" || e == "htm") {
        // small pages: add a default <title> / lang when missing (13B); big ones stream as-is
        if std::fs::metadata(&p).is_ok_and(|m| m.len() <= 4 << 20) {
            let Ok(bytes) = std::fs::read(&p) else {
                return text(404, "Not found.");
            };
            let html = crate::util::with_default_head(&bytes, &app.name);
            return (
                [
                    (header::CONTENT_TYPE, "text/html; charset=utf-8"),
                    (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
                ],
                html,
            )
                .into_response();
        }
    }
    let Ok(file) = tokio::fs::File::open(&p).await else {
        return text(404, "Not found.");
    };
    let len = file.metadata().await.map(|m| m.len()).ok();
    let mut r = (
        [
            (header::CONTENT_TYPE, content_type(&p)),
            (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
        ],
        axum::body::Body::from_stream(tokio_util::io::ReaderStream::new(file)),
    )
        .into_response();
    if let Some(n) = len {
        r.headers_mut().insert(header::CONTENT_LENGTH, n.into());
    }
    r
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn node_install_uses_ci_only_with_a_lockfile() {
        let d = std::env::temp_dir().join(format!("orch-node-install-{}", std::process::id()));
        std::fs::create_dir_all(&d).unwrap();
        std::fs::write(d.join("package.json"), "{}").unwrap();
        assert_eq!(
            node_install(&d),
            "npm install --omit=dev --no-audit --no-fund"
        );
        std::fs::write(d.join("package-lock.json"), "{}").unwrap();
        assert_eq!(node_install(&d), "npm ci --omit=dev");
        let _ = std::fs::remove_dir_all(&d);
    }

    fn manifest(stack: &str) -> Manifest {
        Manifest {
            name: "demo".into(),
            about: String::new(),
            stack: stack.into(),
            start: None,
            health: Some("/health".into()),
            test: None,
            store: "none".into(),
            public: false,
        }
    }

    #[test]
    fn docker_stack_needs_container_mode_and_a_dockerfile() {
        let d = tempfile::tempdir().unwrap();
        let m = manifest("docker");
        let e = check_manifest(&m, d.path(), false).unwrap_err();
        assert!(
            format!("{e:?}").contains("This server doesn't run apps with their own Dockerfile.")
        );
        assert!(check_manifest(&m, d.path(), true).is_err(), "no Dockerfile");
        std::fs::write(d.path().join("Dockerfile"), "FROM scratch\n").unwrap();
        assert!(check_manifest(&m, d.path(), true).is_ok());
        let mut no_health = manifest("docker");
        no_health.health = None;
        assert!(check_manifest(&no_health, d.path(), true).is_err());
        // python/node still need start
        assert!(check_manifest(&manifest("python"), d.path(), false).is_err());
    }

    #[test]
    fn dockerfile_with_syntax_directive_is_refused() {
        let d = tempfile::tempdir().unwrap();
        std::fs::write(
            d.path().join("Dockerfile"),
            "# syntax=evil/x\nFROM scratch\n",
        )
        .unwrap();
        assert!(check_manifest(&manifest("docker"), d.path(), true).is_err());
    }
}
