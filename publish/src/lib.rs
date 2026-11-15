//! orch-publish: encrypted file links (/f/) and small apps (/a/), see docs/publish.md.
pub mod admin;
pub mod api;
pub mod apps;
pub mod config;
pub mod db;
pub mod err;
pub mod files;
pub mod look;
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

/// In-memory state for scale to zero (see apps.rs).
pub struct SleepState {
    /// per app: last request time and requests in flight
    pub activity: Mutex<std::collections::HashMap<String, (std::time::Instant, usize)>>,
    /// apps stopped for idleness (DB status stays "running"); they wake on the next request
    pub sleeping: Mutex<std::collections::HashSet<String>>,
    /// failed wakes: no new try for 30 s
    pub cooldown: Mutex<std::collections::HashMap<String, std::time::Instant>>,
    /// ports picked for a start that is not yet in the DB or the runner (choose_port skips them)
    pub reserved_ports: Mutex<std::collections::HashSet<u16>>,
    /// at most 4 apps start for a wake at the same time
    pub wake_slots: tokio::sync::Semaphore,
    /// one wake at a time per app
    pub wake: Mutex<std::collections::HashMap<String, Arc<tokio::sync::Mutex<()>>>>,
}

impl SleepState {
    fn new() -> Self {
        SleepState {
            activity: Default::default(),
            sleeping: Default::default(),
            cooldown: Default::default(),
            reserved_ports: Default::default(),
            wake_slots: tokio::sync::Semaphore::new(4),
            wake: Default::default(),
        }
    }
}

pub struct Inner {
    pub cfg: Config,
    pub db: Mutex<rusqlite::Connection>,
    pub runner: runner::Runner,
    /// deploy, restart, stop and delete of apps run one at a time
    pub app_lock: tokio::sync::Mutex<()>,
    pub http: Http,
    /// key for private-app capability paths (`/a/<name>/~<cap>/`)
    pub app_key: [u8; 32],
    pub sleep: SleepState,
}

pub type State = Arc<Inner>;

/// Opens the database and folders under `cfg.data_dir`.
pub fn new_state(cfg: Config) -> std::io::Result<State> {
    runner::set_instance(&cfg.data_dir);
    for d in ["files", "logs"] {
        std::fs::create_dir_all(cfg.data_dir.join(d))?;
    }
    std::fs::create_dir_all(&cfg.apps_dir)?;
    runner::set_roots(&[&cfg.data_dir, &cfg.apps_dir]);
    let conn = db::open(&cfg.data_dir.join("publish.db")).map_err(std::io::Error::other)?;
    let http = hyper_util::client::legacy::Client::builder(hyper_util::rt::TokioExecutor::new())
        .build_http();
    let app_key = util::load_or_create_key(&cfg.data_dir.join("app-cap.key"))?;
    Ok(Arc::new(Inner {
        cfg,
        db: Mutex::new(conn),
        runner: runner::Runner::default(),
        app_lock: tokio::sync::Mutex::new(()),
        http,
        app_key,
        sleep: SleepState::new(),
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
        .route(
            "/v1/files/:id",
            axum::routing::delete(api::files_delete)
                .patch(api::files_patch)
                .put(axum::handler::Handler::layer(api::files_put, big)),
        )
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
        .route("/f/:id/meta", get(files::meta))
        .route("/a/:name", any(apps::serve_root))
        .route("/a/:name/", any(apps::serve_root))
        .route("/a/:name/*rest", any(apps::serve))
        .route("/onboarding.sh", get(web::onboarding_sh))
        .route("/onboarding.ps1", get(web::onboarding_ps1))
        .route("/_/file.js", get(web::file_js))
        .route("/_/look.js", get(web::look_js))
        .route("/_/look-data.js", get(web::look_data_js))
        .route("/_/style.css", get(web::style_css))
        .route("/_/frame.html", get(web::frame_html))
        .route("/_/frame.js", get(web::frame_js))
        .route("/_/favicon.svg", get(web::favicon_svg))
        .route("/_/apple-touch-icon.png", get(web::touch_icon))
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
    if st.cfg.idle_secs > 0 {
        let s = st.clone();
        tokio::spawn(async move {
            loop {
                tokio::time::sleep(std::time::Duration::from_secs(s.cfg.sleep_sweep_secs)).await;
                apps::sleep_sweep(&s).await;
            }
        });
    }
    tokio::spawn(async move {
        loop {
            tokio::time::sleep(std::time::Duration::from_secs(3600)).await;
            sweep::sweep(&st).await;
        }
    });
}

/// Call before the listeners bind (container mode: removes leftover containers of this instance).
pub async fn sweep_containers_at_start(st: &State) {
    apps::startup_sweep(st).await;
}
