//! Adversarial tests for "Review cards on the phone" (relay-api.md): blob read widening, answer forging and replay,
//! voice blob access, review_result spoofing and purge (security review, review-p1sec).
mod common;
use common::*;
use orch_relay::store;
use serde_json::{json, Value};

const DIGEST: &str = "46eb5ba8391f7ef3efad8d07111dce416b57326ecf440a211a86e67ec5bf6161";

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

async fn up_phone(t: &T, p: &(String, String), data: Vec<u8>) -> String {
    let r = t
        .http
        .post(format!("{}/v1/phone/blobs", t.base))
        .header("X-Orch-Phone", &p.0)
        .header("Authorization", format!("Bearer {}", p.1))
        .body(data)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 201);
    let v: Value = r.json().await.unwrap();
    v["blob_id"].as_str().unwrap().to_string()
}

async fn phone_get(t: &T, p: &(String, String), id: &str) -> u16 {
    t.phone(p, "GET", &format!("/v1/phone/blobs/{id}"), None)
        .await
        .0
}

async fn ws_get(t: &T, w: &Ws, id: &str) -> u16 {
    t.http
        .get(format!("{}/v1/blobs/{id}", t.base))
        .header("X-Orch-Workspace", &w.id)
        .header("Authorization", format!("Bearer {}", w.token))
        .send()
        .await
        .unwrap()
        .status()
        .as_u16()
}

/// A card question from `w` to `to` showing the uploaded blob `up` as card_files[0].
fn card_q(w: &Ws, to: &str, up: &Value) -> Value {
    json!({"schema": "orch.msg/1", "id": mid(), "from": w.id, "to": to, "type": "question",
        "created_at": "2026-11-15T09:00:00Z", "ticket": "t_m2p8xz",
        "body": {"question_id": "q3", "title": "Invoice", "text": "Send it?", "options": [], "recommended": null,
            "digest": DIGEST,
            "card": {"kind": "draft", "title": "Send it", "then": "It goes out.", "preview": {"type": "img", "src": {"file": 0}}},
            "card_files": [{"blob_id": up["blob_id"], "name": "invoice.png", "size": up["size"], "sha256": up["sha256"], "mime": "image/png"}]}})
}

fn verdict_ans(q: &Value, cid: &str, verdict: &str, voice: &[&str]) -> Value {
    let vo: Vec<Value> = voice
        .iter()
        .map(|b| json!({"blob_id": b, "transcript": "x", "lang": "en", "duration": 1}))
        .collect();
    let mut v = json!({"verdict": verdict, "digest": q["body"]["digest"]});
    if !vo.is_empty() {
        v["note"] = json!({"words": {"voice": vo}});
    }
    json!({"question_message_id": q["id"], "answer": "x", "client_id": cid, "verdict": v})
}

struct F {
    t: T,
    pil: Ws,
    rep: Ws,
    iphone: (String, String),
    ipad: (String, String),
    stranger: (String, String),
}

async fn fixture() -> F {
    let t = start().await;
    let pil = t.add_ws("Pilatus").await;
    let rep = t.add_ws("Reports").await;
    t.rules(json!([
        rule(&pil, &rep, [true, true, false, false]),
        rule(&rep, &pil, [true, true, false, false])
    ]))
    .await;
    let iphone = t.pair_phone(&[&pil]).await;
    let ipad = t.pair_phone(&[&pil]).await;
    let stranger = t.pair_phone(&[&rep]).await;
    F {
        t,
        pil,
        rep,
        iphone,
        ipad,
        stranger,
    }
}

