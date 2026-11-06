//! Phone app v3 (contracts/relay-api.md "Phone app v3"): send/answer dedupe, uploads, receipts, settings,
//! invitations, mute and remove. The contract vector `phone-v3-v1.json` is replayed against the real routes.
mod common;
use common::*;
use serde_json::{json, Value};

type P = (String, String);

fn vectors() -> Value {
    serde_json::from_str(include_str!("../../contracts/vectors/phone-v3-v1.json")).unwrap()
}

const C1: &str = "6f1c2a9e-3b7d-4c8e-9a10-2b3c4d5e6f70";
const C2: &str = "0b7a4c1e-9d2f-4e6a-8b3c-5d6e7f809a1b";

async fn upload(t: &T, p: &P, bytes: Vec<u8>) -> (u16, Value) {
    let r = t
        .http
        .post(format!("{}/v1/phone/blobs", t.base))
        .header("X-Orch-Phone", &p.0)
        .header("Authorization", format!("Bearer {}", p.1))
        .header("Content-Type", "image/jpeg")
        .body(bytes)
        .send()
        .await
        .unwrap();
    (r.status().as_u16(), r.json().await.unwrap_or(Value::Null))
}

async fn raw_get(t: &T, who: (&str, &str, &str), path: &str) -> (u16, Vec<u8>) {
    let r = t
        .http
        .get(format!("{}{}", t.base, path))
        .header(who.0, who.1)
        .header("Authorization", format!("Bearer {}", who.2))
        .send()
        .await
        .unwrap();
    (r.status().as_u16(), r.bytes().await.unwrap().to_vec())
}

async fn phone_blob(t: &T, p: &P, id: &str) -> (u16, Vec<u8>) {
    raw_get(
        t,
        ("X-Orch-Phone", &p.0, &p.1),
        &format!("/v1/phone/blobs/{id}"),
    )
    .await
}

async fn ws_blob(t: &T, w: &Ws, id: &str) -> (u16, Vec<u8>) {
    raw_get(
        t,
        ("X-Orch-Workspace", &w.id, &w.token),
        &format!("/v1/blobs/{id}"),
    )
    .await
}

async fn send(t: &T, p: &P, body: Value) -> (u16, Value) {
    t.phone(p, "POST", "/v1/phone/send", Some(body)).await
}

async fn ack(t: &T, w: &Ws, ids: &[&str]) {
    let (s, _) = t
        .call(w, "POST", "/v1/inbox/ack", Some(json!({"ids": ids})))
        .await;
    assert_eq!(s, 204);
}

async fn ws_text(t: &T, w: &Ws, to: &str, extra: Value, body: Value) -> (u16, Value) {
    let mut m = json!({"schema": "orch.msg/1", "id": mid(), "from": w.id, "to": to, "type": "text",
        "created_at": "2026-11-06T10:00:00Z", "body": body});
    for (k, v) in extra.as_object().unwrap() {
        m[k] = v.clone();
    }
    t.call(w, "POST", "/v1/messages", Some(m)).await
}

async fn messages(t: &T, p: &P) -> Vec<Value> {
    t.phone(p, "GET", "/v1/phone/messages", None).await.1["items"]
        .as_array()
        .unwrap()
        .clone()
}

/// Insert a phone-owned blob row directly (the vector uses fixed blob ids).
fn fake_blob(t: &T, pid: &str, id: &str, size: i64) {
    t.app
        .db
        .lock()
        .unwrap()
        .execute(
            "INSERT OR REPLACE INTO blobs(id,uploader,size,sha256,created_at) VALUES(?1,?2,?3,'x',?4)",
            rusqlite::params![id, pid, size, orch_relay::util::now()],
        )
        .unwrap();
}

