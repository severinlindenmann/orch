//! Encrypted jobs with the fake engine: round trip, refusals, separation, restart, expiry, fairness.
use std::sync::{Arc, Mutex};
use std::time::Duration;

use axum::http::StatusCode;
use base64::Engine as _;
use orch_transcription::engine::{Engine, FakeEngine, Segment, Transcript};
use orch_transcription::opf1;
use serde_json::Value;

mod common;
use common::{fixture, harness, H};

const KEY: [u8; 32] = [7u8; 32];

fn b64(k: &[u8; 32]) -> String {
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(k)
}

fn blob(kind: &str, audio: &[u8]) -> Vec<u8> {
    opf1::seal(&KEY, "rec", kind, audio)
}

/// A 16 kHz mono WAV of `secs` seconds of a 300 Hz tone.
fn wav(secs: f64) -> Vec<u8> {
    let n = (secs * 16_000.0) as u32;
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
        let s = (2.0 * std::f32::consts::PI * 300.0 * i as f32 / 16_000.0).sin() * 0.3;
        v.extend_from_slice(&((s * 32_000.0) as i16).to_le_bytes());
    }
    v
}

async fn create(h: &H, token: &str, key: Option<&str>, body: Vec<u8>) -> (StatusCode, Value) {
    let mut hd = vec![("content-type", "application/octet-stream")];
    if let Some(k) = key {
        hd.push(("x-orch-job-key", k));
    }
    let (s, b) = h.call("POST", "/v1/jobs", Some(token), &hd, body).await;
    (s, serde_json::from_slice(&b).unwrap_or(Value::Null))
}

async fn status(h: &H, token: &str, id: &str) -> (StatusCode, Value) {
    let (s, b) = h
        .call("GET", &format!("/v1/jobs/{id}"), Some(token), &[], vec![])
        .await;
    (s, serde_json::from_slice(&b).unwrap_or(Value::Null))
}