#[tokio::test]
async fn card_file_of_a_question_to_another_phone_or_a_workspace_stays_closed() {
    let f = fixture().await;
    // to one phone: only that phone reads it
    let up = up_ws(&f.t, &f.pil, vec![1u8; 100]).await;
    let q = card_q(&f.pil, &f.ipad.0, &up);
    let (s, v) = f.t.call(&f.pil, "POST", "/v1/messages", Some(q)).await;
    assert_eq!(s, 201, "{v}");
    let b = up["blob_id"].as_str().unwrap();
    assert_eq!(phone_get(&f.t, &f.ipad, b).await, 200);
    assert_eq!(phone_get(&f.t, &f.iphone, b).await, 404);
    assert_eq!(phone_get(&f.t, &f.stranger, b).await, 404);
    // to a workspace: no phone reads it (neither the sender's nor the receiver's)
    let up2 = up_ws(&f.t, &f.pil, vec![2u8; 100]).await;
    let q2 = card_q(&f.pil, &f.rep.id, &up2);
    let (s, v) =
        f.t.call(&f.pil, "POST", "/v1/messages", Some(q2.clone()))
            .await;
    assert_eq!(s, 201, "{v}");
    let b2 = up2["blob_id"].as_str().unwrap();
    for p in [&f.iphone, &f.ipad, &f.stranger] {
        assert_eq!(phone_get(&f.t, p, b2).await, 404);
    }
    // and no phone can answer that workspace-to-workspace question
    let (s, _) =
        f.t.phone(
            &f.iphone,
            "POST",
            "/v1/phone/answer",
            Some(verdict_ans(
                &q2,
                "11111111-1111-4111-8111-111111111111",
                "ok",
                &[],
            )),
        )
        .await;
    assert_eq!(s, 404);
}

#[tokio::test]
async fn naming_a_blob_of_another_party_in_card_files_or_a_text_opens_nothing() {
    let f = fixture().await;
    // rep's blob named by pil: 404, nothing stored
    let theirs = up_ws(&f.t, &f.rep, vec![3u8; 100]).await;
    let (s, _) =
        f.t.call(
            &f.pil,
            "POST",
            "/v1/messages",
            Some(card_q(&f.pil, "phones", &theirs)),
        )
        .await;
    assert_eq!(s, 404);
    // a phone's own voice upload named by the workspace: 404 too
    let pv = up_phone(&f.t, &f.iphone, vec![4u8; 100]).await;
    let fake = json!({"blob_id": pv, "size": 100, "sha256": "0".repeat(64)});
    let (s, _) =
        f.t.call(
            &f.pil,
            "POST",
            "/v1/messages",
            Some(card_q(&f.pil, "phones", &fake)),
        )
        .await;
    assert_eq!(s, 404);
    assert_eq!(phone_get(&f.t, &f.ipad, &pv).await, 404);
    // card_files on a text (not a question) never opens the blob, whatever the status
    let own = up_ws(&f.t, &f.pil, vec![5u8; 100]).await;
    let mut m = card_q(&f.pil, "phones", &own);
    m["type"] = json!("text");
    let _ = f.t.call(&f.pil, "POST", "/v1/messages", Some(m)).await;
    let b = own["blob_id"].as_str().unwrap();
    assert_eq!(phone_get(&f.t, &f.iphone, b).await, 404);
    // the other workspace's phone never reads pil's card file
    let (s, _) =
        f.t.call(
            &f.pil,
            "POST",
            "/v1/messages",
            Some(card_q(&f.pil, "phones", &own)),
        )
        .await;
    assert_eq!(s, 201);
    assert_eq!(phone_get(&f.t, &f.iphone, b).await, 200);
    assert_eq!(phone_get(&f.t, &f.stranger, b).await, 404);
    // rep (not the uploader, not a receiver) cannot read pil's card file through /v1/blobs
    assert_eq!(ws_get(&f.t, &f.rep, b).await, 404);
}

#[tokio::test]
async fn phone_that_drops_the_workspace_loses_the_card_file() {
    let f = fixture().await;
    let up = up_ws(&f.t, &f.pil, vec![6u8; 100]).await;
    assert_eq!(
        f.t.call(
            &f.pil,
            "POST",
            "/v1/messages",
            Some(card_q(&f.pil, "phones", &up))
        )
        .await
        .0,
        201
    );
    let b = up["blob_id"].as_str().unwrap();
    assert_eq!(phone_get(&f.t, &f.iphone, b).await, 200);
    let (s, _) =
        f.t.phone(
            &f.iphone,
            "DELETE",
            &format!("/v1/phone/workspaces/{}", f.pil.id),
            None,
        )
        .await;
    assert_eq!(s, 204);
    assert_eq!(phone_get(&f.t, &f.iphone, b).await, 404);
}

