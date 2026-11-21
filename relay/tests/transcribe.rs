mod common;
use common::*;
use serde_json::json;

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

async fn set_key(t: &T) {
    let (s, v) = t
        .admin_json(
            "PUT",
            "/admin/api/voice",
            Some(json!({"deepgram_key": "dg_secret_key_ABCD1234"})),
        )
        .await;
    assert_eq!(s, 200, "{v}");
}

#[tokio::test]
async fn transcribe_admin_set_remove_never_leaks() {
    let t = start().await;
    let (s, v) = t.admin_json("GET", "/admin/api/voice", None).await;
    assert_eq!((s, v["deepgram"]["set"].as_bool()), (200, Some(false)));
    set_key(&t).await;
    let (_, v) = t.admin_json("GET", "/admin/api/voice", None).await;
    assert_eq!(v["deepgram"], json!({"set": true, "last4": "1234"}));
    // not in any admin response, not in the shared config, not in the db in plain text
    let (_, sh) = t.admin_json("GET", "/admin/api/shared", None).await;
    assert!(!v.to_string().contains("secret") && !sh.to_string().contains("secret"));
    let blob: Vec<u8> = t
        .app
        .db
        .lock()
        .unwrap()
        .query_row("SELECT v FROM settings WHERE k='deepgram'", [], |r| {
            r.get(0)
        })
        .unwrap();
    assert!(!String::from_utf8_lossy(&blob).contains("secret"));
    // bad value
    let (s, _) = t
        .admin_json(
            "PUT",
            "/admin/api/voice",
            Some(json!({"deepgram_key": "x"})),
        )
        .await;
    assert_eq!(s, 422);
    assert_eq!(
        t.admin_json("DELETE", "/admin/api/voice", None).await.0,
        204
    );
    let (_, v) = t.admin_json("GET", "/admin/api/voice", None).await;
    assert_eq!(v["deepgram"]["set"], false);
    // admin auth
    let r = t
        .http
        .get(format!("{}/admin/api/voice", t.admin))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
}

#[tokio::test]
async fn transcribe_phone_success_and_forwarding() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    set_key(&t).await;
    let (s, v) = post_audio(
        &t,
        "/v1/phone/transcribe?language=de",
        &ph(&p),
        "audio/m4a",
        vec![1; 100],
    )
    .await;
    assert_eq!(s, 200, "{v}");
    assert_eq!(
        v,
        json!({"text": "hello world", "language": "en", "duration": 2.5})
    );
    let calls = t.dg.calls.lock().unwrap();
    assert_eq!(
        calls[0],
        (
            "dg_secret_key_ABCD1234".to_string(),
            100,
            "audio/m4a".to_string(),
            Some("de".to_string())
        )
    );
}

#[tokio::test]
async fn transcribe_off_auth_size_type_and_errors() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    // off
    let (s, v) = post_audio(
        &t,
        "/v1/phone/transcribe",
        &ph(&p),
        "audio/wav",
        vec![1; 10],
    )
    .await;
    assert_eq!((s, v["error"].as_str()), (503, Some("transcription_off")));
    set_key(&t).await;
    // no auth, workspace token on phone route
    let (s, _) = post_audio(&t, "/v1/phone/transcribe", &[], "audio/wav", vec![1; 10]).await;
    assert_eq!(s, 401);
    let wsh = vec![
        ("X-Orch-Workspace", a.id.clone()),
        ("Authorization", format!("Bearer {}", a.token)),
    ];
    let (s, _) = post_audio(&t, "/v1/phone/transcribe", &wsh, "audio/wav", vec![1; 10]).await;
    assert_eq!(s, 401);
    // type, empty, size, language
    let (s, _) = post_audio(
        &t,
        "/v1/phone/transcribe",
        &ph(&p),
        "text/plain",
        vec![1; 10],
    )
    .await;
    assert_eq!(s, 422);
    let (s, _) = post_audio(&t, "/v1/phone/transcribe", &ph(&p), "audio/wav", vec![]).await;
    assert_eq!(s, 422);
    let (s, _) = post_audio(
        &t,
        "/v1/phone/transcribe?language=a%20b",
        &ph(&p),
        "audio/wav",
        vec![1; 10],
    )
    .await;
    assert_eq!(s, 422);
    let (s, v) = post_audio(
        &t,
        "/v1/phone/transcribe",
        &ph(&p),
        "audio/wav",
        vec![1; 10 * 1024 * 1024 + 1],
    )
    .await;
    assert_eq!((s, v["error"].as_str()), (413, Some("too_large")));
    assert!(t.dg.calls.lock().unwrap().is_empty());
    // Deepgram fails -> 502 with plain message
    *t.dg.result.lock().unwrap() = Err("The transcription service refused the audio (400).".into());
    let (s, v) = post_audio(
        &t,
        "/v1/phone/transcribe",
        &ph(&p),
        "audio/webm",
        vec![1; 10],
    )
    .await;
    assert_eq!(
        (s, v["error"].as_str()),
        (502, Some("transcription_failed"))
    );
    assert!(!v.to_string().contains("secret"));
}