#[tokio::test]
async fn vector_send_cases_build_the_contract_message() {
    let t = start().await;
    let a = t.add_ws("A").await;
    for case in vectors()["send"].as_array().unwrap() {
        let p = t.pair_phone(&[&a]).await;
        let mut req = case["request"].clone();
        let name = case["name"].as_str().unwrap();
        // The vector's fixed ids: our workspace, this phone's blobs, a stored text to reply to.
        if req["to"].as_str().is_some_and(|t| t.starts_with("ws_")) {
            req["to"] = a.id.clone().into();
        }
        let mut all = vec![];
        for x in req["attachments"].as_array().into_iter().flatten() {
            all.push((x["blob_id"].clone(), x["size"].as_i64().unwrap_or(1)));
        }
        if req["voice"]["blob_id"].is_string() {
            all.push((req["voice"]["blob_id"].clone(), 1));
        }
        for x in req["feedback"]["pins"].as_array().into_iter().flatten() {
            if x["voice_blob_id"].is_string() {
                all.push((x["voice_blob_id"].clone(), 1));
            }
        }
        for (b, size) in all {
            fake_blob(&t, &p.0, b.as_str().unwrap(), size);
        }
        if let Some(r) = req["reply_to"].as_str() {
            t.app.db.lock().unwrap().execute(
                "INSERT INTO messages(id,from_addr,to_addr,type,created_at,digest,payload,stored_at) VALUES(?1,?2,?3,'text','2026-11-06T09:00:00Z','',x'00',?4)",
                rusqlite::params![r, a.id, p.0, orch_relay::util::now()],
            ).unwrap();
        }
        let (s, v) = send(&t, &p, req.clone()).await;
        if case["ok"] == true {
            assert_eq!(s, 201, "{name}: {v}");
            assert_eq!(v["client_id"], req["client_id"], "{name}");
            let got = t
                .inbox(&a)
                .await
                .into_iter()
                .find(|m| m["id"] == v["id"])
                .unwrap_or_else(|| panic!("{name}: not in inbox"));
            let built = &case["built"];
            assert_eq!(got["body"], built["body"], "{name}");
            assert_eq!(got["ticket"], built["ticket"], "{name} ticket");
            assert_eq!(got["reply_to"], built["reply_to"], "{name} reply_to");
            assert_eq!(got["type"], "text");
            assert_eq!(got["from"], p.0.as_str());
        } else {
            assert_eq!(
                (s, v["error"].as_str()),
                (422, Some("invalid")),
                "{name}: {v}"
            );
        }
    }
}

#[tokio::test]
async fn vector_settings_workspace_patch_and_answer_shapes() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    for case in vectors()["settings_patch"].as_array().unwrap() {
        let (s, v) = t
            .phone(
                &p,
                "PATCH",
                "/v1/phone/settings",
                Some(case["request"].clone()),
            )
            .await;
        let n = case["name"].as_str().unwrap();
        if case["ok"] == true {
            assert_eq!(s, 200, "{n}: {v}");
        } else {
            assert_eq!((s, v["error"].as_str()), (422, Some("invalid")), "{n}");
        }
    }
    for case in vectors()["workspace_patch"].as_array().unwrap() {
        let (s, v) = t
            .phone(
                &p,
                "PATCH",
                &format!("/v1/phone/workspaces/{}", a.id),
                Some(case["request"].clone()),
            )
            .await;
        let n = case["name"].as_str().unwrap();
        if case["ok"] == true {
            assert_eq!(s, 200, "{n}: {v}");
        } else {
            assert_eq!((s, v["error"].as_str()), (422, Some("invalid")), "{n}");
        }
    }
    // an answer without client_id is invalid
    let (s, _) = t
        .phone(
            &p,
            "POST",
            "/v1/phone/answer",
            Some(vectors()["answer"][1]["request"].clone()),
        )
        .await;
    assert_eq!(s, 422);
}

