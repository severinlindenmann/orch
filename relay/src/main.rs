use orch_relay::cli::{self, Cmd};
use orch_relay::{admin, api, crypto, push, state};
use std::sync::Arc;

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    // Arguments first: --help and friends never read settings, open the data folder or bind a port.
    let cmd = match cli::parse(&args) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("orch-relay: {e}");
            std::process::exit(2);
        }
    };
    let rt = || {
        tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .expect("tokio runtime")
    };
    match cmd {
        Cmd::Help => print!("{}", cli::HELP),
        Cmd::Version => println!("orch-relay {}", cli::VERSION),
        Cmd::Admin(a) => match rt().block_on(cli::run_admin(a)) {
            Ok(out) => print!("{out}"),
            Err(e) => {
                eprintln!("orch-relay: {e}");
                std::process::exit(1);
            }
        },
        Cmd::Serve { allow_root } => {
            tracing_subscriber::fmt()
                .with_env_filter(
                    tracing_subscriber::EnvFilter::from_default_env()
                        .add_directive("info".parse().unwrap()),
                )
                .init();
            if let Err(e) = rt().block_on(run(allow_root)) {
                eprintln!("orch-relay: {e}");
                std::process::exit(1);
            }
        }
    }
}

async fn run(allow_root: bool) -> Result<(), String> {
    cli::check_root(allow_root, cli::is_root())?;
    let cfg = state::Config::from_env()?;
    let (pub_addr, admin_addr) = (cfg.public_listen.clone(), cfg.admin_listen.clone());
    // Ports before the data folder: a second copy stops here without touching anything.
    let pl = tokio::net::TcpListener::bind(&pub_addr)
        .await
        .map_err(|e| {
            format!("cannot listen on {pub_addr}: {e} (is another orch-relay running?)")
        })?;
    let al = tokio::net::TcpListener::bind(&admin_addr)
        .await
        .map_err(|e| {
            format!("cannot listen on {admin_addr}: {e} (is another orch-relay running?)")
        })?;
    let _lock = cli::lock_data_dir(&cfg.data_dir, "orch-relay")?;
    let key = crypto::load_master_key(&cfg.master_key_file)?;
    let pusher: Arc<dyn push::Pusher> = match &cfg.apns {
        Some(a) => Arc::new(push::ApnsPusher::new(a.clone())),
        None => {
            tracing::info!("APNs push is off (ORCH_RELAY_APNS_KEY_FILE not set)");
            Arc::new(push::NoPush)
        }
    };
    let app = state::App::new(cfg, key, pusher)?;
    orch_relay::spawn_purge(app.clone());
    orch_relay::subs_push::spawn(app.clone());
    orch_relay::mobile::spawn(app.clone());
    tracing::info!("public on {pub_addr}, admin on {admin_addr}");
    let a = axum::serve(pl, api::router(app.clone()));
    let b = axum::serve(al, admin::router(app));
    tokio::select! {
        r = a => r.map_err(|e| e.to_string()),
        r = b => r.map_err(|e| e.to_string()),
    }
}