async fn wait_for(h: &H, id: &str, want: &str) -> Value {
    for _ in 0..2400 {
        let (_, v) = status(h, &h.token, id).await;
        if v["status"] == want {
            return v;
        }
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
    panic!("job {id} never reached {want}");
}

fn start_worker(h: &H) {
    tokio::spawn(orch_transcription::jobs::worker(h.app.clone()));
}

/// Every file in the job folder, joined: what the disk holds.
fn disk(h: &H) -> Vec<u8> {
    let mut all = vec![];
    for e in std::fs::read_dir(h.dir.path().join("jobs"))
        .unwrap()
        .flatten()
    {
        all.extend(std::fs::read(e.path()).unwrap());
    }
    all
}

fn contains(hay: &[u8], needle: &[u8]) -> bool {
    hay.windows(needle.len()).any(|w| w == needle)
}

#[tokio::test]
async fn round_trip_only_ciphertext_on_disk() {
    let h = harness(Arc::new(FakeEngine::default()));
    let (s, v) = create(
        &h,
        &h.token,
        Some(&b64(&KEY)),
        blob("audio/wav", &fixture("jfk.wav")),
    )
    .await;
    assert_eq!(s, StatusCode::ACCEPTED, "{v}");
    let id = v["id"].as_str().unwrap().to_string();
    assert_eq!(v["status"], "waiting");
    assert_eq!(
        v["expires_at"].as_i64().unwrap() - v["created_at"].as_i64().unwrap(),
        7 * 24 * 3600
    );
    // waiting: the stored recording is ciphertext (no WAV header), nothing plain
    let d = disk(&h);
    assert!(!contains(&d, b"RIFF") && !contains(&d, b"WAVE"));
    start_worker(&h);
    let v = wait_for(&h, &id, "done").await;
    assert!((10.5..11.5).contains(&v["duration"].as_f64().unwrap()));
    let (s, out) = h
        .call(
            "GET",
            &format!("/v1/jobs/{id}/result"),
            Some(&h.token),
            &[],
            vec![],
        )
        .await;
    assert_eq!(s, StatusCode::OK);
    // the job key does not open the result; the result key does
    assert!(opf1::open(&KEY, &out).is_none());
    let (hd, body) = opf1::open(&opf1::result_key(&KEY), &out).unwrap();
    assert_eq!(hd.name, "transcript.json");
    let r: Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(r["text"], "hello world");
    assert_eq!(r["language"], "en");
    assert_eq!(r["segments"][0]["text"], "hello world");
    // the recording is gone, the transcript is only stored encrypted
    assert!(!h.dir.path().join(format!("jobs/{id}.in")).exists());
    let d = disk(&h);
    assert!(!contains(&d, b"hello world") && !contains(&d, b"RIFF"));
    // repeatable until deleted
    let (s, again) = h
        .call(
            "GET",
            &format!("/v1/jobs/{id}/result"),
            Some(&h.token),
            &[],
            vec![],
        )
        .await;
    assert_eq!((s, again), (StatusCode::OK, out));
    let (s, _) = h
        .call(
            "DELETE",
            &format!("/v1/jobs/{id}"),
            Some(&h.token),
            &[],
            vec![],
        )
        .await;
    assert_eq!(s, StatusCode::NO_CONTENT);
    assert_eq!(status(&h, &h.token, &id).await.0, StatusCode::NOT_FOUND);
    assert!(std::fs::read_dir(h.dir.path().join("jobs"))
        .unwrap()
        .next()
        .is_none());
}

#[tokio::test]
async fn bad_key_bad_blob_and_wrong_type_are_refused() {
    let h = harness(Arc::new(FakeEngine::default()));
    let good = blob("audio/wav", &fixture("jfk.wav"));
    let other = b64(&[9u8; 32]);
    for (key, body, why) in [
        (None, good.clone(), "no key"),
        (Some("short"), good.clone(), "bad key"),
        (Some(other.as_str()), good.clone(), "wrong key"),
        (Some(&*b64(&KEY)), fixture("jfk.wav"), "not OPF1"),
        (Some(&*b64(&KEY)), blob("text/plain", b"hello"), "not audio"),
    ] {
        let (s, v) = create(&h, &h.token, key, body).await;
        assert_eq!(s, StatusCode::UNPROCESSABLE_ENTITY, "{why}: {v}");
        assert_eq!(v["error"], "invalid");
    }
    assert!(std::fs::read_dir(h.dir.path().join("jobs"))
        .unwrap()
        .next()
        .is_none());
}

#[tokio::test]
async fn another_token_sees_nothing_of_a_job() {
    let h = harness(Arc::new(FakeEngine::default()));
    let other = h.token_for("ws_other");
    let (_, v) = create(
        &h,
        &h.token,
        Some(&b64(&KEY)),
        blob("audio/wav", &fixture("jfk.wav")),
    )
    .await;
    let id = v["id"].as_str().unwrap();
    start_worker(&h);
    wait_for(&h, id, "done").await;
    for (m, path) in [
        ("GET", format!("/v1/jobs/{id}")),
        ("GET", format!("/v1/jobs/{id}/result")),
        ("POST", format!("/v1/jobs/{id}/key")),
        ("DELETE", format!("/v1/jobs/{id}")),
    ] {
        let (s, _) = h
            .call(
                m,
                &path,
                Some(&other),
                &[("x-orch-job-key", &b64(&KEY))],
                vec![],
            )
            .await;
        assert_eq!(s, StatusCode::NOT_FOUND, "{m} {path}");
    }
    // still there for its owner
    assert_eq!(status(&h, &h.token, id).await.1["status"], "done");
}

#[tokio::test]
async fn unknown_or_malformed_ids_are_not_found() {
    let h = harness(Arc::new(FakeEngine::default()));
    for id in ["j_aaaaaaaaaaaaaaaa", "..%2F..%2Ftokens", "x"] {
        assert_eq!(
            status(&h, &h.token, id).await.0,
            StatusCode::NOT_FOUND,
            "{id}"
        );
    }
}

#[tokio::test]
async fn at_most_four_open_jobs_per_token() {
    let h = harness(Arc::new(FakeEngine::default()));
    let b = blob("audio/wav", &wav(1.0));
    for _ in 0..4 {
        assert_eq!(
            create(&h, &h.token, Some(&b64(&KEY)), b.clone()).await.0,
            StatusCode::ACCEPTED
        );
    }
    let (s, v) = create(&h, &h.token, Some(&b64(&KEY)), b.clone()).await;
    assert_eq!(
        (s, v["error"].as_str()),
        (StatusCode::SERVICE_UNAVAILABLE, Some("busy"))
    );
    // another token has its own four
    let other = h.token_for("ws_other");
    assert_eq!(
        create(&h, &other, Some(&b64(&KEY)), b).await.0,
        StatusCode::ACCEPTED
    );
}

#[tokio::test]
async fn after_a_restart_the_job_asks_for_its_key_again() {
    let h = harness(Arc::new(FakeEngine::default()));
    let (_, v) = create(
        &h,
        &h.token,
        Some(&b64(&KEY)),
        blob("audio/wav", &fixture("jfk.wav")),
    )
    .await;
    let id = v["id"].as_str().unwrap().to_string();
    // a new process on the same data folder: the key was only in the old one's memory
    let app2 = orch_transcription::App::new(Arc::new(FakeEngine::default()), h.dir.path());
    let h2 = H {
        router: orch_transcription::router(app2.clone()),
        app: app2,
        dir: tempfile::tempdir().unwrap(),
        token: h.token.clone(),
    };
    let (_, v) = status(&h2, &h.token, &id).await;
    assert_eq!(v["status"], "needs_key");
    let (s, _) = h2
        .call(
            "POST",
            &format!("/v1/jobs/{id}/key"),
            Some(&h.token),
            &[("x-orch-job-key", &b64(&[1u8; 32]))],
            vec![],
        )
        .await;
    assert_eq!(s, StatusCode::UNPROCESSABLE_ENTITY);
    let (s, b) = h2
        .call(
            "POST",
            &format!("/v1/jobs/{id}/key"),
            Some(&h.token),
            &[("x-orch-job-key", &b64(&KEY))],
            vec![],
        )
        .await;
    assert_eq!(s, StatusCode::OK, "{}", String::from_utf8_lossy(&b));
    start_worker(&h2);
    wait_for(&h2, &id, "done").await;
    // a done job takes no key
    let (s, _) = h2
        .call(
            "POST",
            &format!("/v1/jobs/{id}/key"),
            Some(&h.token),
            &[("x-orch-job-key", &b64(&KEY))],
            vec![],
        )
        .await;
    assert_eq!(s, StatusCode::CONFLICT);
}

#[tokio::test]
async fn expired_jobs_and_jobs_of_removed_tokens_are_deleted() {
    let h = harness(Arc::new(FakeEngine::default()));
    let gone = h.token_for("ws_gone");
    let (_, a) = create(&h, &h.token, Some(&b64(&KEY)), blob("audio/wav", &wav(1.0))).await;
    let (_, b) = create(&h, &gone, Some(&b64(&KEY)), blob("audio/wav", &wav(1.0))).await;
    // the token ids after ws_gone is removed: only tester's
    let tester_id = h
        .app
        .tokens
        .list()
        .into_iter()
        .find(|e| e.name == "tester")
        .unwrap()
        .id;
    let owners = vec![tester_id];
    let now = orch_transcription::tokens::now();
    // an unreadable token file (None): only expiry counts, nobody's jobs are taken as orphans
    assert_eq!(h.app.jobs.sweep(None, now), 0);
    assert_eq!(h.app.jobs.sweep(Some(&owners), now), 1); // ws_gone is not among the tokens
    assert_eq!(
        status(&h, &gone, b["id"].as_str().unwrap()).await.0,
        StatusCode::NOT_FOUND
    );
    assert_eq!(h.app.jobs.sweep(Some(&owners), now + 7 * 24 * 3600 + 1), 1);
    assert_eq!(
        status(&h, &h.token, a["id"].as_str().unwrap()).await.0,
        StatusCode::NOT_FOUND
    );
    assert!(std::fs::read_dir(h.dir.path().join("jobs"))
        .unwrap()
        .next()
        .is_none());
}

#[tokio::test]
async fn unreadable_audio_fails_the_job_and_drops_the_recording() {
    let h = harness(Arc::new(FakeEngine::default()));
    let (_, v) = create(
        &h,
        &h.token,
        Some(&b64(&KEY)),
        blob("audio/m4a", &[3u8; 4000]),
    )
    .await;
    let id = v["id"].as_str().unwrap();
    start_worker(&h);
    let v = wait_for(&h, id, "failed").await;
    assert_eq!(v["error"], "unsupported_audio");
    assert!(!h.dir.path().join(format!("jobs/{id}.in")).exists());
}

/// Logs each call's length; takes a while per call.
struct Slow(Mutex<Vec<usize>>);
impl Engine for Slow {
    fn transcribe(&self, s: &[f32], _: Option<&str>) -> Result<Transcript, String> {
        self.0.lock().unwrap().push(s.len());
        std::thread::sleep(Duration::from_millis(400));
        Ok(Transcript {
            text: "x".into(),
            language: Some("de".into()),
            segments: vec![Segment {
                start: 1.0,
                end: 2.0,
                text: "x".into(),
            }],
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
async fn a_voice_memo_goes_between_two_pieces_of_a_long_job() {
    let slow = Arc::new(Slow(Mutex::new(vec![])));
    let h = harness(slow.clone());
    // 9 minutes: two pieces of about 5 and 4 minutes
    let (_, v) = create(
        &h,
        &h.token,
        Some(&b64(&KEY)),
        blob("audio/wav", &wav(540.0)),
    )
    .await;
    let id = v["id"].as_str().unwrap().to_string();
    start_worker(&h);
    // decoding 9 minutes takes seconds in a debug build on a busy machine: wait up to 30 s for piece 1
    for _ in 0..3000 {
        if !slow.0.lock().unwrap().is_empty() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    let (s, _) = h
        .post("/v1/transcribe", "audio/wav", fixture("jfk.wav"))
        .await;
    assert_eq!(s, StatusCode::OK);
    wait_for(&h, &id, "done").await;
    let calls = slow.0.lock().unwrap().clone();
    assert_eq!(calls.len(), 3, "{calls:?}");
    // piece 1, then the memo (11 s), then piece 2
    assert!(calls[0] > 4 * 60 * 16_000, "{calls:?}");
    assert!((168_000..184_000).contains(&calls[1]), "{calls:?}");
    assert!(calls[2] > 3 * 60 * 16_000, "{calls:?}");
    // segment times run on across pieces
    let (_, out) = h
        .call(
            "GET",
            &format!("/v1/jobs/{id}/result"),
            Some(&h.token),
            &[],
            vec![],
        )
        .await;
    let (_, body) = opf1::open(&opf1::result_key(&KEY), &out).unwrap();
    let r: Value = serde_json::from_slice(&body).unwrap();
    let starts: Vec<f64> = r["segments"]
        .as_array()
        .unwrap()
        .iter()
        .map(|s| s["start"].as_f64().unwrap())
        .collect();
    assert_eq!(starts.len(), 2);
    assert_eq!(starts[0], 1.0);
    assert!(starts[1] > 290.0, "{starts:?}");
    assert_eq!(r["text"], "x x");
}

#[tokio::test]
async fn a_token_made_again_under_the_same_name_sees_none_of_the_old_jobs() {
    let h = harness(Arc::new(FakeEngine::default()));
    let old = h.token_for("ws_a");
    let (_, v) = create(&h, &old, Some(&b64(&KEY)), blob("audio/wav", &wav(1.0))).await;
    let id = v["id"].as_str().unwrap().to_string();
    assert!(h.app.tokens.remove("ws_a").unwrap());
    let new = h.token_for("ws_a");
    assert_eq!(status(&h, &new, &id).await.0, StatusCode::NOT_FOUND);
    let (s, _) = h
        .call("DELETE", &format!("/v1/jobs/{id}"), Some(&new), &[], vec![])
        .await;
    assert_eq!(s, StatusCode::NOT_FOUND);
    // and the cleanup deletes the old token's job although the name exists again
    let ids: Vec<String> = h.app.tokens.list().into_iter().map(|e| e.id).collect();
    assert_eq!(
        h.app
            .jobs
            .sweep(Some(&ids), orch_transcription::tokens::now()),
        1
    );
}

#[tokio::test]
async fn an_expired_job_is_gone_at_once_even_before_the_cleanup() {
    let h = harness(Arc::new(FakeEngine::default()));
    let (_, v) = create(&h, &h.token, Some(&b64(&KEY)), blob("audio/wav", &wav(1.0))).await;
    let id = v["id"].as_str().unwrap().to_string();
    let p = h.dir.path().join(format!("jobs/{id}.json"));
    let mut m: Value = serde_json::from_slice(&std::fs::read(&p).unwrap()).unwrap();
    m["expires_at"] = (orch_transcription::tokens::now() - 1).into();
    std::fs::write(&p, serde_json::to_vec(&m).unwrap()).unwrap();
    assert_eq!(status(&h, &h.token, &id).await.0, StatusCode::NOT_FOUND);
}

/// What a stopped process left: a result on disk = done; neither recording nor result = failed.
#[tokio::test]
async fn a_restart_reconciles_half_finished_jobs() {
    let h = harness(Arc::new(FakeEngine::default()));
    let (_, a) = create(&h, &h.token, Some(&b64(&KEY)), blob("audio/wav", &wav(1.0))).await;
    let (_, b) = create(&h, &h.token, Some(&b64(&KEY)), blob("audio/wav", &wav(1.0))).await;
    let (a, b) = (
        a["id"].as_str().unwrap().to_string(),
        b["id"].as_str().unwrap().to_string(),
    );
    let jobs = h.dir.path().join("jobs");
    // a: result written, stopped before its status; b: recording gone, no result
    std::fs::write(jobs.join(format!("{a}.out")), b"OPF1 sealed result").unwrap();
    std::fs::remove_file(jobs.join(format!("{b}.in"))).unwrap();
    let app2 = orch_transcription::App::new(Arc::new(FakeEngine::default()), h.dir.path());
    let h2 = H {
        router: orch_transcription::router(app2.clone()),
        app: app2,
        dir: tempfile::tempdir().unwrap(),
        token: h.token.clone(),
    };
    assert_eq!(status(&h2, &h.token, &a).await.1["status"], "done");
    assert!(!jobs.join(format!("{a}.in")).exists());
    let v = status(&h2, &h.token, &b).await.1;
    assert_eq!(
        (v["status"].as_str(), v["error"].as_str()),
        (Some("failed"), Some("transcription_failed"))
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn deleting_a_running_job_stops_it_after_the_current_piece() {
    let slow = Arc::new(Slow(Mutex::new(vec![])));
    let h = harness(slow.clone());
    let (_, v) = create(
        &h,
        &h.token,
        Some(&b64(&KEY)),
        blob("audio/wav", &wav(540.0)),
    )
    .await;
    let id = v["id"].as_str().unwrap().to_string();
    start_worker(&h);
    // decoding 9 minutes takes seconds in a debug build on a busy machine: wait up to 30 s for piece 1
    for _ in 0..3000 {
        if !slow.0.lock().unwrap().is_empty() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    let (s, _) = h
        .call(
            "DELETE",
            &format!("/v1/jobs/{id}"),
            Some(&h.token),
            &[],
            vec![],
        )
        .await;
    assert_eq!(s, StatusCode::NO_CONTENT);
    tokio::time::sleep(Duration::from_millis(1200)).await;
    assert_eq!(
        slow.0.lock().unwrap().len(),
        1,
        "the second piece must not run"
    );
    assert!(std::fs::read_dir(h.dir.path().join("jobs"))
        .unwrap()
        .next()
        .is_none());
}
