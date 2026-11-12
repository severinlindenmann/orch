//! Ticket display keys (DM1-12) next to `ticket`: kept on messages, copied onto answers, shown in the
//! phone updates feed and first in the push text.
mod common;
use common::*;
use serde_json::json;

async fn push_on(t: &T, p: &(String, String)) {
    t.phone(
        p,
        "POST",
        "/v1/phone/push",
        Some(json!({"apns_token": "abcdef0123000000000000000000000000000000000000000000000000000000", "sandbox": true})),
    )
    .await;
}

#[tokio::test]
async fn update_feed_and_push_carry_the_key() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    push_on(&t, &p).await;
    let m = json!({"schema": "orch.msg/1", "id": mid(), "from": a.id, "to": p.0, "type": "text",
        "created_at": "2026-11-05T10:00:00Z", "ticket": "t_aaaaaa", "key": "DM1-12",
        "body": {"text": "Done.\nmore", "update": {"kind": "result", "title": "Invoice export"}}});
    let (s, v) = t.call(&a, "POST", "/v1/messages", Some(m)).await;
    assert_eq!(s, 201, "{v}");
    {
        let sent = t.push.sent.lock().unwrap();
        assert_eq!(sent.len(), 1);
        assert_eq!(
            sent[0].2["aps"]["alert"]["body"],
            "DM1-12 · Invoice export: Done."
        );
        assert_eq!(sent[0].2["key"], "DM1-12");
        assert_eq!(sent[0].2["ticket"], "t_aaaaaa");
    }
    let (s, g) = t.phone(&p, "GET", "/v1/phone/updates", None).await;
    assert_eq!(s, 200, "{g}");
    assert_eq!(g["items"][0]["ticket"], "t_aaaaaa");
    assert_eq!(g["items"][0]["key"], "DM1-12");
    let q = format!("/v1/phone/updates?workspace={}&ticket=t_aaaaaa", a.id);
    assert_eq!(
        t.phone(&p, "GET", &q, None).await.1["items"][0]["key"],
        "DM1-12"
    );
    // a message without a key: the item has key null, the push text has no prefix
    let m = json!({"schema": "orch.msg/1", "id": mid(), "from": a.id, "to": p.0, "type": "text",
        "created_at": "2026-11-05T10:00:00Z", "ticket": "t_bbbbbb",
        "body": {"text": "ok", "update": {"kind": "ack"}}});
    assert_eq!(t.call(&a, "POST", "/v1/messages", Some(m)).await.0, 201);
    let (_, g) = t.phone(&p, "GET", "/v1/phone/updates", None).await;
    let b = g["items"]
        .as_array()
        .unwrap()
        .iter()
        .find(|i| i["ticket"] == "t_bbbbbb")
        .unwrap()
        .clone();
    assert_eq!(b["key"], json!(null));
}

#[tokio::test]
async fn question_keeps_key_and_phone_answer_copies_it() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    push_on(&t, &p).await;
    let m = json!({"schema": "orch.msg/1", "id": mid(), "from": a.id, "to": "phones", "type": "question",
        "ticket": "t_7k3f9q", "key": "MEC-3", "created_at": "2026-11-04T10:00:00Z",
        "body": {"question_id": "q1", "text": "Which type?", "options": [], "recommended": null}});
    let (s, v) = t.call(&a, "POST", "/v1/messages", Some(m)).await;
    assert_eq!(s, 201, "{v}");
    let qid = v["id"].as_str().unwrap().to_string();
    assert_eq!(
        t.push.sent.lock().unwrap()[0].2["aps"]["alert"]["body"],
        "MEC-3 · Which type?"
    );
    let (_, qs) = t.phone(&p, "GET", "/v1/phone/questions", None).await;
    assert_eq!(qs["items"][0]["message"]["key"], "MEC-3");
    assert_eq!(qs["items"][0]["message"]["ticket"], "t_7k3f9q");
    let (s, v) = t
        .phone(
            &p,
            "POST",
            "/v1/phone/answer",
            Some(json!({"client_id": "4705de22-948e-439d-87b9-fcd4081039ba", "question_message_id": qid, "answer": "DATE"})),
        )
        .await;
    assert_eq!(s, 201, "{v}");
    let inbox = t.inbox(&a).await;
    let ans = inbox.iter().find(|m| m["type"] == "answer").unwrap();
    assert_eq!(
        (ans["ticket"].clone(), ans["key"].clone()),
        (json!("t_7k3f9q"), json!("MEC-3"))
    );
}

#[tokio::test]
async fn workspace_answer_takes_the_askers_key_not_its_own() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    t.rules(json!([
        rule(&a, &b, [true, true, true, true]),
        rule(&b, &a, [true, true, true, true])
    ]))
    .await;
    let q = json!({"schema": "orch.msg/1", "id": mid(), "from": a.id, "to": b.id, "type": "question",
        "ticket": "t_7k3f9q", "key": "AB-7", "created_at": "2026-11-04T10:00:00Z",
        "body": {"question_id": "q1", "text": "Go?", "options": [], "recommended": null}});
    let (s, v) = t.call(&a, "POST", "/v1/messages", Some(q)).await;
    assert_eq!(s, 201, "{v}");
    let qid = v["id"].as_str().unwrap().to_string();
    let ans = json!({"schema": "orch.msg/1", "id": mid(), "from": b.id, "to": a.id, "type": "answer",
        "reply_to": qid, "ticket": "t_zzzzzz", "key": "XX-1", "created_at": "2026-11-04T10:01:00Z",
        "body": {"question_id": "q1", "answer": "yes", "answered_by": "agent:b"}});
    let (s, v) = t.call(&b, "POST", "/v1/messages", Some(ans)).await;
    assert_eq!(s, 201, "{v}");
    let inbox = t.inbox(&a).await;
    let got = inbox.iter().find(|m| m["type"] == "answer").unwrap();
    assert_eq!(
        (got["ticket"].clone(), got["key"].clone()),
        (json!("t_7k3f9q"), json!("AB-7"))
    );
}

#[tokio::test]
async fn a_bad_key_is_dropped_never_listed_or_pushed() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    push_on(&t, &p).await;
    let long = format!("DM1-{}", "1".repeat(115));
    let bad = [
        json!({"k": "DM1-1"}),
        json!(12),
        json!("DM1-1\u{0007}\n"),
        json!(long),
        json!("dm1-1"),
        json!("DM1-0"),
    ];
    for (i, k) in bad.iter().enumerate() {
        let tid = format!("t_bad00{i}");
        let m = json!({"schema": "orch.msg/1", "id": mid(), "from": a.id, "to": p.0, "type": "text",
            "created_at": "2026-11-05T10:00:00Z", "ticket": tid, "key": k,
            "body": {"text": "Done.", "update": {"kind": "result", "title": "Export"}}});
        let (s, v) = t.call(&a, "POST", "/v1/messages", Some(m)).await;
        assert_eq!(s, 201, "the message is kept: {v}");
        let q = format!("/v1/phone/updates?workspace={}&ticket={tid}", a.id);
        let item = t.phone(&p, "GET", &q, None).await.1["items"][0].clone();
        assert_eq!(item["key"], json!(null), "{k}");
        let inbox = t.inbox(&a).await;
        assert!(inbox.iter().all(|m| m.get("key").is_none()));
        // the push budget lets only the first text push through: check that one
        if i == 0 {
            let sent = t.push.sent.lock().unwrap();
            assert_eq!(sent[0].2["aps"]["alert"]["body"], "Export: Done.");
            assert_eq!(sent[0].2["key"], json!(null));
        }
    }
}
