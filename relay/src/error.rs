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
        "Missing or wrong token.",
    )
}
pub fn forbidden(m: impl Into<String>) -> ApiError {
    e(StatusCode::FORBIDDEN, "forbidden", m)
}
pub fn not_allowed(m: impl Into<String>) -> ApiError {
    e(StatusCode::FORBIDDEN, "not_allowed", m)
}
pub fn not_found(m: impl Into<String>) -> ApiError {
    e(StatusCode::NOT_FOUND, "not_found", m)
}
pub fn conflict(m: impl Into<String>) -> ApiError {
    e(StatusCode::CONFLICT, "conflict", m)
}
pub fn already_answered(m: impl Into<String>) -> ApiError {
    e(StatusCode::CONFLICT, "already_answered", m)
}
pub fn gone(m: impl Into<String>) -> ApiError {
    e(StatusCode::GONE, "gone", m)
}
pub fn too_large(m: impl Into<String>) -> ApiError {
    e(StatusCode::PAYLOAD_TOO_LARGE, "too_large", m)
}
pub fn invalid(m: impl Into<String>) -> ApiError {
    e(StatusCode::UNPROCESSABLE_ENTITY, "invalid", m)
}
pub fn internal(m: impl std::fmt::Display) -> ApiError {
    tracing::error!("internal error: {m}");
    e(
        StatusCode::INTERNAL_SERVER_ERROR,
        "internal",
        "Something went wrong on the relay.",
    )
}

impl From<rusqlite::Error> for ApiError {
    fn from(x: rusqlite::Error) -> Self {
        internal(x)
    }
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
