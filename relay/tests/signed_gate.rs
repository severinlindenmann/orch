//! ORCH-1201: the relay accepts only correctly signed messages (relay-api.md "Signed messages (v1)" and
//! "Signing keys: change and withdraw").
mod common;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use common::*;
use ed25519_dalek::{Signer, SigningKey};
use serde_json::{json, Value};

fn b64(b: &[u8]) -> String {
    URL_SAFE_NO_PAD.encode(b)
}

fn sk(n: u8) -> SigningKey {
    SigningKey::from_bytes(&[n; 32])
}

fn pubkey(k: &SigningKey) -> String {
    b64(k.verifying_key().as_bytes())
}

fn key_id(k: &SigningKey) -> String {
    orch_relay::msgsig::key_id(k.verifying_key().as_bytes())
}

fn envelope(k: &SigningKey, purpose: &str, signed: &[u8]) -> Value {
    let sig = k.sign(&orch_relay::msgsig::signature_input(purpose, signed));
    json!({"sig_v": 1, "key_id": key_id(k), "signed": b64(signed), "sig": b64(&sig.to_bytes())})
}

/// Outer message and its signed twin (same id, from, to, type, ticket, body).
fn signed_msg(k: &SigningKey, from: &Ws, to: &str, text: &str) -> (Value, Vec<u8>) {
    let id = mid();
    let body = json!({"text": text});
    let signed = serde_json::to_vec(&json!({"v": 1, "id": id, "from": from.id, "to": to, "type": "text",
        "created_ms": 1_795_000_000_000i64, "origin": "helper", "ticket": "t_7k3f9q", "body": body}))
    .unwrap();
    let outer = json!({"schema": "orch.msg/1", "id": id, "from": from.id, "to": to, "type": "text",
        "created_at": "2026-11-04T10:00:00Z", "ticket": "t_7k3f9q", "body": body,
        "envelope": envelope(k, "msg", &signed)});
    (outer, signed)
}

async fn register(t: &T, w: &Ws, k: &SigningKey) {
    let (s, v) = t
        .call(
            w,
            "PUT",
            "/v1/me/signing-key",
            Some(json!({"alg": "ed25519", "public_key": pubkey(k)})),
        )
        .await;
    assert_eq!(s, 201, "{v}");
}

async fn setup() -> (T, Ws, Ws, SigningKey) {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    t.rules(json!([rule(&a, &b, [true, true, false, false])]))
        .await;
    let k = sk(11);
    register(&t, &a, &k).await;
    (t, a, b, k)
}

async fn post(t: &T, w: &Ws, m: Value) -> (u16, Value) {
    t.call(w, "POST", "/v1/messages", Some(m)).await
}

fn code(v: &Value) -> &str {
    v["error"].as_str().unwrap_or("")
}

#[tokio::test]
async fn good_signature_is_delivered_with_its_envelope_unchanged() {
    let (t, a, b, k) = setup().await;
    let (m, _) = signed_msg(&k, &a, &b.id, "hello");
    let env = m["envelope"].clone();
    let (s, v) = post(&t, &a, m).await;
    assert_eq!(s, 201, "{v}");
    let items = t.inbox(&b).await;
    assert_eq!(items.len(), 1);
    assert_eq!(items[0]["envelope"], env);
    assert_eq!(items[0]["body"]["text"], "hello");
}

