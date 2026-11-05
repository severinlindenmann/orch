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
    let items = t.inbox(&a).await;
    // pairing sent A a refresh-hint (its phone list changed), then the phone's text
    assert_eq!(items[0]["type"], "refresh-hint");
    let m = &items[1];
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

async fn ws_text(t: &T, from: &Ws, to: &str, text: &str) -> (u16, serde_json::Value) {
    t.send(from, to, "text", json!({"text": text})).await
}

#[tokio::test]
async fn phone_reply_paired_workspace_can_send_to_its_phone() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    t.phone(
        &p,
        "POST",
        "/v1/phone/push",
        Some(json!({"apns_token": "abcdef0123", "sandbox": true})),
    )
    .await;
    let (s, _) = t
        .phone(
            &p,
            "POST",
            "/v1/phone/send",
            Some(json!({"to": a.id, "text": "can you answer my phone"})),
        )
        .await;
    assert_eq!(s, 201);
    // A answers the phone directly (no admin rule needed: the pairing is the rule)
    let (s, v) = ws_text(&t, &a, &p.0, "yes, I can").await;
    assert_eq!(s, 201, "{v}");
    // and to all its phones
    let (s, v) = ws_text(&t, &a, "phones", "to every phone").await;
    assert_eq!(s, 201, "{v}");
    let (s, m) = t.phone(&p, "GET", "/v1/phone/messages", None).await;
    assert_eq!(s, 200, "{m}");
    let texts: Vec<&str> = m["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|x| x["message"]["body"]["text"].as_str().unwrap())
        .collect();
    assert_eq!(
        texts,
        ["to every phone", "yes, I can", "can you answer my phone"],
        "newest first, both directions"
    );
    assert_eq!(m["items"][0]["workspace_name"], "A");
    assert_eq!(
        m["items"][2]["workspace_name"], "A",
        "own message names its workspace"
    );
    // both texts were pushed, as text pushes (no question message_id)
    let sent = t.push.sent.lock().unwrap().clone();
    assert_eq!(sent.len(), 2, "{sent:?}");
    assert_eq!(sent[0].2["type"], "text");
    assert_eq!(sent[0].2["aps"]["alert"]["body"], "yes, I can");
    assert!(sent[0].2.get("message_id").is_none());
    assert_eq!(sent[0].2["workspace"], json!(a.id));
}

#[tokio::test]
async fn phone_reply_unpaired_workspace_or_phone_is_refused_plainly() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    let p = t.pair_phone(&[&a]).await;
    // B is not on the phone's list
    let (s, v) = ws_text(&t, &b, &p.0, "hi").await;
    assert_eq!(s, 403, "{v}");
    let msg = v["message"].as_str().unwrap();
    assert!(msg.contains("Phones") && msg.contains("B"), "{msg}");
    // B's "phones" message reaches no phone of A's
    ws_text(&t, &b, "phones", "b broadcast").await;
    let (_, m) = t.phone(&p, "GET", "/v1/phone/messages", None).await;
    assert_eq!(m["items"].as_array().unwrap().len(), 0, "{m}");
    // unknown phone
    let (s, _) = ws_text(&t, &a, "ph_zzzzzzzzzz", "hi").await;
    assert_eq!(s, 403);
    // only text and questions to a phone
    let (s, v) = t
        .send(&a, &p.0, "delegate", json!({"title": "x", "text": "y"}))
        .await;
    assert_eq!(s, 403, "{v}");
    // added but never paired (QR not scanned yet): unreachable
    let (_, v) = t
        .admin_json(
            "POST",
            "/admin/api/phones",
            Some(json!({"name": "Unscanned", "workspaces": [a.id]})),
        )
        .await;
    let (s, _) = ws_text(&t, &a, v["phone_id"].as_str().unwrap(), "hi").await;
    assert_eq!(s, 403);
    // signed out: unreachable
    t.phone(&p, "POST", "/v1/phone/signout", None).await;
    let (s, _) = ws_text(&t, &a, &p.0, "still there?").await;
    assert_eq!(s, 403);
}

#[tokio::test]
async fn phone_reply_question_to_one_phone() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let (p1, p2) = (t.pair_phone(&[&a]).await, t.pair_phone(&[&a]).await);
    let m = json!({"schema": "orch.msg/1", "id": mid(), "from": a.id, "to": p1.0, "type": "question", "ticket": "t_7k3f9q",
        "created_at": "2026-11-04T10:00:00Z", "body": {"question_id": "q1", "text": "ok?", "options": ["yes", "no"], "recommended": null}});
    let (s, v) = t.call(&a, "POST", "/v1/messages", Some(m)).await;
    assert_eq!(s, 201, "{v}");
    let qid = v["id"].as_str().unwrap().to_string();
    let (_, q2) = t.phone(&p2, "GET", "/v1/phone/questions", None).await;
    assert_eq!(
        q2["items"].as_array().unwrap().len(),
        0,
        "other phone sees it"
    );
    let (_, q1) = t.phone(&p1, "GET", "/v1/phone/questions", None).await;
    assert_eq!(q1["items"][0]["message"]["id"], json!(qid));
    let (s, _) = t
        .phone(
            &p2,
            "POST",
            "/v1/phone/answer",
            Some(json!({"question_message_id": qid, "answer": "no"})),
        )
        .await;
    assert_eq!(s, 404);
    let (s, _) = t
        .phone(
            &p1,
            "POST",
            "/v1/phone/answer",
            Some(json!({"question_message_id": qid, "answer": "yes"})),
        )
        .await;
    assert_eq!(s, 201);
}

#[tokio::test]
async fn phone_reply_refresh_lists_reachable_phones() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    let p = t.pair_phone(&[&a]).await;
    // pairing tells A to refresh
    assert!(t
        .inbox(&a)
        .await
        .iter()
        .any(|m| m["type"] == "refresh-hint"));
    let (_, snap) = t.call(&a, "GET", "/v1/refresh", None).await;
    let phones = snap["workspaces"]["phones"].as_array().unwrap();
    assert_eq!(phones.len(), 1, "{snap}");
    assert_eq!(phones[0]["id"], json!(p.0));
    assert_eq!(phones[0]["name"], "Test iPhone");
    assert_eq!(phones[0]["online"], true);
    let (_, snap) = t.call(&b, "GET", "/v1/refresh", None).await;
    assert_eq!(snap["workspaces"]["phones"], json!([]));
    // admin moves the phone to B: both get a hint, lists swap
    let (s, _) = t
        .admin_json(
            "PATCH",
            &format!("/admin/api/phones/{}", p.0),
            Some(json!({"workspaces": [b.id]})),
        )
        .await;
    assert_eq!(s, 200);
    assert!(t
        .inbox(&b)
        .await
        .iter()
        .any(|m| m["type"] == "refresh-hint"));
    let (_, snap) = t.call(&a, "GET", "/v1/refresh", None).await;
    assert_eq!(snap["workspaces"]["phones"], json!([]));
    let (s, _) = ws_text(&t, &a, &p.0, "gone?").await;
    assert_eq!(s, 403);
    let (_, snap) = t.call(&b, "GET", "/v1/refresh", None).await;
    assert_eq!(snap["workspaces"]["phones"][0]["id"], json!(p.0));
}
