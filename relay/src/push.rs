//! APNs push behind a trait. The real sender is off unless RELAY_APNS_ENABLED=1; tests use `FakePusher`.
use async_trait::async_trait;
use serde_json::Value;
use std::sync::Mutex;

#[async_trait]
pub trait Pusher: Send + Sync {
    async fn send(&self, sandbox: bool, device_token: &str, payload: &Value) -> Result<(), String>;
}

pub struct NoPush;

#[async_trait]
impl Pusher for NoPush {
    async fn send(&self, _: bool, _: &str, _: &Value) -> Result<(), String> {
        Ok(())
    }
}

#[derive(Default)]
pub struct FakePusher {
    pub sent: Mutex<Vec<(bool, String, Value)>>,
}

#[async_trait]
impl Pusher for FakePusher {
    async fn send(&self, sandbox: bool, token: &str, payload: &Value) -> Result<(), String> {
        self.sent
            .lock()
            .unwrap()
            .push((sandbox, token.to_string(), payload.clone()));
        Ok(())
    }
}

#[derive(Clone)]
pub struct ApnsConfig {
    pub key_file: String,
    pub key_id: String,
    pub team_id: String,
    pub topic: String,
}

pub struct ApnsPusher {
    cfg: ApnsConfig,
    client: reqwest::Client,
    jwt: Mutex<Option<(i64, String)>>,
}

impl ApnsPusher {
    pub fn new(cfg: ApnsConfig) -> Self {
        ApnsPusher {
            cfg,
            client: reqwest::Client::builder()
                .http2_prior_knowledge()
                .build()
                .expect("http client"),
            jwt: Mutex::new(None),
        }
    }

    fn token(&self) -> Result<String, String> {
        let now = crate::util::now();
        let mut g = self.jwt.lock().unwrap();
        if let Some((t, j)) = g.as_ref() {
            if now - t < 40 * 60 {
                return Ok(j.clone());
            }
        }
        let pem = std::fs::read(&self.cfg.key_file).map_err(|e| e.to_string())?;
        let key = jsonwebtoken::EncodingKey::from_ec_pem(&pem).map_err(|e| e.to_string())?;
        let mut h = jsonwebtoken::Header::new(jsonwebtoken::Algorithm::ES256);
        h.kid = Some(self.cfg.key_id.clone());
        let claims = serde_json::json!({"iss": self.cfg.team_id, "iat": now});
        let j = jsonwebtoken::encode(&h, &claims, &key).map_err(|e| e.to_string())?;
        *g = Some((now, j.clone()));
        Ok(j)
    }
}

#[async_trait]
impl Pusher for ApnsPusher {
    async fn send(&self, sandbox: bool, device_token: &str, payload: &Value) -> Result<(), String> {
        let host = if sandbox {
            "api.sandbox.push.apple.com"
        } else {
            "api.push.apple.com"
        };
        let r = self
            .client
            .post(format!("https://{host}/3/device/{device_token}"))
            .header("authorization", format!("bearer {}", self.token()?))
            .header("apns-topic", &self.cfg.topic)
            .header("apns-push-type", "alert")
            .json(payload)
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if r.status().is_success() {
            Ok(())
        } else {
            Err(format!("apns {}", r.status()))
        }
    }
}
