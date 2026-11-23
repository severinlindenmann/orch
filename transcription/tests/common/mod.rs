//! Shared test setup: an app with one signed-in token in a temp data folder.
#![allow(dead_code)]
use std::sync::Arc;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use axum::Router;
use http_body_util::BodyExt;
use orch_transcription::engine::Engine;
use orch_transcription::{router, App, AppState};
use serde_json::Value;
use tower::ServiceExt;

pub struct H {
    pub dir: tempfile::TempDir,
    pub app: AppState,
    pub router: Router,
    pub token: String,
}

pub fn harness(engine: Arc<dyn Engine>) -> H {
    let dir = tempfile::tempdir().unwrap();
    let app = App::new(engine, dir.path());
    let token = app.tokens.add("tester", 1000).unwrap();
    H {
        router: router(app.clone()),
        app,
        dir,
        token,
    }
}

impl H {
    pub fn token_for(&self, name: &str) -> String {
        self.app.tokens.add(name, 1000).unwrap()
    }

    /// Any request; `token` None = no Authorization header.
    pub async fn call(
        &self,
        method: &str,
        uri: &str,
        token: Option<&str>,
        headers: &[(&str, &str)],
        body: Vec<u8>,
    ) -> (StatusCode, Vec<u8>) {
        let mut b = Request::builder().method(method).uri(uri);
        if let Some(t) = token {
            b = b.header("authorization", format!("Bearer {t}"));
        }
        for (k, v) in headers {
            b = b.header(*k, *v);
        }
        let r = self
            .router
            .clone()
            .oneshot(b.body(Body::from(body)).unwrap())
            .await
            .unwrap();
        let s = r.status();
        (
            s,
            r.into_body().collect().await.unwrap().to_bytes().to_vec(),
        )
    }

    pub async fn post(&self, uri: &str, ct: &str, body: Vec<u8>) -> (StatusCode, Value) {
        let (s, b) = self
            .call(
                "POST",
                uri,
                Some(&self.token.clone()),
                &[("content-type", ct)],
                body,
            )
            .await;
        (s, serde_json::from_slice(&b).unwrap_or(Value::Null))
    }
}

pub fn fixture(name: &str) -> Vec<u8> {
    std::fs::read(format!(
        "{}/tests/fixtures/{name}",
        env!("CARGO_MANIFEST_DIR")
    ))
    .unwrap()
}
