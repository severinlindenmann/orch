//! APNs push behind a trait. The real sender is off unless RELAY_APNS_ENABLED=1; tests use `FakePusher`.
use async_trait::async_trait;
use serde_json::Value;
use std::sync::Mutex;

/// A failed push. `dead_token` = Apple says this device token is gone (410 / BadDeviceToken / Unregistered).
#[derive(Debug, Clone)]
pub struct PushError {
    pub message: String,
    pub dead_token: bool,
}

impl PushError {
    pub fn other(m: impl ToString) -> Self {
        PushError {
            message: m.to_string(),
            dead_token: false,
        }
    }
}

#[async_trait]
pub trait Pusher: Send + Sync {
    async fn send(
        &self,
        sandbox: bool,
        device_token: &str,
        payload: &Value,
    ) -> Result<(), PushError>;
}

pub struct NoPush;

#[async_trait]
impl Pusher for NoPush {
    async fn send(&self, _: bool, _: &str, _: &Value) -> Result<(), PushError> {
        Ok(())
    }
}

#[derive(Default)]
pub struct FakePusher {
    pub sent: Mutex<Vec<(bool, String, Value)>>,
    /// when set, every send is recorded and then fails with this error
    pub fail: Mutex<Option<PushError>>,
}

#[async_trait]
impl Pusher for FakePusher {
    async fn send(&self, sandbox: bool, token: &str, payload: &Value) -> Result<(), PushError> {
        self.sent
            .lock()
            .unwrap()
            .push((sandbox, token.to_string(), payload.clone()));
        match self.fail.lock().unwrap().clone() {
            Some(e) => Err(e),
            None => Ok(()),
        }
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

    fn token(&self) -> Result<String, PushError> {
        let now = crate::util::now();
        let mut g = self.jwt.lock().unwrap();
        if let Some((t, j)) = g.as_ref() {
            if now - t < 40 * 60 {
                return Ok(j.clone());
            }
        }
        let pem = std::fs::read(&self.cfg.key_file).map_err(PushError::other)?;
        let key = jsonwebtoken::EncodingKey::from_ec_pem(&pem).map_err(PushError::other)?;
        let mut h = jsonwebtoken::Header::new(jsonwebtoken::Algorithm::ES256);
        h.kid = Some(self.cfg.key_id.clone());
        let claims = serde_json::json!({"iss": self.cfg.team_id, "iat": now});
        let j = jsonwebtoken::encode(&h, &claims, &key).map_err(PushError::other)?;
        *g = Some((now, j.clone()));
        Ok(j)
    }
}

#[async_trait]
impl Pusher for ApnsPusher {
    async fn send(
        &self,
        sandbox: bool,
        device_token: &str,
        payload: &Value,
    ) -> Result<(), PushError> {
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
            .map_err(|e| PushError::other(e.without_url()))?;
        if r.status().is_success() {
            return Ok(());
        }
        let status = r.status();
        let apns_id = r
            .headers()
            .get("apns-id")
            .and_then(|v| v.to_str().ok())
            .unwrap_or("-")
            .to_string();
        let body: Value = r.json().await.unwrap_or(Value::Null);
        let reason = body["reason"].as_str().unwrap_or("unknown").to_string();
        Err(PushError {
            message: format!(
                "apns status={} apns-id={apns_id} reason={reason}",
                status.as_u16()
            ),
            dead_token: status.as_u16() == 410
                || reason == "BadDeviceToken"
                || reason == "Unregistered",
        })
    }
}
