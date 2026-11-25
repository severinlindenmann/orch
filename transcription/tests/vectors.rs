//! Replays the shared vectors: OPF1 (publish-blob-v1.json), the result key (transcription-result-key-v1.json) and
//! the request/response pairs (transcription-api-v1.json) with the fake engine.
use std::sync::Arc;

use axum::http::StatusCode;
use base64::Engine as _;
use orch_transcription::engine::FakeEngine;
use orch_transcription::opf1;
use serde_json::Value;

mod common;

fn vectors(name: &str) -> Value {
    let p = format!("{}/../contracts/vectors/{name}", env!("CARGO_MANIFEST_DIR"));
    serde_json::from_str(&std::fs::read_to_string(p).unwrap()).unwrap()
}

fn hex(s: &str) -> Vec<u8> {
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap())
        .collect()
}

#[test]
fn opf1_vectors() {
    let v = vectors("publish-blob-v1.json");
    for name in ["good", "good_with_note"] {
        let c = &v[name];
        let key = opf1::key_from_b64(c["key_b64url"].as_str().unwrap()).unwrap();
        let (h, body) = opf1::open(&key, &hex(c["blob_hex"].as_str().unwrap())).expect(name);
        let want: Value = serde_json::from_str(c["header_json"].as_str().unwrap()).unwrap();
        assert_eq!(h.name, want["name"]);
        assert_eq!(body, c["content_utf8"].as_str().unwrap().as_bytes());
        // our writer makes the same bytes for the same IV (no note)
        if name == "good" {
            let iv: [u8; 12] = hex(c["iv_hex"].as_str().unwrap()).try_into().unwrap();
            let again = opf1::seal_with_iv(&key, &iv, &h.name, &h.kind, &body);
            assert_eq!(again, hex(c["blob_hex"].as_str().unwrap()));
        }
    }
    for c in v["must_fail"].as_array().unwrap() {
        let key = opf1::key_from_b64(c["key_b64url"].as_str().unwrap()).unwrap();
        assert!(
            opf1::open(&key, &hex(c["blob_hex"].as_str().unwrap())).is_none(),
            "{}",
            c["name"]
        );
    }
}

#[test]
fn result_key_vectors() {
    let v = vectors("transcription-result-key-v1.json");
    for c in v["cases"].as_array().unwrap() {
        let k = opf1::key_from_b64(c["job_key_b64url"].as_str().unwrap()).unwrap();
        let want = opf1::key_from_b64(c["result_key_b64url"].as_str().unwrap()).unwrap();
        assert_eq!(opf1::result_key(&k), want, "{}", c["name"]);
    }
}

// ---------- request/response pairs (transcription-api-v1.json) ----------

const JOB_KEY: [u8; 32] = [9u8; 32];

/// A 1 s 16 kHz mono 16-bit WAV: a 300 Hz tone at `amp` (0 = silence).
fn wav_1s(amp: f32) -> Vec<u8> {
    let n: u32 = 16_000;
    let mut v = Vec::new();
    v.extend_from_slice(b"RIFF");
    v.extend_from_slice(&(36 + n * 2).to_le_bytes());
    v.extend_from_slice(b"WAVEfmt ");
    v.extend_from_slice(&16u32.to_le_bytes());
    for x in [1u16, 1] {
        v.extend_from_slice(&x.to_le_bytes());
    }
    v.extend_from_slice(&16_000u32.to_le_bytes());
    v.extend_from_slice(&32_000u32.to_le_bytes());
    for x in [2u16, 16] {
        v.extend_from_slice(&x.to_le_bytes());
    }
    v.extend_from_slice(b"data");
    v.extend_from_slice(&(n * 2).to_le_bytes());
    for i in 0..n {
        let s = (2.0 * std::f32::consts::PI * 300.0 * i as f32 / 16_000.0).sin() * amp;
        v.extend_from_slice(&((s * 32_000.0) as i16).to_le_bytes());
    }
    v
}

fn body(kind: &str) -> Vec<u8> {
    match kind {
        "tone_1s" => wav_1s(0.3),
        "silence_1s" => wav_1s(0.0),
        "garbage" => vec![1u8; 64],
        "empty" | "none" => vec![],
        "over_10mb" => vec![1u8; 10 * 1024 * 1024 + 1],
        "job_tone_1s" => opf1::seal(&JOB_KEY, "rec", "audio/wav", &wav_1s(0.3)),
        k => panic!("unknown body {k}"),
    }
}

fn job_key_b64() -> String {
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(JOB_KEY)
}

/// The same field names, each with the same JSON type (string, number, null, ...).
fn same_shape(got: &Value, want: &Value) -> bool {
    let (Some(g), Some(w)) = (got.as_object(), want.as_object()) else {
        return false;
    };
    let kind = |v: &Value| std::mem::discriminant(v);
    g.len() == w.len()
        && w.iter()
            .all(|(k, wv)| g.get(k).is_some_and(|gv| kind(gv) == kind(wv)))
}

