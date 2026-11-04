mod common;
use common::*;
use serde_json::json;

async fn question(t: &T, from: &Ws, text: &str, qid: &str) -> String {
    let m = json!({"schema": "orch.msg/1", "id": mid(), "from": from.id, "to": "phones", "type": "question", "ticket": "t_7k3f9q",
        "created_at": "2026-11-04T10:00:00Z", "body": {"question_id": qid, "text": text, "options": ["DATE", "TIMESTAMP"], "recommended": null}});
    let (s, v) = t.call(from, "POST", "/v1/messages", Some(m)).await;
    assert_eq!(s, 201, "{v}");
    v["id"].as_str().unwrap().to_string()
}

#[tokio::test]
async fn phone_pair_once_workspaces_and_signout() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    let (_, v) = t
        .admin_json(
            "POST",
            "/admin/api/phones",
            Some(json!({"name": "P", "workspaces": [a.id]})),
        )
        .await;
    assert!(v["link"]
        .as_str()
        .unwrap()
        .starts_with("orch://pair?relay=https%3A%2F%2Frelay%2Etest&code=pc_"));
    assert!(v["qr_svg"].as_str().unwrap().contains("<svg"));
    let code = v["link"]
        .as_str()
        .unwrap()
        .split("code=")
        .nth(1)
        .unwrap()
        .to_string();
    let pair = || {
        t.http
            .post(format!("{}/v1/phone/pair", t.base))
            .json(&json!({"code": code, "name": "My iPhone"}))
            .send()
    };
    let r = pair().await.unwrap();
    assert_eq!(r.status(), 201);
    let pv: serde_json::Value = r.json().await.unwrap();
    assert_eq!(pv["workspaces"], json!([{"id": a.id, "name": "A"}]));
    assert_eq!(pair().await.unwrap().status(), 410, "one use only");
    let p = (
        pv["phone_id"].as_str().unwrap().to_string(),
        pv["token"].as_str().unwrap().to_string(),
    );
    let (s, w) = t.phone(&p, "GET", "/v1/phone/workspaces", None).await;
    assert_eq!(s, 200);
    assert_eq!(w["items"].as_array().unwrap().len(), 1);
    assert_eq!(w["items"][0]["open_questions"], 0);
    // phone token does not work on workspace routes and vice versa
    let r = t
        .http
        .get(format!("{}/v1/whoami", t.base))
        .header("X-Orch-Workspace", &a.id)
        .header("Authorization", format!("Bearer {}", p.1))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
    assert_eq!(
        t.phone(
            &(a.id.clone(), a.token.clone()),
            "GET",
            "/v1/phone/workspaces",
            None
        )
        .await
        .0,
        401
    );
    // may not send to B
    assert_eq!(
        t.phone(
            &p,
            "POST",
            "/v1/phone/send",
            Some(json!({"to": b.id, "text": "x"}))
        )
        .await
        .0,
        403
    );
    let (s, v) = t
        .phone(
            &p,
            "POST",
            "/v1/phone/send",
            Some(json!({"to": a.id, "text": "Book the train", "ticket": null})),
        )
        .await;
    assert_eq!(s, 201, "{v}");
    let m = &t.inbox(&a).await[0];
    assert_eq!(
        (
            m["from"].as_str(),
            m["type"].as_str(),
            m["body"]["text"].as_str()
        ),
        (Some(p.0.as_str()), Some("text"), Some("Book the train"))
    );
    assert_eq!(t.phone(&p, "POST", "/v1/phone/signout", None).await.0, 204);
    assert_eq!(
        t.phone(&p, "GET", "/v1/phone/workspaces", None).await.0,
        401
    );
}

