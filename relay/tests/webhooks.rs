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
