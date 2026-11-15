//! Review cards on the phone (relay-api.md "Review cards on the phone"): the relay replays
//! contracts/vectors/review-card-v1.json (question intake, verdict answers, review results) and the
//! verdict_cases of review-question-v1.json, and checks who may read card files and voice files.
mod common;
use common::*;
use orch_relay::store;
use serde_json::{json, Value};
use std::collections::HashMap;

fn vec_json(name: &str) -> Value {
    let p = format!("{}/../contracts/vectors/{name}", env!("CARGO_MANIFEST_DIR"));
    serde_json::from_str(&std::fs::read_to_string(p).unwrap()).unwrap()
}

async fn up_ws(t: &T, w: &Ws, data: Vec<u8>) -> Value {
    let r = t
        .http
        .post(format!("{}/v1/blobs", t.base))
        .header("X-Orch-Workspace", &w.id)
        .header("Authorization", format!("Bearer {}", w.token))
        .body(data)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 201);
    r.json().await.unwrap()
}

async fn up_phone(t: &T, p: &(String, String), data: Vec<u8>) -> Value {
    let r = t
        .http
        .post(format!("{}/v1/phone/blobs", t.base))
        .header("X-Orch-Phone", &p.0)
        .header("Authorization", format!("Bearer {}", p.1))
        .header("Content-Type", "audio/m4a")
        .body(data)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 201);
    r.json().await.unwrap()
}

async fn get_blob(t: &T, hdr: (&str, &str, &str), path: &str) -> u16 {
    t.http
        .get(format!("{}{}", t.base, path))
        .header(hdr.0, hdr.1)
        .header("Authorization", format!("Bearer {}", hdr.2))
        .send()
        .await
        .unwrap()
        .status()
        .as_u16()
}

struct F {
    t: T,
    pil: Ws,
    rep: Ws,
    iphone: (String, String),
    ipad: (String, String),
    stranger: (String, String),
    /// vector string (id, sha, ws/phone id) -> real value
    map: HashMap<String, String>,
}

impl F {
    fn sub(&self, v: &Value) -> Value {
        match v {
            Value::String(s) => json!(self.map.get(s).unwrap_or(s)),
            Value::Array(a) => a.iter().map(|x| self.sub(x)).collect(),
            Value::Object(o) => {
                Value::Object(o.iter().map(|(k, x)| (k.clone(), self.sub(x))).collect())
            }
            _ => v.clone(),
        }
    }
    fn phone(&self, vector_id: &str) -> &(String, String) {
        match vector_id {
            "ph_iphone0001" => &self.iphone,
            "ph_ipad000001" => &self.ipad,
            "ph_stranger01" => &self.stranger,
            x => panic!("unknown phone {x}"),
        }
    }
    async fn post_ws(&self, as_ws: &str, m: &Value) -> (u16, Value) {
        let w = if as_ws == "ws_pilatus001" {
            &self.pil
        } else {
            &self.rep
        };
        self.t
            .call(w, "POST", "/v1/messages", Some(self.sub(m)))
            .await
    }
    async fn new(vec: &Value) -> F {
        let t = start().await;
        let pil = t.add_ws("Pilatus").await;
        let rep = t.add_ws("Reports").await;
        let iphone = t.pair_phone(&[&pil]).await;
        let ipad = t.pair_phone(&[&pil]).await;
        let stranger = t.pair_phone(&[&rep]).await;
        let mut map: HashMap<String, String> = HashMap::new();
        map.insert("ws_pilatus001".into(), pil.id.clone());
        map.insert("ws_reports001".into(), rep.id.clone());
        map.insert("ph_iphone0001".into(), iphone.0.clone());
        map.insert("ph_ipad000001".into(), ipad.0.clone());
        map.insert("ph_stranger01".into(), stranger.0.clone());
        for (i, (vid, b)) in vec["relay"]["blobs"]
            .as_object()
            .unwrap()
            .iter()
            .enumerate()
        {
            let size = b["size"].as_u64().unwrap() as usize;
            let data = vec![i as u8 + 1; size];
            let up = match b["uploader"].as_str().unwrap() {
                "ws_pilatus001" => up_ws(&t, &pil, data).await,
                "ws_reports001" => up_ws(&t, &rep, data).await,
                "ph_iphone0001" => up_phone(&t, &iphone, data).await,
                "ph_ipad000001" => up_phone(&t, &ipad, data).await,
                x => panic!("uploader {x}"),
            };
            map.insert(vid.clone(), up["blob_id"].as_str().unwrap().into());
            map.insert(
                b["sha256"].as_str().unwrap().into(),
                up["sha256"].as_str().unwrap().into(),
            );
        }
        F {
            t,
            pil,
            rep,
            iphone,
            ipad,
            stranger,
            map,
        }
    }
}

