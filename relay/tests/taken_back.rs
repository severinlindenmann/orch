//! Question taken back (contracts/relay-api.md "Question taken back"): replays every entry of
//! contracts/vectors/taken-back-v1.json against the relay itself.
mod common;
use common::*;
use orch_relay::store;
use serde_json::{json, Value};

const OK_QUESTION: &str = "m_tq00000000000001";

fn vectors() -> Value {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../contracts/vectors/taken-back-v1.json");
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

struct Fixture {
    t: T,
    sender: Ws,
    other: Ws,
    phone: (String, String),
}

impl Fixture {
    fn substitute(&self, value: &Value) -> Value {
        match value {
            Value::String(s) => json!(match s.as_str() {
                "ws_pilatus001" => &self.sender.id,
                "ws_other00001" => &self.other.id,
                "ph_iphone0001" => &self.phone.0,
                _ => s,
            }),
            Value::Array(a) => a.iter().map(|v| self.substitute(v)).collect(),
            Value::Object(o) => Value::Object(
                o.iter()
                    .map(|(k, v)| (k.clone(), self.substitute(v)))
                    .collect(),
            ),
            _ => value.clone(),
        }
    }

    async fn post(&self, msg: &Value) -> (u16, Value) {
        let m = self.substitute(msg);
        let ws = if m["from"] == self.other.id {
            &self.other
        } else {
            &self.sender
        };
        self.t.call(ws, "POST", "/v1/messages", Some(m)).await
    }

    async fn new(state: &Value) -> Self {
        let data = vectors();
        let t = start().await;
        let sender = t.add_ws("Sender").await;
        let other = t.add_ws("Other").await;
        let phone = t.pair_phone(&[&sender]).await;
        let f = Self {
            t,
            sender,
            other,
            phone,
        };
        let extra = state["questions_extra"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        for q in data["questions"]
            .as_array()
            .unwrap()
            .iter()
            .chain(extra.iter())
        {
            let ws = if q["from"] == "ws_other00001" {
                &f.other
            } else {
                &f.sender
            };
            let mut body = json!({"question_id": q["question_id"], "title": "Ticket", "text": "Shall I go on?", "options": ["yes","no"], "recommended": null});
            match q["kind"].as_str().unwrap() {
                "review" => {
                    body["review"] = json!(true);
                    body["options"] = json!(["accept", "changes"]);
                    body["text"] = json!("Is this done?");
                }
                "proposal" => {
                    body["proposal"] = json!("make_ticket");
                    body["options"] = json!(["make", "not_now"]);
                }
                _ => {}
            }
            let mut msg = json!({"schema":"orch.msg/1", "id":q["id"], "from":ws.id, "to":f.substitute(&q["to"]).as_str().unwrap_or("phones"), "type":"question",
                "created_at":"2026-11-15T09:00:00Z", "body":body});
            if let Some(tk) = q["ticket"].as_str() {
                msg["ticket"] = json!(tk);
            }
            if let Some(k) = q["key"].as_str() {
                msg["key"] = json!(k);
            }
            let (s, v) = f.t.call(ws, "POST", "/v1/messages", Some(msg)).await;
            assert_eq!(s, 201, "fixture question {}: {v}", q["id"]);
        }
        let plain = json!({"schema":"orch.msg/1", "id":"m_tt00000000000001", "from":f.sender.id, "to":"phones", "type":"text", "created_at":"2026-11-15T09:00:00Z", "body":{"text":"Plain text"}});
        let (s, v) =
            f.t.call(&f.sender, "POST", "/v1/messages", Some(plain))
                .await;
        assert_eq!(s, 201, "{v}");
        for qid in state["answered"].as_array().into_iter().flatten() {
            let (s, v) =
                f.t.phone(
                    &f.phone,
                    "POST",
                    "/v1/phone/answer",
                    Some(json!({"question_message_id": qid, "answer": "yes"})),
                )
                .await;
            assert_eq!(s, 201, "{v}");
        }
        // Register for push after the fixture texts so they cannot use the text push budget.
        let (s, v) =
            f.t.phone(
                &f.phone,
                "POST",
                "/v1/phone/push",
                Some(json!({"apns_token":"abcdef0123000000000000000000000000000000000000000000000000000000", "sandbox":true})),
            )
            .await;
        assert_eq!(s, 204, "{v}");
        for m in state["taken_back"].as_array().into_iter().flatten() {
            let (s, v) = f.post(m).await;
            assert_eq!(s, 201, "stored take-back: {v}");
        }
        f.t.push.sent.lock().unwrap().clear();
        f
    }
}

#[tokio::test]
async fn replay_all_contract_vectors() {
    let data = vectors();
    for entry in data["relay"].as_array().unwrap() {
        let name = entry["name"].as_str().unwrap();
        let f = Fixture::new(&entry["state"]).await;
        let (status, body) = if entry["call"] == "POST /v1/phone/answer" {
            f.t.phone(
                &f.phone,
                "POST",
                "/v1/phone/answer",
                Some(f.substitute(&entry["request"])),
            )
            .await
        } else if entry.get("request").is_some() {
            let r =
                f.t.phone(
                    &f.phone,
                    "POST",
                    "/v1/phone/send",
                    Some(f.substitute(&entry["request"])),
                )
                .await;
            assert_eq!(r.0, 201, "{name}: {}", r.1);
            let c = f.t.app.db.lock().unwrap();
            let stored = store::get_msg(&c, r.1["id"].as_str().unwrap())
                .unwrap()
                .unwrap();
            let (b, _) = store::open_payload(&f.t.app.key, &stored);
            assert!(b
                .get(entry["stored_body_lacks"].as_str().unwrap())
                .is_none());
            let marked: i64 = c
                .query_row("SELECT COUNT(*) FROM question_taken_back", [], |r| r.get(0))
                .unwrap();
            assert_eq!(
                marked, 0,
                "{name}: a phone text must never mark a take-back"
            );
            r
        } else {
            f.post(&entry["message"]).await
        };
        let expect = entry["expect"].as_u64().unwrap() as u16;
        assert_eq!(status, expect, "{name}: {body}");
        match expect {
            200 => assert_eq!(body["duplicate"], true, "{name}"),
            409 => {
                let code = entry["error"].as_str().unwrap_or("conflict");
                assert_eq!(body["error"], code, "{name}: {body}");
                if let Some(m) = entry["message"].as_str() {
                    assert_eq!(body["message"], m, "{name}: {body}");
                }
            }
            _ => {}
        }
        if entry.get("message").is_some() && matches!(expect, 200 | 201) {
            assert!(
                f.t.push.sent.lock().unwrap().is_empty(),
                "{name}: pushed a take-back"
            );
        }
        if expect >= 400 && entry["call"] != "POST /v1/phone/answer" {
            // a refused take-back leaves no mark
            let c = f.t.app.db.lock().unwrap();
            let marked: i64 = c
                .query_row("SELECT COUNT(*) FROM question_taken_back", [], |r| r.get(0))
                .unwrap();
            let had = entry["state"]["taken_back"]
                .as_array()
                .map_or(0, |a| a.len()) as i64;
            assert_eq!(marked, had, "{name}: refused but marked");
        }
    }
}

#[tokio::test]
async fn taken_back_answer_stores_nothing() {
    let f = Fixture::new(&json!({})).await;
    let ok = vectors()["valid"][0]["message"].clone();
    assert_eq!(f.post(&ok).await.0, 201);
    let before: i64 =
        f.t.app
            .db
            .lock()
            .unwrap()
            .query_row(
                "SELECT COUNT(*) FROM messages WHERE type='answer'",
                [],
                |r| r.get(0),
            )
            .unwrap();
    let (s, v) =
        f.t.phone(
            &f.phone,
            "POST",
            "/v1/phone/answer",
            Some(json!({"question_message_id": OK_QUESTION, "answer": "yes"})),
        )
        .await;
    assert_eq!((s, v["error"].as_str()), (409, Some("taken_back")), "{v}");
    let after: i64 =
        f.t.app
            .db
            .lock()
            .unwrap()
            .query_row(
                "SELECT COUNT(*) FROM messages WHERE type='answer'",
                [],
                |r| r.get(0),
            )
            .unwrap();
    assert_eq!(before, after);
}

#[tokio::test]
async fn open_questions_leave_out_a_taken_back_question() {
    for case in vectors()["open_questions"].as_array().unwrap() {
        let f = Fixture::new(&case["state"]).await;
        let (s, v) =
            f.t.phone(&f.phone, "GET", "/v1/phone/questions", None)
                .await;
        assert_eq!(s, 200, "{v}");
        let mut got: Vec<String> = v["items"]
            .as_array()
            .unwrap()
            .iter()
            .map(|i| i["message"]["id"].as_str().unwrap().to_string())
            .collect();
        let mut want: Vec<String> = case["listed"]
            .as_array()
            .unwrap()
            .iter()
            .map(|i| i.as_str().unwrap().to_string())
            .collect();
        got.sort();
        want.sort();
        assert_eq!(got, want, "{}", case["name"]);
        let (s, v) =
            f.t.phone(&f.phone, "GET", "/v1/phone/workspaces", None)
                .await;
        assert_eq!(s, 200, "{v}");
        let card = v["items"]
            .as_array()
            .unwrap()
            .iter()
            .find(|c| c["id"] == f.sender.id)
            .unwrap();
        assert_eq!(card["open_questions"], want.len(), "{}", case["name"]);
    }
}

#[tokio::test]
async fn take_back_is_stored_listed_and_quiet() {
    let f = Fixture::new(&json!({})).await;
    let ok = vectors()["valid"][0]["message"].clone();
    assert_eq!(f.post(&ok).await.0, 201);
    let (s, v) = f.t.phone(&f.phone, "GET", "/v1/phone/messages", None).await;
    assert_eq!(s, 200, "{v}");
    let hit = v["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|i| &i["message"])
        .find(|m| m["id"] == "m_tb00000000000001")
        .expect("the take-back text is listed like any text");
    assert_eq!(hit["reply_to"], OK_QUESTION);
    assert_eq!(hit["body"]["taken_back"]["reason"], "plans changed");
    assert!(f.t.push.sent.lock().unwrap().is_empty());
    // a text of the same sender after it still pushes (the budget was not used)
    let mut plain = ok;
    plain["id"] = json!(mid());
    plain["reply_to"] = json!(null);
    plain["body"] = json!({"text": "An ordinary text still pushes"});
    plain.as_object_mut().unwrap().remove("reply_to");
    assert_eq!(f.post(&plain).await.0, 201);
    assert_eq!(f.t.push.sent.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn unknown_and_other_workspace_questions_have_identical_404_bodies() {
    let f = Fixture::new(&json!({})).await;
    let mut msg = vectors()["valid"][0]["message"].clone();
    msg["reply_to"] = json!("m_nosuchmsg0000001");
    let unknown = f.post(&msg).await;
    msg["reply_to"] = json!("m_tq0000other00001");
    let other = f.post(&msg).await;
    assert_eq!(unknown.0, 404);
    assert_eq!(unknown, other);
}

#[tokio::test]
async fn another_workspace_cannot_take_back_our_question() {
    let f = Fixture::new(&json!({})).await;
    let mut msg = vectors()["valid"][0]["message"].clone();
    msg["from"] = json!("ws_other00001");
    let (s, v) = f.post(&msg).await;
    assert_eq!(s, 404, "{v}");
    let marked: i64 =
        f.t.app
            .db
            .lock()
            .unwrap()
            .query_row("SELECT COUNT(*) FROM question_taken_back", [], |r| r.get(0))
            .unwrap();
    assert_eq!(marked, 0);
}

#[tokio::test]
async fn a_subscriber_cannot_answer_a_taken_back_question() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let (s, v) = t
        .admin_json(
            "POST",
            "/admin/api/subscribers",
            Some(json!({"name": "Night monitor", "workspaces": [a.id], "can_answer": true})),
        )
        .await;
    assert_eq!(s, 201, "{v}");
    let token = v["token"].as_str().unwrap().to_string();
    tokio::time::sleep(std::time::Duration::from_millis(1100)).await;
    let q = json!({"schema":"orch.msg/1", "id":"m_tq00000000000001", "from":a.id, "to":"phones", "type":"question", "ticket":"t_7k3f9q",
        "created_at":"2026-11-15T09:00:00Z", "body":{"question_id":"q1", "title":"Ticket", "text":"Go on?", "options":["yes","no"], "recommended":null}});
    assert_eq!(t.call(&a, "POST", "/v1/messages", Some(q)).await.0, 201);
    let mut tb = vectors()["valid"][0]["message"].clone();
    tb["from"] = json!(a.id);
    tb["key"] = json!(null);
    tb.as_object_mut().unwrap().remove("key");
    assert_eq!(t.call(&a, "POST", "/v1/messages", Some(tb)).await.0, 201);
    let r = t
        .http
        .post(format!("{}/v1/sub/{token}/answer", t.base))
        .json(&json!({"question_id": OK_QUESTION, "answer": "yes"}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status().as_u16(), 409);
    let v: Value = r.json().await.unwrap();
    assert_eq!(v["error"], "taken_back", "{v}");
    assert_eq!(v["message"], "This question was taken back: plans changed");
    // The events view no longer offers the taken-back question as answerable.
    let r = t
        .http
        .get(format!("{}/v1/sub/{token}/events", t.base))
        .send()
        .await
        .unwrap();
    let v: Value = r.json().await.unwrap();
    let q = v["items"]
        .as_array()
        .unwrap()
        .iter()
        .find(|e| e["type"] == "question")
        .expect("the question stays in the history");
    assert_eq!(q["answerable"], false, "{v}");
}

/// Phone lists: the take-back text is no work update, so `/v1/phone/updates` never carries it, and a taken-back
/// question is on no open list (the relay has no unread count for phones; the phone treats `taken_back` as never unread).
#[tokio::test]
async fn taken_back_is_not_an_update_and_not_open_anywhere() {
    let f = Fixture::new(&json!({})).await;
    let ok = vectors()["valid"][0]["message"].clone();
    assert_eq!(f.post(&ok).await.0, 201);
    let (s, v) = f.t.phone(&f.phone, "GET", "/v1/phone/updates", None).await;
    assert_eq!(s, 200, "{v}");
    assert!(
        !v.to_string().contains("taken_back") && !v.to_string().contains("Taken back"),
        "{v}"
    );
    let (s, v) =
        f.t.phone(&f.phone, "GET", "/v1/phone/questions", None)
            .await;
    assert_eq!(s, 200, "{v}");
    assert!(!v.to_string().contains(OK_QUESTION), "{v}");
}

/// A database error is never read as "not taken back": the answer ends in 500, nothing is stored.
#[tokio::test]
async fn a_database_error_fails_closed() {
    let f = Fixture::new(&json!({})).await;
    {
        let c = f.t.app.db.lock().unwrap();
        c.execute_batch("ALTER TABLE question_taken_back RENAME TO question_taken_back_x")
            .unwrap();
        assert!(store::taken_back_reason(&c, &f.t.app.key, OK_QUESTION).is_err());
    }
    let (s, _) =
        f.t.phone(
            &f.phone,
            "POST",
            "/v1/phone/answer",
            Some(json!({"question_message_id": OK_QUESTION, "answer": "yes"})),
        )
        .await;
    assert_eq!(s, 500);
}

/// The marker and the message row are one step: a failing marker insert leaves no message behind.
#[tokio::test]
async fn a_failed_marker_leaves_no_message() {
    let f = Fixture::new(&json!({})).await;
    let ok = f.substitute(&vectors()["valid"][0]["message"]);
    let c = f.t.app.db.lock().unwrap();
    c.execute_batch("DROP TABLE question_taken_back").unwrap();
    assert!(store::insert_message(&c, &f.t.app.key, &ok, "d").is_err());
    let n: i64 = c
        .query_row(
            "SELECT COUNT(*) FROM messages WHERE id='m_tb00000000000001'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(n, 0);
}
