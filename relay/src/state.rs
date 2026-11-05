use crate::crypto::Key;
use crate::push::{ApnsConfig, Pusher};
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
    /// phone/workspace id -> (window start, calls in window)
    pub transcribe_rate: Mutex<HashMap<String, (i64, u32)>>,
    /// "workspace|phone" -> text-push budget state
    pub push_budget: Mutex<HashMap<String, PushBudget>>,
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
            transcribe_rate: Mutex::new(HashMap::new()),
            push_budget: Mutex::new(HashMap::new()),
        }))
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
