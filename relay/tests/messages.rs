mod common;
use common::*;
use serde_json::json;

#[tokio::test]
async fn messages_send_and_from_bound() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    t.rules(json!([rule(&a, &b, [true, false, false, false])]))
        .await;
    let (s, v) = t.send(&a, &b.id, "text", json!({"text": "hi"})).await;
    assert_eq!(s, 201, "{v}");
    // from must be the caller
    let m = json!({"schema": "orch.msg/1", "id": mid(), "from": b.id, "to": a.id, "type": "text",
        "created_at": "2026-11-04T10:00:00Z", "body": {"text": "spoof"}});
    let (s, v) = t.call(&a, "POST", "/v1/messages", Some(m)).await;
    assert_eq!((s, v["error"].as_str()), (403, Some("forbidden")));
    // wrong token
    let bad = Ws {
        id: a.id.clone(),
        token: "orn_wrong".into(),
    };
    assert_eq!(t.call(&bad, "GET", "/v1/whoami", None).await.0, 401);
}

#[tokio::test]
async fn messages_rule_is_one_way_and_per_type() {
    let t = start().await;
    let (a, b) = (
        t.add_ws("Pilatus Workspace").await,
        t.add_ws("Reports").await,
    );
    t.rules(json!([rule(&a, &b, [true, false, false, false])]))
        .await;
    let (s, v) = t.send(&b, &a.id, "text", json!({"text": "x"})).await;
    assert_eq!(s, 403);
    assert_eq!(v["error"], "not_allowed");
    assert_eq!(
        v["message"],
        "Reports may not send text to Pilatus Workspace."
    );
    assert_eq!(
        t.send(&a, &b.id, "delegate", json!({"title": "t", "text": "x"}))
            .await
            .0,
        403
    );
    assert_eq!(
        t.send(&a, &b.id, "start", json!({"key": "k", "text": "x"}))
            .await
            .0,
        403
    );
    assert_eq!(
        t.send(&a, "ws_unknown001", "text", json!({"text": "x"}))
            .await
            .0,
        404
    );
}

#[tokio::test]
async fn messages_duplicate_and_conflict() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    t.rules(json!([rule(&a, &b, [true, false, false, false])]))
        .await;
    let m = json!({"schema": "orch.msg/1", "id": "m_a1b2c3d4e5f6g7h8", "from": a.id, "to": b.id, "type": "text",
        "created_at": "2026-11-04T10:00:00Z", "body": {"text": "one"}});
    assert_eq!(
        t.call(&a, "POST", "/v1/messages", Some(m.clone())).await.0,
        201
    );
    let (s, v) = t.call(&a, "POST", "/v1/messages", Some(m.clone())).await;
    assert_eq!((s, v["duplicate"].clone()), (200, json!(true)));
    assert_eq!(t.inbox(&b).await.len(), 1);
    let mut m2 = m.clone();
    m2["body"]["text"] = json!("two");
    let (s, v) = t.call(&a, "POST", "/v1/messages", Some(m2)).await;
    assert_eq!((s, v["error"].as_str()), (409, Some("conflict")));
}

#[tokio::test]
async fn messages_schema_invalid_is_422() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    t.rules(json!([rule(&a, &b, [true, false, false, false])]))
        .await;
    let (s, v) = t.send(&a, &b.id, "text", json!({"nope": 1})).await;
    assert_eq!((s, v["error"].as_str()), (422, Some("invalid")));
    // a question needs a ticket; relay-only types are refused
    let m = json!({"schema": "orch.msg/1", "id": mid(), "from": a.id, "to": b.id, "type": "refresh-hint",
        "created_at": "2026-11-04T10:00:00Z", "body": {"version": 1}});
    assert_eq!(t.call(&a, "POST", "/v1/messages", Some(m)).await.0, 422);
}

