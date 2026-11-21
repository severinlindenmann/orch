use orch_publish::cli::{self, Cmd};
use orch_publish::{
    admin_router, new_state, private_router, public_router, start_background, Config,
};

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    // Arguments first: --help and friends never read settings, write to the data folder or bind a port.
    let cmd = match cli::parse(&args) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("orch-publish: {e}");
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
        Cmd::Version => println!("orch-publish {}", cli::VERSION),
        Cmd::Admin(a) => match rt().block_on(cli::run_admin(a)) {
            Ok(out) => print!("{out}"),
            Err(e) => {
                eprintln!("orch-publish: {e}");
                std::process::exit(1);
            }
        },
        Cmd::Serve { allow_root } => {
            tracing_subscriber::fmt().with_target(false).init();
            if let Err(e) = rt().block_on(serve(allow_root)) {
                eprintln!("orch-publish: {e}");
                std::process::exit(1);
            }
        }
    }
}

async fn bind(addr: &str) -> Result<tokio::net::TcpListener, String> {
    tokio::net::TcpListener::bind(addr)
        .await
        .map_err(|e| format!("cannot listen on {addr}: {e} (is another orch-publish running?)"))
}

async fn serve(allow_root: bool) -> Result<(), String> {
    cli::check_root(allow_root, cli::is_root())?;
    let env = |a: &str, b: &str, d: &str| {
        std::env::var(a)
            .or_else(|_| std::env::var(b))
            .unwrap_or_else(|_| d.into())
    };
    let listen = env("ORCH_PUBLISH_LISTEN", "PUBLISH_LISTEN", "127.0.0.1:8102");
    let admin_listen = env(
        "ORCH_PUBLISH_ADMIN_LISTEN",
        "PUBLISH_ADMIN_LISTEN",
        "127.0.0.1:8411",
    );
    // Ports, then the data folder lock, and only then the settings (they may write an admin token): a second copy
    // stops before it touches the data folder.
    let public = bind(&listen).await?;
    let admin = bind(&admin_listen).await?;
    let _lock = cli::lock_data_dir(&cli::data_dir_from_env(), "orch-publish")?;
    let cfg = Config::from_env();
    cfg.validate()?;
    let private_listen = cfg.private_listen.clone();
    let private = match &private_listen {
        Some(l) => match tokio::net::TcpListener::bind(l).await {
            Ok(p) => Some(p),
            Err(e) => {
                tracing::error!("cannot listen on {l}: {e}; private-network apps stay hidden");
                None
            }
        },
        None => None,
    };
    let st = new_state(cfg).map_err(|e| format!("cannot open the data folder: {e}"))?;
    orch_publish::sweep_containers_at_start(&st).await;
    tracing::info!("orch-publish: public {listen}, admin {admin_listen}");
    start_background(st.clone());
    let a = axum::serve(public, public_router(st.clone()));
    let b = axum::serve(admin, admin_router(st.clone()));
    let c = async {
        match private {
            Some(p) => {
                let _ = axum::serve(p, private_router(st)).await;
            }
            None => std::future::pending::<()>().await,
        }
    };
    let _ = tokio::join!(a, b, c);
    Ok(())
}
