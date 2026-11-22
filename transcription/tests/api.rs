//! The HTTP surface with the fake engine: formats, limits, silence, language, busy. No model needed.
use std::sync::Arc;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use http_body_util::BodyExt;
use orch_transcription::engine::{Engine, FakeEngine, Transcript};
use serde_json::Value;
use tower::ServiceExt;

mod common;

fn fixture(name: &str) -> Vec<u8> {
    std::fs::read(format!(
        "{}/tests/fixtures/{name}",
        env!("CARGO_MANIFEST_DIR")
    ))
    .unwrap()
}

/// A 16 kHz mono 16-bit WAV of `secs` seconds; `amp` 0 = silence, else a 300 Hz tone.
fn wav(secs: f64, amp: f32) -> Vec<u8> {
    let n = (secs * 16_000.0) as u32;
    let mut v = Vec::with_capacity(44 + n as usize * 2);
    v.extend_from_slice(b"RIFF");
    v.extend_from_slice(&(36 + n * 2).to_le_bytes());
    v.extend_from_slice(b"WAVEfmt ");
    v.extend_from_slice(&16u32.to_le_bytes());
    v.extend_from_slice(&1u16.to_le_bytes());
    v.extend_from_slice(&1u16.to_le_bytes());
    v.extend_from_slice(&16_000u32.to_le_bytes());
    v.extend_from_slice(&32_000u32.to_le_bytes());
    v.extend_from_slice(&2u16.to_le_bytes());
    v.extend_from_slice(&16u16.to_le_bytes());
    v.extend_from_slice(b"data");
    v.extend_from_slice(&(n * 2).to_le_bytes());
    for i in 0..n {
        let s = (2.0 * std::f32::consts::PI * 300.0 * i as f32 / 16_000.0).sin() * amp;
        v.extend_from_slice(&((s * 32_000.0) as i16).to_le_bytes());
    }
    v
}

async fn post(engine: Arc<dyn Engine>, uri: &str, ct: &str, body: Vec<u8>) -> (StatusCode, Value) {
    common::harness(engine).post(uri, ct, body).await
}

#[tokio::test]
async fn each_format_decodes_to_16k_mono() {
    // jfk.* is 11 s of speech: about 176 000 samples at 16 kHz, whatever the container
    for (f, ct) in [
        ("jfk.wav", "audio/wav"),
        ("jfk.m4a", "audio/m4a"),
        ("jfk.webm", "audio/webm"),
        ("jfk.ogg", "audio/ogg"),
        ("jfk.aac", "audio/aac"),
    ] {
        let fake = Arc::new(FakeEngine::default());
        let (s, v) = post(fake.clone(), "/v1/transcribe", ct, fixture(f)).await;
        assert_eq!(s, StatusCode::OK, "{f}: {v}");
        assert_eq!(v["text"], "hello world");
        let d = v["duration"].as_f64().unwrap();
        assert!((10.5..11.5).contains(&d), "{f}: duration {d}");
        let calls = fake.calls.lock().unwrap();
        assert_eq!(calls.len(), 1);
        assert!(
            (168_000..184_000).contains(&calls[0].0),
            "{f}: {} samples",
            calls[0].0
        );
    }
}

#[tokio::test]
async fn content_type_with_parameters_is_fine() {
    let fake = Arc::new(FakeEngine::default());
    let (s, _) = post(
        fake,
        "/v1/transcribe",
        "audio/webm;codecs=opus",
        fixture("jfk.webm"),
    )
    .await;
    assert_eq!(s, StatusCode::OK);
}

#[tokio::test]
async fn unknown_type_and_broken_audio_are_refused() {
    let fake = Arc::new(FakeEngine::default());
    let (s, v) = post(
        fake.clone(),
        "/v1/transcribe",
        "text/plain",
        b"hello".to_vec(),
    )
    .await;
    assert_eq!(s, StatusCode::UNSUPPORTED_MEDIA_TYPE);
    assert_eq!(v["error"], "unsupported_audio");
    let (s, v) = post(fake.clone(), "/v1/transcribe", "audio/m4a", vec![7u8; 5000]).await;
    assert_eq!(s, StatusCode::UNSUPPORTED_MEDIA_TYPE, "{v}");
    // the first 2 kB of an m4a: header only, no audio
    let (s, _) = post(
        fake.clone(),
        "/v1/transcribe",
        "audio/m4a",
        fixture("jfk.m4a")[..2000].to_vec(),
    )
    .await;
    assert_eq!(s, StatusCode::UNSUPPORTED_MEDIA_TYPE);
    assert!(fake.calls.lock().unwrap().is_empty());
}

