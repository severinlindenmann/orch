//! Read-aloud: a workspace text becomes an mp3 through Deepgram Aura-2 (one relay-wide Deepgram key).
//! The core is `generate`, a plain function over the database and a `Speaker`, so tests never touch the network.
//! Audio is cached per (message, language) and sealed like blobs; the cost counter is per phone and UTC month.
use crate::crypto::{self, Key};
use crate::error::*;
use async_trait::async_trait;
use axum::http::StatusCode;
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::Value;
use std::path::Path;
use std::sync::Mutex;

pub const MAX_CHARS: usize = 900;
/// USD per 1,000 spoken characters.
pub const USD_PER_1000: f64 = 0.030;

pub fn tts_off() -> ApiError {
    ApiError {
        status: StatusCode::SERVICE_UNAVAILABLE,
        code: "tts_off",
        message: "Reading aloud is not set up on this relay.".into(),
    }
}
pub fn tts_cap_reached() -> ApiError {
    ApiError {
        status: StatusCode::PAYMENT_REQUIRED,
        code: "tts_cap_reached",
        message: "The monthly limit for reading aloud is reached.".into(),
    }
}
pub fn tts_failed(m: impl Into<String>) -> ApiError {
    ApiError {
        status: StatusCode::BAD_GATEWAY,
        code: "tts_failed",
        message: m.into(),
    }
}

// ---------- the text ----------

/// Strip links and markdown marks; whitespace runs become one space.
fn clean(s: &str) -> String {
    let mut words: Vec<String> = vec![];
    for w in s.split_whitespace() {
        let lw = w.to_ascii_lowercase();
        if lw.starts_with("http://") || lw.starts_with("https://") {
            words.push("link".into());
        } else {
            let t: String = w
                .chars()
                .filter(|c| !matches!(c, '*' | '`' | '#'))
                .collect();
            if !t.is_empty() {
                words.push(t);
            }
        }
    }
    words.join(" ")
}

/// Cut to `MAX_CHARS`: after the last `.`, `!` or `?` followed by a space within the first 900, else at the last
/// space, else at 900.
fn cut(s: &str) -> String {
    let ch: Vec<char> = s.chars().collect();
    if ch.len() <= MAX_CHARS {
        return s.to_string();
    }
    let end = (0..MAX_CHARS)
        .rev()
        .find(|&i| matches!(ch[i], '.' | '!' | '?') && ch[i + 1] == ' ')
        .map(|i| i + 1)
        .or_else(|| ch[..MAX_CHARS].iter().rposition(|c| *c == ' '))
        .unwrap_or(MAX_CHARS);
    ch[..end].iter().collect::<String>().trim_end().to_string()
}

/// The text read aloud for a message body: `speak.summary` if set, else `text`, cleaned and cut.
pub fn spoken_text(body: &Value) -> String {
    let raw = body["speak"]["summary"]
        .as_str()
        .filter(|s| !s.trim().is_empty())
        .or_else(|| body["text"].as_str())
        .unwrap_or("");
    cut(&clean(raw))
}

pub fn voice(lang: &str) -> &'static str {
    if lang == "de" {
        "aura-2-julius-de"
    } else {
        "aura-2-thalia-en"
    }
}

// ---------- Deepgram Aura ----------

#[async_trait]
pub trait Speaker: Send + Sync {
    /// mp3 bytes for `text` in `voice`.
    async fn speak(&self, api_key: &str, text: &str, voice: &str) -> Result<Vec<u8>, String>;
}

pub struct Aura {
    client: reqwest::Client,
    base: String,
}

impl Aura {
    pub fn new(base: &str) -> Aura {
        Aura {
            client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(60))
                .build()
                .expect("http client"),
            base: base.trim_end_matches('/').to_string(),
        }
    }
}

impl Default for Aura {
    fn default() -> Self {
        Aura::new("https://api.deepgram.com")
    }
}