#[tokio::test]
async fn transcribe_rate_limit_per_phone() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    let p2 = t.pair_phone(&[&a]).await;
    set_key(&t).await;
    for _ in 0..30 {
        assert_eq!(
            post_audio(
                &t,
                "/v1/phone/transcribe",
                &ph(&p),
                "audio/wav",
                vec![1; 10]
            )
            .await
            .0,
            200
        );
    }
    let (s, v) = post_audio(
        &t,
        "/v1/phone/transcribe",
        &ph(&p),
        "audio/wav",
        vec![1; 10],
    )
    .await;
    assert_eq!((s, v["error"].as_str()), (429, Some("rate_limited")));
    assert_eq!(
        post_audio(
            &t,
            "/v1/phone/transcribe",
            &ph(&p2),
            "audio/wav",
            vec![1; 10]
        )
        .await
        .0,
        200
    );
}

#[tokio::test]
async fn transcribe_workspace_endpoint() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let wsh = vec![
        ("X-Orch-Workspace", a.id.clone()),
        ("Authorization", format!("Bearer {}", a.token)),
    ];
    let (s, _) = post_audio(&t, "/v1/transcribe", &wsh, "audio/wav", vec![1; 10]).await;
    assert_eq!(s, 503);
    set_key(&t).await;
    let (s, v) = post_audio(&t, "/v1/transcribe", &wsh, "audio/wav", vec![1; 10]).await;
    assert_eq!((s, v["text"].as_str()), (200, Some("hello world")));
    let (s, _) = post_audio(&t, "/v1/transcribe", &[], "audio/wav", vec![1; 10]).await;
    assert_eq!(s, 401);
}

#[test]
fn language_swiss_german_setting_and_explicit() {
    use orch_relay::transcribe::effective_language as l;
    assert_eq!(l(None, false), None);
    assert_eq!(l(None, true).as_deref(), Some("de-CH"));
    assert_eq!(l(Some(""), true).as_deref(), Some("de-CH"));
    assert_eq!(l(Some("en"), true).as_deref(), Some("en"), "explicit wins");
    assert_eq!(l(Some("de-CH"), false).as_deref(), Some("de-CH"));
}

#[tokio::test]
async fn transcribe_accepts_de_ch_explicitly() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    set_key(&t).await;
    let (s, v) = post_audio(
        &t,
        "/v1/phone/transcribe?language=de-CH",
        &ph(&p),
        "audio/m4a",
        vec![1; 100],
    )
    .await;
    assert_eq!(s, 200, "{v}");
    assert_eq!(t.dg.calls.lock().unwrap()[0].3.as_deref(), Some("de-CH"));
}