#[tokio::test]
async fn send_client_id_dedupes_across_send_and_answer() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    let (s, v) = send(
        &t,
        &p,
        json!({"to": a.id, "client_id": C1, "text": "one", "general": true}),
    )
    .await;
    assert_eq!((s, v["client_id"].as_str()), (201, Some(C1)));
    let id = v["id"].clone();
    // retry, even with different content: 200 duplicate, no second message
    let (s, v) = send(
        &t,
        &p,
        json!({"to": a.id, "client_id": C1, "text": "changed"}),
    )
    .await;
    assert_eq!(s, 200, "{v}");
    assert_eq!(v, json!({"id": id, "client_id": C1, "duplicate": true}));
    let texts: Vec<_> = t
        .inbox(&a)
        .await
        .into_iter()
        .filter(|m| m["type"] == "text")
        .collect();
    assert_eq!(texts.len(), 1);
    // the same id on the answer route is the same namespace
    let q = mid();
    let m = json!({"schema": "orch.msg/1", "id": q, "from": a.id, "to": "phones", "type": "question", "ticket": "t_7k3f9q",
        "created_at": "2026-11-06T10:00:00Z", "body": {"question_id": "q1", "text": "?", "options": ["A", "B"], "recommended": null}});
    assert_eq!(t.call(&a, "POST", "/v1/messages", Some(m)).await.0, 201);
    let (s, v) = t
        .phone(
            &p,
            "POST",
            "/v1/phone/answer",
            Some(json!({"question_message_id": q, "answer": "A", "client_id": C1})),
        )
        .await;
    assert_eq!(
        (s, v["duplicate"].clone(), v["id"].clone()),
        (200, json!(true), id)
    );
    // a new client_id answers; a retry of the winning answer is a duplicate, not a 409
    let ans = json!({"question_message_id": q, "answer": "A", "client_id": C2});
    let (s, v) = t
        .phone(&p, "POST", "/v1/phone/answer", Some(ans.clone()))
        .await;
    assert_eq!((s, v["client_id"].as_str()), (201, Some(C2)));
    let first = v["id"].clone();
    let (s, v) = t.phone(&p, "POST", "/v1/phone/answer", Some(ans)).await;
    assert_eq!(
        (s, v["duplicate"].clone(), v["id"].clone()),
        (200, json!(true), first)
    );
    let (s, v) = t
        .phone(&p, "POST", "/v1/phone/answer", Some(json!({"question_message_id": q, "answer": "B", "client_id": "11111111-2222-4333-8444-555555555555"})))
        .await;
    assert_eq!((s, v["error"].as_str()), (409, Some("already_answered")));
    // the stored answer carries the client_id
    let inbox = t.inbox(&a).await;
    let ans = inbox.iter().find(|m| m["type"] == "answer").unwrap();
    assert_eq!(ans["body"]["client_id"], C2);
    // another phone's client_id space is separate
    let p2 = t.pair_phone(&[&a]).await;
    assert_eq!(
        send(
            &t,
            &p2,
            json!({"to": a.id, "client_id": C1, "text": "mine"})
        )
        .await
        .0,
        201
    );
}

