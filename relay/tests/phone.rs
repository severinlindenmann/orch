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
            Some(json!({"client_id": "506c7836-7437-445a-9d9b-d89cfa9280b1", "to": b.id, "text": "x"}))
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
            Some(json!({"client_id": "16d0f8ca-8ef5-4fe0-85f9-a49c4b36b2f0", "to": a.id, "text": "Book the train", "ticket": null})),
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
            Some(json!({"client_id": "89844c7d-c056-4358-96fa-0029ddda285e", "question_message_id": qid, "answer": "TIMESTAMP"})),
        )
        .await;
    assert_eq!(s, 201, "{v}");
    let (s, v) = t
        .phone(
            &p2,
            "POST",
            "/v1/phone/answer",
            Some(json!({"client_id": "caff3c95-72c7-41aa-9eaf-dfbdf8c28d86", "question_message_id": qid, "answer": "DATE"})),
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
            Some(json!({"client_id": "13ef7789-cc8e-4925-8274-ff257cda9365", "question_message_id": bq, "answer": "x"}))
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
                Some(json!({"client_id": "ae0fc0e2-1274-4189-8a8a-81ede0473a22", "to": a.id, "text": "x", "ticket": bad})),
            )
            .await;
        assert_eq!((s, v["error"].as_str()), (422, Some("invalid")), "{bad}");
    }
    assert_eq!(
        t.phone(
            &p,
            "POST",
            "/v1/phone/send",
            Some(json!({"client_id": "ee0e9b92-1964-4cdd-91ae-0ba7baea9b67", "to": a.id, "text": "x", "ticket": "t_abc123"}))
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
            Some(json!({"client_id": "e630af20-fef5-4bd5-a526-3a3c376a94c3", "to": a.id, "text": "can you answer my phone"})),
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
    // the first text was pushed as a text push (no question message_id); the second came within 10 s
    // of it, so it is stored and readable (above) but not pushed (L2)
    let sent = t.push.sent.lock().unwrap().clone();
    assert_eq!(sent.len(), 1, "{sent:?}");
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
            Some(json!({"client_id": "e4b43c69-d851-43ff-88e6-f1f92aee9dfd", "question_message_id": qid, "answer": "no"})),
        )
        .await;
    assert_eq!(s, 404);
    let (s, _) = t
        .phone(
            &p1,
            "POST",
            "/v1/phone/answer",
            Some(json!({"client_id": "261a3f6e-b052-4009-9ff1-17f42c53e689", "question_message_id": qid, "answer": "yes"})),
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

#[tokio::test]
async fn phone_text_push_budget_skips_extra_pushes_but_keeps_texts() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    let p = t.pair_phone(&[&a, &b]).await;
    t.phone(
        &p,
        "POST",
        "/v1/phone/push",
        Some(json!({"apns_token": "abcdef0123", "sandbox": true})),
    )
    .await;
    for i in 0..5 {
        assert_eq!(ws_text(&t, &a, &p.0, &format!("a{i}")).await.0, 201);
    }
    // another workspace has its own budget; questions are never limited
    assert_eq!(ws_text(&t, &b, &p.0, "b0").await.0, 201);
    question(&t, &a, "q?", "q1").await;
    assert_eq!(
        t.push.sent.lock().unwrap().len(),
        3,
        "1 text from A, 1 from B, 1 question"
    );
    let (_, m) = t.phone(&p, "GET", "/v1/phone/messages", None).await;
    assert_eq!(
        m["items"].as_array().unwrap().len(),
        6,
        "every text is stored and readable"
    );
}

#[tokio::test]
async fn phone_name_at_pairing_is_cleaned() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let pair = |name: String| {
        let t = &t;
        let a = &a;
        async move {
            let (_, v) = t
                .admin_json(
                    "POST",
                    "/admin/api/phones",
                    Some(json!({"name": "Label", "workspaces": [a.id]})),
                )
                .await;
            let code = v["link"]
                .as_str()
                .unwrap()
                .split("code=")
                .nth(1)
                .unwrap()
                .to_string();
            let r = t
                .http
                .post(format!("{}/v1/phone/pair", t.base))
                .json(&json!({"code": code, "name": name}))
                .send()
                .await
                .unwrap();
            assert_eq!(r.status(), 201);
            let (_, w) = t.call(a, "GET", "/v1/refresh", None).await;
            w["workspaces"]["phones"]
                .as_array()
                .unwrap()
                .iter()
                .map(|p| p["name"].as_str().unwrap().to_string())
                .collect::<Vec<_>>()
        }
    };
    let names = pair(format!("  {}\n\u{202e}x\u{200b}  ", "n".repeat(100_000))).await;
    let n = names
        .iter()
        .find(|n| n.starts_with('n'))
        .expect("cleaned name listed");
    assert_eq!(n.chars().count(), 60);
    assert!(
        n.chars().all(|c| c == 'n'),
        "control and invisible characters dropped: {n:?}"
    );
    let names = pair("\u{200b}\n".into()).await;
    assert!(
        names.contains(&"Label".to_string()),
        "nothing left: the admin's label stays: {names:?}"
    );
}