#[tokio::test]
async fn wrong_missing_or_changed_signature_is_refused() {
    let (t, a, b, k) = setup().await;
    // wrong: signed by a key that is not the registered one
    let (m, _) = signed_msg(&sk(99), &a, &b.id, "forged");
    let (s, v) = post(&t, &a, m).await;
    assert_eq!((s, code(&v)), (422, "unknown_key"), "{v}");
    // wrong: right key id, signature of another key (forged sig over the right id)
    let (mut m, signed) = signed_msg(&k, &a, &b.id, "forged");
    let other = sk(99).sign(&orch_relay::msgsig::signature_input("msg", &signed));
    m["envelope"]["sig"] = b64(&other.to_bytes()).into();
    let (s, v) = post(&t, &a, m).await;
    assert_eq!((s, code(&v)), (422, "bad_signature"), "{v}");
    // wrong purpose: a key-withdraw signature over message bytes
    let (mut m, signed) = signed_msg(&k, &a, &b.id, "x");
    m["envelope"] = envelope(&k, "key-withdraw", &signed);
    assert_eq!(code(&post(&t, &a, m).await.1), "bad_signature");
    // missing: envelope without sig, and an envelope that is null
    let (mut m, _) = signed_msg(&k, &a, &b.id, "x");
    m["envelope"].as_object_mut().unwrap().remove("sig");
    let (s, v) = post(&t, &a, m).await;
    assert_eq!((s, code(&v)), (422, "missing_signature"), "{v}");
    let (mut m, _) = signed_msg(&k, &a, &b.id, "x");
    m["envelope"] = Value::Null;
    assert_eq!(code(&post(&t, &a, m).await.1), "missing_signature");
    // changed: the signed bytes altered after signing
    let (mut m, signed) = signed_msg(&k, &a, &b.id, "pay 10");
    let changed = String::from_utf8(signed)
        .unwrap()
        .replace("pay 10", "pay 99");
    m["envelope"]["signed"] = b64(changed.as_bytes()).into();
    m["body"]["text"] = "pay 99".into();
    let (s, v) = post(&t, &a, m).await;
    assert_eq!((s, code(&v)), (422, "bad_signature"), "{v}");
    // changed: one bit of the signature flipped
    let (mut m, _) = signed_msg(&k, &a, &b.id, "x");
    let mut sig = URL_SAFE_NO_PAD
        .decode(m["envelope"]["sig"].as_str().unwrap())
        .unwrap();
    sig[3] ^= 1;
    m["envelope"]["sig"] = b64(&sig).into();
    assert_eq!(code(&post(&t, &a, m).await.1), "bad_signature");
    // changed: the outer message says something else than the signed bytes
    let (mut m, _) = signed_msg(&k, &a, &b.id, "real");
    m["body"]["text"] = "shown to the admin".into();
    let (s, v) = post(&t, &a, m).await;
    assert_eq!((s, code(&v)), (422, "signed_mismatch"), "{v}");
    // nothing of it reached B
    assert!(t.inbox(&b).await.is_empty());
}

#[tokio::test]
async fn a_signed_sender_must_be_the_caller() {
    let (t, a, b, _k) = setup().await;
    let kb = sk(12);
    register(&t, &b, &kb).await;
    // B signs a message claiming to be from A and A's token posts it
    let (m, _) = signed_msg(&kb, &a, &b.id, "x");
    let (s, v) = post(&t, &a, m).await;
    assert_eq!((s, code(&v)), (422, "unknown_key"), "{v}");
    // A's own key signs bytes that name B as the sender: refused as wrong_sender (403, like rule 1)
    let (mut m, _) = signed_msg(&a_key(), &b, &a.id, "x");
    m["from"] = a.id.clone().into();
    m["to"] = b.id.clone().into();
    let (s, v) = post(&t, &a, m).await;
    assert_eq!((s, code(&v)), (403, "wrong_sender"), "{v}");
}

fn a_key() -> SigningKey {
    sk(11)
}

#[tokio::test]
async fn replayed_message_is_refused_and_a_retry_is_a_duplicate() {
    let (t, a, b, k) = setup().await;
    let (m, _) = signed_msg(&k, &a, &b.id, "once");
    assert_eq!(post(&t, &a, m.clone()).await.0, 201);
    // the same bytes again: not delivered a second time
    let (s, v) = post(&t, &a, m.clone()).await;
    assert_eq!((s, v["duplicate"].as_bool()), (200, Some(true)), "{v}");
    // the same id with other signed bytes: refused
    let id = m["id"].as_str().unwrap();
    let signed = serde_json::to_vec(&json!({"v": 1, "id": id, "from": a.id, "to": b.id, "type": "text",
        "created_ms": 1_795_000_000_001i64, "origin": "helper", "ticket": "t_7k3f9q", "body": {"text": "twice"}}))
    .unwrap();
    let mut m2 = m.clone();
    m2["body"]["text"] = "twice".into();
    m2["envelope"] = envelope(&k, "msg", &signed);
    let (s, v) = post(&t, &a, m2).await;
    assert_eq!((s, code(&v)), (409, "replayed"), "{v}");
    assert_eq!(t.inbox(&b).await.len(), 1);
}