#[tokio::test]
async fn send_checks_list_reply_to_and_blob_ownership() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    let p = t.pair_phone(&[&a]).await;
    let p2 = t.pair_phone(&[&a]).await;
    // not on the list: 403
    let (s, v) = send(&t, &p, json!({"to": b.id, "client_id": C1, "text": "x"})).await;
    assert_eq!((s, v["error"].as_str()), (403, Some("not_allowed")));
    // unauthenticated
    let r = t
        .http
        .post(format!("{}/v1/phone/send", t.base))
        .json(&json!({}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
    // reply_to must be a text of this phone's conversation with that workspace
    let (s, _) = send(
        &t,
        &p,
        json!({"to": a.id, "client_id": C1, "text": "x", "reply_to": "m_aaaaaaaaaaaaaaaa"}),
    )
    .await;
    assert_eq!(s, 422, "unknown reply_to");
    let (s, v) = send(
        &t,
        &p2,
        json!({"to": a.id, "client_id": C1, "text": "from p2"}),
    )
    .await;
    assert_eq!(s, 201);
    let others = v["id"].as_str().unwrap().to_string();
    let (s, _) = send(
        &t,
        &p,
        json!({"to": a.id, "client_id": C2, "text": "x", "reply_to": others}),
    )
    .await;
    assert_eq!(s, 422, "another phone's text");
    let (_, v) = send(
        &t,
        &p,
        json!({"to": a.id, "client_id": "11111111-2222-4333-8444-555555555555", "text": "mine"}),
    )
    .await;
    let mine = v["id"].as_str().unwrap().to_string();
    let (s, _) = send(
        &t,
        &p,
        json!({"to": a.id, "client_id": C2, "text": "x", "reply_to": mine}),
    )
    .await;
    assert_eq!(s, 201, "own text");
    // blobs: unknown, another phone's, and a wrong size
    let (s, up) = upload(&t, &p, vec![1u8; 100]).await;
    assert_eq!(s, 201);
    let bid = up["blob_id"].as_str().unwrap();
    let att = |size: i64| json!([{"blob_id": bid, "kind": "image", "name": "a.jpg", "size": size, "mime": "image/jpeg"}]);
    let c3 = "22222222-2222-4333-8444-555555555555";
    let (s, _) = send(
        &t,
        &p2,
        json!({"to": a.id, "client_id": c3, "attachments": att(100)}),
    )
    .await;
    assert_eq!(s, 404, "another phone's upload");
    let (s, _) = send(
        &t,
        &p,
        json!({"to": a.id, "client_id": c3, "attachments": att(99)}),
    )
    .await;
    assert_eq!(s, 422, "size must match");
    let (s, _) = send(&t, &p, json!({"to": a.id, "client_id": c3, "voice": {"blob_id": "b_nonexistent00000", "transcript": "", "lang": "de", "lang_source": "detected"}})).await;
    assert_eq!(s, 404, "unknown voice blob");
    let (s, _) = send(
        &t,
        &p,
        json!({"to": a.id, "client_id": c3, "attachments": att(100)}),
    )
    .await;
    assert_eq!(s, 201);
}

#[tokio::test]
async fn phone_uploads_have_limits_and_read_rules() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    let p = t.pair_phone(&[&a, &b]).await;
    let p2 = t.pair_phone(&[&a]).await;
    // empty, too big, unauthenticated
    assert_eq!(upload(&t, &p, vec![]).await.0, 422);
    let (s, v) = upload(&t, &p, vec![0u8; 25 * 1024 * 1024 + 1]).await;
    assert_eq!((s, v["error"].as_str()), (413, Some("too_large")));
    let r = t
        .http
        .post(format!("{}/v1/phone/blobs", t.base))
        .body("x")
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
    // exactly 25 MB is fine
    let (s, v) = upload(&t, &p, vec![7u8; 25 * 1024 * 1024]).await;
    assert_eq!(s, 201, "{v}");
    // upload: size + sha256, read back by the uploader only, served as octet-stream
    let data = b"hello photo".to_vec();
    let (s, up) = upload(&t, &p, data.clone()).await;
    assert_eq!(s, 201);
    assert_eq!(up["size"], 11);
    assert_eq!(up["sha256"], orch_relay::util::sha256_hex(&data));
    let bid = up["blob_id"].as_str().unwrap().to_string();
    assert_eq!(phone_blob(&t, &p, &bid).await, (200, data.clone()));
    assert_eq!(phone_blob(&t, &p2, &bid).await.0, 404, "another phone");
    // workspaces cannot read it before a text names it
    assert_eq!(ws_blob(&t, &a, &bid).await.0, 404);
    let att = json!([{"blob_id": bid, "kind": "file", "name": "n.txt", "size": 11, "mime": "text/plain"}]);
    let (s, _) = send(
        &t,
        &p,
        json!({"to": a.id, "client_id": C1, "attachments": att}),
    )
    .await;
    assert_eq!(s, 201);
    assert_eq!(
        ws_blob(&t, &a, &bid).await,
        (200, data),
        "the named workspace"
    );
    assert_eq!(ws_blob(&t, &b, &bid).await.0, 404, "another workspace");
    // removing the workspace from the phone does not take the read access back
    assert_eq!(
        t.phone(
            &p,
            "DELETE",
            &format!("/v1/phone/workspaces/{}", a.id),
            None
        )
        .await
        .0,
        204
    );
    assert_eq!(ws_blob(&t, &a, &bid).await.0, 200);
    // an expired blob is gone
    {
        let c = t.app.db.lock().unwrap();
        c.execute(
            "UPDATE blobs SET created_at=?2 WHERE id=?1",
            rusqlite::params![bid, orch_relay::util::now() - 91 * 86400],
        )
        .unwrap();
        orch_relay::store::purge(&c, t.dir.path(), orch_relay::util::now()).unwrap();
    }
    assert_eq!(phone_blob(&t, &p, &bid).await.0, 404);
}