#[tokio::test]
async fn phone_broadcast_history_starts_at_pairing_and_filters_in_sql() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    // a broadcast from before any phone existed
    assert_eq!(ws_text(&t, &a, "phones", "old broadcast").await.0, 201);
    // stored_at has second resolution: make the old one strictly older
    t.app
        .db
        .lock()
        .unwrap()
        .execute("UPDATE messages SET stored_at=stored_at-5", [])
        .unwrap();
    let p = t.pair_phone(&[&a]).await;
    assert_eq!(ws_text(&t, &a, "phones", "new broadcast").await.0, 201);
    assert_eq!(ws_text(&t, &a, &p.0, "direct").await.0, 201);
    assert_eq!(
        ws_text(&t, &b, "phones", "from a workspace not on the list")
            .await
            .0,
        201
    );
    let (_, m) = t.phone(&p, "GET", "/v1/phone/messages", None).await;
    let texts: Vec<&str> = m["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|x| x["message"]["body"]["text"].as_str().unwrap())
        .collect();
    assert_eq!(texts, ["direct", "new broadcast"]);
    // paging by cursor still works with the SQL limit
    let (_, m) = t.phone(&p, "GET", "/v1/phone/messages?limit=1", None).await;
    assert_eq!(m["items"].as_array().unwrap().len(), 1);
    assert!(m["next"].is_string());
}

#[tokio::test]
async fn phone_message_queries_use_the_indexes() {
    let t = start().await;
    let c = t.app.db.lock().unwrap();
    let plan_of = |sql: &str, n: usize| -> String {
        let mut st = c.prepare(&format!("EXPLAIN QUERY PLAN {sql}")).unwrap();
        let all: Vec<rusqlite::types::Value> = vec![
            rusqlite::types::Value::Text("ph_x".into()),
            if n == 5 {
                i64::MAX.into()
            } else {
                rusqlite::types::Value::Text("[]".into())
            },
            rusqlite::types::Value::Text("[]".into()),
            0i64.into(),
            50i64.into(),
        ];
        let rows = st
            .query_map(rusqlite::params_from_iter(all.into_iter().take(n)), |r| {
                r.get::<_, String>(3)
            })
            .unwrap();
        rows.map(|r| r.unwrap()).collect::<Vec<_>>().join("\n")
    };
    for (name, plan) in [
        ("messages", plan_of(orch_relay::phone::MESSAGES_SQL, 5)),
        (
            "questions",
            plan_of(orch_relay::phone::OPEN_QUESTIONS_SQL, 2),
        ),
    ] {
        assert!(
            !plan.contains("SCAN m") && !plan.contains("SCAN messages"),
            "{name}: {plan}"
        );
        for line in plan.lines().filter(|l| l.contains("messages")) {
            assert!(
                line.contains("INDEX msg_type_") || line.contains("INDEX msg_reply"),
                "{name}: messages must be read through an index: {line}\n{plan}"
            );
            assert!(
                line.contains("from_addr=")
                    || line.contains("to_addr=")
                    || line.contains("reply_to="),
                "{name}: not just (type=?): {line}\n{plan}"
            );
        }
        // any sort is of the (small) matched rows, never of the main table
    }
}

