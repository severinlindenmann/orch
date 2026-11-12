mod common;
use common::*;
use serde_json::json;

async fn make(t: &T, w: &Ws, mode: &str) -> (String, String) {
    let (s, v) = t
        .call(
            w,
            "POST",
            "/v1/webhooks",
            Some(json!({"mode": mode, "ticket": "t_7k3f9q"})),
        )
        .await;
    assert_eq!(s, 201, "{v}");
    let url = v["url"].as_str().unwrap();
    assert!(url.starts_with("https://relay.test/webhook/wh_"));
    let path = url.strip_prefix("https://relay.test").unwrap().to_string();
    (
        v["id"].as_str().unwrap().to_string(),
        format!("{}{}", t.base, path),
    )
}

#[tokio::test]
async fn webhooks_once_is_consumed_and_delivered_as_message() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let (id, url) = make(&t, &a, "once").await;
    let r = t
        .http
        .post(&url)
        .header("X-GitHub-Event", "pull_request")
        .header("X-Secret", "no")
        .body("{\"action\":\"closed\"}")
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 202);
    let r = t.http.post(&url).send().await.unwrap();
    assert_eq!(r.status(), 410);
    let items = t.inbox(&a).await;
    assert_eq!(items.len(), 1);
    let m = &items[0];
    assert_eq!(m["type"], "webhook");
    assert_eq!(m["from"], format!("webhook:{id}"));
    assert_eq!(m["ticket"], "t_7k3f9q");
    assert_eq!(m["body"]["payload"], "{\"action\":\"closed\"}");
    assert_eq!(m["body"]["method"], "POST");
    assert_eq!(m["body"]["headers"]["x-github-event"], "pull_request");
    assert!(m["body"]["headers"].get("x-secret").is_none());
    assert!(m["body"]["query"].get("token").is_none());
    let (_, l) = t.call(&a, "GET", "/v1/webhooks", None).await;
    assert!(!l["items"][0]["last_call_at"].is_null());
}

#[tokio::test]
async fn webhooks_once_concurrent_calls_only_one_wins() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let (_, url) = make(&t, &a, "once").await;
    let mut hs = vec![];
    for _ in 0..8 {
        let (c, u) = (t.http.clone(), url.clone());
        hs.push(tokio::spawn(async move {
            c.put(u).body("x").send().await.unwrap().status().as_u16()
        }));
    }
    let mut codes = vec![];
    for h in hs {
        codes.push(h.await.unwrap());
    }
    assert_eq!(codes.iter().filter(|c| **c == 202).count(), 1, "{codes:?}");
    assert_eq!(t.inbox(&a).await.len(), 1);
}

#[tokio::test]
async fn webhooks_permanent_token_and_delete() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    let (id, url) = make(&t, &a, "permanent").await;
    for _ in 0..3 {
        assert_eq!(t.http.get(&url).send().await.unwrap().status(), 202);
    }
    let bad = url.split("token=").next().unwrap().to_string() + "token=whk_wrong";
    assert_eq!(t.http.get(&bad).send().await.unwrap().status(), 401);
    assert_eq!(
        t.http
            .get(format!("{}/webhook/wh_nonexist01?token=x", t.base))
            .send()
            .await
            .unwrap()
            .status(),
        404
    );
    // only the owner can delete
    assert_eq!(
        t.call(&b, "DELETE", &format!("/v1/webhooks/{id}"), None)
            .await
            .0,
        404
    );
    assert_eq!(
        t.call(&a, "DELETE", &format!("/v1/webhooks/{id}"), None)
            .await
            .0,
        204
    );
    assert_eq!(t.http.get(&url).send().await.unwrap().status(), 404);
    // body > 1 MB
    let (_, url2) = make(&t, &a, "permanent").await;
    let big = vec![b'a'; 1024 * 1024 + 1];
    assert_eq!(
        t.http.post(&url2).body(big).send().await.unwrap().status(),
        413
    );
}

async fn post(t: &T, url: &str, body: impl Into<reqwest::Body>) -> reqwest::Response {
    t.http.post(url).body(body).send().await.unwrap()
}

