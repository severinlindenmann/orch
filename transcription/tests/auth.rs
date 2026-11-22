//! Sign-in: every route but health needs a valid token; limits per token; removed tokens stop at once.
use std::sync::Arc;

use axum::http::StatusCode;
use orch_transcription::engine::FakeEngine;
use serde_json::Value;

mod common;
use common::{fixture, harness};

#[tokio::test]
async fn no_or_wrong_token_is_refused_and_the_engine_is_not_asked() {
    let fake = Arc::new(FakeEngine::default());
    let h = harness(fake.clone());
    let wav = fixture("jfk.wav");
    let ct = [("content-type", "audio/wav")];
    let wrong = format!("ort_{}", "A".repeat(43));
    for tok in [None, Some("nonsense"), Some(wrong.as_str())] {
        let (s, b) = h
            .call("POST", "/v1/transcribe", tok, &ct, wav.clone())
            .await;
        assert_eq!(s, StatusCode::UNAUTHORIZED, "{tok:?}");
        let v: Value = serde_json::from_slice(&b).unwrap();
        assert_eq!(v["error"], "unauthorized");
    }
    assert!(fake.calls.lock().unwrap().is_empty());
    let (s, _) = h
        .call("POST", "/v1/transcribe", Some(&h.token), &ct, wav)
        .await;
    assert_eq!(s, StatusCode::OK);
}

#[tokio::test]
async fn health_needs_no_token_and_says_nothing_private() {
    let h = harness(Arc::new(FakeEngine::default()));
    let (s, b) = h.call("GET", "/v1/health", None, &[], vec![]).await;
    assert_eq!(s, StatusCode::OK);
    let v: Value = serde_json::from_slice(&b).unwrap();
    assert_eq!(v["ok"], true);
    assert!(v.get("model").is_none() && v.get("tokens").is_none());
}

#[tokio::test]
async fn a_removed_token_is_refused_from_the_next_request() {
    let h = harness(Arc::new(FakeEngine::default()));
    let t = h.token_for("ws_gone");
    let ct = [("content-type", "audio/wav")];
    let (s, _) = h
        .call("POST", "/v1/transcribe", Some(&t), &ct, fixture("jfk.wav"))
        .await;
    assert_eq!(s, StatusCode::OK);
    assert!(h.app.tokens.remove("ws_gone").unwrap());
    let (s, _) = h
        .call("POST", "/v1/transcribe", Some(&t), &ct, fixture("jfk.wav"))
        .await;
    assert_eq!(s, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn each_token_has_its_own_per_minute_limit() {
    let h = harness(Arc::new(FakeEngine::default()));
    let small = h.app.tokens.add("small", 2).unwrap();
    let ct = [("content-type", "audio/wav")];
    let wav = fixture("jfk.wav");
    for _ in 0..2 {
        let (s, _) = h
            .call("POST", "/v1/transcribe", Some(&small), &ct, wav.clone())
            .await;
        assert_eq!(s, StatusCode::OK);
    }
    let (s, b) = h
        .call("POST", "/v1/transcribe", Some(&small), &ct, wav.clone())
        .await;
    assert_eq!(s, StatusCode::TOO_MANY_REQUESTS);
    assert_eq!(
        serde_json::from_slice::<Value>(&b).unwrap()["error"],
        "rate_limited"
    );
    // another token is not affected
    let (s, _) = h
        .call("POST", "/v1/transcribe", Some(&h.token), &ct, wav)
        .await;
    assert_eq!(s, StatusCode::OK);
}

#[tokio::test]
async fn token_file_holds_hashes_only() {
    let h = harness(Arc::new(FakeEngine::default()));
    let file = std::fs::read_to_string(h.dir.path().join("tokens.json")).unwrap();
    assert!(!file.contains(&h.token[4..]));
    assert!(file.contains("\"tester\""));
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let m = std::fs::metadata(h.dir.path().join("tokens.json"))
            .unwrap()
            .permissions()
            .mode();
        assert_eq!(m & 0o777, 0o600);
    }
}
