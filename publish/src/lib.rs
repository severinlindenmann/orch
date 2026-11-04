//! orch-publish: encrypted file links (/f/) and small apps (/a/), see docs/publish.md.
pub mod admin;
pub mod api;
pub mod apps;
pub mod config;
pub mod db;
pub mod err;
pub mod files;
pub mod runner;
pub mod sweep;
pub mod util;
pub mod web;

use axum::body::Body;
use axum::routing::{any, get, post};
use axum::Router;
use std::sync::{Arc, Mutex};

pub use config::Config;

pub type Http =
    hyper_util::client::legacy::Client<hyper_util::client::legacy::connect::HttpConnector, Body>;

pub struct Inner {
    pub cfg: Config,
    pub db: Mutex<rusqlite::Connection>,
    pub runner: runner::Runner,
    /// deploy, restart, stop and delete of apps run one at a time
    pub app_lock: tokio::sync::Mutex<()>,
    pub http: Http,
}

pub type State = Arc<Inner>;

/// Opens the database and folders under `cfg.data_dir`.
pub fn new_state(cfg: Config) -> std::io::Result<State> {
    for d in ["files", "logs"] {
        std::fs::create_dir_all(cfg.data_dir.join(d))?;
    }
    std::fs::create_dir_all(&cfg.apps_dir)?;
    let conn = db::open(&cfg.data_dir.join("publish.db")).map_err(std::io::Error::other)?;
    let http = hyper_util::client::legacy::Client::builder(hyper_util::rt::TokioExecutor::new())
        .build_http();
    Ok(Arc::new(Inner {
        cfg,
        db: Mutex::new(conn),
        runner: runner::Runner::default(),
        app_lock: tokio::sync::Mutex::new(()),
        http,
    }))
}

/// Public listener: workspace API, /f/, /a/, onboarding scripts, /health.
pub fn public_router(st: State) -> Router {
    let big = axum::extract::DefaultBodyLimit::disable();
    Router::new()
        .route("/", get(web::root))
        .route("/health", get(|| async { "ok" }))
        .route("/v1/whoami", get(api::whoami))
        .route("/v1/me", axum::routing::patch(api::me_patch))
        .route(
            "/v1/files",
            post(api::files_post).get(api::files_list).layer(big),
        )
        .route("/v1/files/:id", axum::routing::delete(api::files_delete))
        .route("/v1/apps", get(api::apps_list))
        .route(
            "/v1/apps/:name",
            axum::routing::put(api::apps_put)
                .delete(api::apps_delete)
                .layer(big),
        )
        .route("/v1/apps/:name/restart", post(api::apps_restart))
        .route("/v1/apps/:name/stop", post(api::apps_stop))
        .route("/f/:id", get(files::page))
        .route("/f/:id/blob", get(files::blob))
        .route("/a/:name", any(apps::serve_root))
        .route("/a/:name/", any(apps::serve_root))
        .route("/a/:name/*rest", any(apps::serve))
        .route("/onboarding.sh", get(web::onboarding_sh))
        .route("/onboarding.ps1", get(web::onboarding_ps1))
        .route("/_/file.js", get(web::file_js))
        .route("/_/style.css", get(web::style_css))
        .fallback(web::not_found)
        .with_state(st)
}

/// Admin listener (private network only).
pub fn admin_router(st: State) -> Router {
    admin::router(st)
}

/// Re-starts apps that were running before a restart of the server, and runs the hourly sweep.
pub fn start_background(st: State) {
    let s = st.clone();
    tokio::spawn(async move { apps::resume_all(&s).await });
    tokio::spawn(async move {
        loop {
            tokio::time::sleep(std::time::Duration::from_secs(3600)).await;
            sweep::sweep(&st).await;
        }
    });
}