#[tokio::test]
async fn phone_question_push_answer_first_wins() {
    let t = start().await;
    let (a, b) = (t.add_ws("Pilatus Workspace").await, t.add_ws("Other").await);
    let p = t.pair_phone(&[&a]).await;
    let p2 = t.pair_phone(&[&a, &b]).await;
    assert_eq!(
        t.phone(
            &p,
            "POST",
            "/v1/phone/push",
            Some(json!({"apns_token": "abcdef0123", "sandbox": true}))
        )
        .await
        .0,
        204
    );
    let long = "x".repeat(300);
    let qid = question(&t, &a, &long, "q1").await;
    {
        let sent = t.push.sent.lock().unwrap();
        assert_eq!(sent.len(), 1);
        assert_eq!((sent[0].0, sent[0].1.as_str()), (true, "abcdef0123"));
        let pl = &sent[0].2;
        assert_eq!(pl["aps"]["alert"]["title"], "Pilatus Workspace");
        assert_eq!(pl["aps"]["alert"]["body"].as_str().unwrap().len(), 120);
        assert_eq!(
            (pl["message_id"].as_str(), pl["workspace"].as_str()),
            (Some(qid.as_str()), Some(a.id.as_str()))
        );
    }
    // a question from B is invisible to the first phone
    question(&t, &b, "other?", "q1").await;
    let (_, qs) = t.phone(&p, "GET", "/v1/phone/questions", None).await;
    assert_eq!(qs["items"].as_array().unwrap().len(), 1);
    assert_eq!(qs["items"][0]["workspace_name"], "Pilatus Workspace");
    assert_eq!(
        t.phone(&p2, "GET", "/v1/phone/questions", None).await.1["items"]
            .as_array()
            .unwrap()
            .len(),
        2
    );
    assert_eq!(
        t.phone(&p, "GET", "/v1/phone/workspaces", None).await.1["items"][0]["open_questions"],
        1
    );
    // answer
    let (s, v) = t
        .phone(
            &p,
            "POST",
            "/v1/phone/answer",
            Some(json!({"question_message_id": qid, "answer": "TIMESTAMP"})),
        )
        .await;
    assert_eq!(s, 201, "{v}");
    let (s, v) = t
        .phone(
            &p2,
            "POST",
            "/v1/phone/answer",
            Some(json!({"question_message_id": qid, "answer": "DATE"})),
        )
        .await;
    assert_eq!((s, v["error"].as_str()), (409, Some("already_answered")));
    assert_eq!(
        v["message"],
        "This question was already answered: TIMESTAMP."
    );
    let inbox = t.inbox(&a).await;
    let ans = inbox.iter().find(|m| m["type"] == "answer").unwrap();
    assert_eq!(ans["reply_to"], qid.as_str());
    assert_eq!(ans["ticket"], "t_7k3f9q");
    assert_eq!(ans["body"]["question_id"], "q1");
    assert_eq!(ans["body"]["answered_by"], "human:Test iPhone");
    assert_eq!(ans["from"], p.0.as_str());
    assert_eq!(
        t.phone(&p, "GET", "/v1/phone/questions", None).await.1["items"]
            .as_array()
            .unwrap()
            .len(),
        0
    );
    // answering a question of a workspace the phone cannot reach
    let bq = question(&t, &b, "again?", "q2").await;
    assert_eq!(
        t.phone(
            &p,
            "POST",
            "/v1/phone/answer",
            Some(json!({"question_message_id": bq, "answer": "x"}))
        )
        .await
        .0,
        404
    );
}

#[tokio::test]
async fn phone_access_edit_and_remove_by_admin() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    let p = t.pair_phone(&[&a, &b]).await;
    assert_eq!(
        t.phone(&p, "GET", "/v1/phone/workspaces", None).await.1["items"]
            .as_array()
            .unwrap()
            .len(),
        2
    );
    let (s, _) = t
        .admin_json(
            "PATCH",
            &format!("/admin/api/phones/{}", p.0),
            Some(json!({"workspaces": [a.id]})),
        )
        .await;
    assert_eq!(s, 200);
    assert_eq!(
        t.phone(&p, "GET", "/v1/phone/workspaces", None).await.1["items"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    assert_eq!(
        t.admin_json("DELETE", &format!("/admin/api/phones/{}", p.0), None)
            .await
            .0,
        204
    );
    assert_eq!(
        t.phone(&p, "GET", "/v1/phone/workspaces", None).await.0,
        401
    );
}

#[tokio::test]
async fn phone_send_validates_ticket() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    for bad in ["t_x", "T_ABCDEF", "nope", "t_0123456789abcdefg"] {
        let (s, v) = t
            .phone(
                &p,
                "POST",
                "/v1/phone/send",
                Some(json!({"to": a.id, "text": "x", "ticket": bad})),
            )
            .await;
        assert_eq!((s, v["error"].as_str()), (422, Some("invalid")), "{bad}");
    }
    assert_eq!(
        t.phone(
            &p,
            "POST",
            "/v1/phone/send",
            Some(json!({"to": a.id, "text": "x", "ticket": "t_abc123"}))
        )
        .await
        .0,
        201
    );
}

#[tokio::test]
async fn phone_dead_apns_token_is_removed() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    t.phone(
        &p,
        "POST",
        "/v1/phone/push",
        Some(json!({"apns_token": "abcdef0123", "sandbox": false})),
    )
    .await;
    *t.push.fail.lock().unwrap() = Some(orch_relay::push::PushError {
        message: "apns status=410 apns-id=- reason=Unregistered".into(),
        dead_token: true,
    });
    question(&t, &a, "one?", "q1").await;
    question(&t, &a, "two?", "q2").await;
    // first push failed and dropped the token; the second question sends nothing
    assert_eq!(t.push.sent.lock().unwrap().len(), 1);
}