#[tokio::test]
async fn admin_voice_switch_for_reading_aloud() {
    let t = start().await;
    let (_, v) = t.admin_json("GET", "/admin/api/voice", None).await;
    assert_eq!(v["tts_enabled"], true);
    // the switch alone needs no key and leaves the key alone
    set_key(&t).await;
    let (s, v) = t
        .admin_json(
            "PUT",
            "/admin/api/voice",
            Some(json!({"tts_enabled": false})),
        )
        .await;
    assert_eq!(
        (s, v["tts_enabled"].clone(), v["deepgram"]["set"].clone()),
        (200, json!(false), json!(true))
    );
    assert!(!orch_relay::speech::enabled(&t.app.db.lock().unwrap()));
    let (s, _) = t
        .admin_json(
            "PUT",
            "/admin/api/voice",
            Some(json!({"tts_enabled": "no"})),
        )
        .await;
    assert_eq!(s, 422);
    let (_, v) = t
        .admin_json(
            "PUT",
            "/admin/api/voice",
            Some(json!({"tts_enabled": true})),
        )
        .await;
    assert_eq!(v["tts_enabled"], true);
    // an empty PUT is still an invalid key
    assert_eq!(
        t.admin_json("PUT", "/admin/api/voice", Some(json!({})))
            .await
            .0,
        422
    );
}

// ---------- our own transcription service (transcription-api.md) ----------

const SVC_TOKEN: &str = "ort_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_abcde";

fn own(t: &T) -> std::sync::Arc<orch_relay::transcribe::FakeOwnService> {
    let f = std::sync::Arc::new(orch_relay::transcribe::FakeOwnService::default());
    *t.app.own_service.lock().unwrap() = f.clone();
    f
}

async fn set_service(t: &T) {
    let (s, v) = t
        .admin_json(
            "PUT",
            "/admin/api/voice/service",
            Some(json!({"url": "http://transcription.example:8104/", "token": SVC_TOKEN})),
        )
        .await;
    assert_eq!(s, 200, "{v}");
}

#[tokio::test]
async fn service_admin_set_remove_never_shows_the_token() {
    let t = start().await;
    let (s, v) = t.admin_json("GET", "/admin/api/voice/service", None).await;
    assert_eq!((s, v["set"].as_bool()), (200, Some(false)));
    set_service(&t).await;
    let (_, v) = t.admin_json("GET", "/admin/api/voice/service", None).await;
    assert_eq!(
        v,
        json!({"set": true, "url": "http://transcription.example:8104"})
    );
    let (_, voice) = t.admin_json("GET", "/admin/api/voice", None).await;
    assert_eq!(voice["service"]["set"], true);
    assert!(!voice.to_string().contains("ort_") && !v.to_string().contains("ort_"));
    // sealed in the database
    let blob: Vec<u8> = t
        .app
        .db
        .lock()
        .unwrap()
        .query_row(
            "SELECT v FROM settings WHERE k='transcription_service'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert!(!String::from_utf8_lossy(&blob).contains("ort_"));
    for bad in [
        json!({"url": "ftp://x", "token": SVC_TOKEN}),
        json!({"url": "http://x?y=1", "token": SVC_TOKEN}),
        json!({"url": "http://user@x", "token": SVC_TOKEN}),
        json!({"url": "http://x:8104", "token": "ort_short"}),
        json!({"url": "http://x:8104"}),
    ] {
        let (s, _) = t
            .admin_json("PUT", "/admin/api/voice/service", Some(bad.clone()))
            .await;
        assert_eq!(s, 422, "{bad}");
    }
    assert_eq!(
        t.admin_json("DELETE", "/admin/api/voice/service", None)
            .await
            .0,
        204
    );
    let (_, v) = t.admin_json("GET", "/admin/api/voice/service", None).await;
    assert_eq!(v["set"], false);
    let r = t
        .http
        .get(format!("{}/admin/api/voice/service", t.admin))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
}

#[tokio::test]
async fn with_our_service_set_deepgram_is_never_called() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    set_key(&t).await; // a Deepgram key is set too
    set_service(&t).await;
    let svc = own(&t);
    let (s, v) = post_audio(
        &t,
        "/v1/phone/transcribe?language=de-CH",
        &ph(&p),
        "audio/m4a",
        vec![1; 100],
    )
    .await;
    assert_eq!(s, 200, "{v}");
    assert_eq!(
        v,
        json!({"text": "from our service", "language": "de", "duration": 3.0})
    );
    let calls = svc.calls.lock().unwrap().clone();
    assert_eq!(
        calls[0],
        (
            "http://transcription.example:8104".to_string(),
            SVC_TOKEN.to_string(),
            100,
            "audio/m4a".to_string(),
            Some("de-CH".to_string())
        )
    );
    // the workspace route too
    let wsh = vec![
        ("X-Orch-Workspace", a.id.clone()),
        ("Authorization", format!("Bearer {}", a.token)),
    ];
    let (s, _) = post_audio(&t, "/v1/transcribe", &wsh, "audio/wav", vec![1; 10]).await;
    assert_eq!(s, 200);
    assert_eq!(svc.calls.lock().unwrap().len(), 2);
    assert!(
        t.dg.calls.lock().unwrap().is_empty(),
        "Deepgram must not be called"
    );
}

