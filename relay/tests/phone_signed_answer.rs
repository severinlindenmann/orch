//! A phone's answer, signed (ORCH-1204 step c9, contracts/msgsig.md): it names the question by its id and the
//! SHA-256 of the question's signed bytes. The relay checks the phone's key, that the request says what the
//! signed answer says, and that the hash is the one it kept for the workspace's signed question; then it hands
//! the envelope to the workspace unchanged.
mod common;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use common::*;
use ed25519_dalek::{Signer, SigningKey};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

fn sk(n: u8) -> SigningKey {
    SigningKey::from_bytes(&[n; 32])
}

fn b64(b: &[u8]) -> String {
    URL_SAFE_NO_PAD.encode(b)
}

fn envelope(k: &SigningKey, signed: &[u8]) -> Value {
    let sig = k.sign(&orch_relay::msgsig::signature_input("msg", signed));
    json!({"sig_v": 1, "key_id": orch_relay::msgsig::key_id(k.verifying_key().as_bytes()),
        "signed": b64(signed), "sig": b64(&sig.to_bytes())})
}

fn now_ms() -> i64 {
    (std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis()) as i64
}

const CID: &str = "0b0c3f5e-6f3a-4d2b-9c41-2f0a8e7d6c5b";
const TICKET: &str = "t_7k3f9q";

struct Setup {
    t: T,
    ws: Ws,
    phone: (String, String),
    pk: SigningKey,
}