#[tokio::test]
async fn verdict_voice_must_be_this_phones_upload_and_card_files_do_not_count() {
    let f = fixture().await;
    let up = up_ws(&f.t, &f.pil, vec![7u8; 100]).await;
    let q = card_q(&f.pil, "phones", &up);
    assert_eq!(
        f.t.call(&f.pil, "POST", "/v1/messages", Some(q.clone()))
            .await
            .0,
        201
    );
    // the card file itself (readable by the phone, but a workspace upload) is not a voice file of the phone
    let card_blob = up["blob_id"].as_str().unwrap();
    let (s, _) =
        f.t.phone(
            &f.iphone,
            "POST",
            "/v1/phone/answer",
            Some(verdict_ans(
                &q,
                "21111111-1111-4111-8111-111111111111",
                "talk",
                &[card_blob],
            )),
        )
        .await;
    assert_eq!(s, 404);
    // one own + one of the other phone: refused as a whole, nothing stored
    let mine = up_phone(&f.t, &f.iphone, vec![8u8; 50]).await;
    let other = up_phone(&f.t, &f.ipad, vec![9u8; 50]).await;
    let (s, _) =
        f.t.phone(
            &f.iphone,
            "POST",
            "/v1/phone/answer",
            Some(verdict_ans(
                &q,
                "31111111-1111-4111-8111-111111111111",
                "talk",
                &[&mine, &other],
            )),
        )
        .await;
    assert_eq!(s, 404);
    assert_eq!(ws_get(&f.t, &f.pil, &mine).await, 404);
    assert_eq!(ws_get(&f.t, &f.pil, &other).await, 404);
    // a verdict without a digest is refused by the schema/relay
    let mut a = verdict_ans(&q, "41111111-1111-4111-8111-111111111111", "ok", &[]);
    a["verdict"].as_object_mut().unwrap().remove("digest");
    let (s, _) =
        f.t.phone(&f.iphone, "POST", "/v1/phone/answer", Some(a))
            .await;
    assert_eq!(s, 422);
    // nothing was stored by the refused tries: the question is still open
    let n: i64 =
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
    assert_eq!(n, 0);
}

#[tokio::test]
async fn replayed_client_id_keeps_the_first_verdict_and_a_second_phone_gets_409() {
    let f = fixture().await;
    let up = up_ws(&f.t, &f.pil, vec![10u8; 100]).await;
    let q = card_q(&f.pil, "phones", &up);
    assert_eq!(
        f.t.call(&f.pil, "POST", "/v1/messages", Some(q.clone()))
            .await
            .0,
        201
    );
    let cid = "51111111-1111-4111-8111-111111111111";
    let (s, first) =
        f.t.phone(
            &f.iphone,
            "POST",
            "/v1/phone/answer",
            Some(verdict_ans(&q, cid, "ok", &[])),
        )
        .await;
    assert_eq!(s, 201);
    // same client_id, different verdict: the stored one stays
    let (s, v) =
        f.t.phone(
            &f.iphone,
            "POST",
            "/v1/phone/answer",
            Some(verdict_ans(&q, cid, "no", &[])),
        )
        .await;
    assert_eq!(
        (s, v["duplicate"].clone(), v["id"].clone()),
        (200, json!(true), first["id"].clone())
    );
    // a new client_id from the same phone, and the other phone: already answered
    for (p, c) in [
        (&f.iphone, "61111111-1111-4111-8111-111111111111"),
        (&f.ipad, "71111111-1111-4111-8111-111111111111"),
    ] {
        let (s, _) =
            f.t.phone(
                p,
                "POST",
                "/v1/phone/answer",
                Some(verdict_ans(&q, c, "no", &[])),
            )
            .await;
        assert_eq!(s, 409);
    }
    // a phone of another workspace: no such question
    let (s, _) =
        f.t.phone(
            &f.stranger,
            "POST",
            "/v1/phone/answer",
            Some(verdict_ans(
                &q,
                "81111111-1111-4111-8111-111111111111",
                "no",
                &[],
            )),
        )
        .await;
    assert_eq!(s, 404);
    let c = f.t.app.db.lock().unwrap();
    let m = store::get_msg(&c, first["id"].as_str().unwrap())
        .unwrap()
        .unwrap();
    assert_eq!(
        store::open_payload(&f.t.app.key, &m).0["verdict"]["verdict"],
        "ok"
    );
}