#[tokio::test]
async fn signed_files_must_match_the_stored_blob() {
    let (t, a, b, k) = setup().await;
    let data = b"signed file".to_vec();
    let up: Value = t
        .http
        .post(format!("{}/v1/blobs", t.base))
        .header("X-Orch-Workspace", &a.id)
        .header("Authorization", format!("Bearer {}", a.token))
        .body(data.clone())
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    let (bid, sha) = (
        up["blob_id"].as_str().unwrap(),
        up["sha256"].as_str().unwrap(),
    );
    let send = |sha256: String| {
        let id = mid();
        let body = json!({"blob_id": bid, "name": "a.txt", "size": data.len(), "sha256": sha});
        let signed = serde_json::to_vec(&json!({"v": 1, "id": id, "from": a.id, "to": b.id, "type": "file",
            "created_ms": 1_795_000_000_000i64, "origin": "helper", "ticket": "t_7k3f9q", "body": body,
            "files": [{"blob_id": bid, "size": data.len(), "sha256": sha256}]}))
        .unwrap();
        json!({"schema": "orch.msg/1", "id": id, "from": a.id, "to": b.id, "type": "file",
            "created_at": "2026-11-04T10:00:00Z", "ticket": "t_7k3f9q", "body": body,
            "envelope": envelope(&k, "msg", &signed)})
    };
    let (s, v) = post(&t, &a, send("0".repeat(64))).await;
    assert_eq!((s, code(&v)), (422, "signed_mismatch"), "{v}");
    let (s, v) = post(&t, &a, send(sha.to_string())).await;
    assert_eq!(s, 201, "{v}");
}

#[tokio::test]
async fn switch_off_lets_unsigned_through_switch_on_refuses_it() {
    let (t, a, b, _) = setup().await;
    let (s, v) = t.admin_json("GET", "/admin/api/signing-keys", None).await;
    assert_eq!((s, v["require_signed"].as_bool()), (200, Some(false)));
    assert_eq!(
        t.send(&a, &b.id, "text", json!({"text": "old"})).await.0,
        201
    );
    let (s, _) = t
        .admin_json(
            "PUT",
            "/admin/api/signing-keys/settings",
            Some(json!({"require_signed": true})),
        )
        .await;
    assert_eq!(s, 200);
    let (s, v) = t.send(&a, &b.id, "text", json!({"text": "old"})).await;
    assert_eq!((s, code(&v)), (422, "missing_signature"), "{v}");
    // a workspace with no key at all cannot send either
    t.rules(json!([rule(&b, &a, [true, false, false, false])]))
        .await;
    assert_eq!(t.send(&b, &a.id, "text", json!({"text": "x"})).await.0, 422);
    // only the admin turns it on or off
    let (s, _) = t
        .call(
            &a,
            "PUT",
            "/admin/api/signing-keys/settings",
            Some(json!({"require_signed": false})),
        )
        .await;
    assert_ne!(s, 200);
}

fn rotate_body(old: Option<&SigningKey>, new: &SigningKey, ws: &Ws) -> Value {
    let signed = serde_json::to_vec(&json!({"v": 1, "type": "key-rotate", "from": ws.id,
        "old_key_id": old.map(key_id), "new_public_key": pubkey(new), "created_ms": 1_795_000_000_000i64}))
    .unwrap();
    match old {
        Some(o) => {
            let ns = new.sign(&orch_relay::msgsig::signature_input("key-rotate", &signed));
            json!({"envelope": envelope(o, "key-rotate", &signed), "new_sig": b64(&ns.to_bytes())})
        }
        None => json!({"envelope": envelope(new, "key-rotate", &signed)}),
    }
}