#[tokio::test]
async fn receipts_delivered_at_client_id_and_general_updates() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    let (_, v) = send(
        &t,
        &p,
        json!({"to": a.id, "client_id": C1, "text": "hi", "general": true}),
    )
    .await;
    let id = v["id"].as_str().unwrap().to_string();
    let items = messages(&t, &p).await;
    assert_eq!(items[0]["client_id"], C1);
    assert_eq!(items[0]["delivered_at"], Value::Null);
    ack(&t, &a, &[&id]).await;
    let items = messages(&t, &p).await;
    let at = items[0]["delivered_at"].as_str().unwrap();
    assert!(at.ends_with('Z'), "{at}");
    // push on, then a General ack and working from the workspace: listed, never pushed, not in updates
    assert_eq!(
        t.phone(
            &p,
            "POST",
            "/v1/phone/push",
            Some(json!({"apns_token": "ab12", "sandbox": true}))
        )
        .await
        .0,
        204
    );
    for kind in ["ack", "working"] {
        let (s, v) = ws_text(
            &t,
            &a,
            &p.0,
            json!({"reply_to": id}),
            json!({"general": true, "text": "on it", "update": {"kind": kind}}),
        )
        .await;
        assert_eq!(s, 201, "{v}");
    }
    assert!(
        t.push.sent.lock().unwrap().is_empty(),
        "quiet kinds are not pushed"
    );
    let items = messages(&t, &p).await;
    assert_eq!(items.len(), 3);
    let ws_side: Vec<_> = items
        .iter()
        .filter(|i| i["message"]["from"] == a.id.as_str())
        .collect();
    assert_eq!(ws_side.len(), 2);
    for i in ws_side {
        assert_eq!(
            (i["delivered_at"].clone(), i["client_id"].clone()),
            (Value::Null, Value::Null)
        );
        assert!(i["message"].get("ticket").is_none());
    }
    let (s, u) = t.phone(&p, "GET", "/v1/phone/updates", None).await;
    assert_eq!((s, u["items"].as_array().unwrap().len()), (200, 0));
    // a General result is refused by the schema (only ack and working)
    let (s, _) = ws_text(
        &t,
        &a,
        &p.0,
        json!({"reply_to": id}),
        json!({"general": true, "text": "done", "update": {"kind": "result", "title": "Done"}}),
    )
    .await;
    assert_eq!(s, 422);
}

