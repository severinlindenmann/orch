#![allow(dead_code)]
use axum::body::Body;
use axum::http::{HeaderMap, Request, StatusCode};
use axum::Router;
use orch_publish::{admin_router, new_state, public_router, Config, State};
use serde_json::{json, Value};
use std::sync::atomic::{AtomicU16, Ordering};
use tower::ServiceExt;

static N: AtomicU16 = AtomicU16::new(0);
pub const ADMIN: &str = "admin-test-token";

pub struct T {
    pub st: State,
    pub public: Router,
    pub admin: Router,
    pub dir: tempfile::TempDir,
}

pub fn setup_with(f: impl FnOnce(&mut Config)) -> T {
    let dir = tempfile::tempdir().unwrap();
    let mut cfg = Config::new(dir.path().to_path_buf(), ADMIN.into());
    let n = N.fetch_add(1, Ordering::SeqCst);
    cfg.port_lo = 18100 + n * 5;
    cfg.port_hi = cfg.port_lo + 4;
    cfg.health_secs = 8;
    cfg.public_url = "https://publish.test".into();
    f(&mut cfg);
    let st = new_state(cfg).unwrap();
    T {
        public: public_router(st.clone()),
        admin: admin_router(st.clone()),
        st,
        dir,
    }
}

pub fn setup() -> T {
    setup_with(|_| {})
}

pub struct Resp {
    pub status: StatusCode,
    pub headers: HeaderMap,
    pub body: Vec<u8>,
}
impl Resp {
    pub fn json(&self) -> Value {
        serde_json::from_slice(&self.body).unwrap_or_else(|_| panic!("not json: {}", self.text()))
    }
    pub fn text(&self) -> String {
        String::from_utf8_lossy(&self.body).to_string()
    }
}

pub async fn call(
    r: &Router,
    method: &str,
    uri: &str,
    headers: &[(&str, &str)],
    body: Vec<u8>,
) -> Resp {
    let mut b = Request::builder().method(method).uri(uri);
    for (k, v) in headers {
        b = b.header(*k, *v);
    }
    let resp = r
        .clone()
        .oneshot(b.body(Body::from(body)).unwrap())
        .await
        .unwrap();
    let (p, body) = resp.into_parts();
    let body = axum::body::to_bytes(body, 1 << 30).await.unwrap().to_vec();
    Resp {
        status: p.status,
        headers: p.headers,
        body,
    }
}

impl T {
    /// Adds a workspace through the admin API. Returns (id, token).
    pub async fn workspace(&self, name: &str, rights: Value) -> (String, String) {
        let r = call(
            &self.admin,
            "POST",
            "/admin/api/workspaces",
            &[
                ("x-orch-admin", ADMIN),
                ("content-type", "application/json"),
            ],
            json!({"name": name, "description": "d", "tags": ["a"], "rights": rights})
                .to_string()
                .into_bytes(),
        )
        .await;
        assert_eq!(r.status, 201, "{}", r.text());
        let j = r.json();
        (
            j["id"].as_str().unwrap().into(),
            j["token"].as_str().unwrap().into(),
        )
    }

    pub async fn api(&self, ws: &(String, String), method: &str, uri: &str, body: Vec<u8>) -> Resp {
        let auth = format!("Bearer {}", ws.1);
        call(
            &self.public,
            method,
            uri,
            &[("x-orch-workspace", &ws.0), ("authorization", &auth)],
            body,
        )
        .await
    }

    pub async fn adm(&self, method: &str, uri: &str, body: Value) -> Resp {
        let b = if body.is_null() {
            vec![]
        } else {
            body.to_string().into_bytes()
        };
        call(
            &self.admin,
            method,
            uri,
            &[
                ("x-orch-admin", ADMIN),
                ("content-type", "application/json"),
            ],
            b,
        )
        .await
    }
}

pub fn all_rights() -> Value {
    json!({"files": true, "apps": true, "permanent": true, "public": true})
}
pub fn basic_rights() -> Value {
    json!({"files": true, "apps": true, "permanent": false, "public": false})
}

/// .tar.gz of (path, content) pairs
pub fn bundle(files: &[(&str, &str)]) -> Vec<u8> {
    let gz = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::fast());
    let mut tb = tar::Builder::new(gz);
    for (p, c) in files {
        let mut h = tar::Header::new_gnu();
        h.set_size(c.len() as u64);
        h.set_mode(0o644);
        h.set_cksum();
        tb.append_data(&mut h, p, c.as_bytes()).unwrap();
    }
    tb.into_inner().unwrap().finish().unwrap()
}

pub const PY_APP: &str = r#"import os
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = ("hello " + self.path + " " + os.environ.get("BASE_PATH", "")).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass
HTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
"#;

pub fn py_toml(name: &str, extra: &str) -> String {
    format!("name = \"{name}\"\nstack = \"python\"\nstart = \"python3 main.py\"\nhealth = \"/health\"\n{extra}\n")
}

/// a valid OPF1 blob from the contract vector
pub fn vector_blob() -> Vec<u8> {
    let v: Value = serde_json::from_str(
        &std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../contracts/vectors/publish-blob-v1.json"
        ))
        .unwrap(),
    )
    .unwrap();
    let h = v["good"]["blob_hex"].as_str().unwrap();
    (0..h.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&h[i..i + 2], 16).unwrap())
        .collect()
}