#[tokio::test]
async fn key_change_is_held_until_the_relay_admin_approves() {
    let (t, a, b, k) = setup().await;
    let k2 = sk(22);
    // a plain PUT of another key is refused (1200), the change goes through the signed statement
    let (s, _) = t
        .call(
            &a,
            "PUT",
            "/v1/me/signing-key",
            Some(json!({"alg": "ed25519", "public_key": pubkey(&k2)})),
        )
        .await;
    assert_eq!(s, 409);
    // a change whose new-key proof is missing or wrong is refused
    let mut bad = rotate_body(Some(&k), &k2, &a);
    bad["new_sig"] = bad["envelope"]["sig"].clone();
    assert_eq!(
        t.call(&a, "POST", "/v1/me/signing-key/change", Some(bad))
            .await
            .0,
        422
    );
    // signed by a key that is not the old one: refused
    let (s, _) = t
        .call(
            &a,
            "POST",
            "/v1/me/signing-key/change",
            Some(rotate_body(Some(&sk(99)), &k2, &a)),
        )
        .await;
    assert_eq!(s, 422);
    let (s, v) = t
        .call(
            &a,
            "POST",
            "/v1/me/signing-key/change",
            Some(rotate_body(Some(&k), &k2, &a)),
        )
        .await;
    assert_eq!(
        (s, v["status"].as_str(), v["kind"].as_str()),
        (202, Some("pending"), Some("signed")),
        "{v}"
    );
    // held: the new key does not work yet, the old one still does
    let (m, _) = signed_msg(&k2, &a, &b.id, "new key");
    assert_eq!(code(&post(&t, &a, m).await.1), "unknown_key");
    let (m, _) = signed_msg(&k, &a, &b.id, "old key");
    assert_eq!(post(&t, &a, m).await.0, 201);
    // the admin page shows the key and the pending change
    let (_, list) = t.admin_json("GET", "/admin/api/signing-keys", None).await;
    let row = list["workspaces"]
        .as_array()
        .unwrap()
        .iter()
        .find(|w| w["workspace"] == a.id.as_str())
        .unwrap()
        .clone();
    assert_eq!(row["key"]["key_id"], key_id(&k));
    assert_eq!(row["key"]["state"], "active");
    assert_eq!(row["pending"]["key_id"], key_id(&k2));
    assert_eq!(row["pending"]["kind"], "signed");
    assert_eq!(row["pending"]["fingerprint"].as_str().unwrap().len(), 39);
    // the workspace cannot approve itself; a stale key id is refused
    let path = format!("/admin/api/signing-keys/{}/approve", a.id);
    assert_ne!(
        t.call(&a, "POST", &path, Some(json!({"key_id": key_id(&k2)})))
            .await
            .0,
        200
    );
    assert_eq!(
        t.admin_json(
            "POST",
            &path,
            Some(json!({"key_id": key_id(&k), "kind": "signed"}))
        )
        .await
        .0,
        409
    );
    // approval is bound to the kind the admin saw: a "without the old key" approval does not fit
    assert_eq!(
        t.admin_json(
            "POST",
            &path,
            Some(json!({"key_id": key_id(&k2), "kind": "no_old_key"}))
        )
        .await
        .0,
        409
    );
    let (s, v) = t
        .admin_json(
            "POST",
            &path,
            Some(json!({"key_id": key_id(&k2), "kind": "signed"})),
        )
        .await;
    assert_eq!(s, 200, "{v}");
    // now the new key works and the old one is refused
    let (m, _) = signed_msg(&k2, &a, &b.id, "new key");
    assert_eq!(post(&t, &a, m).await.0, 201);
    let (m, _) = signed_msg(&k, &a, &b.id, "old key");
    assert_eq!(code(&post(&t, &a, m).await.1), "unknown_key");
    let (_, list) = t.admin_json("GET", "/admin/api/signing-keys", None).await;
    let row = list["workspaces"]
        .as_array()
        .unwrap()
        .iter()
        .find(|w| w["workspace"] == a.id.as_str())
        .unwrap()
        .clone();
    assert!(row["pending"].is_null());
    assert_eq!(row["ended"][0]["state"], "replaced");
    // an old statement replayed (old key -> k2) does not start a new change
    let (s, _) = t
        .call(
            &a,
            "POST",
            "/v1/me/signing-key/change",
            Some(rotate_body(Some(&k), &k2, &a)),
        )
        .await;
    assert_eq!(s, 422);
}