#[tokio::test]
async fn settings_defaults_patch_and_monthly_usage() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    let (s, v) = t.phone(&p, "GET", "/v1/phone/settings", None).await;
    assert_eq!(s, 200);
    assert_eq!(
        v,
        json!({"speak": "auto", "swiss_german": false, "tts_cap_usd": 10, "tts_used_usd_month": 0})
    );
    let (s, v) = t
        .phone(
            &p,
            "PATCH",
            "/v1/phone/settings",
            Some(json!({"speak": "always", "tts_cap_usd": 2.5, "theme": "dark"})),
        )
        .await;
    assert_eq!(s, 200);
    assert_eq!(
        (
            v["speak"].clone(),
            v["tts_cap_usd"].clone(),
            v["swiss_german"].clone()
        ),
        (json!("always"), json!(2.5), json!(false))
    );
    // a later patch keeps the other fields
    let (_, v) = t
        .phone(
            &p,
            "PATCH",
            "/v1/phone/settings",
            Some(json!({"swiss_german": true})),
        )
        .await;
    assert_eq!(
        (v["speak"].clone(), v["swiss_german"].clone()),
        (json!("always"), json!(true))
    );
    // usage written by the speech route counts only in its own month
    let month = orch_relay::store::month_key(orch_relay::util::now());
    t.app
        .db
        .lock()
        .unwrap()
        .execute(
            "UPDATE phone_settings SET tts_used_usd=1.25, tts_month=?2 WHERE phone=?1",
            rusqlite::params![p.0, month],
        )
        .unwrap();
    assert_eq!(
        t.phone(&p, "GET", "/v1/phone/settings", None).await.1["tts_used_usd_month"],
        1.25
    );
    t.app
        .db
        .lock()
        .unwrap()
        .execute(
            "UPDATE phone_settings SET tts_month='2020-01' WHERE phone=?1",
            [&p.0],
        )
        .unwrap();
    assert_eq!(
        t.phone(&p, "GET", "/v1/phone/settings", None).await.1["tts_used_usd_month"],
        0
    );
    // settings are per phone
    let p2 = t.pair_phone(&[&a]).await;
    assert_eq!(
        t.phone(&p2, "GET", "/v1/phone/settings", None).await.1["speak"],
        "auto"
    );
    assert_eq!(
        t.phone(
            &p2,
            "PATCH",
            "/v1/phone/settings",
            Some(json!({"speak": "sometimes"}))
        )
        .await
        .0,
        422
    );
    let r = t
        .http
        .get(format!("{}/v1/phone/settings", t.base))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
}

