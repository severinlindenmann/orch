//! `POST /v1/transcribe`: audio in the body, `{"text","language","duration"}` back.
//! Audio and text live only in memory for the length of the call; nothing about the content is logged.
use std::collections::HashMap;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use axum::body::Body;
use axum::extract::{Query, State};
use axum::http::HeaderMap;
use axum::Json;
use serde_json::{json, Value};
use tokio::sync::Semaphore;

use crate::audio::{self, AudioError};
use crate::engine::{Engine, Transcript};
use crate::error::*;

/// Largest upload (same as the relay's voice limit).
pub const MAX_AUDIO: usize = 10 * 1024 * 1024;
/// Longest audio for one call (same as the relay's voice limit).
pub const MAX_SECONDS: f64 = 120.0;
/// Calls that may wait while one runs; more get `busy` at once instead of hanging.
pub const MAX_WAITING: usize = 4;
/// Time to send a short clip (10 MB) / a job recording (200 MB); a slower upload is cut off.
const SHORT_UPLOAD_SECS: u64 = 60;
const JOB_UPLOAD_SECS: u64 = 600;
/// Below this loudness (RMS) the clip is silence: empty text, the engine is not asked (it would make text up).
const SILENCE_RMS: f32 = 1e-4;

pub struct App {
    pub engine: Arc<dyn Engine>,
    pub tokens: crate::tokens::Tokens,
    pub jobs: crate::jobs::Jobs,
    /// One transcription at a time: the engine uses all its threads for one clip.
    pub run: Arc<Semaphore>,
    /// Job uploads being read; more get `busy` before their body is read.
    pub uploads: Arc<Semaphore>,
    waiting: AtomicUsize,
}

pub type AppState = Arc<App>;

impl App {
    pub fn new(engine: Arc<dyn Engine>, data_dir: &std::path::Path) -> AppState {
        Arc::new(App {
            engine,
            tokens: crate::tokens::Tokens::open(data_dir),
            jobs: crate::jobs::Jobs::open(data_dir),
            run: Arc::new(Semaphore::new(1)),
            uploads: Arc::new(Semaphore::new(crate::jobs::MAX_UPLOADS)),
            waiting: AtomicUsize::new(0),
        })
    }
}

/// Counts a caller in the line while it waits for the engine.
struct InLine<'a>(&'a AtomicUsize);
impl Drop for InLine<'_> {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::SeqCst);
    }
}

/// `de-CH`, `DE`, `de` -> `de`. Err when it is not a language code the engine knows.
pub fn language_code(raw: Option<&str>, engine: &dyn Engine) -> Res<Option<String>> {
    let Some(raw) = raw.map(str::trim).filter(|s| !s.is_empty()) else {
        return Ok(None);
    };
    let primary = raw
        .split(['-', '_'])
        .next()
        .unwrap_or("")
        .to_ascii_lowercase();
    let ok = (2..=3).contains(&primary.len())
        && primary.chars().all(|c| c.is_ascii_lowercase())
        && engine.knows_language(&primary);
    if !ok {
        return Err(invalid(
            "`language` must be a language code such as `en` or `de`, or left out to detect it.",
        ));
    }
    Ok(Some(primary))
}

pub fn content_type(h: &HeaderMap) -> String {
    h.get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .split(';')
        .next()
        .unwrap_or("")
        .trim()
        .to_ascii_lowercase()
}

/// Read a body of at most `max` bytes within `secs` seconds.
async fn read_body(body: Body, max: usize, secs: u64, too_big: &str) -> Res<axum::body::Bytes> {
    let data = tokio::time::timeout(
        std::time::Duration::from_secs(secs),
        axum::body::to_bytes(body, max + 1),
    )
    .await
    .map_err(|_| invalid("The upload took too long. Send it again on a better connection."))?
    .map_err(|_| too_large(too_big))?;
    if data.len() > max {
        return Err(too_large(too_big));
    }
    Ok(data)
}

fn rms(x: &[f32]) -> f32 {
    if x.is_empty() {
        return 0.0;
    }
    (x.iter().map(|v| v * v).sum::<f32>() / x.len() as f32).sqrt()
}

/// Decode, check, transcribe. Blocking: runs on the blocking pool.
pub fn transcribe_blocking(
    engine: &dyn Engine,
    data: Vec<u8>,
    ext: &str,
    language: Option<&str>,
) -> Res<(Transcript, f64)> {
    let samples = audio::decode(data, ext, MAX_SECONDS).map_err(|e| match e {
        AudioError::TooLong => too_large("The audio is longer than 2 minutes."),
        AudioError::Unreadable => unsupported_audio(),
    })?;
    let duration = samples.len() as f64 / audio::RATE as f64;
    if rms(&samples) < SILENCE_RMS {
        let t = Transcript {
            text: String::new(),
            language: language.map(String::from),
            segments: vec![],
        };
        return Ok((t, duration));
    }
    let t = engine
        .transcribe(&samples, language)
        .map_err(|_| failed())?;
    Ok((t, duration))
}