#[tokio::test]
async fn key_change_without_the_old_key_is_marked_and_can_be_rejected() {
    let (t, a, _b, _k) = setup().await;
    let k2 = sk(23);
    let (s, v) = t
        .call(
            &a,
            "POST",
            "/v1/me/signing-key/change",
            Some(rotate_body(None, &k2, &a)),
        )
        .await;
    assert_eq!((s, v["kind"].as_str()), (202, Some("no_old_key")), "{v}");
    let (_, list) = t.admin_json("GET", "/admin/api/signing-keys", None).await;
    let row = &list["workspaces"]
        .as_array()
        .unwrap()
        .iter()
        .find(|w| w["workspace"] == a.id.as_str())
        .unwrap()
        .clone();
    assert_eq!(row["pending"]["kind"], "no_old_key");
    let path = format!("/admin/api/signing-keys/{}/reject", a.id);
    let (s, _) = t
        .admin_json("POST", &path, Some(json!({"key_id": key_id(&k2)})))
        .await;
    assert_eq!(s, 200);
    let (_, list) = t.admin_json("GET", "/admin/api/signing-keys", None).await;
    assert!(list["workspaces"]
        .as_array()
        .unwrap()
        .iter()
        .all(|w| w["pending"].is_null()));
}

fn withdraw_body(k: &SigningKey, ws: &Ws) -> Value {
    let signed = serde_json::to_vec(&json!({"v": 1, "type": "key-withdraw", "from": ws.id,
        "key_id": key_id(k), "created_ms": 1_795_000_000_000i64}))
    .unwrap();
    json!({"envelope": envelope(k, "key-withdraw", &signed)})
}

#[tokio::test]
async fn withdrawn_key_is_refused_and_vouches_for_nothing() {
    let (t, a, b, k) = setup().await;
    let (_, before) = t.call(&b, "GET", "/v1/refresh", None).await;
    // only a statement signed by the key itself withdraws it
    let (s, _) = t
        .call(
            &a,
            "POST",
            "/v1/me/signing-key/withdraw",
            Some(withdraw_body(&sk(99), &a)),
        )
        .await;
    assert_eq!(s, 422);
    let (s, v) = t
        .call(
            &a,
            "POST",
            "/v1/me/signing-key/withdraw",
            Some(withdraw_body(&k, &a)),
        )
        .await;
    assert_eq!((s, v["status"].as_str()), (200, Some("withdrawn")), "{v}");
    let (m, _) = signed_msg(&k, &a, &b.id, "after withdraw");
    let (s, v) = post(&t, &a, m).await;
    assert_eq!((s, code(&v)), (422, "key_withdrawn"), "{v}");
    // whoami and the directory say so (a hint for receivers)
    let (_, me) = t.call(&a, "GET", "/v1/whoami", None).await;
    assert_eq!(me["signing_key_state"]["state"], "withdrawn");
    let (_, dir) = t.call(&b, "GET", "/v1/refresh", None).await;
    let seen_by_b = dir["workspaces"]["workspaces"]
        .as_array()
        .into_iter()
        .flatten()
        .find(|w| w["id"] == a.id.as_str())
        .map(|w| w["signing_key_state"]["state"].clone());
    assert_eq!(seen_by_b, Some(json!("withdrawn")), "{dir}");
    assert_ne!(
        dir["version"], before["version"],
        "the withdrawal raises the version"
    );
    // the withdrawn key cannot vouch for a new one; a change without it waits for the admin
    let k2 = sk(24);
    let (s, v) = t
        .call(
            &a,
            "POST",
            "/v1/me/signing-key/change",
            Some(rotate_body(Some(&k), &k2, &a)),
        )
        .await;
    assert_eq!((s, code(&v)), (422, "key_withdrawn"), "{v}");
    let (s, _) = t
        .call(
            &a,
            "POST",
            "/v1/me/signing-key/change",
            Some(rotate_body(None, &k2, &a)),
        )
        .await;
    assert_eq!(s, 202);
    let path = format!("/admin/api/signing-keys/{}/approve", a.id);
    assert_eq!(
        t.admin_json(
            "POST",
            &path,
            Some(json!({"key_id": key_id(&k2), "kind": "no_old_key"}))
        )
        .await
        .0,
        200
    );
    let (m, _) = signed_msg(&k2, &a, &b.id, "new key");
    assert_eq!(post(&t, &a, m).await.0, 201);
    // the withdrawn key can never come back
    let (s, _) = t
        .call(
            &a,
            "POST",
            "/v1/me/signing-key/change",
            Some(rotate_body(Some(&k2), &k, &a)),
        )
        .await;
    assert_eq!(s, 422);
}

