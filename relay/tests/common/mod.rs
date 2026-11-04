#![allow(dead_code)]
use orch_relay::push::FakePusher;
use orch_relay::state::{App, AppState, Config};
use rand::Rng;
use serde_json::{json, Value};
use std::future::IntoFuture;
use std::sync::Arc;

pub const ADMIN: &str = "admin-token-for-tests-0123456789abcdef";

pub struct T {
    pub base: String,
    pub admin: String,
    pub app: AppState,
    pub push: Arc<FakePusher>,
    pub http: reqwest::Client,
    pub dir: tempfile::TempDir,
}

pub struct Ws {
    pub id: String,
    pub token: String,
}

async fn bind() -> tokio::net::TcpListener {
    loop {
        let p = rand::thread_rng().gen_range(18000..19000);
        if let Ok(l) = tokio::net::TcpListener::bind(("127.0.0.1", p)).await {
            return l;
        }
    }
}

pub async fn start() -> T {
    let dir = tempfile::tempdir().unwrap();
    let (pl, al) = (bind().await, bind().await);
    let base = format!("http://{}", pl.local_addr().unwrap());
    let admin = format!("http://{}", al.local_addr().unwrap());
    let cfg = Config {
        public_listen: String::new(),
        admin_listen: String::new(),
        data_dir: dir.path().to_path_buf(),
        master_key_file: dir.path().join("master.key"),
        admin_token: ADMIN.into(),
        public_url: "https://relay.test".into(),
        install_ref: "develop".into(),
        apns: None,
    };
    let push = Arc::new(FakePusher::default());
    let app = App::new(cfg, [7u8; 32], push.clone()).unwrap();
    tokio::spawn(axum::serve(pl, orch_relay::api::router(app.clone())).into_future());
    tokio::spawn(axum::serve(al, orch_relay::admin::router(app.clone())).into_future());
    T {
        base,
        admin,
        app,
        push,
        http: reqwest::Client::new(),
        dir,
    }
}

pub fn mid() -> String {
    orch_relay::util::rand_id("m_", 16)
}

impl T {
    pub async fn admin_json(&self, method: &str, path: &str, body: Option<Value>) -> (u16, Value) {
        let m = reqwest::Method::from_bytes(method.as_bytes()).unwrap();
        let mut r = self
            .http
            .request(m, format!("{}{}", self.admin, path))
            .header("X-Orch-Admin", ADMIN);
        if let Some(b) = body {
            r = r.json(&b);
        }
        let resp = r.send().await.unwrap();
        let s = resp.status().as_u16();
        (s, resp.json().await.unwrap_or(Value::Null))
    }

    pub async fn add_ws(&self, name: &str) -> Ws {
        let (s, v) = self
            .admin_json(
                "POST",
                "/admin/api/workspaces",
                Some(json!({"name": name, "description": "d", "tags": ["x"]})),
            )
            .await;
        assert_eq!(s, 201, "{v}");
        Ws {
            id: v["id"].as_str().unwrap().into(),
            token: v["token"].as_str().unwrap().into(),
        }
    }

    pub async fn rules(&self, rules: Value) {
        let (s, v) = self
            .admin_json("PUT", "/admin/api/rules", Some(json!({"rules": rules})))
            .await;
        assert_eq!(s, 200, "{v}");
        // tests start from an empty inbox: drop the refresh-hints the rule change made
        self.app
            .db
            .lock()
            .unwrap()
            .execute("DELETE FROM messages WHERE type='refresh-hint'", [])
            .unwrap();
    }

    pub async fn call(
        &self,
        w: &Ws,
        method: &str,
        path: &str,
        body: Option<Value>,
    ) -> (u16, Value) {
        let m = reqwest::Method::from_bytes(method.as_bytes()).unwrap();
        let mut r = self
            .http
            .request(m, format!("{}{}", self.base, path))
            .header("X-Orch-Workspace", &w.id)
            .header("Authorization", format!("Bearer {}", w.token));
        if let Some(b) = body {
            r = r.json(&b);
        }
        let resp = r.send().await.unwrap();
        let s = resp.status().as_u16();
        (s, resp.json().await.unwrap_or(Value::Null))
    }

    pub async fn send(&self, from: &Ws, to: &str, typ: &str, body: Value) -> (u16, Value) {
        let m = json!({"schema": "orch.msg/1", "id": mid(), "from": from.id, "to": to, "type": typ,
            "created_at": "2026-11-04T10:00:00Z", "ticket": "t_7k3f9q", "body": body});
        self.call(from, "POST", "/v1/messages", Some(m)).await
    }

    pub async fn inbox(&self, w: &Ws) -> Vec<Value> {
        self.call(w, "GET", "/v1/inbox", None).await.1["items"]
            .as_array()
            .unwrap()
            .clone()
    }

    /// Admin adds a phone, the phone pairs. Returns (phone id, token).
    pub async fn pair_phone(&self, ws: &[&Ws]) -> (String, String) {
        let ids: Vec<&str> = ws.iter().map(|w| w.id.as_str()).collect();
        let (s, v) = self
            .admin_json(
                "POST",
                "/admin/api/phones",
                Some(json!({"name": "Test iPhone", "workspaces": ids})),
            )
            .await;
        assert_eq!(s, 201, "{v}");
        let link = v["link"].as_str().unwrap();
        let code = link.split("code=").nth(1).unwrap();
        let r = self
            .http
            .post(format!("{}/v1/phone/pair", self.base))
            .json(&json!({"code": code, "name": "Test iPhone"}))
            .send()
            .await
            .unwrap();
        assert_eq!(r.status(), 201);
        let v: Value = r.json().await.unwrap();
        (
            v["phone_id"].as_str().unwrap().into(),
            v["token"].as_str().unwrap().into(),
        )
    }

    pub async fn phone(
        &self,
        p: &(String, String),
        method: &str,
        path: &str,
        body: Option<Value>,
    ) -> (u16, Value) {
        let m = reqwest::Method::from_bytes(method.as_bytes()).unwrap();
        let mut r = self
            .http
            .request(m, format!("{}{}", self.base, path))
            .header("X-Orch-Phone", &p.0)
            .header("Authorization", format!("Bearer {}", p.1));
        if let Some(b) = body {
            r = r.json(&b);
        }
        let resp = r.send().await.unwrap();
        let s = resp.status().as_u16();
        (s, resp.json().await.unwrap_or(Value::Null))
    }
}

pub fn rule(from: &Ws, to: &Ws, flags: [bool; 4]) -> Value {
    json!({"from": from.id, "to": to.id, "text": flags[0], "files": flags[1], "delegate": flags[2], "start": flags[3]})
}
