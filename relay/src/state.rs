use crate::crypto::Key;
use crate::push::{ApnsConfig, Pusher};
use crate::speech::{Aura, Speaker};
use crate::transcribe::{Deepgram, Transcriber};
use rusqlite::Connection;
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use tokio::sync::Notify;

#[derive(Clone)]
pub struct Config {
    pub public_listen: String,
    pub admin_listen: String,
    pub data_dir: PathBuf,
    pub master_key_file: PathBuf,
    pub admin_token: String,
    pub public_url: String,
    pub install_ref: String,
    pub apns: Option<ApnsConfig>,
}

impl Config {
    pub fn from_env() -> Result<Config, String> {
        let get = |k: &str| std::env::var(k).ok().filter(|v| !v.is_empty());
        let admin_token = match (
            get("ORCH_RELAY_ADMIN_TOKEN"),
            get("ORCH_RELAY_ADMIN_TOKEN_FILE"),
        ) {
            (Some(t), _) => t,
            (None, Some(f)) => std::fs::read_to_string(&f)
                .map_err(|e| format!("admin token file {f}: {e}"))?
                .trim()
                .to_string(),
            _ => return Err("set ORCH_RELAY_ADMIN_TOKEN or ORCH_RELAY_ADMIN_TOKEN_FILE".into()),
        };
        if admin_token.len() < 20 {
            return Err("admin token is too short".into());
        }
        let apns = get("ORCH_RELAY_APNS_KEY_FILE").map(|key_file| ApnsConfig {
            key_file,
            key_id: get("ORCH_RELAY_APNS_KEY_ID").unwrap_or("TD27F9Z9V7".into()),
            team_id: get("ORCH_RELAY_APNS_TEAM_ID").unwrap_or("77D4THRYUN".into()),
            topic: get("ORCH_RELAY_APNS_TOPIC").unwrap_or("io.severin.orch".into()),
        });
        Ok(Config {
            public_listen: get("ORCH_RELAY_LISTEN").unwrap_or("127.0.0.1:8103".into()),
            admin_listen: get("ORCH_RELAY_ADMIN_LISTEN").unwrap_or("127.0.0.1:8412".into()),
            data_dir: get("ORCH_RELAY_DATA_DIR")
                .unwrap_or("/var/lib/orch-relay".into())
                .into(),
            master_key_file: get("ORCH_RELAY_MASTER_KEY_FILE")
                .unwrap_or("/etc/orch-relay/master.key".into())
                .into(),
            admin_token,
            public_url: get("ORCH_RELAY_PUBLIC_ORIGIN")
                .unwrap_or("https://relay.severin.io".into())
                .trim_end_matches('/')
                .to_string(),
            install_ref: get("ORCH_INSTALL_REF").unwrap_or("main".into()),
            apns,
        })
    }
}

pub struct App {
    pub cfg: Config,
    pub key: Key,
    pub db: Mutex<Connection>,
    pub notify: Notify,
    pub pusher: Arc<dyn Pusher>,
    pub transcriber: Arc<dyn Transcriber>,
    /// Text to speech (Deepgram Aura); tests put a fake in.
    pub speaker: Mutex<Arc<dyn Speaker>>,
    /// phone/workspace id -> (window start, calls in window)
    pub transcribe_rate: Mutex<HashMap<String, (i64, u32)>>,
    /// Phone uploads in flight (memory bound).
    pub upload_slots: tokio::sync::Semaphore,
    /// Waiting for an upload slot / silence between two chunks, in ms (fields so tests can shorten them).
    pub upload_wait_ms: std::sync::atomic::AtomicU64,
    pub upload_idle_ms: std::sync::atomic::AtomicU64,
    /// From this age on, an upload must average at least 16 KB/s (tests lower it).
    pub upload_grace_ms: std::sync::atomic::AtomicU64,
    /// phone id -> bytes reserved by its upload in flight (one at a time per phone)
    pub upload_inflight: Mutex<HashMap<String, i64>>,
    /// phone id -> (window start, calls in window) for `POST /v1/phone/invitations/redeem`
    pub redeem_rate: Mutex<HashMap<String, (i64, u32)>>,
    /// webhook id -> (window start, accepted calls in window); see `webhook_admit`
    pub webhook_rate: Mutex<HashMap<String, (i64, u32)>>,
    /// webhook id -> (UTC day number, accepted payload bytes that day)
    pub webhook_bytes: Mutex<HashMap<String, (i64, u64)>>,
    /// Limits for `webhook_admit` (fields so tests can lower them).
    pub webhook_calls_per_minute: std::sync::atomic::AtomicU32,
    pub webhook_bytes_per_day: std::sync::atomic::AtomicU64,
    /// "workspace|phone" -> text-push budget state
    pub push_budget: Mutex<HashMap<String, PushBudget>>,
    /// Subscribers: open streams, rate limits, push rounds (subs.rs).
    pub subs: crate::subs::Live,
}

/// Text pushes per (workspace, phone): at most 1 per 10 s and 30 per hour. Extra texts are stored, not pushed.
#[derive(Default)]
pub struct PushBudget {
    last: i64,
    hour_start: i64,
    in_hour: u32,
}

