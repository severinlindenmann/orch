//! Voice transcription through Deepgram. One API key, set by the admin, sealed with the master key.
//! The key never leaves the relay: not in any response, not to phones, not to workspaces.
use crate::crypto;
use crate::error::*;
use crate::state::{App, AppState};
use crate::{auth, util};
use async_trait::async_trait;
use axum::body::Bytes;
use axum::extract::{Query, State};
use axum::http::HeaderMap;
use axum::Json;
use rusqlite::{Connection, OptionalExtension};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::Mutex;

pub const MAX_AUDIO: usize = 10 * 1024 * 1024;
const MAX_SECONDS: f64 = 120.0;
const PER_MINUTE: u32 = 30;
const AAD: &str = "setting:deepgram";

#[derive(Debug, Clone, PartialEq)]
pub struct Transcript {
    pub text: String,
    pub language: Option<String>,
    pub duration: f64,
}

/// The Deepgram call, behind a trait so tests never touch the network.
#[async_trait]
pub trait Transcriber: Send + Sync {
    async fn transcribe(
        &self,
        api_key: &str,
        audio: Bytes,
        content_type: &str,
        language: Option<&str>,
    ) -> Result<Transcript, String>;
}

pub struct Deepgram {
    client: reqwest::Client,
}

impl Default for Deepgram {
    fn default() -> Self {
        Deepgram {
            client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(60))
                .build()
                .expect("http client"),
        }
    }
}

#[async_trait]
impl Transcriber for Deepgram {
    async fn transcribe(
        &self,
        api_key: &str,
        audio: Bytes,
        content_type: &str,
        language: Option<&str>,
    ) -> Result<Transcript, String> {
        let mut q = vec![("model", "nova-3"), ("smart_format", "true")];
        match language {
            Some(l) => q.push(("language", l)),
            None => q.push(("detect_language", "true")),
        }
        let r = self
            .client
            .post("https://api.deepgram.com/v1/listen")
            .query(&q)
            .header("Authorization", format!("Token {api_key}"))
            .header("Content-Type", content_type)
            .body(audio)
            .send()
            .await
            .map_err(|_| "Could not reach the transcription service.".to_string())?;
        let status = r.status();
        let v: Value = r.json().await.unwrap_or(Value::Null);
        if !status.is_success() {
            return Err(format!(
                "The transcription service refused the audio ({}).",
                status.as_u16()
            ));
        }
        let ch = &v["results"]["channels"][0];
        Ok(Transcript {
            text: ch["alternatives"][0]["transcript"]
                .as_str()
                .unwrap_or("")
                .trim()
                .to_string(),
            language: ch["detected_language"]
                .as_str()
                .or(language)
                .map(String::from),
            duration: v["metadata"]["duration"].as_f64().unwrap_or(0.0),
        })
    }
}

/// Test double: records the calls, answers with a fixed result.
/// (api key, audio bytes, content type, language)
pub type Call = (String, usize, String, Option<String>);

pub struct FakeTranscriber {
    pub calls: Mutex<Vec<Call>>,
    pub result: Mutex<Result<Transcript, String>>,
}

impl Default for FakeTranscriber {
    fn default() -> Self {
        FakeTranscriber {
            calls: Mutex::new(vec![]),
            result: Mutex::new(Ok(Transcript {
                text: "hello world".into(),
                language: Some("en".into()),
                duration: 2.5,
            })),
        }
    }
}

#[async_trait]
impl Transcriber for FakeTranscriber {
    async fn transcribe(
        &self,
        api_key: &str,
        audio: Bytes,
        content_type: &str,
        language: Option<&str>,
    ) -> Result<Transcript, String> {
        self.calls.lock().unwrap().push((
            api_key.to_string(),
            audio.len(),
            content_type.to_string(),
            language.map(String::from),
        ));
        self.result.lock().unwrap().clone()
    }
}

// ---------- the stored key ----------

pub fn set_key(c: &Connection, key: &crypto::Key, value: &str) -> rusqlite::Result<()> {
    c.execute(
        "INSERT INTO settings(k,v) VALUES('deepgram',?1) ON CONFLICT(k) DO UPDATE SET v=?1",
        [crypto::seal(key, AAD, value.as_bytes())],
    )?;
    Ok(())
}

pub fn remove_key(c: &Connection) -> rusqlite::Result<()> {
    c.execute("DELETE FROM settings WHERE k='deepgram'", [])?;
    Ok(())
}

