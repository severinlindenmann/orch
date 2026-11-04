use orch_publish::{admin_router, new_state, public_router, start_background, Config};

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
    let st = new_state(cfg).expect("cannot open the data folder");
    let public = tokio::net::TcpListener::bind(&listen)
        .await
        .unwrap_or_else(|e| panic!("cannot listen on {listen}: {e}"));
    let admin = tokio::net::TcpListener::bind(&admin_listen)
        .await
        .unwrap_or_else(|e| panic!("cannot listen on {admin_listen}: {e}"));
    tracing::info!("orch-publish: public {listen}, admin {admin_listen}");
    start_background(st.clone());
    let a = axum::serve(public, public_router(st.clone()));
    let b = axum::serve(admin, admin_router(st));
    let _ = tokio::join!(a, b);
}
