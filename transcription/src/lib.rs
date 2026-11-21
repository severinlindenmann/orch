//! orch transcription service: speech to text with a self-hosted Whisper model (whisper.cpp).
//! Used by the relay in place of Deepgram when it is set up (docs/transcription.md).
pub mod api;
pub mod audio;
pub mod config;
pub mod engine;
pub mod error;
pub mod jobs;
pub mod opf1;
pub mod tokens;

use axum::extract::{Request, State};
use axum::middleware::{self, Next};
use axum::response::Response;
use axum::routing::{get, post};
use axum::Router;

pub use api::{App, AppState};

/// The signed-in caller: the token's name. Jobs belong to it.
#[derive(Clone, Debug)]
pub struct Caller(pub String);

async fn signed_in(
    State(app): State<AppState>,
    mut req: Request,
    next: Next,
) -> Result<Response, error::ApiError> {
    let h = req
        .headers()
        .get(axum::http::header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok());
    let e = app.tokens.check(h).ok_or_else(error::unauthorized)?;
    if !app.tokens.take(&e) {
        return Err(error::rate_limited());
    }
    req.extensions_mut().insert(Caller(e.name));
    Ok(next.run(req).await)
}

pub fn router(app: AppState) -> Router {
    let signed = Router::new()
        .route("/v1/transcribe", post(api::transcribe))
        .route("/v1/jobs", post(api::job_create))
        .route("/v1/jobs/:id", get(api::job_get).delete(api::job_delete))
        .route("/v1/jobs/:id/key", post(api::job_key))
        .route("/v1/jobs/:id/result", get(api::job_result))
        .route_layer(middleware::from_fn_with_state(app.clone(), signed_in));
    Router::new()
        .route("/v1/health", get(api::health))
        .merge(signed)
        .fallback(api::fallback)
        .with_state(app)
}