#[tokio::test]
async fn invitation_redeem_adds_workspaces_once() {
    let t = start().await;
    let (a, b, c) = (
        t.add_ws("A").await,
        t.add_ws("B").await,
        t.add_ws("C").await,
    );
    let p = t.pair_phone(&[&a]).await;
    let (s, v) = t
        .admin_json(
            "POST",
            "/admin/api/phones",
            Some(json!({"name": "invite", "workspaces": [a.id, b.id, c.id]})),
        )
        .await;
    assert_eq!(s, 201);
    let inv_id = v["phone_id"].as_str().unwrap().to_string();
    let code = v["link"]
        .as_str()
        .unwrap()
        .split("code=")
        .nth(1)
        .unwrap()
        .to_string();
    let redeem = |code: String| {
        let p = p.clone();
        let t = &t;
        async move {
            t.phone(
                &p,
                "POST",
                "/v1/phone/invitations/redeem",
                Some(json!({"code": code})),
            )
            .await
        }
    };
    let (s, v) = redeem(code.clone()).await;
    assert_eq!(s, 200, "{v}");
    let names: Vec<&str> = v["workspaces"]
        .as_array()
        .unwrap()
        .iter()
        .map(|w| w["name"].as_str().unwrap())
        .collect();
    assert_eq!(names, ["A", "B", "C"]);
    let (_, l) = t.phone(&p, "GET", "/v1/phone/workspaces", None).await;
    assert_eq!(
        l["items"].as_array().unwrap().len(),
        3,
        "A stayed, B and C added"
    );
    // the invitation's phone entry is gone, the code works once
    let (_, phones) = t.admin_json("GET", "/admin/api/phones", None).await;
    assert!(phones["items"]
        .as_array()
        .unwrap()
        .iter()
        .all(|x| x["id"] != inv_id.as_str()));
    assert_eq!(redeem(code).await.0, 410);
    // added workspaces get a refresh-hint
    assert!(t
        .inbox(&b)
        .await
        .iter()
        .any(|m| m["type"] == "refresh-hint"));
    // unknown / badly shaped codes, expired code
    assert_eq!(redeem("pc_AAAAAAAAAAAAAAAAAAAAAA".into()).await.0, 404);
    assert_eq!(redeem("nope".into()).await.0, 422);
    let (_, v) = t
        .admin_json(
            "POST",
            "/admin/api/phones",
            Some(json!({"name": "old", "workspaces": [a.id]})),
        )
        .await;
    let old = v["link"]
        .as_str()
        .unwrap()
        .split("code=")
        .nth(1)
        .unwrap()
        .to_string();
    t.app
        .db
        .lock()
        .unwrap()
        .execute("UPDATE pair_codes SET expires_at=1", [])
        .unwrap();
    assert_eq!(redeem(old).await.0, 410);
    // auth and rate limit (10 a minute per phone)
    let r = t
        .http
        .post(format!("{}/v1/phone/invitations/redeem", t.base))
        .json(&json!({"code": "pc_AAAAAAAAAAAAAAAAAAAAAA"}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
    let mut last = 0;
    for _ in 0..12 {
        last = redeem("pc_AAAAAAAAAAAAAAAAAAAAAA".into()).await.0;
    }
    assert_eq!(last, 429);
    // another phone is not limited
    let p2 = t.pair_phone(&[&a]).await;
    assert_eq!(
        t.phone(
            &p2,
            "POST",
            "/v1/phone/invitations/redeem",
            Some(json!({"code": "pc_AAAAAAAAAAAAAAAAAAAAAA"}))
        )
        .await
        .0,
        404
    );
}

#[tokio::test]
async fn mute_skips_push_and_remove_drops_the_workspace() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    let p = t.pair_phone(&[&a, &b]).await;
    assert_eq!(
        t.phone(
            &p,
            "POST",
            "/v1/phone/push",
            Some(json!({"apns_token": "ab12", "sandbox": true}))
        )
        .await
        .0,
        204
    );
    let list = |t: &T| {
        let p = p.clone();
        let t = t as *const T;
        async move {
            unsafe { &*t }
                .phone(&p, "GET", "/v1/phone/workspaces", None)
                .await
                .1["items"]
                .clone()
        }
    };
    let muted = |items: &Value, id: &str| {
        items
            .as_array()
            .unwrap()
            .iter()
            .find(|w| w["id"] == id)
            .unwrap()["muted_until"]
            .clone()
    };
    assert_eq!(muted(&list(&t).await, &a.id), Value::Null);
    let wsp = format!("/v1/phone/workspaces/{}", a.id);
    let (s, v) = t
        .phone(&p, "PATCH", &wsp, Some(json!({"muted_until": "forever"})))
        .await;
    assert_eq!(
        (s, v["muted_until"].clone(), v["id"].clone()),
        (200, json!("forever"), json!(a.id))
    );
    assert_eq!(muted(&list(&t).await, &a.id), "forever");
    // A is muted: its text and question are stored, nothing is pushed; B still pushes
    let (s, _) = ws_text(
        &t,
        &a,
        "phones",
        json!({"ticket": "t_7k3f9q"}),
        json!({"text": "hello"}),
    )
    .await;
    assert_eq!(s, 201);
    let q = json!({"schema": "orch.msg/1", "id": mid(), "from": a.id, "to": "phones", "type": "question", "ticket": "t_7k3f9q",
        "created_at": "2026-11-06T10:00:00Z", "body": {"question_id": "q1", "text": "?", "options": ["A"], "recommended": null}});
    assert_eq!(t.call(&a, "POST", "/v1/messages", Some(q)).await.0, 201);
    assert_eq!(t.push.sent.lock().unwrap().len(), 0);
    assert_eq!(messages(&t, &p).await.len(), 1, "stored and listed");
    let (s, _) = ws_text(
        &t,
        &b,
        "phones",
        json!({"ticket": "t_7k3f9q"}),
        json!({"text": "from b"}),
    )
    .await;
    assert_eq!(s, 201);
    assert_eq!(t.push.sent.lock().unwrap().len(), 1);
    // a time in the future mutes, a past time or null does not
    let future = orch_relay::util::fmt_time(orch_relay::util::now() + 3600);
    let (s, v) = t
        .phone(&p, "PATCH", &wsp, Some(json!({"muted_until": future})))
        .await;
    assert_eq!((s, v["muted_until"].clone()), (200, json!(future)));
    let (_, v) = t
        .phone(
            &p,
            "PATCH",
            &wsp,
            Some(json!({"muted_until": "2020-01-01T00:00:00Z"})),
        )
        .await;
    assert_eq!(v["muted_until"], Value::Null);
    t.phone(&p, "PATCH", &wsp, Some(json!({"muted_until": "forever"})))
        .await;
    let (_, v) = t
        .phone(&p, "PATCH", &wsp, Some(json!({"muted_until": null})))
        .await;
    assert_eq!(v["muted_until"], Value::Null);
    tokio::time::sleep(std::time::Duration::from_millis(1100)).await;
    t.push.sent.lock().unwrap().clear();
    ws_text(
        &t,
        &a,
        "phones",
        json!({"ticket": "t_7k3f9q"}),
        json!({"text": "again"}),
    )
    .await;
    assert_eq!(t.push.sent.lock().unwrap().len(), 1, "unmuted pushes again");
    // 404 for a workspace that is not on the list
    assert_eq!(
        t.phone(
            &p,
            "PATCH",
            &format!("/v1/phone/workspaces/{}", "ws_zzzzzzzzzz"),
            Some(json!({"muted_until": null}))
        )
        .await
        .0,
        404
    );
    // remove: gone from the list, the workspace gets a refresh-hint, the phone can no longer send to it
    t.inbox(&a).await;
    assert_eq!(t.phone(&p, "DELETE", &wsp, None).await.0, 204);
    let items = list(&t).await;
    assert_eq!(items.as_array().unwrap().len(), 1);
    assert_eq!(t.phone(&p, "DELETE", &wsp, None).await.0, 404);
    assert_eq!(
        t.phone(&p, "PATCH", &wsp, Some(json!({"muted_until": null})))
            .await
            .0,
        404
    );
    assert_eq!(
        send(&t, &p, json!({"to": a.id, "client_id": C1, "text": "x"}))
            .await
            .0,
        403
    );
    assert!(t
        .inbox(&a)
        .await
        .iter()
        .any(|m| m["type"] == "refresh-hint"));
    let r = t
        .http
        .delete(format!("{}{}", t.base, wsp))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
}

#[tokio::test]
async fn vector_general_updates_are_accepted_or_refused_by_the_relay() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    for case in vectors()["general_updates"].as_array().unwrap() {
        let mut m = case["message"].clone();
        m["from"] = a.id.clone().into();
        m["to"] = p.0.clone().into();
        m["id"] = mid().into();
        let (s, v) = t.call(&a, "POST", "/v1/messages", Some(m)).await;
        let n = case["name"].as_str().unwrap();
        if case["ok"] == true {
            assert_eq!(s, 201, "{n}: {v}");
        } else {
            assert_eq!((s, v["error"].as_str()), (422, Some("invalid")), "{n}: {v}");
        }
    }
    // only the ticketed ack appears in the per-ticket updates view
    let (_, u) = t.phone(&p, "GET", "/v1/phone/updates", None).await;
    assert_eq!(u["items"].as_array().unwrap().len(), 1);
    assert_eq!(u["items"][0]["ticket"], "t_q3sum1");
}
