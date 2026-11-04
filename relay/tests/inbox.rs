mod common;
use common::*;
use serde_json::json;
use std::time::{Duration, Instant};

async fn pair(t: &T) -> (Ws, Ws) {
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    t.rules(json!([rule(&a, &b, [true, true, true, true])]))
        .await;
    (a, b)
}

#[tokio::test]
async fn inbox_ack_removes_and_only_receiver() {
    let t = start().await;
    let (a, b) = pair(&t).await;
    let id = t.send(&a, &b.id, "text", json!({"text": "1"})).await.1["id"]
        .as_str()
        .unwrap()
        .to_string();
    assert!(t.inbox(&a).await.is_empty(), "sender does not see it");
    assert_eq!(t.inbox(&b).await.len(), 1);
    assert_eq!(t.inbox(&b).await.len(), 1, "not acked yet: delivered again");
    // sender cannot ack it
    assert_eq!(
        t.call(&a, "POST", "/v1/inbox/ack", Some(json!({"ids": [id]})))
            .await
            .0,
        204
    );
    assert_eq!(t.inbox(&b).await.len(), 1);
    assert_eq!(
        t.call(&b, "POST", "/v1/inbox/ack", Some(json!({"ids": [id]})))
            .await
            .0,
        204
    );
    assert!(t.inbox(&b).await.is_empty());
}

#[tokio::test]
async fn inbox_oldest_first_and_cursor_pagination() {
    let t = start().await;
    let (a, b) = pair(&t).await;
    for i in 0..5 {
        t.send(&a, &b.id, "text", json!({"text": format!("m{i}")}))
            .await;
    }
    let (_, v) = t.call(&b, "GET", "/v1/inbox?limit=2", None).await;
    assert_eq!(v["items"][0]["body"]["text"], "m0");
    assert_eq!(v["items"].as_array().unwrap().len(), 2);
    let next = v["next"].as_str().unwrap();
    let (_, v2) = t
        .call(&b, "GET", &format!("/v1/inbox?limit=2&after={next}"), None)
        .await;
    assert_eq!(v2["items"][0]["body"]["text"], "m2");
    let (_, v3) = t
        .call(
            &b,
            "GET",
            &format!("/v1/inbox?limit=2&after={}", v2["next"].as_str().unwrap()),
            None,
        )
        .await;
    assert_eq!(v3["items"].as_array().unwrap().len(), 1);
    assert!(v3["next"].is_null());
}

#[tokio::test]
async fn inbox_long_poll_wakes_on_new_message() {
    let t = start().await;
    let (a, b) = pair(&t).await;
    let t = std::sync::Arc::new(t);
    let t2 = t.clone();
    let start_at = Instant::now();
    let h = tokio::spawn(async move {
        let b2 = Ws {
            id: b.id,
            token: b.token,
        };
        t2.call(&b2, "GET", "/v1/inbox?wait=10", None).await
    });
    tokio::time::sleep(Duration::from_millis(400)).await;
    let bid = t
        .app
        .db
        .lock()
        .unwrap()
        .query_row("SELECT id FROM workspaces WHERE name='B'", [], |r| {
            r.get::<_, String>(0)
        })
        .unwrap();
    t.send(&a, &bid, "text", json!({"text": "wake"})).await;
    let (s, v) = h.await.unwrap();
    assert_eq!(s, 200);
    assert_eq!(v["items"].as_array().unwrap().len(), 1);
    assert!(start_at.elapsed() < Duration::from_secs(5));
}

#[tokio::test]
async fn inbox_wait_times_out_empty() {
    let t = start().await;
    let (_a, b) = pair(&t).await;
    let at = Instant::now();
    let (s, v) = t.call(&b, "GET", "/v1/inbox?wait=1", None).await;
    assert_eq!(s, 200);
    assert!(v["items"].as_array().unwrap().is_empty());
    assert!(at.elapsed() >= Duration::from_millis(900));
}

