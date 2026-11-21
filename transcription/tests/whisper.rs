//! The real engine with a small multilingual model. Runs when ORCH_TRANSCRIPTION_TEST_MODEL and
//! ORCH_TRANSCRIPTION_TEST_VAD point at the files (CI downloads ggml-tiny.bin and the Silero model);
//! skipped with a note otherwise.
#![cfg(feature = "whisper")]

use std::path::PathBuf;
use std::sync::{Arc, OnceLock};

use axum::http::StatusCode;
use orch_transcription::engine::{Engine, WhisperEngine};
use serde_json::Value;

mod common;
use common::fixture;

fn engine() -> Option<Arc<dyn Engine>> {
    static E: OnceLock<Option<Arc<dyn Engine>>> = OnceLock::new();
    E.get_or_init(|| {
        let m = std::env::var("ORCH_TRANSCRIPTION_TEST_MODEL").ok()?;
        let v = std::env::var("ORCH_TRANSCRIPTION_TEST_VAD").ok()?;
        let e =
            WhisperEngine::load(&PathBuf::from(m), Some(PathBuf::from(v)), 4).expect("model loads");
        Some(Arc::new(e) as Arc<dyn Engine>)
    })
    .clone()
}

macro_rules! need_model {
    () => {
        match engine() {
            Some(e) => e,
            None => {
                eprintln!(
                    "skipped: set ORCH_TRANSCRIPTION_TEST_MODEL and ORCH_TRANSCRIPTION_TEST_VAD"
                );
                return;
            }
        }
    };
}

async fn post(e: Arc<dyn Engine>, uri: &str, ct: &str, body: Vec<u8>) -> (StatusCode, Value) {
    common::harness(e).post(uri, ct, body).await
}

fn words(v: &Value) -> String {
    v["text"]
        .as_str()
        .unwrap()
        .to_lowercase()
        .chars()
        .filter(|c| c.is_alphanumeric() || c.is_whitespace())
        .collect()
}

#[tokio::test]
async fn speech_becomes_text_and_the_language_is_detected() {
    let e = need_model!();
    for (f, ct) in [
        ("jfk.wav", "audio/wav"),
        ("jfk.m4a", "audio/m4a"),
        ("jfk.webm", "audio/webm"),
    ] {
        let (s, v) = post(e.clone(), "/v1/transcribe", ct, fixture(f)).await;
        assert_eq!(s, StatusCode::OK, "{f}: {v}");
        let w = words(&v);
        assert!(
            w.contains("ask not what your country can do for you"),
            "{f}: {w}"
        );
        assert_eq!(v["language"], "en", "{f}");
    }
}

#[tokio::test]
async fn a_given_language_is_used() {
    let e = need_model!();
    let (s, v) = post(
        e,
        "/v1/transcribe?language=en",
        "audio/wav",
        fixture("jfk.wav"),
    )
    .await;
    assert_eq!(s, StatusCode::OK);
    assert_eq!(v["language"], "en");
    assert!(words(&v).contains("country"));
}

/// Noise and a too-short burst: voice detection finds no speech, so no made-up text.
#[tokio::test]
async fn noise_gives_no_made_up_text() {
    let e = need_model!();
    let mut seed: u32 = 1;
    let mut noise = |secs: f64, amp: f32| -> Vec<u8> {
        let n = (secs * 16_000.0) as u32;
        let mut v = Vec::new();
        v.extend_from_slice(b"RIFF");
        v.extend_from_slice(&(36 + n * 2).to_le_bytes());
        v.extend_from_slice(b"WAVEfmt ");
        v.extend_from_slice(&16u32.to_le_bytes());
        for x in [1u16, 1u16] {
            v.extend_from_slice(&x.to_le_bytes());
        }
        v.extend_from_slice(&16_000u32.to_le_bytes());
        v.extend_from_slice(&32_000u32.to_le_bytes());
        for x in [2u16, 16u16] {
            v.extend_from_slice(&x.to_le_bytes());
        }
        v.extend_from_slice(b"data");
        v.extend_from_slice(&(n * 2).to_le_bytes());
        for _ in 0..n {
            seed = seed.wrapping_mul(1_103_515_245).wrapping_add(12_345);
            let s = ((seed >> 16) as f32 / 32_768.0 - 1.0) * amp;
            v.extend_from_slice(&((s * 32_000.0) as i16).to_le_bytes());
        }
        v
    };
    for (secs, amp) in [(4.0, 0.01), (0.34, 0.2)] {
        let (s, v) = post(e.clone(), "/v1/transcribe", "audio/wav", noise(secs, amp)).await;
        assert_eq!(s, StatusCode::OK);
        assert_eq!(v["text"], "", "{secs}s noise gave {v}");
    }
}