#[async_trait]
impl Speaker for Aura {
    async fn speak(&self, api_key: &str, text: &str, voice: &str) -> Result<Vec<u8>, String> {
        let r = self
            .client
            .post(format!("{}/v1/speak", self.base))
            .query(&[("model", voice), ("encoding", "mp3")])
            .header("Authorization", format!("Token {api_key}"))
            .json(&serde_json::json!({"text": text}))
            .send()
            .await
            .map_err(|_| "Could not reach the speech service.".to_string())?;
        let status = r.status();
        if !status.is_success() {
            return Err(format!(
                "The speech service refused the text ({}).",
                status.as_u16()
            ));
        }
        let b = r
            .bytes()
            .await
            .map_err(|_| "The speech service sent no audio.".to_string())?;
        if b.is_empty() {
            return Err("The speech service sent no audio.".into());
        }
        Ok(b.to_vec())
    }
}

/// Test double: (api key, text, voice) per call; answers with fixed bytes or an error.
pub struct FakeSpeaker {
    pub calls: Mutex<Vec<(String, String, String)>>,
    pub result: Mutex<Result<Vec<u8>, String>>,
}

impl Default for FakeSpeaker {
    fn default() -> Self {
        FakeSpeaker {
            calls: Mutex::new(vec![]),
            result: Mutex::new(Ok(b"ID3fake-mp3".to_vec())),
        }
    }
}

#[async_trait]
impl Speaker for FakeSpeaker {
    async fn speak(&self, api_key: &str, text: &str, voice: &str) -> Result<Vec<u8>, String> {
        self.calls
            .lock()
            .unwrap()
            .push((api_key.into(), text.into(), voice.into()));
        self.result.lock().unwrap().clone()
    }
}

// ---------- cost counter and the admin switch ----------

pub fn init(c: &Connection) -> rusqlite::Result<()> {
    c.execute_batch(
        "CREATE TABLE IF NOT EXISTS tts_usage(phone_id TEXT NOT NULL, month TEXT NOT NULL, usd REAL NOT NULL,
            PRIMARY KEY(phone_id, month));",
    )
}

/// "YYYY-MM" (UTC) of a unix time.
pub fn month_of(t: i64) -> String {
    let d =
        time::OffsetDateTime::from_unix_timestamp(t).unwrap_or(time::OffsetDateTime::UNIX_EPOCH);
    format!("{:04}-{:02}", d.year(), d.month() as u8)
}

/// Read-aloud cost of a phone in the month of `at`: what `GET /v1/phone/settings` shows as `tts_used_usd_month`.
pub fn used_usd_month(c: &Connection, phone: &str, at: i64) -> f64 {
    init(c).ok();
    c.query_row(
        "SELECT usd FROM tts_usage WHERE phone_id=?1 AND month=?2",
        params![phone, month_of(at)],
        |r| r.get(0),
    )
    .optional()
    .ok()
    .flatten()
    .unwrap_or(0.0)
}

pub fn cost_usd(chars: usize) -> f64 {
    chars as f64 * USD_PER_1000 / 1000.0
}

/// Admin switch for reading aloud (on unless turned off). The Deepgram key stays in `transcribe`.
pub fn enabled(c: &Connection) -> bool {
    c.query_row("SELECT 1 FROM settings WHERE k='tts_off'", [], |_| Ok(()))
        .optional()
        .ok()
        .flatten()
        .is_none()
}

pub fn set_enabled(c: &Connection, on: bool) -> rusqlite::Result<()> {
    if on {
        c.execute("DELETE FROM settings WHERE k='tts_off'", [])?;
    } else {
        c.execute(
            "INSERT INTO settings(k,v) VALUES('tts_off',x'31') ON CONFLICT(k) DO UPDATE SET v=x'31'",
            [],
        )?;
    }
    Ok(())
}

// ---------- the request ----------

/// The phone settings this route needs (R1's settings store provides them).
pub struct Settings {
    /// `auto`, `always` or `never`
    pub speak: String,
    pub tts_cap_usd: f64,
}

fn cache_path(data_dir: &Path, msg: &str, lang: &str) -> std::path::PathBuf {
    data_dir.join("tts").join(format!("{msg}.{lang}.mp3"))
}

fn cache_aad(msg: &str, lang: &str) -> String {
    format!("tts:{msg}:{lang}")
}