impl PushBudget {
    pub fn allow(&mut self, now: i64) -> bool {
        if now - self.last < 10 {
            return false;
        }
        if now - self.hour_start >= 3600 {
            self.hour_start = now;
            self.in_hour = 0;
        }
        if self.in_hour >= 30 {
            return false;
        }
        self.in_hour += 1;
        self.last = now;
        true
    }
}

pub type AppState = Arc<App>;

/// Accepted calls per webhook per fixed one-minute window.
pub const WEBHOOK_CALLS_PER_MINUTE: u32 = 60;
/// Accepted payload bytes per webhook per UTC day (20 MB).
pub const WEBHOOK_BYTES_PER_DAY: u64 = 20 * 1024 * 1024;
/// Above this many entries, the webhook rate maps drop entries of past windows/days.
const WEBHOOK_RATE_PRUNE_AT: usize = 1024;

/// Why `webhook_admit` refused a call; carries the seconds until it may be retried.
#[derive(Debug, PartialEq)]
pub enum WebhookLimit {
    Calls(i64),
    Bytes(i64),
}

impl App {
    pub fn new(cfg: Config, key: Key, pusher: Arc<dyn Pusher>) -> Result<AppState, String> {
        Self::with_transcriber(cfg, key, pusher, Arc::new(Deepgram::default()))
    }

    pub fn with_transcriber(
        cfg: Config,
        key: Key,
        pusher: Arc<dyn Pusher>,
        transcriber: Arc<dyn Transcriber>,
    ) -> Result<AppState, String> {
        std::fs::create_dir_all(cfg.data_dir.join("blobs")).map_err(|e| e.to_string())?;
        let conn = Connection::open(cfg.data_dir.join("relay.db")).map_err(|e| e.to_string())?;
        crate::store::init(&conn).map_err(|e| e.to_string())?;
        Ok(Arc::new(App {
            cfg,
            key,
            db: Mutex::new(conn),
            notify: Notify::new(),
            pusher,
            transcriber,
            speaker: Mutex::new(Arc::new(Aura::default())),
            transcribe_rate: Mutex::new(HashMap::new()),
            redeem_rate: Mutex::new(HashMap::new()),
            upload_slots: tokio::sync::Semaphore::new(4),
            upload_wait_ms: 5_000.into(),
            upload_idle_ms: 20_000.into(),
            upload_grace_ms: 30_000.into(),
            upload_inflight: Mutex::new(HashMap::new()),
            push_budget: Mutex::new(HashMap::new()),
            webhook_rate: Mutex::new(HashMap::new()),
            webhook_bytes: Mutex::new(HashMap::new()),
            webhook_calls_per_minute: WEBHOOK_CALLS_PER_MINUTE.into(),
            webhook_bytes_per_day: WEBHOOK_BYTES_PER_DAY.into(),
            subs: Default::default(),
        }))
    }

    pub fn upload_wait(&self) -> std::time::Duration {
        std::time::Duration::from_millis(
            self.upload_wait_ms
                .load(std::sync::atomic::Ordering::Relaxed),
        )
    }

    pub fn upload_idle(&self) -> std::time::Duration {
        std::time::Duration::from_millis(
            self.upload_idle_ms
                .load(std::sync::atomic::Ordering::Relaxed),
        )
    }

    /// Counts one call of `bytes` payload against webhook `id` at time `now`, or refuses it without counting.
    /// Call only after the token was verified, so a caller without the token cannot use up the limit.
    pub fn webhook_admit(&self, id: &str, bytes: u64, now: i64) -> Result<(), WebhookLimit> {
        use std::sync::atomic::Ordering::Relaxed;
        let per_min = self.webhook_calls_per_minute.load(Relaxed);
        let per_day = self.webhook_bytes_per_day.load(Relaxed);
        let day = now.div_euclid(86_400);
        let mut rate = self.webhook_rate.lock().unwrap();
        let mut used = self.webhook_bytes.lock().unwrap();
        if rate.len() > WEBHOOK_RATE_PRUNE_AT {
            rate.retain(|_, e| now - e.0 < 60);
        }
        if used.len() > WEBHOOK_RATE_PRUNE_AT {
            used.retain(|_, e| e.0 == day);
        }
        let r = rate.entry(id.to_string()).or_insert((now, 0));
        if now - r.0 >= 60 {
            *r = (now, 0);
        }
        let u = used.entry(id.to_string()).or_insert((day, 0));
        if u.0 != day {
            *u = (day, 0);
        }
        if r.1 >= per_min {
            return Err(WebhookLimit::Calls((r.0 + 60 - now).max(1)));
        }
        if u.1.saturating_add(bytes) > per_day {
            return Err(WebhookLimit::Bytes((day + 1) * 86_400 - now));
        }
        r.1 += 1;
        u.1 += bytes;
        Ok(())
    }

    pub fn blob_path(&self, id: &str) -> PathBuf {
        self.cfg.data_dir.join("blobs").join(id)
    }
}

#[cfg(test)]
mod tests {
    use super::PushBudget;

    #[test]
    fn push_budget_10s_and_30_per_hour() {
        let mut b = PushBudget::default();
        assert!(b.allow(1000));
        assert!(!b.allow(1005), "within 10 s");
        let mut t = 1000;
        for _ in 0..29 {
            t += 10;
            assert!(b.allow(t));
        }
        assert!(!b.allow(t + 10), "31st in the hour");
        assert!(b.allow(1000 + 3600), "new hour");
    }
}
