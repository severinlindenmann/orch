mod common;
use common::*;
use orch_relay::store;
use serde_json::{json, Value};

const PROPOSAL: &str = "m_pr00000000000001";

fn vectors() -> Value {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../contracts/vectors/proposal-result-v1.json");
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

struct Fixture {
    t: T,
    sender: Ws,
    other: Ws,
    phones: Vec<(String, String)>,
}

impl Fixture {
    fn substitute(&self, value: &Value) -> Value {
        match value {
            Value::String(s) => {
                let replacement = match s.as_str() {
                    "ws_pilatus001" => &self.sender.id,
                    "ws_other00001" => &self.other.id,
                    "ph_iphone0001" => &self.phones[0].0,
                    "ph_iphone0002" => &self.phones[1].0,
                    "ph_stranger01" => &self.phones[2].0,
                    _ => s,
                };
                json!(replacement)
            }
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
        self.t
            .call(
                &self.sender,
                "POST",
                "/v1/messages",
                Some(self.substitute(msg)),
            )
            .await
    }

    async fn new(state: &Value) -> Self {
        let t = start().await;
        let sender = t.add_ws("Sender").await;
        let other = t.add_ws("Other").await;
        let phones = vec![
            t.pair_phone(&[&sender]).await,
            t.pair_phone(&[&sender]).await,
            t.pair_phone(&[&other]).await,
        ];
        let f = Self {
            t,
            sender,
            other,
            phones,
        };
        for (ws, id, proposal) in [
            (&f.sender, PROPOSAL, true),
            (&f.sender, "m_qq00000000000001", false),
            (&f.other, "m_pr0000other00001", true),
        ] {
            let mut msg = json!({"schema":"orch.msg/1", "id":id, "from":ws.id, "to":"phones", "type":"question", "created_at":"2026-11-09T10:00:00Z",
                "body":{"question_id":format!("proposal-{id}"), "proposal":"make_ticket", "title":"Make a ticket", "text":"Shall I make this a ticket?", "options":["make","not_now"], "recommended":null}});
            if !proposal {
                msg["body"].as_object_mut().unwrap().remove("proposal");
                msg["body"]["question_id"] = json!("q1");
                msg["ticket"] = json!("t_7k3f9q");
            }
            let (s, v) = f.t.call(ws, "POST", "/v1/messages", Some(msg)).await;
            assert_eq!(s, 201, "fixture: {v}");
        }
        let (s, v) = f.post(&json!({"schema":"orch.msg/1", "id":"m_tt00000000000001", "from":"ws_pilatus001", "to":"phones", "type":"text", "created_at":"2026-11-09T10:00:00Z", "body":{"text":"Plain text"}})).await;
        assert_eq!(s, 201, "{v}");
        for (i, phone) in state["answered_by"]
            .as_array()
            .into_iter()
            .flatten()
            .enumerate()
        {
            let index = match phone.as_str().unwrap() {
                "ph_iphone0001" => 0,
                "ph_iphone0002" => 1,
                "ph_stranger01" => 2,
                name => panic!("Unknown fixture phone {name}"),
            };
            let (s, v) =
                f.t.phone(
                    &f.phones[index],
                    "POST",
                    "/v1/phone/answer",
                    Some(json!({"question_message_id":PROPOSAL, "answer":"make"})),
                )
                .await;
            if index == 2 && i == 0 {
                assert_eq!(s, 404, "{v}");
                // This vector requires an unpaired phone's stored answer, impossible via the API.
                let msg = json!({"schema":"orch.msg/1", "id":mid(), "from":f.phones[index].0, "to":f.sender.id, "type":"answer", "reply_to":PROPOSAL, "created_at":"2026-11-09T10:01:00Z", "body":{"answer":"make"}});
                store::insert_message(&f.t.app.db.lock().unwrap(), &f.t.app.key, &msg, "fixture")
                    .unwrap();
            } else {
                assert_eq!(s, if i == 0 { 201 } else { 409 }, "{v}");
            }
        }
        // Register after ordinary fixture texts so they cannot consume the text push budget.
        for p in &f.phones {
            let (s, v) =
                f.t.phone(
                    p,
                    "POST",
                    "/v1/phone/push",
                    Some(json!({"apns_token":"abcdef0123", "sandbox":true})),
                )
                .await;
            assert_eq!(s, 204, "{v}");
        }
        for result in state["results"].as_array().into_iter().flatten() {
            let (s, v) = f.post(&result["message"]).await;
            assert_eq!(s, 201, "stored result: {v}");
        }
        f
    }
}

#[tokio::test]
async fn replay_all_contract_vectors() {
    let data = vectors();
    for group in ["valid", "invalid", "relay"] {
        for entry in data[group].as_array().unwrap() {
            let state = if group == "relay" {
                entry["state"].clone()
            } else {
                json!({"answered_by":["ph_iphone0001"]})
            };
            let f = Fixture::new(&state).await;
            let (status, body) = if entry.get("request").is_some() {
                let response =
                    f.t.phone(
                        &f.phones[0],
                        "POST",
                        "/v1/phone/send",
                        Some(f.substitute(&entry["request"])),
                    )
                    .await;
                assert_eq!(response.0, 201, "{}: {}", entry["name"], response.1);
                let c = f.t.app.db.lock().unwrap();
                let stored = store::get_msg(&c, response.1["id"].as_str().unwrap())
                    .unwrap()
                    .unwrap();
                let (body, _) = store::open_payload(&f.t.app.key, &stored);
                assert!(body
                    .get(entry["stored_body_lacks"].as_str().unwrap())
                    .is_none());
                response
            } else {
                f.post(&entry["message"]).await
            };
            let expected = match group {
                "valid" => 201,
                "invalid" => 422,
                _ => entry["expect"].as_u64().unwrap() as u16,
            };
            assert_eq!(status, expected, "{group}/{}: {body}", entry["name"]);
            if expected == 200 {
                assert_eq!(body["duplicate"], true);
            }
            if expected == 409 {
                assert_eq!(body["error"], "conflict");
            }
            assert!(
                f.t.push.sent.lock().unwrap().is_empty(),
                "{} pushed a result",
                entry["name"]
            );
        }
    }
}

#[tokio::test]
async fn result_is_quiet_duplicate_and_does_not_use_push_budget() {
    let f = Fixture::new(&json!({})).await;
    let msg = vectors()["valid"][0]["message"].clone();
    assert_eq!(f.post(&msg).await.0, 201);
    let (s, v) = f.post(&msg).await;
    assert_eq!(s, 200, "{v}");
    assert_eq!(v["duplicate"], true);
    assert!(f.t.push.sent.lock().unwrap().is_empty());
    let mut plain = msg;
    plain["id"] = json!(mid());
    plain["body"] = json!({"text":"An ordinary text still pushes"});
    assert_eq!(f.post(&plain).await.0, 201);
    assert_eq!(f.t.push.sent.lock().unwrap().len(), 2);
}

#[tokio::test]
async fn unknown_and_other_workspace_proposals_have_identical_404_bodies() {
    let f = Fixture::new(&json!({})).await;
    let mut msg = vectors()["valid"][0]["message"].clone();
    msg["reply_to"] = json!("m_nosuchmsg0000001");
    let unknown = f.post(&msg).await;
    msg["reply_to"] = json!("m_pr0000other00001");
    let other = f.post(&msg).await;
    assert_eq!(unknown.0, 404);
    assert_eq!(unknown, other);
    assert_eq!(unknown.1["error"], "not_found");
}
