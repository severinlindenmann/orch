//! orch transcription service: speech to text with a self-hosted Whisper model (whisper.cpp).
//! Used by the relay in place of Deepgram when it is set up (docs/transcription.md).
pub mod api;
pub mod audio;
pub mod config;
pub mod engine;
pub mod error;

use axum::routing::{get, post};
use axum::Router;

pub use api::{App, AppState};

pub fn router(app: AppState) -> Router {
    Router::new()
        .route("/v1/health", get(api::health))
        .route("/v1/transcribe", post(api::transcribe))
        .fallback(api::fallback)
        .with_state(app)
}
