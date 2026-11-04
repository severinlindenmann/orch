mod common;
use common::*;
use serde_json::json;

#[tokio::test]
async fn allow_delegate_start_need_rule_but_relay_does_not_check_allow() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    t.rules(json!([rule(&a, &b, [false, false, true, true])]))
        .await;
    // no allow_token needed at the relay: the receiver checks locally
    assert_eq!(
        t.send(&a, &b.id, "delegate", json!({"title": "t", "text": "x"}))
            .await
            .0,
        201
    );
    assert_eq!(
        t.send(
            &a,
            &b.id,
            "start",
            json!({"key": "weekly-report", "text": "x"})
        )
        .await
        .0,
        201
    );
    assert_eq!(t.send(&a, &b.id, "text", json!({"text": "x"})).await.0, 403);
}

#[tokio::test]
async fn allow_reply_must_answer_a_delegate_sent_to_you() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    t.rules(json!([rule(&a, &b, [false, false, true, true])]))
        .await;
    let (_, v) = t
        .send(
            &a,
            &b.id,
            "start",
            json!({"key": "weekly-report", "text": "x"}),
        )
        .await;
    let sid = v["id"].as_str().unwrap();
    let allow = |from: &Ws, to: &str, kind: &str| {
        json!({"schema": "orch.msg/1", "id": mid(), "from": from.id, "to": to, "type": "allow", "reply_to": sid,
            "created_at": "2026-11-04T10:00:00Z",
            "body": {"mode": "permanent", "kind": kind, "key": "weekly-report", "token": "ora_Ab3dE6gH9jK2mN5pQ8sT1v"}})
    };
    // wrong kind
    assert_eq!(
        t.call(
            &b,
            "POST",
            "/v1/messages",
            Some(allow(&b, &a.id, "delegate"))
        )
        .await
        .0,
        403
    );
    // the sender cannot allow itself
    assert_eq!(
        t.call(&a, "POST", "/v1/messages", Some(allow(&a, &b.id, "start")))
            .await
            .0,
        403
    );
    // right: B allows A, no pair rule B -> A needed
    assert_eq!(
        t.call(&b, "POST", "/v1/messages", Some(allow(&b, &a.id, "start")))
            .await
            .0,
        201
    );
    let (s, v) = t.admin_json("GET", "/admin/api/allows", None).await;
    assert_eq!(s, 200);
    let it = &v["items"][0];
    assert_eq!(
        (
            it["from"].as_str(),
            it["to"].as_str(),
            it["kind"].as_str(),
            it["key"].as_str(),
            it["mode"].as_str()
        ),
        (
            Some(b.id.as_str()),
            Some(a.id.as_str()),
            Some("start"),
            Some("weekly-report"),
            Some("permanent")
        )
    );
    // the token never appears in the admin allows list
    assert!(!v.to_string().contains("ora_"));
}
