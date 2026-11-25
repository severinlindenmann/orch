//! The shared request/response pairs with our transcription service (contracts/vectors/transcription-api-v1.json),
//! replayed through the relay against a stand-in service.
mod common;
use common::*;
use serde_json::json;

const SVC_TOKEN: &str = "ort_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_abcde";

async fn post_audio(
    t: &T,
    path: &str,
    headers: &[(&str, String)],
    ct: &str,
    body: Vec<u8>,
) -> (u16, serde_json::Value) {
    let mut r = t
        .http
        .post(format!("{}{}", t.base, path))
        .header("Content-Type", ct)
        .body(body);
    for (k, v) in headers {
        r = r.header(*k, v);
    }
    let resp = r.send().await.unwrap();
    (
        resp.status().as_u16(),
        resp.json().await.unwrap_or_default(),
    )
}

fn ph(p: &(String, String)) -> Vec<(&'static str, String)> {
    vec![
        ("X-Orch-Phone", p.0.clone()),
        ("Authorization", format!("Bearer {}", p.1)),
    ]
}

struct LogSink(std::sync::Arc<std::sync::Mutex<Vec<u8>>>);

impl std::io::Write for LogSink {
    fn write(&mut self, b: &[u8]) -> std::io::Result<usize> {
        self.0.lock().unwrap().extend_from_slice(b);
        Ok(b.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

/// A phone memo goes through the relay (the real client) to a stand-in service that answers each shared
/// POST /v1/transcribe pair; the phone gets what the vector's `relay` says. The relay's log holds none of the
/// text, the service's messages or the token.
#[tokio::test]
async fn relay_reads_every_shared_service_answer() {
    use std::future::IntoFuture;
    use std::sync::{Arc, Mutex};
    let log = Arc::new(Mutex::new(Vec::<u8>::new()));
    let sink = log.clone();
    // global, and the only test in this file: a per-test subscriber misses events while other tests run
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::TRACE)
        .with_ansi(false)
        .with_writer(move || LogSink(sink.clone()))
        .init();

    let v: serde_json::Value = serde_json::from_str(
        &std::fs::read_to_string(format!(
            "{}/../contracts/vectors/transcription-api-v1.json",
            env!("CARGO_MANIFEST_DIR")
        ))
        .unwrap(),
    )
    .unwrap();
    let answer = Arc::new(Mutex::new((200u16, json!({}))));
    let seen = Arc::new(Mutex::new(Vec::<(String, String)>::new()));
    let (a2, s2) = (answer.clone(), seen.clone());
    let svc = axum::Router::new().route(
        "/v1/transcribe",
        axum::routing::post(move |h: axum::http::HeaderMap| {
            let (answer, seen) = (a2.clone(), s2.clone());
            async move {
                let hv = |k: &str| h[k].to_str().unwrap().to_string();
                seen.lock()
                    .unwrap()
                    .push((hv("authorization"), hv("content-type")));
                let (s, b) = answer.lock().unwrap().clone();
                (axum::http::StatusCode::from_u16(s).unwrap(), axum::Json(b))
            }
        }),
    );
    let l = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", l.local_addr().unwrap());
    tokio::spawn(axum::serve(l, svc).into_future());

    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    let (s, r) = t
        .admin_json(
            "PUT",
            "/admin/api/voice/service",
            Some(json!({"url": url, "token": SVC_TOKEN})),
        )
        .await;
    assert_eq!(s, 200, "{r}");

    let mut secrets = vec![SVC_TOKEN.to_string()];
    let mut n = 0;
    for ex in v["exchanges"].as_array().unwrap() {
        if !ex["request"]["path"]
            .as_str()
            .unwrap()
            .starts_with("/v1/transcribe")
        {
            continue;
        }
        let name = ex["name"].as_str().unwrap();
        let resp = &ex["response"];
        *answer.lock().unwrap() = (
            resp["status"].as_u64().unwrap() as u16,
            resp["body"].clone(),
        );
        for k in ["text", "message"] {
            if let Some(s) = resp["body"][k].as_str().filter(|s| !s.trim().is_empty()) {
                secrets.push(s.trim().to_string());
            }
        }
        let (s, got) = post_audio(
            &t,
            "/v1/phone/transcribe",
            &ph(&p),
            "audio/m4a",
            vec![1; 100],
        )
        .await;
        let want = &ex["relay"];
        let (ws, wcode) = match want["error"].as_str() {
            None => (200, None),
            Some("unavailable") => (502, Some("transcription_failed")),
            Some("too_large") => (413, Some("too_large")),
            Some("unreadable") => (422, Some("invalid")),
            Some(o) => panic!("{name}: unknown relay reading {o}"),
        };
        assert_eq!((s, got["error"].as_str()), (ws, wcode), "{name}: {got}");
        if ws == 200 {
            assert_eq!(got, want["transcript"], "{name}");
        }
        n += 1;
    }
    assert!(n >= 10, "only {n} pairs");

    // every type the relay forwards (and the vector names) reaches the service as it was sent
    *answer.lock().unwrap() = (200, json!({"text": "", "language": null, "duration": 1.0}));
    seen.lock().unwrap().clear();
    let types: Vec<String> = v["relay_sends_types"]
        .as_array()
        .unwrap()
        .iter()
        .map(|x| x.as_str().unwrap().to_string())
        .collect();
    for ct in &types {
        let wsh = vec![
            ("X-Orch-Workspace", a.id.clone()),
            ("Authorization", format!("Bearer {}", a.token)),
        ];
        let (s, got) = post_audio(&t, "/v1/transcribe", &wsh, ct, vec![1; 10]).await;
        assert_eq!(s, 200, "{ct}: {got}");
    }
    let seen = seen.lock().unwrap().clone();
    assert_eq!(seen.iter().map(|x| x.1.clone()).collect::<Vec<_>>(), types);
    assert!(seen.iter().all(|x| x.0 == format!("Bearer {SVC_TOKEN}")));

    let log = String::from_utf8(log.lock().unwrap().clone()).unwrap();
    assert!(log.contains("answered 503"), "the log listened:\n{log}");
    for s in &secrets {
        assert!(
            !log.contains(s.as_str()),
            "the relay's log holds {s:?}:\n{log}"
        );
    }
}