#[tokio::test]
async fn workspace_answer_with_a_verdict_cannot_open_a_phone_voice_blob() {
    let f = fixture().await;
    let voice = up_phone(&f.t, &f.iphone, vec![11u8; 60]).await;
    // rep asks pil a plain question; pil answers it naming the phone's voice blob in a verdict
    let qid = mid();
    let q = json!({"schema": "orch.msg/1", "id": qid, "from": f.rep.id, "to": f.pil.id, "type": "question",
        "created_at": "2026-11-15T09:00:00Z", "ticket": "t_m2p8xz",
        "body": {"question_id": "q1", "title": "T", "text": "?", "options": [], "recommended": null, "digest": DIGEST}});
    assert_eq!(
        f.t.call(&f.rep, "POST", "/v1/messages", Some(q)).await.0,
        201
    );
    let a = json!({"schema": "orch.msg/1", "id": mid(), "from": f.pil.id, "to": f.rep.id, "type": "answer",
        "created_at": "2026-11-15T09:01:00Z", "reply_to": qid,
        "body": {"question_id": "q1", "answer": "x", "answered_by": "human:x",
            "verdict": {"verdict": "talk", "digest": DIGEST, "note": {"words": {"voice": [{"blob_id": voice, "transcript": "x", "lang": "en", "duration": 1}]}}}}});
    let _ = f.t.call(&f.pil, "POST", "/v1/messages", Some(a)).await;
    assert_eq!(ws_get(&f.t, &f.rep, &voice).await, 404);
    assert_eq!(ws_get(&f.t, &f.pil, &voice).await, 404);
}

#[tokio::test]
async fn phone_cannot_send_a_review_result_and_a_null_marker_is_refused() {
    let f = fixture().await;
    let up = up_ws(&f.t, &f.pil, vec![12u8; 100]).await;
    let q = card_q(&f.pil, "phones", &up);
    assert_eq!(
        f.t.call(&f.pil, "POST", "/v1/messages", Some(q.clone()))
            .await
            .0,
        201
    );
    // phone send with a review_result field: refused or dropped, never stored
    let (_s, _) =
        f.t.phone(
            &f.iphone,
            "POST",
            "/v1/phone/send",
            Some(
                json!({"to": f.pil.id, "client_id": "91111111-1111-4111-8111-111111111111",
            "text": "Got it", "reply_to": q["id"], "review_result": {"result": "applied"}}),
            ),
        )
        .await;
    {
        let c = f.t.app.db.lock().unwrap();
        let mut st = c
            .prepare(&format!(
                "SELECT {} FROM messages WHERE type='text'",
                store::MSG_COLS
            ))
            .unwrap();
        for m in st.query_map([], store::msg_from_row).unwrap() {
            assert!(store::open_payload(&f.t.app.key, &m.unwrap())
                .0
                .get("review_result")
                .is_none());
        }
    }
    // workspace: review_result null or with an unknown result is refused (422), even after a real answer
    assert_eq!(
        f.t.phone(
            &f.iphone,
            "POST",
            "/v1/phone/answer",
            Some(verdict_ans(
                &q,
                "a1111111-1111-4111-8111-111111111111",
                "ok",
                &[]
            ))
        )
        .await
        .0,
        201
    );
    for rr in [
        json!(null),
        json!({"result": "applied", "reason": "x"}),
        json!({"result": "nope"}),
    ] {
        let m = json!({"schema": "orch.msg/1", "id": mid(), "from": f.pil.id, "to": f.iphone.0, "type": "text",
            "created_at": "2026-11-15T09:02:00Z", "ticket": "t_m2p8xz", "reply_to": q["id"],
            "body": {"text": "Got it", "review_result": rr}});
        assert_eq!(
            f.t.call(&f.pil, "POST", "/v1/messages", Some(m)).await.0,
            422,
            "{rr}"
        );
    }
    // a result to the phone that answered, but with a reply_to of the phone's own answer (not a question): 404
    let aid: String =
        f.t.app
            .db
            .lock()
            .unwrap()
            .query_row("SELECT id FROM messages WHERE type='answer'", [], |r| {
                r.get(0)
            })
            .unwrap();
    let m = json!({"schema": "orch.msg/1", "id": mid(), "from": f.pil.id, "to": f.iphone.0, "type": "text",
        "created_at": "2026-11-15T09:02:00Z", "ticket": "t_m2p8xz", "reply_to": aid,
        "body": {"text": "Got it", "review_result": {"result": "applied"}}});
    assert_eq!(
        f.t.call(&f.pil, "POST", "/v1/messages", Some(m)).await.0,
        404
    );
}

