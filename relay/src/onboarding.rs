use crate::state::AppState;
use axum::extract::State;
use axum::http::header;
use axum::response::IntoResponse;

const SH: &str = include_str!("../onboarding/onboarding.sh");
const PS1: &str = include_str!("../onboarding/onboarding.ps1");

pub async fn sh(State(app): State<AppState>) -> impl IntoResponse {
    (
        [(header::CONTENT_TYPE, "text/x-shellscript; charset=utf-8")],
        SH.replace("__RELAY_URL__", &app.cfg.public_url),
    )
}

pub async fn ps1(State(app): State<AppState>) -> impl IntoResponse {
    (
        [(header::CONTENT_TYPE, "text/plain; charset=utf-8")],
        PS1.replace("__RELAY_URL__", &app.cfg.public_url),
    )
}