#[tokio::test]
async fn our_service_down_gives_a_plain_message_and_no_fallback() {
    use orch_relay::transcribe::OwnError;
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    set_key(&t).await;
    set_service(&t).await;
    let svc = own(&t);
    *svc.result.lock().unwrap() = Err(OwnError::Unavailable);
    let (s, v) = post_audio(
        &t,
        "/v1/phone/transcribe",
        &ph(&p),
        "audio/m4a",
        vec![1; 100],
    )
    .await;
    assert_eq!(
        (s, v["error"].as_str()),
        (502, Some("transcription_failed"))
    );
    assert!(
        v["message"]
            .as_str()
            .unwrap()
            .contains("not available right now"),
        "{v}"
    );
    assert!(
        t.dg.calls.lock().unwrap().is_empty(),
        "no Deepgram fallback"
    );
    *svc.result.lock().unwrap() = Err(OwnError::TooLarge);
    let (s, _) = post_audio(
        &t,
        "/v1/phone/transcribe",
        &ph(&p),
        "audio/m4a",
        vec![1; 100],
    )
    .await;
    assert_eq!(s, 413);
    *svc.result.lock().unwrap() = Err(OwnError::Unreadable);
    let (s, _) = post_audio(
        &t,
        "/v1/phone/transcribe",
        &ph(&p),
        "audio/m4a",
        vec![1; 100],
    )
    .await;
    assert_eq!(s, 422);
    // removing our service: Deepgram again, as before
    assert_eq!(
        t.admin_json("DELETE", "/admin/api/voice/service", None)
            .await
            .0,
        204
    );
    let (s, v) = post_audio(
        &t,
        "/v1/phone/transcribe",
        &ph(&p),
        "audio/m4a",
        vec![1; 100],
    )
    .await;
    assert_eq!((s, v["text"].as_str()), (200, Some("hello world")));
    assert_eq!(t.dg.calls.lock().unwrap().len(), 1);
}

