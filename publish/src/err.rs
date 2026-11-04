use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde_json::json;

#[derive(Debug)]
pub struct ApiError {
    pub status: StatusCode,
    pub code: &'static str,
    pub message: String,
    pub output: Option<String>,
}

pub type ApiResult<T> = Result<T, ApiError>;

impl ApiError {
    pub fn new(status: u16, code: &'static str, message: impl Into<String>) -> Self {
        ApiError {
            status: StatusCode::from_u16(status).unwrap(),
            code,
            message: message.into(),
            output: None,
        }
    }
    pub fn unauthorized() -> Self {
        Self::new(
            401,
            "unauthorized",
            "Missing or wrong workspace ID or token.",
        )
    }
    pub fn forbidden(m: impl Into<String>) -> Self {
        Self::new(403, "forbidden", m)
    }
    pub fn not_found(m: impl Into<String>) -> Self {
        Self::new(404, "not_found", m)
    }
    pub fn conflict(m: impl Into<String>) -> Self {
        Self::new(409, "conflict", m)
    }
    pub fn gone(m: impl Into<String>) -> Self {
        Self::new(410, "gone", m)
    }
    pub fn too_large(m: impl Into<String>) -> Self {
        Self::new(413, "too_large", m)
    }
    pub fn invalid(m: impl Into<String>) -> Self {
        Self::new(422, "invalid", m)
    }
    pub fn internal(m: impl std::fmt::Display) -> Self {
        tracing::error!("internal error: {m}");
        Self::new(500, "internal", "Something went wrong on the server.")
    }
    pub fn with_output(mut self, o: String) -> Self {
        self.output = Some(o);
        self
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let mut b = json!({"error": self.code, "message": self.message});
        if let Some(o) = self.output {
            b["output"] = json!(o);
        }
        (self.status, Json(b)).into_response()
    }
}

impl From<rusqlite::Error> for ApiError {
    fn from(e: rusqlite::Error) -> Self {
        ApiError::internal(e)
    }
}
impl From<std::io::Error> for ApiError {
    fn from(e: std::io::Error) -> Self {
        ApiError::internal(e)
    }
}