async fn replay(h: &common::H, ex: &Value) -> (StatusCode, Value) {
    let req = &ex["request"];
    let mut hd: Vec<(&str, String)> = vec![];
    if let Some(ct) = req["content_type"].as_str() {
        hd.push(("content-type", ct.to_string()));
    }
    if req["job_key"] == true {
        hd.push(("x-orch-job-key", job_key_b64()));
    }
    let hd: Vec<(&str, &str)> = hd.iter().map(|(k, v)| (*k, v.as_str())).collect();
    let token = (req["token"] == true).then(|| h.token.clone());
    let (s, b) = h
        .call(
            req["method"].as_str().unwrap(),
            req["path"].as_str().unwrap(),
            token.as_deref(),
            &hd,
            body(req["body"].as_str().unwrap()),
        )
        .await;
    (s, serde_json::from_slice(&b).unwrap_or(Value::Null))
}

/// The service answers every pair it can be made to answer as the vector says, with the fake engine.
#[tokio::test]
async fn service_answers_the_shared_pairs() {
    let v = vectors("transcription-api-v1.json");
    let mut replayed = 0;
    for ex in v["exchanges"].as_array().unwrap() {
        let name = ex["name"].as_str().unwrap();
        let mode = ex["service"].as_str().unwrap();
        if mode == "none" {
            continue;
        }
        let fake = Arc::new(FakeEngine::default());
        if ex["engine"] == "fails" {
            *fake.result.lock().unwrap() = Err("engine broke".into());
        }
        let h = common::harness(fake);
        let (s, got) = replay(&h, ex).await;
        let want = &ex["response"]["body"];
        assert_eq!(
            s.as_u16() as u64,
            ex["response"]["status"].as_u64().unwrap(),
            "{name}: {got}"
        );
        match mode {
            "exact" => assert_eq!(&got, want, "{name}"),
            _ => {
                assert!(same_shape(&got, want), "{name}: {got} vs {want}");
                assert_eq!(got.get("error"), want.get("error"), "{name}");
            }
        }
        replayed += 1;
    }
    assert!(replayed >= 15, "only {replayed} pairs replayed");
}

/// Every type the relay forwards is one the service takes.
#[test]
fn service_takes_every_type_the_relay_sends() {
    let v = vectors("transcription-api-v1.json");
    for t in v["relay_sends_types"].as_array().unwrap() {
        let t = t.as_str().unwrap();
        assert!(orch_transcription::audio::hint_for(t).is_some(), "{t}");
    }
}

/// A job end to end: the status and the transcript file inside the result blob have the vector's shape and
/// content, and nothing of the transcript, the key or the token reaches the log.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn job_result_matches_the_vector_and_the_log_holds_no_content() {
    let log = Arc::new(std::sync::Mutex::new(Vec::<u8>::new()));
    let sink = log.clone();
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::TRACE)
        .with_ansi(false)
        .with_writer(move || Sink(sink.clone()))
        .init();

    let v = vectors("transcription-api-v1.json");
    let pair = |n: &str| {
        v["exchanges"]
            .as_array()
            .unwrap()
            .iter()
            .find(|e| e["name"] == n)
            .unwrap()
            .clone()
    };
    let h = common::harness(Arc::new(FakeEngine::default()));
    tokio::spawn(orch_transcription::jobs::worker(h.app.clone()));
    let (s, created) = replay(&h, &pair("job_created")).await;
    assert_eq!(s, StatusCode::ACCEPTED, "{created}");
    let id = created["id"].as_str().unwrap().to_string();
    let mut done = Value::Null;
    for _ in 0..2400 {
        let (_, st) = h
            .call(
                "GET",
                &format!("/v1/jobs/{id}"),
                Some(&h.token),
                &[],
                vec![],
            )
            .await;
        done = serde_json::from_slice(&st).unwrap();
        if done["status"] == "done" || done["status"] == "failed" {
            break;
        }
        tokio::time::sleep(std::time::Duration::from_millis(25)).await;
    }
    let want_done = &pair("job_done")["response"]["body"];
    assert!(same_shape(&done, want_done), "{done} vs {want_done}");
    assert_eq!(done["status"], "done");
    let (s, blob) = h
        .call(
            "GET",
            &format!("/v1/jobs/{id}/result"),
            Some(&h.token),
            &[],
            vec![],
        )
        .await;
    assert_eq!(s, StatusCode::OK);
    let (hdr, file) =
        opf1::open(&opf1::result_key(&JOB_KEY), &blob).expect("opens with the result key");
    assert_eq!(
        (hdr.name.as_str(), hdr.kind.as_str()),
        ("transcript.json", "application/json")
    );
    let file: Value = serde_json::from_slice(&file).unwrap();
    let want = v["transcript_files"]
        .as_array()
        .unwrap()
        .iter()
        .find(|f| f["service"] == "exact")
        .unwrap();
    assert_eq!(file, want["file"]);
    // a short call too, so both paths have run while the log was listening
    let (s, short) = replay(&h, &pair("short_speech")).await;
    assert_eq!(
        (s, short["text"].as_str()),
        (StatusCode::OK, Some("hello world"))
    );

    let log = String::from_utf8(log.lock().unwrap().clone()).unwrap();
    assert!(
        log.contains(&id),
        "the log listened: it has the job's id:\n{log}"
    );
    for secret in ["hello world", &job_key_b64(), &h.token] {
        assert!(!log.contains(secret), "the log holds {secret:?}:\n{log}");
    }
}

struct Sink(Arc<std::sync::Mutex<Vec<u8>>>);

impl std::io::Write for Sink {
    fn write(&mut self, b: &[u8]) -> std::io::Result<usize> {
        self.0.lock().unwrap().extend_from_slice(b);
        Ok(b.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
