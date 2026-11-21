//! Errors in the same shape as the relay and publish (common.md): `{"error": "<code>", "message"}`.
//! Every message says what to do next (R8.4) and never echoes audio or transcript content.
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde_json::json;

#[derive(Debug)]
pub struct ApiError {
    pub status: StatusCode,
    pub code: &'static str,
    pub message: String,
}

pub type Res<T> = Result<T, ApiError>;

fn e(status: StatusCode, code: &'static str, m: impl Into<String>) -> ApiError {
    ApiError {
        status,
        code,
        message: m.into(),
    }
}

pub fn unauthorized() -> ApiError {
    e(
        StatusCode::UNAUTHORIZED,
        "unauthorized",
        "Missing or wrong token. Ask the admin of the transcription service for a token.",
    )
}
pub fn invalid(m: impl Into<String>) -> ApiError {
    e(StatusCode::UNPROCESSABLE_ENTITY, "invalid", m)
}
pub fn too_large(m: impl Into<String>) -> ApiError {
    e(StatusCode::PAYLOAD_TOO_LARGE, "too_large", m)
}
pub fn unsupported_audio() -> ApiError {
    e(
        StatusCode::UNSUPPORTED_MEDIA_TYPE,
        "unsupported_audio",
        "The audio could not be read. Send m4a, wav, webm, ogg, mp3 or flac.",
    )
}
pub fn busy() -> ApiError {
    e(
        StatusCode::SERVICE_UNAVAILABLE,
        "busy",
        "The transcription service is busy. Try again in a minute.",
    )
}
pub fn rate_limited() -> ApiError {
    e(
        StatusCode::TOO_MANY_REQUESTS,
        "rate_limited",
        "Too many transcriptions. Try again in a minute.",
    )
}
pub fn failed() -> ApiError {
    e(
        StatusCode::INTERNAL_SERVER_ERROR,
        "transcription_failed",
        "The transcription failed. Try again; if it keeps failing, tell the admin.",
    )
}
pub fn not_found() -> ApiError {
    e(StatusCode::NOT_FOUND, "not_found", "No such address.")
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (
            self.status,
            Json(json!({"error": self.code, "message": self.message})),
        )
            .into_response()
    }
}