#[tokio::test]
async fn inbox_blobs_ownership_size_sha_and_encryption() {
    let t = start().await;
    let (a, b) = pair(&t).await;
    let c = t.add_ws("C").await;
    let data = b"hello blob data".to_vec();
    let up = t
        .http
        .post(format!("{}/v1/blobs", t.base))
        .header("X-Orch-Workspace", &a.id)
        .header("Authorization", format!("Bearer {}", a.token))
        .body(data.clone())
        .send()
        .await
        .unwrap();
    assert_eq!(up.status(), 201);
    let v: serde_json::Value = up.json().await.unwrap();
    let (bid, sha) = (
        v["blob_id"].as_str().unwrap().to_string(),
        v["sha256"].as_str().unwrap().to_string(),
    );
    assert_eq!(v["size"], data.len());
    // wrong sha -> 422; right -> 201
    let bad =
        json!({"blob_id": bid, "name": "a.txt", "size": data.len(), "sha256": "0".repeat(64)});
    assert_eq!(t.send(&a, &b.id, "file", bad).await.0, 422);
    // someone else cannot attach it
    t.rules(json!([
        rule(&a, &b, [true, true, true, true]),
        rule(&b, &a, [true, true, true, true])
    ]))
    .await;
    let ok = json!({"blob_id": bid, "name": "a.txt", "size": data.len(), "sha256": sha});
    assert_eq!(t.send(&b, &a.id, "file", ok.clone()).await.0, 403);
    // receiver cannot read before the file message
    let get = |w: &Ws| {
        t.http
            .get(format!("{}/v1/blobs/{}", t.base, bid))
            .header("X-Orch-Workspace", w.id.clone())
            .header("Authorization", format!("Bearer {}", w.token))
            .send()
    };
    assert_eq!(get(&b).await.unwrap().status(), 404);
    assert_eq!(t.send(&a, &b.id, "file", ok).await.0, 201);
    let r = get(&b).await.unwrap();
    assert_eq!(r.status(), 200);
    assert_eq!(r.bytes().await.unwrap().to_vec(), data);
    assert_eq!(get(&c).await.unwrap().status(), 404);
    assert_eq!(get(&a).await.unwrap().status(), 200);
    // at rest: file on disk is not the plaintext
    let raw = std::fs::read(t.app.blob_path(&bid)).unwrap();
    assert!(!String::from_utf8_lossy(&raw).contains("hello blob"));
}

#[tokio::test]
async fn inbox_retention_purges_after_90_days() {
    let t = start().await;
    let (a, b) = pair(&t).await;
    t.send(&a, &b.id, "text", json!({"text": "old"})).await;
    let c = t.app.db.lock().unwrap();
    let (m, _) =
        orch_relay::store::purge(&c, t.dir.path(), orch_relay::util::now() + 89 * 86400).unwrap();
    assert_eq!(m, 0);
    let (m, _) =
        orch_relay::store::purge(&c, t.dir.path(), orch_relay::util::now() + 91 * 86400).unwrap();
    assert_eq!(m, 1);
}

#[tokio::test]
async fn blob_upload_checks_auth_before_body_and_caps_size_while_streaming() {
    let t = start().await;
    let (a, _b) = pair(&t).await;
    // no credentials: refused (401), body not needed
    let r = t
        .http
        .post(format!("{}/v1/blobs", t.base))
        .body(vec![0u8; 1024 * 1024])
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
    // wrong token: refused
    let r = t
        .http
        .post(format!("{}/v1/blobs", t.base))
        .header("X-Orch-Workspace", &a.id)
        .header("Authorization", "Bearer nope")
        .body(vec![0u8; 16])
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
    // chunked (no content-length) body over the cap: 413
    let chunks = futures_util::stream::iter(
        (0..105).map(|_| Ok::<_, std::io::Error>(axum::body::Bytes::from(vec![7u8; 1024 * 1024]))),
    );
    let r = t
        .http
        .post(format!("{}/v1/blobs", t.base))
        .header("X-Orch-Workspace", &a.id)
        .header("Authorization", format!("Bearer {}", a.token))
        .body(reqwest::Body::wrap_stream(chunks))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 413);
}