fn err_of(v: &Value) -> Option<&str> {
    v["error"].as_str()
}

#[tokio::test]
async fn replay_review_card_vector_relay_cases() {
    let vec = vec_json("review-card-v1.json");
    let mut f = F::new(&vec).await;
    // q4, q5 and the plain question are stored first (the vector's `stored` note).
    for m in [
        &vec["question_shapes"][1]["message"],
        &vec["question_shapes"][2]["message"],
        &vec["relay"]["plain_question"],
    ] {
        let (s, v) = f.post_ws("ws_pilatus001", m).await;
        assert_eq!(s, 201, "fixture {v}");
    }
    for c in vec["relay"]["cases"].as_array().unwrap() {
        let name = c["name"].as_str().unwrap();
        let want = c["status"].as_u64().unwrap() as u16;
        if let Some(path) = c["call"].as_str().unwrap().strip_prefix("GET ") {
            let who = c["as"].as_str().unwrap();
            let (dir, vid) = path.rsplit_once('/').unwrap();
            let path = format!("{dir}/{}", f.map[vid]);
            let s = if who.starts_with("ws_") {
                let w = if who == "ws_pilatus001" {
                    &f.pil
                } else {
                    &f.rep
                };
                get_blob(&f.t, ("X-Orch-Workspace", &w.id, &w.token), &path).await
            } else if who == "ph_newphone01" {
                // paired after the question was stored: the same rule as ticket_view
                let p = f.t.pair_phone(&[&f.pil]).await;
                f.t.app
                    .db
                    .lock()
                    .unwrap()
                    .execute(
                        "UPDATE phones SET paired_at=(SELECT MAX(stored_at) FROM messages)+1000 WHERE id=?1",
                        [&p.0],
                    )
                    .unwrap();
                get_blob(&f.t, ("X-Orch-Phone", &p.0, &p.1), &path).await
            } else {
                let p = f.phone(who);
                get_blob(&f.t, ("X-Orch-Phone", &p.0, &p.1), &path).await
            };
            assert_eq!(s, want, "{name}");
            continue;
        }
        let (s, v) = if c["call"] == "POST /v1/messages" {
            if name == "question-files-over-20mb" {
                // the vector's note: three real 8 MB blobs of these ids
                for fl in c["body"]["body"]["card_files"].as_array().unwrap() {
                    let up = up_ws(&f.t, &f.pil, vec![9u8; 8_000_000]).await;
                    f.map.insert(
                        fl["blob_id"].as_str().unwrap().into(),
                        up["blob_id"].as_str().unwrap().into(),
                    );
                    f.map.insert(
                        fl["sha256"].as_str().unwrap().into(),
                        up["sha256"].as_str().unwrap().into(),
                    );
                }
            }
            f.post_ws(c["as"].as_str().unwrap(), &c["body"]).await
        } else {
            let p = f.phone(c["as"].as_str().unwrap()).clone();
            f.t.phone(&p, "POST", "/v1/phone/answer", Some(f.sub(&c["body"])))
                .await
        };
        assert_eq!(s, want, "{name}: {v}");
        if let Some(e) = c["error"].as_str() {
            assert_eq!(err_of(&v), Some(e), "{name}: {v}");
        }
        if c["duplicate"] == true {
            assert_eq!(v["duplicate"], true, "{name}");
        }
        if name == "answer-verdict-ok" {
            // verdict copied unchanged into the stored answer
            let c2 = f.t.app.db.lock().unwrap();
            let q = f.sub(&c["body"]["question_message_id"]);
            let id: String = c2
                .query_row(
                    "SELECT id FROM messages WHERE reply_to=?1 AND type='answer'",
                    [q.as_str().unwrap()],
                    |r| r.get(0),
                )
                .unwrap();
            let m = store::get_msg(&c2, &id).unwrap().unwrap();
            let (b, _) = store::open_payload(&f.t.app.key, &m);
            assert_eq!(b["verdict"], c["body"]["verdict"]);
            assert_eq!(b["answered_by"], "human:Test iPhone");
        }
    }
}