#[tokio::test]
async fn admin_blocked_key_is_refused() {
    let (t, a, b, k) = setup().await;
    // a pending change signed by the key is dropped when it is blocked
    let k2 = sk(25);
    assert_eq!(
        t.call(
            &a,
            "POST",
            "/v1/me/signing-key/change",
            Some(rotate_body(Some(&k), &k2, &a))
        )
        .await
        .0,
        202
    );
    let path = format!("/admin/api/signing-keys/{}/block", a.id);
    assert_eq!(
        t.admin_json("POST", &path, Some(json!({"key_id": key_id(&k2)})))
            .await
            .0,
        409
    );
    let (s, v) = t
        .admin_json("POST", &path, Some(json!({"key_id": key_id(&k)})))
        .await;
    assert_eq!(s, 200, "{v}");
    let (m, _) = signed_msg(&k, &a, &b.id, "blocked");
    let (s, v) = post(&t, &a, m).await;
    assert_eq!((s, code(&v)), (422, "key_blocked"), "{v}");
    let (_, list) = t.admin_json("GET", "/admin/api/signing-keys", None).await;
    let row = list["workspaces"]
        .as_array()
        .unwrap()
        .iter()
        .find(|w| w["workspace"] == a.id.as_str())
        .unwrap()
        .clone();
    assert_eq!(row["key"]["state"], "blocked");
    assert!(row["pending"].is_null(), "{row}");
    // the blocked key never vouches for a replacement
    let (s, v) = t
        .call(
            &a,
            "POST",
            "/v1/me/signing-key/change",
            Some(rotate_body(Some(&k), &k2, &a)),
        )
        .await;
    assert_eq!((s, code(&v)), (422, "key_blocked"), "{v}");
    let (_, me) = t.call(&a, "GET", "/v1/whoami", None).await;
    assert_eq!(me["signing_key_state"]["state"], "blocked");
}

#[tokio::test]
async fn new_token_drops_a_waiting_key_change() {
    let (t, a, _b, k) = setup().await;
    let k2 = sk(26);
    assert_eq!(
        t.call(
            &a,
            "POST",
            "/v1/me/signing-key/change",
            Some(rotate_body(Some(&k), &k2, &a))
        )
        .await
        .0,
        202
    );
    let (s, _) = t
        .admin_json(
            "POST",
            &format!("/admin/api/workspaces/{}/token", a.id),
            None,
        )
        .await;
    assert!(s == 200 || s == 201, "{s}");
    let (_, list) = t.admin_json("GET", "/admin/api/signing-keys", None).await;
    let row = list["workspaces"]
        .as_array()
        .unwrap()
        .iter()
        .find(|w| w["workspace"] == a.id.as_str())
        .unwrap()
        .clone();
    assert!(row["key"].is_null() && row["pending"].is_null(), "{row}");
}
