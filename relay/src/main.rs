use orch_relay::{admin, api, crypto, push, state};
use std::sync::Arc;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("info".parse().unwrap()),
        )
        .init();
    if let Err(e) = run().await {
        eprintln!("orch-relay: {e}");
        std::process::exit(1);
    }
}

async fn run() -> Result<(), String> {
    let cfg = state::Config::from_env()?;
    let key = crypto::load_master_key(&cfg.master_key_file)?;
    let pusher: Arc<dyn push::Pusher> = match &cfg.apns {
        Some(a) => Arc::new(push::ApnsPusher::new(a.clone())),
        None => {
            tracing::info!("APNs push is off (ORCH_RELAY_APNS_KEY_FILE not set)");
            Arc::new(push::NoPush)
        }
    };
    let (pub_addr, admin_addr) = (cfg.public_listen.clone(), cfg.admin_listen.clone());
    let app = state::App::new(cfg, key, pusher)?;
    orch_relay::spawn_purge(app.clone());
    orch_relay::subs_push::spawn(app.clone());
    let pl = tokio::net::TcpListener::bind(&pub_addr)
        .await
        .map_err(|e| format!("{pub_addr}: {e}"))?;
    let al = tokio::net::TcpListener::bind(&admin_addr)
        .await
        .map_err(|e| format!("{admin_addr}: {e}"))?;
    tracing::info!("public on {pub_addr}, admin on {admin_addr}");
    let a = axum::serve(pl, api::router(app.clone()));
    let b = axum::serve(al, admin::router(app));
    tokio::select! {
        r = a => r.map_err(|e| e.to_string()),
        r = b => r.map_err(|e| e.to_string()),
    }
}