/// Delete cached audio older than `max_age` seconds (call next to the blob purge).
pub fn purge(data_dir: &Path, now: i64, max_age: i64) -> usize {
    let mut n = 0;
    if let Ok(rd) = std::fs::read_dir(data_dir.join("tts")) {
        for e in rd.flatten() {
            let old = e
                .metadata()
                .and_then(|m| m.modified())
                .ok()
                .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                .is_some_and(|d| now - d.as_secs() as i64 > max_age);
            if old && std::fs::remove_file(e.path()).is_ok() {
                n += 1;
            }
        }
    }
    n
}

/// Everything `GET /v1/phone/speech/<message_id>` does after authentication: access, text, cache, cap, Deepgram.
/// `lang_q` = the `?lang=` value. Never holds the database lock across the Deepgram call.
#[allow(clippy::too_many_arguments)]
pub async fn generate(
    db: &Mutex<Connection>,
    key: &Key,
    data_dir: &Path,
    speaker: &dyn Speaker,
    phone: &str,
    workspaces: &[String],
    settings: &Settings,
    msg_id: &str,
    lang_q: Option<&str>,
    at: i64,
) -> Res<Vec<u8>> {
    let none = || not_found("No audio for this message.");
    if let Some(l) = lang_q {
        if l != "de" && l != "en" {
            return Err(invalid("`lang` must be `de` or `en`."));
        }
    }
    if settings.speak == "never" {
        return Err(none());
    }
    let (text, lang, api_key) = {
        let c = db.lock().unwrap();
        let since: i64 = c
            .query_row(
                "SELECT COALESCE(paired_at, created_at) FROM phones WHERE id=?1",
                [phone],
                |r| r.get(0),
            )
            .optional()?
            .ok_or_else(none)?;
        // same filter as /v1/phone/messages: a text to this phone, or to `phones` after it paired, from its list
        let m = c
            .query_row(
                "SELECT id,payload FROM messages WHERE id=?1 AND type='text' AND from_addr IN (SELECT value FROM json_each(?2))
                   AND ((to_addr='phones' AND stored_at>=?3) OR to_addr=?4)",
                params![
                    msg_id,
                    serde_json::to_string(workspaces).unwrap_or("[]".into()),
                    since,
                    phone
                ],
                |r| Ok((r.get::<_, String>(0)?, r.get::<_, Vec<u8>>(1)?)),
            )
            .optional()?
            .ok_or_else(none)?;
        let v: Value = crypto::open(key, &m.0, &m.1)
            .and_then(|b| serde_json::from_slice(&b).ok())
            .unwrap_or(Value::Null);
        let body = v["body"].clone();
        if body["speak"].is_null() && settings.speak != "always" {
            return Err(none());
        }
        let text = spoken_text(&body);
        if text.is_empty() {
            return Err(none());
        }
        let lang = lang_q
            .or(body["speak"]["lang"]
                .as_str()
                .filter(|l| *l == "de" || *l == "en"))
            .unwrap_or("en")
            .to_string();
        // cached audio is free and always served
        if let Ok(raw) = std::fs::read(cache_path(data_dir, msg_id, &lang)) {
            if let Some(mp3) = crypto::open(key, &cache_aad(msg_id, &lang), &raw) {
                return Ok(mp3);
            }
        }
        let api_key = if enabled(&c) {
            crate::transcribe::get_key(&c, key)
        } else {
            None
        };
        let api_key = api_key.ok_or_else(tts_off)?;
        let cost = cost_usd(text.chars().count());
        if used_usd_month(&c, phone, at) + cost > settings.tts_cap_usd + 1e-9 {
            return Err(tts_cap_reached());
        }
        (text, lang, api_key)
    };
    let mp3 = speaker
        .speak(&api_key, &text, voice(&lang))
        .await
        .map_err(tts_failed)?;
    {
        let c = db.lock().unwrap();
        init(&c)?;
        c.execute(
            "INSERT INTO tts_usage(phone_id,month,usd) VALUES(?1,?2,?3)
             ON CONFLICT(phone_id,month) DO UPDATE SET usd=usd+?3",
            params![phone, month_of(at), cost_usd(text.chars().count())],
        )?;
    }
    let p = cache_path(data_dir, msg_id, &lang);
    if let Some(dir) = p.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    // a failed cache write only costs a second generation next time
    let _ = std::fs::write(p, crypto::seal(key, &cache_aad(msg_id, &lang), &mp3));
    Ok(mp3)
}
