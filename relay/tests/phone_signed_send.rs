//! What a phone sends, signed (ORCH-1204, contracts/msgsig.md): the relay checks the envelope against the key the
//! phone sent at pairing, refuses a changed, foreign or mismatched message, keeps the signed id and hands the
//! envelope to the workspace unchanged.
mod common;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use common::*;
use ed25519_dalek::{Signer, SigningKey};
use serde_json::{json, Value};

fn key(seed: u8) -> SigningKey {
    SigningKey::from_bytes(&[seed; 32])
}

fn pk(k: &SigningKey) -> String {
    URL_SAFE_NO_PAD.encode(k.verifying_key().to_bytes())
}

async fn pair_with_key(t: &T, ws: &Ws, k: Option<&SigningKey>) -> (String, String) {
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
    let mut body = json!({"code": code, "name": "Test iPhone"});
    if let Some(k) = k {
        body["public_key"] = pk(k).into();
    }
    let r = t
        .http
        .post(format!("{}/v1/phone/pair", t.base))
        .json(&body)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 201);
    let v: Value = r.json().await.unwrap();
    (
        v["phone_id"].as_str().unwrap().into(),
        v["token"].as_str().unwrap().into(),
    )
}

fn signed_bytes(m: &Value) -> Vec<u8> {
    serde_json::to_vec(m).unwrap()
}

fn envelope(k: &SigningKey, signed: &[u8]) -> Value {
    let mut input = b"orch-sig-v1\0msg\0".to_vec();
    input.extend_from_slice(signed);
    let sig = k.sign(&input);
    json!({"sig_v": 1, "key_id": orch_relay::msgsig::key_id(&k.verifying_key().to_bytes()),
        "signed": URL_SAFE_NO_PAD.encode(signed), "sig": URL_SAFE_NO_PAD.encode(sig.to_bytes())})
}

fn now_ms() -> i64 {
    (std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis()) as i64
}

fn msg(id: &str, from: &str, to: &str, text: &str, cid: &str) -> Value {
    json!({"v": 1, "id": id, "from": from, "to": to, "type": "text", "created_ms": now_ms(), "origin": "person",
        "body": {"client_id": cid, "text": text}})
}

const CID: &str = "0b0c3f5e-6f3a-4d2b-9c41-2f0a8e7d6c5b";

fn request(to: &str, text: &str, env: Value) -> Value {
    json!({"to": to, "client_id": CID, "text": text, "envelope": env})
}

#[tokio::test]
async fn a_signed_send_keeps_its_id_and_reaches_the_workspace_unchanged() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let k = key(7);
    let p = pair_with_key(&t, &a, Some(&k)).await;
    let id = "m_aaaaaaaaaaaaaaa1";
    let bytes = signed_bytes(&msg(id, &p.0, &a.id, "Hallo", CID));
    let env = envelope(&k, &bytes);
    let (s, v) = t
        .phone(
            &p,
            "POST",
            "/v1/phone/send",
            Some(request(&a.id, "Hallo", env.clone())),
        )
        .await;
    assert_eq!(s, 201, "{v}");
    assert_eq!(v["id"], id);
    let inbox = t.inbox(&a).await;
    let m = inbox.iter().find(|m| m["id"] == id).expect("in the inbox");
    assert_eq!(m["envelope"], env, "handed over unchanged");
    // The phone's own feed carries it too (the phone rebuilds and checks from it).
    let (_, feed) = t.phone(&p, "GET", "/v1/phone/messages", None).await;
    let mine = feed["items"]
        .as_array()
        .unwrap()
        .iter()
        .find(|i| i["message"]["id"] == id)
        .expect("in the feed");
    assert_eq!(mine["message"]["envelope"], env);
    assert_eq!(m["body"]["text"], "Hallo");
    // The same bytes again: a duplicate, not a second message.
    let (s, v) = t
        .phone(
            &p,
            "POST",
            "/v1/phone/send",
            Some(request(&a.id, "Hallo", env)),
        )
        .await;
    assert_eq!(s, 200, "{v}");
    assert_eq!(v["duplicate"], true);
}