#[tokio::test]
async fn card_files_are_read_by_the_phone_it_went_to_and_voice_files_by_the_named_workspace() {
    let vec = vec_json("review-card-v1.json");
    let f = F::new(&vec).await;
    let q3 = &vec["question_shapes"][0]["message"];
    let (s, v) = f.post_ws("ws_pilatus001", q3).await;
    assert_eq!(s, 201, "{v}");
    let card_blob = f.map["b_inv0000000000001"].clone();
    let path = format!("/v1/phone/blobs/{card_blob}");
    for p in [&f.iphone, &f.ipad] {
        assert_eq!(
            get_blob(&f.t, ("X-Orch-Phone", &p.0, &p.1), &path).await,
            200
        );
    }
    // a phone not on the sender's list never reads it
    assert_eq!(
        get_blob(&f.t, ("X-Orch-Phone", &f.stranger.0, &f.stranger.1), &path).await,
        404
    );
    // a card file of a question that is not named by any message stays closed (uploaded, never sent)
    let loose = up_ws(&f.t, &f.pil, vec![5u8; 10]).await["blob_id"]
        .as_str()
        .unwrap()
        .to_string();
    assert_eq!(
        get_blob(
            &f.t,
            ("X-Orch-Phone", &f.iphone.0, &f.iphone.1),
            &format!("/v1/phone/blobs/{loose}")
        )
        .await,
        404
    );
    // voice file: named in the answer, so only the workspace the answer went to reads it
    let voice = f.map["b_voice0000000001a"].clone();
    let vpath = format!("/v1/blobs/{voice}");
    assert_eq!(
        get_blob(&f.t, ("X-Orch-Workspace", &f.pil.id, &f.pil.token), &vpath).await,
        404
    );
    let ans = json!({"question_message_id": q3["id"], "answer": "x", "client_id": "44444444-4444-4444-8444-444444444444",
        "verdict": {"verdict": "talk", "digest": q3["body"]["digest"], "note": {"words": {"voice": [{"blob_id": voice, "transcript": "hi", "lang": "en", "duration": 1}]}}}});
    let (s, v) =
        f.t.phone(&f.iphone, "POST", "/v1/phone/answer", Some(ans))
            .await;
    assert_eq!(s, 201, "{v}");
    assert_eq!(
        get_blob(&f.t, ("X-Orch-Workspace", &f.pil.id, &f.pil.token), &vpath).await,
        200
    );
    assert_eq!(
        get_blob(&f.t, ("X-Orch-Workspace", &f.rep.id, &f.rep.token), &vpath).await,
        404
    );
    // a voice file the answer did not name stays closed to the workspace
    let other = f.map["b_voice00000000002"].clone();
    assert_eq!(
        get_blob(
            &f.t,
            ("X-Orch-Workspace", &f.pil.id, &f.pil.token),
            &format!("/v1/blobs/{other}")
        )
        .await,
        404
    );
}

