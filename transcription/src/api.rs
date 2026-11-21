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
/// Below this loudness (RMS) the clip is silence: empty text, the engine is not asked (it would make text up).
const SILENCE_RMS: f32 = 1e-4;

pub struct App {
    pub engine: Arc<dyn Engine>,
    /// One transcription at a time: the engine uses all its threads for one clip.
    run: Semaphore,
    waiting: AtomicUsize,
}

pub type AppState = Arc<App>;

impl App {
    pub fn new(engine: Arc<dyn Engine>) -> AppState {
        Arc::new(App {
            engine,
            run: Semaphore::new(1),
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
    let data = axum::body::to_bytes(body, MAX_AUDIO + 1)
        .await
        .map_err(|_| too_large("The audio is larger than 10 MB."))?;
    if data.is_empty() {
        return Err(invalid("The audio is empty."));
    }
    if data.len() > MAX_AUDIO {
        return Err(too_large("The audio is larger than 10 MB."));
    }
    if app.waiting.fetch_add(1, Ordering::SeqCst) >= MAX_WAITING {
        app.waiting.fetch_sub(1, Ordering::SeqCst);
        return Err(busy());
    }
    let line = InLine(&app.waiting);
    let _permit = app.run.acquire().await.map_err(|_| busy())?;
    drop(line);
    let engine = app.engine.clone();
    let data = data.to_vec();
    let (t, duration) = tokio::task::spawn_blocking(move || {
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

pub async fn health() -> Json<Value> {
    Json(json!({"ok": true, "version": env!("CARGO_PKG_VERSION")}))
}

pub async fn fallback() -> ApiError {
    not_found()
}