fn stored(t: &T, id: &str) -> i64 {
    t.app
        .db
        .lock()
        .unwrap()
        .query_row(
            "SELECT COUNT(*) FROM messages WHERE from_addr=?1",
            [format!("webhook:{id}")],
            |r| r.get(0),
        )
        .unwrap()
}

#[tokio::test]
async fn webhooks_rate_limit_60_per_minute_then_429() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let (id, url) = make(&t, &a, "permanent").await;
    for _ in 0..60 {
        assert_eq!(post(&t, &url, "x").await.status(), 202);
    }
    let r = post(&t, &url, "x").await;
    assert_eq!(r.status(), 429);
    let retry = r.headers()["retry-after"].to_str().unwrap();
    let retry: i64 = retry.parse().unwrap();
    assert!((1..=60).contains(&retry), "{retry}");
    let v: serde_json::Value = r.json().await.unwrap();
    assert_eq!(v["error"], "rate_limited");
    assert_eq!(
        v["message"],
        "Too many calls to this webhook. Try again in a minute."
    );
    assert_eq!(stored(&t, &id), 60);
}

#[tokio::test]
async fn webhooks_wrong_token_does_not_count_and_limit_is_per_webhook() {
    let t = start().await;
    let a = t.add_ws("A").await;
    t.app
        .webhook_calls_per_minute
        .store(2, std::sync::atomic::Ordering::Relaxed);
    let (id, url) = make(&t, &a, "permanent").await;
    let bad = url.split("token=").next().unwrap().to_string() + "token=whk_wrong";
    for _ in 0..5 {
        assert_eq!(post(&t, &bad, "").await.status(), 401);
    }
    for _ in 0..2 {
        assert_eq!(post(&t, &url, "").await.status(), 202);
    }
    assert_eq!(post(&t, &url, "").await.status(), 429);
    assert_eq!(stored(&t, &id), 2);
    // another webhook is unaffected
    let (id2, url2) = make(&t, &a, "permanent").await;
    assert_eq!(post(&t, &url2, "").await.status(), 202);
    assert_eq!(stored(&t, &id2), 1);
}

#[tokio::test]
async fn webhooks_daily_byte_cap() {
    let t = start().await;
    let a = t.add_ws("A").await;
    t.app
        .webhook_bytes_per_day
        .store(100, std::sync::atomic::Ordering::Relaxed);
    let (id, url) = make(&t, &a, "permanent").await;
    let r = post(&t, &url, vec![b'a'; 101]).await;
    assert_eq!(r.status(), 429);
    assert!(r.headers().contains_key("retry-after"));
    let v: serde_json::Value = r.json().await.unwrap();
    assert_eq!(
        v["message"],
        "This webhook reached its daily size limit. Try again tomorrow."
    );
    assert_eq!(stored(&t, &id), 0);
    assert_eq!(post(&t, &url, vec![b'a'; 60]).await.status(), 202);
    assert_eq!(post(&t, &url, vec![b'a'; 41]).await.status(), 429);
    assert_eq!(stored(&t, &id), 1);
    // a refused call does not use up bytes: exactly the remaining 40 still fit
    assert_eq!(post(&t, &url, vec![b'a'; 40]).await.status(), 202);
    assert_eq!(stored(&t, &id), 2);
}

#[tokio::test]
async fn webhooks_once_refused_by_limit_is_not_consumed() {
    let t = start().await;
    let a = t.add_ws("A").await;
    t.app
        .webhook_bytes_per_day
        .store(10, std::sync::atomic::Ordering::Relaxed);
    let (id, url) = make(&t, &a, "once").await;
    assert_eq!(post(&t, &url, vec![b'a'; 11]).await.status(), 429);
    assert_eq!(stored(&t, &id), 0);
    assert_eq!(post(&t, &url, "ok").await.status(), 202);
    assert_eq!(post(&t, &url, "ok").await.status(), 410);
    assert_eq!(stored(&t, &id), 1);
}