#[tokio::test]
async fn a_changed_foreign_or_mismatched_send_is_refused() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let k = key(7);
    let p = pair_with_key(&t, &a, Some(&k)).await;
    let cid2 = "1b0c3f5e-6f3a-4d2b-9c41-2f0a8e7d6c5b";
    let send = |text: &str, env: Value, cid: &str| json!({"to": a.id, "client_id": cid, "text": text, "envelope": env});

    // One byte changed after signing.
    let mut bytes = signed_bytes(&msg("m_aaaaaaaaaaaaaaa2", &p.0, &a.id, "Pay 10", cid2));
    let env_ok = envelope(&k, &bytes);
    let i = bytes.iter().position(|b| *b == b'1').unwrap();
    bytes[i] = b'9';
    let mut env = env_ok.clone();
    env["signed"] = URL_SAFE_NO_PAD.encode(&bytes).into();
    let (s, v) = t
        .phone(
            &p,
            "POST",
            "/v1/phone/send",
            Some(send("Pay 90", env, cid2)),
        )
        .await;
    assert_eq!(
        (s, v["error"].as_str()),
        (422, Some("bad_signature")),
        "{v}"
    );

    // Signed by another key.
    let other = key(9);
    let bytes = signed_bytes(&msg("m_aaaaaaaaaaaaaaa3", &p.0, &a.id, "Hi", cid2));
    let (s, v) = t
        .phone(
            &p,
            "POST",
            "/v1/phone/send",
            Some(send("Hi", envelope(&other, &bytes), cid2)),
        )
        .await;
    assert_eq!((s, v["error"].as_str()), (422, Some("unknown_key")), "{v}");

    // The request says other words than the signed bytes.
    let bytes = signed_bytes(&msg("m_aaaaaaaaaaaaaaa4", &p.0, &a.id, "Hi", cid2));
    let (s, v) = t
        .phone(
            &p,
            "POST",
            "/v1/phone/send",
            Some(send("Bye", envelope(&k, &bytes), cid2)),
        )
        .await;
    assert_eq!(
        (s, v["error"].as_str()),
        (422, Some("signed_mismatch")),
        "{v}"
    );

    // Signed as another sender.
    let bytes = signed_bytes(&msg(
        "m_aaaaaaaaaaaaaaa5",
        "ph_zzzzzzzzzz",
        &a.id,
        "Hi",
        cid2,
    ));
    let (s, v) = t
        .phone(
            &p,
            "POST",
            "/v1/phone/send",
            Some(send("Hi", envelope(&k, &bytes), cid2)),
        )
        .await;
    assert_eq!(s, 403, "{v}");

    // Nothing of these reached the workspace.
    assert!(t.inbox(&a).await.iter().all(|m| m["from"] != p.0.as_str()));

    // The same id with other bytes: a replay.
    let bytes = signed_bytes(&msg("m_aaaaaaaaaaaaaaa6", &p.0, &a.id, "One", cid2));
    assert_eq!(
        t.phone(
            &p,
            "POST",
            "/v1/phone/send",
            Some(send("One", envelope(&k, &bytes), cid2))
        )
        .await
        .0,
        201
    );
    let cid3 = "2b0c3f5e-6f3a-4d2b-9c41-2f0a8e7d6c5b";
    let bytes = signed_bytes(&msg("m_aaaaaaaaaaaaaaa6", &p.0, &a.id, "Two", cid3));
    let (s, v) = t
        .phone(
            &p,
            "POST",
            "/v1/phone/send",
            Some(send("Two", envelope(&k, &bytes), cid3)),
        )
        .await;
    assert_eq!((s, v["error"].as_str()), (409, Some("replayed")), "{v}");
}