pub fn get_key(c: &Connection, key: &crypto::Key) -> Option<String> {
    let blob: Vec<u8> = c
        .query_row("SELECT v FROM settings WHERE k='deepgram'", [], |r| {
            r.get(0)
        })
        .optional()
        .ok()??;
    String::from_utf8(crypto::open(key, AAD, &blob)?).ok()
}

/// What the admin may see: whether a key is set and its last 4 characters.
pub fn status(c: &Connection, key: &crypto::Key) -> Value {
    match get_key(c, key) {
        Some(k) => {
            let tail: String = k
                .chars()
                .rev()
                .take(4)
                .collect::<Vec<_>>()
                .into_iter()
                .rev()
                .collect();
            json!({"set": true, "last4": tail})
        }
        None => json!({"set": false, "last4": null}),
    }
}

// ---------- the endpoints ----------

fn rate_ok(app: &App, who: &str) -> bool {
    let now = util::now();
    let mut m = app.transcribe_rate.lock().unwrap();
    let e = m.entry(who.to_string()).or_insert((now, 0));
    if now - e.0 >= 60 {
        *e = (now, 0);
    }
    e.1 += 1;
    e.1 <= PER_MINUTE
}

/// The language sent to Deepgram: an explicit `?language=` wins; else `de-CH` when the phone's `swiss_german`
/// setting is on; else none (the language is detected).
pub fn effective_language(explicit: Option<&str>, swiss_german: bool) -> Option<String> {
    match explicit.filter(|l| !l.is_empty()) {
        Some(l) => Some(l.to_string()),
        None if swiss_german => Some("de-CH".into()),
        None => None,
    }
}

/// The phone's `swiss_german` setting. Wired to the settings store of `/v1/phone/settings` (lane R1) after that merges.
fn swiss_german(_c: &Connection, _phone: &str) -> bool {
    false
}

async fn run(
    app: &AppState,
    who: &str,
    swiss: bool,
    h: &HeaderMap,
    q: &HashMap<String, String>,
    body: Bytes,
) -> Res<Json<Value>> {
    let ct = h
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .split(';')
        .next()
        .unwrap_or("")
        .trim()
        .to_ascii_lowercase();
    if !matches!(
        ct.as_str(),
        "audio/m4a" | "audio/x-m4a" | "audio/mp4" | "audio/wav" | "audio/x-wav" | "audio/webm"
    ) {
        return Err(invalid(
            "Content-Type must be audio/m4a, audio/wav or audio/webm.",
        ));
    }
    if body.is_empty() {
        return Err(invalid("The audio is empty."));
    }
    if body.len() > MAX_AUDIO {
        return Err(too_large("The audio is larger than 10 MB."));
    }
    let lang = effective_language(q.get("language").map(String::as_str), swiss);
    let lang = lang.as_deref();
    if let Some(l) = lang {
        if l.len() > 12 || !l.chars().all(|c| c.is_ascii_alphanumeric() || c == '-') {
            return Err(invalid(
                "`language` must be a language code such as `en` or `de`.",
            ));
        }
    }
    let api_key = {
        let c = app.db.lock().unwrap();
        get_key(&c, &app.key)
    };
    let Some(api_key) = api_key else {
        return Err(transcription_off());
    };
    if !rate_ok(app, who) {
        return Err(rate_limited());
    }
    let t = app
        .transcriber
        .transcribe(&api_key, body, &ct, lang)
        .await
        .map_err(transcription_failed)?;
    if t.duration > MAX_SECONDS {
        return Err(too_large("The audio is longer than 2 minutes."));
    }
    Ok(Json(
        json!({"text": t.text, "language": t.language, "duration": t.duration}),
    ))
}

pub async fn phone(
    State(app): State<AppState>,
    h: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
    body: Bytes,
) -> Res<Json<Value>> {
    let (id, swiss) = {
        let c = app.db.lock().unwrap();
        let id = auth::phone(&c, &h)?.0;
        let swiss = swiss_german(&c, &id);
        (id, swiss)
    };
    run(&app, &id, swiss, &h, &q, body).await
}

pub async fn workspace(
    State(app): State<AppState>,
    h: HeaderMap,
    Query(q): Query<HashMap<String, String>>,
    body: Bytes,
) -> Res<Json<Value>> {
    let id = {
        let c = app.db.lock().unwrap();
        auth::workspace(&c, &h)?
    };
    run(&app, &id, false, &h, &q, body).await
}