async fn setup() -> Setup {
    let t = start().await;
    let ws = t.add_ws("A").await;
    let (s, v) = t
        .call(
            &ws,
            "PUT",
            "/v1/me/signing-key",
            Some(json!({"alg": "ed25519", "public_key": b64(sk(11).verifying_key().as_bytes())})),
        )
        .await;
    assert_eq!(s, 201, "{v}");
    let pk = sk(42);
    let (_, v) = t
        .admin_json(
            "POST",
            "/admin/api/phones",
            Some(json!({"name": "P", "workspaces": [ws.id]})),
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
        .json(&json!({"code": code, "name": "Test iPhone", "public_key": b64(pk.verifying_key().as_bytes())}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 201);
    let v: Value = r.json().await.unwrap();
    let phone = (
        v["phone_id"].as_str().unwrap().to_string(),
        v["token"].as_str().unwrap().to_string(),
    );
    Setup { t, ws, phone, pk }
}

fn question_body(qid: &str) -> Value {
    json!({"question_id": qid, "title": "Ticket", "text": "Delete the old backups?", "options": ["yes", "no"],
        "recommended": "no"})
}

/// The workspace sends a question to the phones, signed when `signed`. Returns (message id, sha256 of the
/// signed bytes or "").
async fn ask(s: &Setup, qid: &str, signed: bool) -> (String, String) {
    let id = mid();
    let body = question_body(qid);
    let mut m = json!({"schema": "orch.msg/1", "id": id, "from": s.ws.id, "to": "phones", "type": "question",
        "created_at": "2026-11-26T10:00:00Z", "ticket": TICKET, "body": body});
    let mut digest = String::new();
    if signed {
        let bytes = serde_json::to_vec(&json!({"v": 1, "id": id, "from": s.ws.id, "to": "phones",
            "type": "question", "created_ms": now_ms(), "origin": "helper", "ticket": TICKET, "body": body}))
        .unwrap();
        digest = hex::encode(Sha256::digest(&bytes));
        m["envelope"] = envelope(&sk(11), &bytes);
    }
    let (st, v) = s.t.call(&s.ws, "POST", "/v1/messages", Some(m)).await;
    assert_eq!(st, 201, "{v}");
    (id, digest)
}

/// The signed answer object as a phone writes it.
fn answer_obj(s: &Setup, qmid: &str, qid: &str, sha: &str, text: &str) -> Value {
    json!({"v": 1, "id": mid(), "from": s.phone.0, "to": s.ws.id, "type": "answer", "created_ms": now_ms(),
        "origin": "person", "ticket": TICKET, "reply_to": qmid, "question_id": qid, "question_sha256": sha,
        "body": {"question_id": qid, "answer": text, "answered_by": format!("human:{}", s.phone.0), "client_id": CID}})
}

async fn post_answer(
    s: &Setup,
    qmid: &str,
    text: &str,
    signed: &Value,
    key: &SigningKey,
) -> (u16, Value) {
    let env = envelope(key, &serde_json::to_vec(signed).unwrap());
    s.t.phone(
        &s.phone,
        "POST",
        "/v1/phone/answer",
        Some(
            json!({"question_message_id": qmid, "answer": text, "client_id": CID, "envelope": env}),
        ),
    )
    .await
}

fn code(v: &Value) -> &str {
    v["error"].as_str().unwrap_or("")
}

#[tokio::test]
async fn a_signed_answer_names_the_signed_question_and_reaches_the_workspace_unchanged() {
    let s = setup().await;
    let (qmid, sha) = ask(&s, "q1", true).await;
    let signed = answer_obj(&s, &qmid, "q1", &sha, "no");
    let env = envelope(&s.pk, &serde_json::to_vec(&signed).unwrap());
    let req = json!({"question_message_id": qmid, "answer": "no", "client_id": CID, "envelope": env.clone()});
    let (st, v) =
        s.t.phone(&s.phone, "POST", "/v1/phone/answer", Some(req.clone()))
            .await;
    assert_eq!(st, 201, "{v}");
    assert_eq!(v["id"], signed["id"], "the relay keeps the signed id");
    let items = s.t.inbox(&s.ws).await;
    let a = items
        .iter()
        .find(|m| m["type"] == "answer")
        .expect("the answer reaches the workspace");
    assert_eq!(a["envelope"], env, "the envelope goes on unchanged");
    assert_eq!(
        a["body"], signed["body"],
        "the workspace gets exactly the signed body"
    );
    assert_eq!(a["reply_to"], qmid);
    assert_eq!(a["ticket"], TICKET);
    // a retry of the same request is the same answer, never a second one
    let (st, v) =
        s.t.phone(&s.phone, "POST", "/v1/phone/answer", Some(req))
            .await;
    assert_eq!((st, v["duplicate"].as_bool()), (200, Some(true)), "{v}");
}

#[tokio::test]
async fn a_signed_answer_with_another_question_hash_id_or_words_is_refused() {
    let s = setup().await;
    let (qmid, sha) = ask(&s, "q1", true).await;
    // another question's hash (a broken relay or a replay onto another question)
    let wrong = answer_obj(&s, &qmid, "q1", &"0".repeat(64), "no");
    let (st, v) = post_answer(&s, &qmid, "no", &wrong, &s.pk).await;
    assert_eq!((st, code(&v)), (422, "signed_mismatch"), "{v}");
    // another question id
    let mut other = answer_obj(&s, &qmid, "q2", &sha, "no");
    other["body"]["question_id"] = "q2".into();
    let (st, v) = post_answer(&s, &qmid, "no", &other, &s.pk).await;
    assert_eq!((st, code(&v)), (422, "signed_mismatch"), "{v}");
    // the request says yes, the signature says no
    let signed = answer_obj(&s, &qmid, "q1", &sha, "no");
    let (st, v) = post_answer(&s, &qmid, "yes", &signed, &s.pk).await;
    assert_eq!((st, code(&v)), (422, "signed_mismatch"), "{v}");
    // a name the phone picked instead of its id
    let mut named = answer_obj(&s, &qmid, "q1", &sha, "no");
    named["body"]["answered_by"] = "human:Severin".into();
    let (st, v) = post_answer(&s, &qmid, "no", &named, &s.pk).await;
    assert_eq!((st, code(&v)), (422, "signed_mismatch"), "{v}");
    // signed by a key that is not the phone's
    let (st, v) = post_answer(
        &s,
        &qmid,
        "no",
        &answer_obj(&s, &qmid, "q1", &sha, "no"),
        &sk(99),
    )
    .await;
    assert_eq!((st, code(&v)), (422, "unknown_key"), "{v}");
    // sent as a text, not an answer
    let mut text = answer_obj(&s, &qmid, "q1", &sha, "no");
    text["type"] = "text".into();
    text.as_object_mut().unwrap().remove("question_id");
    text.as_object_mut().unwrap().remove("question_sha256");
    let (st, v) = post_answer(&s, &qmid, "no", &text, &s.pk).await;
    assert_eq!((st, code(&v)), (422, "signed_mismatch"), "{v}");
    // nothing reached the workspace, and the question is still open for the right answer
    assert!(s.t.inbox(&s.ws).await.iter().all(|m| m["type"] != "answer"));
    let (st, v) = post_answer(
        &s,
        &qmid,
        "no",
        &answer_obj(&s, &qmid, "q1", &sha, "no"),
        &s.pk,
    )
    .await;
    assert_eq!(st, 201, "{v}");
}

#[tokio::test]
async fn an_answer_to_an_unsigned_question_cannot_be_signed_but_still_goes_unsigned() {
    let s = setup().await;
    let (qmid, _) = ask(&s, "q1", false).await;
    let signed = answer_obj(&s, &qmid, "q1", &"a".repeat(64), "no");
    let (st, v) = post_answer(&s, &qmid, "no", &signed, &s.pk).await;
    assert_eq!((st, code(&v)), (422, "signed_mismatch"), "{v}");
    let (st, v) =
        s.t.phone(
            &s.phone,
            "POST",
            "/v1/phone/answer",
            Some(json!({"question_message_id": qmid, "answer": "no", "client_id": CID})),
        )
        .await;
    assert_eq!(st, 201, "{v}");
    let items = s.t.inbox(&s.ws).await;
    let a = items.iter().find(|m| m["type"] == "answer").unwrap();
    assert!(a.get("envelope").is_none());
    assert_eq!(
        a["body"]["answered_by"], "human:Test iPhone",
        "unsigned: the relay's name as before"
    );
}

#[tokio::test]
async fn signed_only_refuses_an_unsigned_phone_answer() {
    let s = setup().await;
    let (qmid, _) = ask(&s, "q1", true).await;
    let (st, _) =
        s.t.admin_json(
            "PUT",
            "/admin/api/signing-keys/settings",
            Some(json!({"require_signed": true})),
        )
        .await;
    assert_eq!(st, 200);
    let (st, v) =
        s.t.phone(
            &s.phone,
            "POST",
            "/v1/phone/answer",
            Some(json!({"question_message_id": qmid, "answer": "no", "client_id": CID})),
        )
        .await;
    assert_eq!((st, code(&v)), (422, "missing_signature"), "{v}");
}