#[tokio::test]
async fn empty_and_too_big_are_refused() {
    let fake = Arc::new(FakeEngine::default());
    let (s, v) = post(fake.clone(), "/v1/transcribe", "audio/wav", vec![]).await;
    assert_eq!(s, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(v["error"], "invalid");
    let (s, v) = post(
        fake.clone(),
        "/v1/transcribe",
        "audio/wav",
        vec![0u8; 10 * 1024 * 1024 + 1],
    )
    .await;
    assert_eq!(s, StatusCode::PAYLOAD_TOO_LARGE);
    assert_eq!(v["error"], "too_large");
    assert!(fake.calls.lock().unwrap().is_empty());
}

#[tokio::test]
async fn longer_than_two_minutes_is_refused_while_decoding() {
    let fake = Arc::new(FakeEngine::default());
    let (s, v) = post(fake.clone(), "/v1/transcribe", "audio/wav", wav(121.0, 0.3)).await;
    assert_eq!(s, StatusCode::PAYLOAD_TOO_LARGE);
    assert!(v["message"].as_str().unwrap().contains("2 minutes"));
    assert!(fake.calls.lock().unwrap().is_empty());
    let (s, _) = post(fake.clone(), "/v1/transcribe", "audio/wav", wav(119.0, 0.3)).await;
    assert_eq!(s, StatusCode::OK);
}

#[tokio::test]
async fn silence_gives_empty_text_without_asking_the_engine() {
    let fake = Arc::new(FakeEngine::default());
    let (s, v) = post(fake.clone(), "/v1/transcribe", "audio/wav", wav(3.0, 0.0)).await;
    assert_eq!(s, StatusCode::OK);
    assert_eq!(v["text"], "");
    assert_eq!(v["duration"], 3.0);
    assert!(fake.calls.lock().unwrap().is_empty());
}

#[tokio::test]
async fn language_is_passed_as_its_primary_code() {
    let fake = Arc::new(FakeEngine::default());
    let (s, _) = post(
        fake.clone(),
        "/v1/transcribe?language=de-CH",
        "audio/wav",
        fixture("jfk.wav"),
    )
    .await;
    assert_eq!(s, StatusCode::OK);
    let (s, _) = post(
        fake.clone(),
        "/v1/transcribe",
        "audio/wav",
        fixture("jfk.wav"),
    )
    .await;
    assert_eq!(s, StatusCode::OK);
    let calls = fake.calls.lock().unwrap();
    assert_eq!(calls[0].1.as_deref(), Some("de"));
    assert_eq!(calls[1].1, None);
}

#[tokio::test]
async fn unknown_language_is_refused() {
    let fake = Arc::new(FakeEngine::default());
    for l in ["xx", "deutsch", "d3", "../x"] {
        let (s, v) = post(
            fake.clone(),
            &format!("/v1/transcribe?language={l}"),
            "audio/wav",
            fixture("jfk.wav"),
        )
        .await;
        assert_eq!(s, StatusCode::UNPROCESSABLE_ENTITY, "{l}");
        assert_eq!(v["error"], "invalid");
    }
    assert!(fake.calls.lock().unwrap().is_empty());
}

#[tokio::test]
async fn engine_failure_is_a_plain_error_without_details() {
    let fake = Arc::new(FakeEngine::default());
    *fake.result.lock().unwrap() = Err("ggml: secret internal detail".into());
    let (s, v) = post(fake, "/v1/transcribe", "audio/wav", fixture("jfk.wav")).await;
    assert_eq!(s, StatusCode::INTERNAL_SERVER_ERROR);
    assert_eq!(v["error"], "transcription_failed");
    assert!(!v.to_string().contains("ggml"));
}

/// An engine that takes a while, to fill the line.
struct Slow;
impl Engine for Slow {
    fn transcribe(&self, _: &[f32], _: Option<&str>) -> Result<Transcript, String> {
        std::thread::sleep(std::time::Duration::from_millis(400));
        Ok(Transcript {
            text: "ok".into(),
            language: None,
            segments: vec![],
        })
    }
    fn knows_language(&self, _: &str) -> bool {
        true
    }
    fn name(&self) -> String {
        "slow".into()
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn a_full_line_answers_busy_at_once() {
    let h = common::harness(Arc::new(Slow));
    let app = h.router.clone();
    let auth = format!("Bearer {}", h.token);
    let body = fixture("jfk.wav");
    let mut tasks = vec![];
    for _ in 0..8 {
        let app = app.clone();
        let body = body.clone();
        let auth = auth.clone();
        tasks.push(tokio::spawn(async move {
            let req = Request::post("/v1/transcribe")
                .header("content-type", "audio/wav")
                .header("authorization", auth)
                .body(Body::from(body))
                .unwrap();
            app.oneshot(req).await.unwrap().status()
        }));
    }
    let mut ok = 0;
    let mut busy = 0;
    for t in tasks {
        match t.await.unwrap() {
            StatusCode::OK => ok += 1,
            StatusCode::SERVICE_UNAVAILABLE => busy += 1,
            s => panic!("unexpected {s}"),
        }
    }
    // one runs, four wait, the rest are told at once
    assert_eq!(ok + busy, 8);
    assert!(ok >= 5 && busy >= 1, "ok {ok} busy {busy}");
}

#[tokio::test]
async fn health_and_unknown_paths() {
    let h = common::harness(Arc::new(FakeEngine::default()));
    let app = h.router.clone();
    let r = app
        .clone()
        .oneshot(Request::get("/v1/health").body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(r.status(), StatusCode::OK);
    let r = app
        .oneshot(Request::get("/nope").body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(r.status(), StatusCode::NOT_FOUND);
    let b = r.into_body().collect().await.unwrap().to_bytes();
    let v: Value = serde_json::from_slice(&b).unwrap();
    assert_eq!(v["error"], "not_found");
}