/// The real client against a stand-in service on a local port: path, token, type, language, answer.
#[tokio::test]
async fn self_hosted_client_speaks_the_contract() {
    use axum::extract::Query;
    use axum::http::HeaderMap;
    use orch_relay::transcribe::{OwnError, OwnService, SelfHosted};
    use std::collections::HashMap;
    use std::future::IntoFuture;
    let seen = std::sync::Arc::new(std::sync::Mutex::new(vec![]));
    let seen2 = seen.clone();
    let app = axum::Router::new().route(
        "/v1/transcribe",
        axum::routing::post(
            move |h: HeaderMap, q: Query<HashMap<String, String>>, body: axum::body::Bytes| {
                let seen = seen2.clone();
                async move {
                    let auth = h["authorization"].to_str().unwrap().to_string();
                    let ct = h["content-type"].to_str().unwrap().to_string();
                    seen.lock().unwrap().push((
                        auth.clone(),
                        ct,
                        q.get("language").cloned(),
                        body.len(),
                    ));
                    if auth != format!("Bearer {SVC_TOKEN}") {
                        return (
                            axum::http::StatusCode::UNAUTHORIZED,
                            axum::Json(json!({"error": "unauthorized"})),
                        );
                    }
                    (
                        axum::http::StatusCode::OK,
                        axum::Json(json!({"text": " hallo ", "language": "de", "duration": 1.25})),
                    )
                }
            },
        ),
    );
    let l = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", l.local_addr().unwrap());
    tokio::spawn(axum::serve(l, app).into_future());
    let c = SelfHosted::default();
    let t = c
        .transcribe(
            &url,
            SVC_TOKEN,
            vec![1u8; 42].into(),
            "audio/m4a",
            Some("de-CH"),
        )
        .await
        .unwrap();
    assert_eq!(
        (t.text.as_str(), t.language.as_deref(), t.duration),
        ("hallo", Some("de"), 1.25)
    );
    assert_eq!(
        seen.lock().unwrap()[0],
        (
            format!("Bearer {SVC_TOKEN}"),
            "audio/m4a".to_string(),
            Some("de-CH".to_string()),
            42
        )
    );
    // a removed token (401) and a closed port are both "not available"
    let wrong = format!("ort_{}", "x".repeat(43));
    assert_eq!(
        c.transcribe(&url, &wrong, vec![1u8].into(), "audio/m4a", None)
            .await,
        Err(OwnError::Unavailable)
    );
    assert_eq!(
        c.transcribe(
            "http://127.0.0.1:9",
            SVC_TOKEN,
            vec![1u8].into(),
            "audio/m4a",
            None
        )
        .await,
        Err(OwnError::Unavailable)
    );
}

#[tokio::test]
async fn an_unreadable_service_setting_never_falls_back_to_deepgram() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    set_key(&t).await;
    // a stored setting that does not open (e.g. damaged): set, but unreadable
    t.app
        .db
        .lock()
        .unwrap()
        .execute(
            "INSERT INTO settings(k,v) VALUES('transcription_service',?1)",
            [vec![
                1u8, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22,
                23, 24, 25, 26, 27, 28, 29,
            ]],
        )
        .unwrap();
    let (s, v) = post_audio(
        &t,
        "/v1/phone/transcribe",
        &ph(&p),
        "audio/m4a",
        vec![1; 100],
    )
    .await;
    assert_eq!(
        (s, v["error"].as_str()),
        (502, Some("transcription_failed"))
    );
    assert!(
        t.dg.calls.lock().unwrap().is_empty(),
        "no Deepgram fallback"
    );
    let (_, st) = t.admin_json("GET", "/admin/api/voice/service", None).await;
    assert_eq!(
        (st["set"].as_bool(), st["broken"].as_bool()),
        (Some(true), Some(true))
    );
}

/// A redirect from the service is a failure: the recording is never sent on to another address.
#[tokio::test]
async fn self_hosted_client_never_follows_a_redirect() {
    use orch_relay::transcribe::{OwnError, OwnService, SelfHosted};
    use std::future::IntoFuture;
    let hits = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let h2 = hits.clone();
    let outside = axum::Router::new().route(
        "/steal",
        axum::routing::post(move || {
            h2.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            async { "got it" }
        }),
    );
    let lo = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let outside_url = format!("http://{}/steal", lo.local_addr().unwrap());
    tokio::spawn(axum::serve(lo, outside).into_future());
    let target = outside_url.clone();
    let svc = axum::Router::new().route(
        "/v1/transcribe",
        axum::routing::post(move || {
            let target = target.clone();
            async move {
                (
                    axum::http::StatusCode::TEMPORARY_REDIRECT,
                    [("location", target)],
                )
            }
        }),
    );
    let ls = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", ls.local_addr().unwrap());
    tokio::spawn(axum::serve(ls, svc).into_future());
    let r = SelfHosted::default()
        .transcribe(&url, SVC_TOKEN, vec![1u8; 10].into(), "audio/m4a", None)
        .await;
    assert_eq!(r, Err(OwnError::Unavailable));
    assert_eq!(hits.load(std::sync::atomic::Ordering::SeqCst), 0);
}