#[tokio::test]
async fn purge_drops_unused_voice_after_a_day_keeps_used_voice_and_closes_old_cards() {
    let f = fixture().await;
    let up = up_ws(&f.t, &f.pil, vec![13u8; 100]).await;
    let q = card_q(&f.pil, "phones", &up);
    assert_eq!(
        f.t.call(&f.pil, "POST", "/v1/messages", Some(q.clone()))
            .await
            .0,
        201
    );
    let used = up_phone(&f.t, &f.iphone, vec![14u8; 40]).await;
    let unused = up_phone(&f.t, &f.iphone, vec![15u8; 40]).await;
    assert_eq!(
        f.t.phone(
            &f.iphone,
            "POST",
            "/v1/phone/answer",
            Some(verdict_ans(
                &q,
                "b1111111-1111-4111-8111-111111111111",
                "talk",
                &[&used]
            ))
        )
        .await
        .0,
        201
    );
    let now = orch_relay::util::now();
    {
        let c = f.t.app.db.lock().unwrap();
        store::purge(&c, f.t.dir.path(), now + 2 * 86400).unwrap();
    }
    assert_eq!(ws_get(&f.t, &f.pil, &used).await, 200);
    assert_eq!(phone_get(&f.t, &f.iphone, &unused).await, 404);
    let b = up["blob_id"].as_str().unwrap();
    assert_eq!(phone_get(&f.t, &f.iphone, b).await, 200);
    {
        let c = f.t.app.db.lock().unwrap();
        store::purge(&c, f.t.dir.path(), now + store::RETENTION_SECS + 86400).unwrap();
    }
    assert_eq!(phone_get(&f.t, &f.iphone, b).await, 404);
    assert_eq!(ws_get(&f.t, &f.pil, &used).await, 404);
}

#[tokio::test]
async fn review_result_cannot_relabel_the_ticket_key() {
    let f = fixture().await;
    let up = up_ws(&f.t, &f.pil, vec![13u8; 100]).await;
    let mut q = card_q(&f.pil, "phones", &up);
    q["key"] = json!("DM1-12");
    assert_eq!(
        f.t.call(&f.pil, "POST", "/v1/messages", Some(q.clone()))
            .await
            .0,
        201
    );
    let ans = verdict_ans(&q, "b1111111-1111-4111-8111-111111111111", "ok", &[]);
    assert_eq!(
        f.t.phone(&f.iphone, "POST", "/v1/phone/answer", Some(ans))
            .await
            .0,
        201
    );
    let res = |key: &str| {
        json!({"schema": "orch.msg/1", "id": mid(), "from": f.pil.id, "to": f.iphone.0, "type": "text",
            "created_at": "2026-11-15T09:02:00Z", "ticket": "t_m2p8xz", "key": key, "reply_to": q["id"],
            "body": {"text": "Got it", "review_result": {"result": "applied"}}})
    };
    assert_eq!(
        f.t.call(&f.pil, "POST", "/v1/messages", Some(res("DM1-99")))
            .await
            .0,
        422
    );
    assert_eq!(
        f.t.call(&f.pil, "POST", "/v1/messages", Some(res("DM1-12")))
            .await
            .0,
        201
    );
}
