use orch_publish::{
    admin_router, new_state, private_router, public_router, start_background, Config,
};

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt().with_target(false).init();
    let cfg = Config::from_env();
    let listen = std::env::var("ORCH_PUBLISH_LISTEN")
        .or_else(|_| std::env::var("PUBLISH_LISTEN"))
        .unwrap_or_else(|_| "127.0.0.1:8102".into());
    let admin_listen = std::env::var("ORCH_PUBLISH_ADMIN_LISTEN")
        .or_else(|_| std::env::var("PUBLISH_ADMIN_LISTEN"))
        .unwrap_or_else(|_| "127.0.0.1:8411".into());
    if let Err(e) = cfg.validate() {
        eprintln!("orch-publish: {e}");
        std::process::exit(1);
    }
    let private_listen = cfg.private_listen.clone();
    let st = new_state(cfg).expect("cannot open the data folder");
    orch_publish::sweep_containers_at_start(&st).await;
    let public = tokio::net::TcpListener::bind(&listen)
        .await
        .unwrap_or_else(|e| panic!("cannot listen on {listen}: {e}"));
    let admin = tokio::net::TcpListener::bind(&admin_listen)
        .await
        .unwrap_or_else(|e| panic!("cannot listen on {admin_listen}: {e}"));
    let private = match &private_listen {
        Some(l) => Some(
            tokio::net::TcpListener::bind(l)
                .await
                .unwrap_or_else(|e| panic!("cannot listen on {l}: {e}")),
        ),
        None => None,
    };
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
}