#[tokio::test]
async fn phone_list_with_a_workspace_twice_shows_everything_once() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    // the admin saves the same workspace twice: stored once
    let (s, v) = t
        .admin_json(
            "PATCH",
            &format!("/admin/api/phones/{}", p.0),
            Some(json!({"workspaces": [a.id, a.id]})),
        )
        .await;
    assert_eq!(s, 200, "{v}");
    let (_, l) = t.admin_json("GET", "/admin/api/phones", None).await;
    assert_eq!(l["items"][0]["workspaces"], json!([a.id]));
    // an old row with a repeat (saved before the fix) is read once too
    t.app
        .db
        .lock()
        .unwrap()
        .execute(
            "UPDATE phones SET workspaces=?2 WHERE id=?1",
            rusqlite::params![p.0, json!([a.id, a.id]).to_string()],
        )
        .unwrap();
    question(&t, &a, "q?", "q1").await;
    assert_eq!(ws_text(&t, &a, &p.0, "hi").await.0, 201);
    assert_eq!(
        t.phone(&p, "GET", "/v1/phone/questions", None).await.1["items"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    assert_eq!(
        t.phone(&p, "GET", "/v1/phone/messages", None).await.1["items"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    assert_eq!(
        t.phone(&p, "GET", "/v1/phone/workspaces", None).await.1["items"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
}

async fn upd(
    t: &T,
    from: &Ws,
    to: &str,
    ticket: &str,
    kind: &str,
    title: Option<&str>,
    text: &str,
) -> (u16, serde_json::Value) {
    let mut u = json!({"kind": kind});
    if let Some(t) = title {
        u["title"] = t.into();
    }
    let m = json!({"schema": "orch.msg/1", "id": mid(), "from": from.id, "to": to, "type": "text",
        "created_at": "2026-11-05T10:00:00Z", "ticket": ticket, "body": {"text": text, "update": u}});
    t.call(from, "POST", "/v1/messages", Some(m)).await
}

async fn push_on(t: &T, p: &(String, String)) {
    t.phone(
        p,
        "POST",
        "/v1/phone/push",
        Some(json!({"apns_token": "abcdef0123", "sandbox": true})),
    )
    .await;
}

#[tokio::test]
async fn phone_updates_push_only_result_question_failure_stopped() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    push_on(&t, &p).await;
    for k in ["ack", "working", "note"] {
        assert_eq!(
            upd(&t, &a, &p.0, "t_aaaaaa", k, Some("Invoice"), "x")
                .await
                .0,
            201
        );
    }
    assert_eq!(t.push.sent.lock().unwrap().len(), 0, "quiet kinds");
    assert_eq!(
        upd(
            &t,
            &a,
            &p.0,
            "t_aaaaaa",
            "result",
            Some("Invoice export"),
            "Done.\nmore"
        )
        .await
        .0,
        201
    );
    {
        let sent = t.push.sent.lock().unwrap();
        assert_eq!(sent.len(), 1, "quiet kinds did not use up the budget");
        assert_eq!(sent[0].2["aps"]["alert"]["body"], "Invoice export: Done.");
    }
    // a plain text keeps today's rule (second push within 10 s is over the budget, still stored)
    assert_eq!(ws_text(&t, &a, &p.0, "hello").await.0, 201);
    assert_eq!(t.push.sent.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn phone_updates_grouped_per_ticket_and_one_ticket_paged() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    let p = t.pair_phone(&[&a, &b]).await;
    ws_text(&t, &a, &p.0, "plain, not an update").await;
    let mut ids = vec![];
    for (i, k) in ["ack", "working", "result"].iter().enumerate() {
        let (s, v) = upd(&t, &a, &p.0, "t_aaaaaa", k, Some("One"), &format!("n{i}")).await;
        assert_eq!(s, 201);
        ids.push(v["id"].as_str().unwrap().to_string());
    }
    upd(&t, &a, "phones", "t_bbbbbb", "ack", None, "got it").await;
    upd(
        &t,
        &b,
        &p.0,
        "t_aaaaaa",
        "note",
        None,
        "same ticket id, other ws",
    )
    .await;
    let (s, g) = t.phone(&p, "GET", "/v1/phone/updates", None).await;
    assert_eq!(s, 200, "{g}");
    let items = g["items"].as_array().unwrap();
    assert_eq!(items.len(), 3, "one per (workspace, ticket)");
    assert_eq!(g["next"], json!(null));
    assert_eq!(items[0]["workspace"], json!(b.id));
    assert_eq!(items[0]["workspace_name"], "B");
    assert_eq!(items[2]["id"], json!(ids[2]), "newest of A/t_aaaaaa");
    assert_eq!(items[2]["kind"], "result");
    assert_eq!(items[2]["title"], "One");
    assert_eq!(items[1]["title"], json!(null));
    // title falls back to the newest update that has one
    upd(&t, &a, &p.0, "t_cccccc", "ack", Some("Older title"), "a").await;
    upd(&t, &a, &p.0, "t_cccccc", "result", None, "b").await;
    let (_, g2) = t.phone(&p, "GET", "/v1/phone/updates", None).await;
    assert_eq!(g2["items"][0]["kind"], "result");
    assert_eq!(g2["items"][0]["title"], "Older title");
    // narrowed by workspace
    let (_, g) = t
        .phone(
            &p,
            "GET",
            &format!("/v1/phone/updates?workspace={}", b.id),
            None,
        )
        .await;
    assert_eq!(g["items"].as_array().unwrap().len(), 1);
    // one ticket, paged 2 + 1
    let base = format!(
        "/v1/phone/updates?workspace={}&ticket=t_aaaaaa&limit=2",
        a.id
    );
    let (_, p1) = t.phone(&p, "GET", &base, None).await;
    let i1: Vec<_> = p1["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|i| i["id"].clone())
        .collect();
    assert_eq!(i1, vec![json!(ids[2]), json!(ids[1])]);
    assert_eq!(p1["next"], json!(ids[1]));
    let (_, p2) = t
        .phone(&p, "GET", &format!("{base}&after={}", ids[1]), None)
        .await;
    assert_eq!(p2["items"].as_array().unwrap().len(), 1);
    assert_eq!(p2["items"][0]["id"], json!(ids[0]));
    assert_eq!(p2["items"][0]["reply_to"], json!(null));
    assert_eq!(p2["next"], json!(null));
    // errors
    let (s, _) = t
        .phone(&p, "GET", "/v1/phone/updates?ticket=t_aaaaaa", None)
        .await;
    assert_eq!(s, 422, "ticket without workspace");
    let (s, _) = t
        .phone(&p, "GET", &format!("{base}&after=m_doesnotexist0000"), None)
        .await;
    assert_eq!(s, 422, "after not in the view");
    // an `after` from another ticket is not in this view either
    let (_, o) = t
        .phone(
            &p,
            "GET",
            &format!("/v1/phone/updates?workspace={}&ticket=t_bbbbbb", a.id),
            None,
        )
        .await;
    let other = o["items"][0]["id"].as_str().unwrap().to_string();
    let (s, _) = t
        .phone(&p, "GET", &format!("{base}&after={other}"), None)
        .await;
    assert_eq!(s, 422);
}

#[tokio::test]
async fn phone_updates_hide_unlisted_workspaces_like_unknown_ones() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    let p = t.pair_phone(&[&a]).await;
    upd(&t, &a, &p.0, "t_aaaaaa", "result", Some("T"), "x").await;
    let q = format!("/v1/phone/updates?workspace={}&ticket=t_aaaaaa", b.id);
    let unknown = "/v1/phone/updates?workspace=ws_unknown0000&ticket=t_aaaaaa";
    let (s1, v1) = t.phone(&p, "GET", &q, None).await;
    let (s2, v2) = t.phone(&p, "GET", unknown, None).await;
    assert_eq!((s1, &v1), (200, &json!({"items": [], "next": null})));
    assert_eq!((s2, v2), (200, v1));
    // removed from the list at read time: disappears at once
    let (s, _) = t
        .admin_json(
            "PATCH",
            &format!("/admin/api/phones/{}", p.0),
            Some(json!({"workspaces": [b.id]})),
        )
        .await;
    assert_eq!(s, 200);
    let (_, g) = t.phone(&p, "GET", "/v1/phone/updates", None).await;
    assert_eq!(g["items"], json!([]));
    // no token, no view
    let r = t
        .http
        .get(format!("{}/v1/phone/updates", t.base))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
}

#[tokio::test]
async fn phone_updates_title_rule_is_enforced() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    let nfd = "Cafe\u{301}"; // not NFC
    for bad in [
        nfd,
        "   ",
        "two\nlines",
        "zero\u{200b}width",
        "bidi\u{202e}x",
        "zalgo\u{301}\u{302}\u{303}",
        "x\u{fe0f}",
    ] {
        let (s, v) = upd(&t, &a, &p.0, "t_aaaaaa", "note", Some(bad), "x").await;
        assert_eq!(s, 422, "{bad:?}: {v}");
    }
    let long = "x".repeat(121);
    assert_eq!(
        upd(&t, &a, &p.0, "t_aaaaaa", "note", Some(&long), "x")
            .await
            .0,
        422
    );
    assert_eq!(
        upd(
            &t,
            &a,
            &p.0,
            "t_aaaaaa",
            "note",
            Some("Caf\u{e9} Rechnung \u{1f4c4}"),
            "x"
        )
        .await
        .0,
        201
    );
}

#[tokio::test]
async fn phone_updates_scan_is_capped_per_request() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    let (s, old) = upd(&t, &a, &p.0, "t_aaaaaa", "result", Some("Old"), "old").await;
    assert_eq!(s, 201);
    let (_, newer) = upd(&t, &a, &p.0, "t_aaaaaa", "note", Some("Old"), "newer").await;
    for i in 0..2100 {
        assert_eq!(ws_text(&t, &a, &p.0, &format!("n{i}")).await.0, 201);
    }
    // the two updates lie beyond 2000 newer rows: the request stops at the cap instead of walking them
    let (s, g) = t.phone(&p, "GET", "/v1/phone/updates", None).await;
    assert_eq!((s, &g["items"]), (200, &json!([])));
    // `after` is resolved in SQL: the page after `newer` is found without walking the newer rows
    let q = format!(
        "/v1/phone/updates?workspace={}&ticket=t_aaaaaa&after={}",
        a.id,
        newer["id"].as_str().unwrap()
    );
    let (s, v) = t.phone(&p, "GET", &q, None).await;
    assert_eq!(s, 200, "{v}");
    assert_eq!(v["items"][0]["id"], old["id"]);
}