#[tokio::test]
async fn a_phone_without_a_key_cannot_send_signed_but_may_still_send_unsigned() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = pair_with_key(&t, &a, None).await;
    let k = key(7);
    let bytes = signed_bytes(&msg("m_aaaaaaaaaaaaaaa7", &p.0, &a.id, "Hi", CID));
    let (s, v) = t
        .phone(
            &p,
            "POST",
            "/v1/phone/send",
            Some(request(&a.id, "Hi", envelope(&k, &bytes))),
        )
        .await;
    assert_eq!((s, v["error"].as_str()), (422, Some("unknown_key")), "{v}");
    let (s, v) = t
        .phone(
            &p,
            "POST",
            "/v1/phone/send",
            Some(json!({"to": a.id, "client_id": CID, "text": "Hi"})),
        )
        .await;
    assert_eq!(s, 201, "until the hard cut: {v}");
}

#[tokio::test]
async fn a_signed_send_with_a_team_choice_must_sign_the_team_choice() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let k = key(7);
    let p = pair_with_key(&t, &a, Some(&k)).await;
    let team = json!({"add": "ws_sales00001", "mentions": ["ws_bank000001"]});
    let mut m = msg("m_aaaaaaaaaaaaaab1", &p.0, &a.id, "Add Sales", CID);
    m["ticket"] = "t_7k3f9q".into();
    m["body"]["team"] = team.clone();
    let mut req = request(&a.id, "Add Sales", envelope(&k, &signed_bytes(&m)));
    req["ticket"] = "t_7k3f9q".into();
    req["team"] = team.clone();
    let (s, v) = t
        .phone(&p, "POST", "/v1/phone/send", Some(req.clone()))
        .await;
    assert_eq!(s, 201, "{v}");
    assert_eq!(v["team"], json!(true), "{v}");
    let inbox = t.inbox(&a).await;
    let got = inbox
        .iter()
        .find(|x| x["id"] == "m_aaaaaaaaaaaaaab1")
        .expect("in the inbox");
    assert_eq!(got["body"]["team"], team);

    // The request names a team choice the signed bytes do not carry.
    let cid2 = "3b0c3f5e-6f3a-4d2b-9c41-2f0a8e7d6c5b";
    let mut m = msg("m_aaaaaaaaaaaaaab2", &p.0, &a.id, "Add Sales", cid2);
    m["ticket"] = "t_7k3f9q".into();
    let mut req = request(&a.id, "Add Sales", envelope(&k, &signed_bytes(&m)));
    req["client_id"] = cid2.into();
    req["ticket"] = "t_7k3f9q".into();
    req["team"] = team;
    let (s, v) = t.phone(&p, "POST", "/v1/phone/send", Some(req)).await;
    assert_eq!(
        (s, v["error"].as_str()),
        (422, Some("signed_mismatch")),
        "{v}"
    );
}

// ---- outside review (ORCH-1206) --------------------------------------------------------------------------------------

#[tokio::test]
async fn signed_only_refuses_an_unsigned_phone_send() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = pair_with_key(&t, &a, Some(&key(7))).await;
    let (s, _) = t
        .admin_json(
            "PUT",
            "/admin/api/signing-keys/settings",
            Some(json!({"require_signed": true})),
        )
        .await;
    assert_eq!(s, 200);
    let unsigned = json!({"to": a.id, "client_id": CID, "text": "Hi"});
    let (s, v) = t
        .phone(&p, "POST", "/v1/phone/send", Some(unsigned.clone()))
        .await;
    assert_eq!(
        (s, v["error"].as_str()),
        (422, Some("missing_signature")),
        "{v}"
    );
    let (s, _) = t
        .admin_json(
            "PUT",
            "/admin/api/signing-keys/settings",
            Some(json!({"require_signed": false})),
        )
        .await;
    assert_eq!(s, 200);
    let (s, v) = t.phone(&p, "POST", "/v1/phone/send", Some(unsigned)).await;
    assert_eq!(s, 201, "switch off again: {v}");
}

