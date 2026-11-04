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