pub async fn transcribe(
    State(app): State<AppState>,
    h: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
    body: Body,
) -> Res<Json<Value>> {
    let ct = content_type(&h);
    let Some(ext) = audio::hint_for(&ct) else {
        return Err(unsupported_audio());
    };
    let lang = language_code(q.get("language").map(String::as_str), app.engine.as_ref())?;
    // In line before the body is read: at most 1 + MAX_WAITING bodies in memory, however many callers.
    if app.waiting.fetch_add(1, Ordering::SeqCst) >= MAX_WAITING {
        app.waiting.fetch_sub(1, Ordering::SeqCst);
        return Err(busy());
    }
    let line = InLine(&app.waiting);
    let data = read_body(
        body,
        MAX_AUDIO,
        SHORT_UPLOAD_SECS,
        "The audio is larger than 10 MB.",
    )
    .await?;
    if data.is_empty() {
        return Err(invalid("The audio is empty."));
    }
    let permit = app.run.clone().acquire_owned().await.map_err(|_| busy())?;
    drop(line);
    let engine = app.engine.clone();
    let data = data.to_vec();
    // The slot goes with the work: a caller who hangs up does not free it while the engine still runs.
    let (t, duration) = tokio::task::spawn_blocking(move || {
        let _slot = permit;
        transcribe_blocking(engine.as_ref(), data, ext, lang.as_deref())
    })
    .await
    .map_err(|_| failed())??;
    Ok(Json(json!({
        "text": t.text,
        "language": t.language,
        "duration": (duration * 100.0).round() / 100.0,
    })))
}

// ---------- encrypted jobs ----------

use crate::jobs::JobError;
use crate::Caller;
use axum::extract::{Extension, Path};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};

fn job_err(e: JobError) -> ApiError {
    match e {
        JobError::NotFound => not_found(),
        JobError::BadKey => invalid(
            "X-Orch-Job-Key is missing or does not open the recording. Send the job's key (base64url, 43 characters).",
        ),
        JobError::BadBlob => invalid(
            "The body must be an OPF1 blob (crypto.md) whose type is an audio type such as audio/m4a.",
        ),
        JobError::TooLarge => too_large("The recording is larger than 200 MB."),
        JobError::Busy => busy(),
        JobError::Conflict => conflict(
            "Not possible in this job's state. Look at it with GET /v1/jobs/<id>.",
        ),
        JobError::Io => failed(),
    }
}

fn job_key_header(h: &HeaderMap) -> Option<String> {
    h.get("x-orch-job-key")
        .and_then(|v| v.to_str().ok())
        .map(String::from)
}

pub async fn job_create(
    State(app): State<AppState>,
    Extension(who): Extension<Caller>,
    h: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
    body: Body,
) -> Res<Response> {
    let lang = language_code(q.get("language").map(String::as_str), app.engine.as_ref())?;
    // Room first, then read: a full store or too many uploads never get a body into memory.
    let upload = app
        .uploads
        .clone()
        .try_acquire_owned()
        .map_err(|_| busy())?;
    app.jobs.room_for(&who.0).map_err(job_err)?;
    let blob = read_body(
        body,
        crate::jobs::MAX_BLOB,
        JOB_UPLOAD_SECS,
        "The recording is larger than 200 MB.",
    )
    .await?;
    let key = job_key_header(&h);
    let app2 = app.clone();
    // The upload slot goes with the work: a caller who hangs up does not free it while it still runs.
    let m = tokio::task::spawn_blocking(move || {
        let _upload = upload;
        app2.jobs.create(&who.0, key.as_deref(), &blob, lang)
    })
    .await
    .map_err(|_| failed())?
    .map_err(job_err)?;
    Ok((StatusCode::ACCEPTED, Json(m.public())).into_response())
}

pub async fn job_get(
    State(app): State<AppState>,
    Extension(who): Extension<Caller>,
    Path(id): Path<String>,
) -> Res<Json<Value>> {
    Ok(Json(app.jobs.get(&who.0, &id).map_err(job_err)?.public()))
}

pub async fn job_key(
    State(app): State<AppState>,
    Extension(who): Extension<Caller>,
    Path(id): Path<String>,
    h: HeaderMap,
) -> Res<Json<Value>> {
    let key = job_key_header(&h);
    let app2 = app.clone();
    let m = tokio::task::spawn_blocking(move || app2.jobs.resupply(&who.0, &id, key.as_deref()))
        .await
        .map_err(|_| failed())?
        .map_err(job_err)?;
    Ok(Json(json!({"id": m.id, "status": m.status})))
}

pub async fn job_result(
    State(app): State<AppState>,
    Extension(who): Extension<Caller>,
    Path(id): Path<String>,
) -> Res<Response> {
    let blob = app.jobs.result(&who.0, &id).map_err(job_err)?;
    Ok(([("content-type", "application/octet-stream")], blob).into_response())
}

pub async fn job_delete(
    State(app): State<AppState>,
    Extension(who): Extension<Caller>,
    Path(id): Path<String>,
) -> Res<StatusCode> {
    app.jobs.delete(&who.0, &id).map_err(job_err)?;
    Ok(StatusCode::NO_CONTENT)
}

pub async fn health() -> Json<Value> {
    Json(json!({"ok": true, "version": env!("CARGO_PKG_VERSION")}))
}

pub async fn fallback() -> ApiError {
    not_found()
}