#[tokio::test]
async fn a_retry_that_says_something_else_is_a_mismatch_not_a_duplicate() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let b = t.add_ws("B").await;
    let k = key(7);
    let (_, v) = t
        .admin_json(
            "POST",
            "/admin/api/phones",
            Some(json!({"name": "P", "workspaces": [a.id, b.id]})),
        )
        .await;
    let code = v["link"].as_str().unwrap().split("code=").nth(1).unwrap();
    let r = t
        .http
        .post(format!("{}/v1/phone/pair", t.base))
        .json(&json!({"code": code, "name": "P", "public_key": pk(&k)}))
        .send()
        .await
        .unwrap();
    let v: Value = r.json().await.unwrap();
    let p: (String, String) = (
        v["phone_id"].as_str().unwrap().into(),
        v["token"].as_str().unwrap().into(),
    );
    let bytes = signed_bytes(&msg("m_aaaaaaaaaaaaaab1", &p.0, &a.id, "Hallo", CID));
    let env = envelope(&k, &bytes);
    let (s, v) = t
        .phone(
            &p,
            "POST",
            "/v1/phone/send",
            Some(request(&a.id, "Hallo", env.clone())),
        )
        .await;
    assert_eq!(s, 201, "{v}");
    // the same client id is answered as a duplicate before any check (nothing new is stored); another client id
    // with the stored envelope must still say what the signed bytes say
    let other = "1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f";
    for req in [
        json!({"to": a.id, "client_id": other, "text": "Hallo", "envelope": env.clone()}),
        json!({"to": b.id, "client_id": other, "text": "Hallo", "envelope": env}),
    ] {
        let (s, v) = t.phone(&p, "POST", "/v1/phone/send", Some(req)).await;
        assert_eq!(
            (s, v["error"].as_str()),
            (422, Some("signed_mismatch")),
            "{v}"
        );
    }
}

#[tokio::test]
async fn one_file_named_twice_never_stands_for_two_signed_files() {
    use sha2::{Digest, Sha256};
    let t = start().await;
    let a = t.add_ws("A").await;
    let k = key(7);
    let p = pair_with_key(&t, &a, Some(&k)).await;
    let mut ids = vec![];
    for fill in [1u8, 2u8] {
        let bytes = vec![fill; 100];
        let r = t
            .http
            .post(format!("{}/v1/phone/blobs", t.base))
            .header("X-Orch-Phone", &p.0)
            .header("Authorization", format!("Bearer {}", p.1))
            .header("Content-Type", "image/jpeg")
            .body(bytes.clone())
            .send()
            .await
            .unwrap();
        assert_eq!(r.status(), 201);
        let v: Value = r.json().await.unwrap();
        ids.push((
            v["blob_id"].as_str().unwrap().to_string(),
            hex::encode(Sha256::digest(&bytes)),
        ));
    }
    let att = |b: &str| json!({"blob_id": b, "kind": "image", "name": "a.jpg", "size": 100, "mime": "image/jpeg"});
    let twice = json!([att(&ids[0].0), att(&ids[0].0)]);
    let mut m = msg("m_aaaaaaaaaaaaaab2", &p.0, &a.id, "x", CID);
    m["body"] = json!({"client_id": CID, "attachments": twice});
    m["files"] = json!(ids
        .iter()
        .map(|(b, sha)| json!({"blob_id": b, "size": 100, "sha256": sha}))
        .collect::<Vec<_>>());
    let env = envelope(&k, &signed_bytes(&m));
    let (s, v) = t
        .phone(
            &p,
            "POST",
            "/v1/phone/send",
            Some(json!({"to": a.id, "client_id": CID, "attachments": twice, "envelope": env})),
        )
        .await;
    assert_eq!(
        (s, v["error"].as_str()),
        (422, Some("signed_mismatch")),
        "{v}"
    );
}