#[tokio::test]
async fn review_result_is_never_pushed_and_never_uses_the_text_budget() {
    let vec = vec_json("review-card-v1.json");
    let f = F::new(&vec).await;
    let q3 = &vec["question_shapes"][0]["message"];
    assert_eq!(f.post_ws("ws_pilatus001", q3).await.0, 201);
    let ans = json!({"question_message_id": q3["id"], "answer": "x", "client_id": "44444444-4444-4444-8444-444444444444",
        "verdict": {"verdict": "ok", "digest": q3["body"]["digest"]}});
    assert_eq!(
        f.t.phone(&f.iphone, "POST", "/v1/phone/answer", Some(ans))
            .await
            .0,
        201
    );
    for p in [&f.iphone, &f.ipad] {
        let (s, v) = f.t.phone(p, "POST", "/v1/phone/push", Some(json!({"apns_token":"abcdef0123000000000000000000000000000000000000000000000000000000", "sandbox":true}))).await;
        assert_eq!(s, 204, "{v}");
    }
    let res = vec["relay"]["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == "result-applied")
        .unwrap();
    let (s, v) = f.post_ws("ws_pilatus001", &res["body"]).await;
    assert_eq!(s, 201, "{v}");
    assert!(
        f.t.push.sent.lock().unwrap().is_empty(),
        "review_result was pushed"
    );
    // the text budget is untouched: an ordinary text still pushes
    let plain = json!({"schema":"orch.msg/1","id":mid(),"from":f.pil.id,"to":f.iphone.0,"type":"text","created_at":"2026-11-15T09:03:00Z","body":{"text":"hello"}});
    assert_eq!(
        f.t.call(&f.pil, "POST", "/v1/messages", Some(plain))
            .await
            .0,
        201
    );
    assert_eq!(f.t.push.sent.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn review_result_extra_fields_free_text_and_other_senders_are_refused() {
    let vec = vec_json("review-card-v1.json");
    let f = F::new(&vec).await;
    let q3 = &vec["question_shapes"][0]["message"];
    assert_eq!(f.post_ws("ws_pilatus001", q3).await.0, 201);
    let ans = json!({"question_message_id": q3["id"], "answer": "x", "client_id": "44444444-4444-4444-8444-444444444444",
        "verdict": {"verdict": "ok", "digest": q3["body"]["digest"]}});
    assert_eq!(
        f.t.phone(&f.iphone, "POST", "/v1/phone/answer", Some(ans))
            .await
            .0,
        201
    );
    let good = vec["relay"]["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == "result-applied")
        .unwrap()["body"]
        .clone();
    // an extra body key, an extra message key, a result on a non-text type
    let mut m = good.clone();
    m["body"]["extra"] = json!("x");
    assert_eq!(f.post_ws("ws_pilatus001", &m).await.0, 422);
    let mut m = good.clone();
    m["group"] = json!("g");
    assert_eq!(f.post_ws("ws_pilatus001", &m).await.0, 422);
    let mut m = good.clone();
    m["type"] = json!("question");
    assert_eq!(f.post_ws("ws_pilatus001", &m).await.0, 422);
    // another workspace cannot answer for the question: its id answers 404 like an unknown one
    let mut theirs = good.clone();
    theirs["from"] = json!(f.rep.id);
    let (s, v) = f.post_ws("ws_reports001", &theirs).await;
    assert_eq!((s, err_of(&v)), (404, Some("not_found")), "{v}");
    // the good one still goes through
    assert_eq!(f.post_ws("ws_pilatus001", &good).await.0, 201);
}

#[tokio::test]
async fn review_question_verdict_cases_pass_through_when_the_digest_matches() {
    let rq = vec_json("review-question-v1.json");
    let vec = vec_json("review-card-v1.json");
    let q = &rq["question_with_digest"];
    let digest = q["body"]["digest"].as_str().unwrap();
    for c in rq["verdict_cases"].as_array().unwrap() {
        let name = c["name"].as_str().unwrap();
        // workspace-side situations (unpaired phone, subscriber, group-routed) are not the relay's decision
        if matches!(
            name,
            "verdict-unpaired" | "verdict-subscriber" | "verdict-group-routed"
        ) {
            continue;
        }
        let f = F::new(&vec).await;
        let (s, v) = f.post_ws("ws_pilatus001", q).await;
        assert_eq!(s, 201, "{name}: {v}");
        let req = json!({"question_message_id": q["id"], "answer": c["answer"], "client_id": "55555555-5555-4555-8555-555555555555", "verdict": c["verdict"]});
        let (s, v) =
            f.t.phone(&f.iphone, "POST", "/v1/phone/answer", Some(req))
                .await;
        if c["verdict"]["digest"] == digest {
            assert_eq!(s, 201, "{name}: {v}");
            let c2 = f.t.app.db.lock().unwrap();
            let id: String = c2
                .query_row(
                    "SELECT id FROM messages WHERE reply_to=?1 AND type='answer'",
                    [q["id"].as_str().unwrap()],
                    |r| r.get(0),
                )
                .unwrap();
            let (b, _) =
                store::open_payload(&f.t.app.key, &store::get_msg(&c2, &id).unwrap().unwrap());
            assert_eq!(b["verdict"], c["verdict"], "{name}");
        } else {
            assert_eq!((s, err_of(&v)), (422, Some("invalid")), "{name}: {v}");
        }
    }
}