#[tokio::test]
async fn messages_answer_copies_ticket_from_question() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    t.rules(json!([rule(&a, &b, [true, false, false, false])]))
        .await;
    let q = json!({"schema": "orch.msg/1", "id": mid(), "from": a.id, "to": b.id, "type": "question", "ticket": "t_aaaaaa",
        "created_at": "2026-11-04T10:00:00Z", "body": {"question_id": "q1", "text": "?", "options": ["x", "y"], "recommended": null}});
    assert_eq!(
        t.call(&a, "POST", "/v1/messages", Some(q.clone())).await.0,
        201
    );
    // B answers (no rule B -> A needed), with a bogus ticket and question id
    let ans = json!({"schema": "orch.msg/1", "id": mid(), "from": b.id, "to": a.id, "type": "answer", "ticket": "t_bbbbbb",
        "reply_to": q["id"], "created_at": "2026-11-04T10:00:00Z",
        "body": {"question_id": "q9", "answer": "x", "answered_by": "agent:b"}});
    assert_eq!(t.call(&b, "POST", "/v1/messages", Some(ans)).await.0, 201);
    let got = t.inbox(&a).await;
    assert_eq!(got[0]["ticket"], "t_aaaaaa");
    assert_eq!(got[0]["body"]["question_id"], "q1");
    assert_eq!(got[0]["body"]["answered_by"], "agent:B", "set by the relay");
    // a second answer to the same question is refused
    let again = json!({"schema": "orch.msg/1", "id": mid(), "from": b.id, "to": a.id, "type": "answer", "ticket": "t_aaaaaa",
        "reply_to": q["id"], "created_at": "2026-11-04T10:00:00Z",
        "body": {"question_id": "q1", "answer": "y", "answered_by": "agent:b"}});
    let (s, v) = t.call(&b, "POST", "/v1/messages", Some(again)).await;
    assert_eq!((s, v["error"].as_str()), (409, Some("already_answered")));
    // an answer to something that is not a question for you is refused
    let bad = json!({"schema": "orch.msg/1", "id": mid(), "from": a.id, "to": b.id, "type": "answer", "ticket": "t_aaaaaa",
        "reply_to": q["id"], "created_at": "2026-11-04T10:00:00Z",
        "body": {"question_id": "q1", "answer": "x", "answered_by": "agent:a"}});
    assert_eq!(t.call(&a, "POST", "/v1/messages", Some(bad)).await.0, 403);
}

#[tokio::test]
async fn messages_unknown_fields_kept_and_body_encrypted_at_rest() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    t.rules(json!([rule(&a, &b, [true, false, false, false])]))
        .await;
    let m = json!({"schema": "orch.msg/1", "id": mid(), "from": a.id, "to": b.id, "type": "text",
        "created_at": "2026-11-04T10:00:00Z", "x_extra": {"k": 1}, "body": {"text": "SECRET-PLAINTEXT-123"}});
    assert_eq!(t.call(&a, "POST", "/v1/messages", Some(m)).await.0, 201);
    let got = t.inbox(&b).await;
    assert_eq!(got[0]["x_extra"], json!({"k": 1}));
    assert_eq!(got[0]["body"]["text"], "SECRET-PLAINTEXT-123");
    let c = t.app.db.lock().unwrap();
    let raw: Vec<u8> = c
        .query_row("SELECT payload FROM messages LIMIT 1", [], |r| r.get(0))
        .unwrap();
    assert!(!String::from_utf8_lossy(&raw).contains("SECRET-PLAINTEXT"));
}

#[tokio::test]
async fn messages_ids_with_wrong_shape_refused() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    t.rules(json!([rule(&a, &b, [true, false, false, false])]))
        .await;
    let m = json!({"schema": "orch.msg/1", "id": "m_short", "from": a.id, "to": b.id, "type": "text",
        "created_at": "2026-11-04T10:00:00Z", "body": {"text": "x"}});
    assert_eq!(t.call(&a, "POST", "/v1/messages", Some(m)).await.0, 422);
}

#[tokio::test]
async fn messages_workspace_cannot_answer_a_question_to_phones() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    t.rules(json!([rule(&a, &b, [true, false, false, false])]))
        .await;
    let q = json!({"schema": "orch.msg/1", "id": mid(), "from": a.id, "to": "phones", "type": "question", "ticket": "t_aaaaaa",
        "created_at": "2026-11-04T10:00:00Z", "body": {"question_id": "q1", "text": "?", "options": []}});
    assert_eq!(
        t.call(&a, "POST", "/v1/messages", Some(q.clone())).await.0,
        201
    );
    let ans = json!({"schema": "orch.msg/1", "id": mid(), "from": b.id, "to": a.id, "type": "answer", "ticket": "t_aaaaaa",
        "reply_to": q["id"], "created_at": "2026-11-04T10:00:00Z",
        "body": {"question_id": "q1", "answer": "x", "answered_by": "agent:b"}});
    assert_eq!(t.call(&b, "POST", "/v1/messages", Some(ans)).await.0, 403);
}

#[tokio::test]
async fn not_found_is_the_same_for_unknown_and_unconnected() {
    let t = start().await;
    let (a, b, c) = (
        t.add_ws("Alpha").await,
        t.add_ws("Secret Beta").await,
        t.add_ws("Gamma").await,
    );
    t.rules(json!([rule(&a, &c, [true, true, false, false])]))
        .await;
    let (s1, v1) = t
        .send(&a, "ws_unknown001", "text", json!({"text": "x"}))
        .await;
    let (s2, v2) = t.send(&a, &b.id, "text", json!({"text": "x"})).await;
    assert_eq!((s1, s2), (404, 404));
    assert_eq!(v1, v2);
    assert_eq!(v1["error"], "not_found");
    assert!(!v2.to_string().contains("Secret Beta"));
    // connected pair keeps the specific answer
    let (s3, v3) = t
        .send(&a, &c.id, "delegate", json!({"title": "t", "text": "x"}))
        .await;
    assert_eq!(s3, 403);
    assert!(v3["message"].as_str().unwrap().contains("Gamma"));
}
