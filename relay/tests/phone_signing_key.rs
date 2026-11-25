//! Phone signing keys (ORCH-1204, relay-api.md "Signing key of a phone"): the phone sends its public key when it
//! redeems the pairing code; a bad key refuses the pairing and leaves the code unused; there is no route that sets
//! a key with the phone token alone; its workspaces see the key in the directory.
mod common;
use common::*;
use serde_json::{json, Value};

fn keys() -> (String, String, String) {
    let v: Value =
        serde_json::from_str(include_str!("../../contracts/vectors/signing-key-v1.json")).unwrap();
    let g = v["good"].as_array().unwrap();
    let bad = v["bad"][0]["public_key"].as_str().unwrap().to_string();
    (
        g[0]["public_key"].as_str().unwrap().to_string(),
        g[1]["public_key"].as_str().unwrap().to_string(),
        bad,
    )
}

async fn new_code(t: &T, ws: &Ws) -> String {
    let (s, v) = t
        .admin_json(
            "POST",
            "/admin/api/phones",
            Some(json!({"name": "P", "workspaces": [ws.id]})),
        )
        .await;
    assert!(s == 200 || s == 201, "{v}");
    v["link"]
        .as_str()
        .unwrap()
        .split("code=")
        .nth(1)
        .unwrap()
        .to_string()
}

async fn redeem(t: &T, code: &str, pk: Option<&str>) -> (u16, Value) {
    let mut body = json!({"code": code, "name": "My iPhone"});
    if let Some(pk) = pk {
        body["public_key"] = pk.into();
    }
    let r = t
        .http
        .post(format!("{}/v1/phone/pair", t.base))
        .json(&body)
        .send()
        .await
        .unwrap();
    let s = r.status().as_u16();
    (s, r.json().await.unwrap_or(Value::Null))
}

async fn phone_key_in_directory(t: &T, ws: &Ws) -> Value {
    let (s, d) = t.call(ws, "GET", "/v1/refresh", None).await;
    assert_eq!(s, 200, "{d}");
    d["workspaces"]["phones"][0]["signing_key"].clone()
}

#[tokio::test]
async fn pairing_stores_the_key_and_the_workspace_sees_it() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let (k1, k2, bad) = keys();

    // A bad key refuses the pairing; the code stays usable.
    let code = new_code(&t, &a).await;
    let (s, v) = redeem(&t, &code, Some(&bad)).await;
    assert_eq!(s, 422, "{v}");
    let (s, v) = redeem(&t, &code, Some(&k1)).await;
    assert_eq!(s, 201, "{v}");
    let p = (
        v["phone_id"].as_str().unwrap().to_string(),
        v["token"].as_str().unwrap().to_string(),
    );
    let sk = phone_key_in_directory(&t, &a).await;
    assert_eq!(sk["public_key"], k1.as_str());
    assert_eq!(sk["alg"], "ed25519");
    assert_eq!(sk["key_id"].as_str().unwrap().len(), 16);
    assert!(
        sk.get("fingerprint").is_none(),
        "the relay never sends a fingerprint"
    );

    // The token alone cannot set or swap it: no such route.
    let (s, _) = t
        .phone(
            &p,
            "PUT",
            "/v1/phone/signing-key",
            Some(json!({"alg": "ed25519", "public_key": k2})),
        )
        .await;
    assert!(s == 404 || s == 405, "{s}");
    assert_eq!(
        phone_key_in_directory(&t, &a).await["public_key"],
        k1.as_str()
    );
}

#[tokio::test]
async fn a_pairing_without_a_key_has_none() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let code = new_code(&t, &a).await;
    let (s, v) = redeem(&t, &code, None).await;
    assert_eq!(s, 201, "{v}");
    assert!(phone_key_in_directory(&t, &a).await.is_null());
}

#[tokio::test]
async fn a_new_pairing_replaces_the_key() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let (k1, k2, _) = keys();
    let code = new_code(&t, &a).await;
    assert_eq!(redeem(&t, &code, Some(&k1)).await.0, 201);
    let code = new_code(&t, &a).await;
    assert_eq!(redeem(&t, &code, Some(&k2)).await.0, 201);
    let (_, d) = t.call(&a, "GET", "/v1/refresh", None).await;
    let keys: Vec<&Value> = d["workspaces"]["phones"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| &p["signing_key"]["public_key"])
        .collect();
    assert!(keys.contains(&&json!(k2)), "{d}");
}

#[tokio::test]
async fn the_phone_sees_each_workspace_key_as_a_hint() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let (k1, _, _) = keys();
    let (s, _) = t
        .call(
            &a,
            "PUT",
            "/v1/me/signing-key",
            Some(json!({"alg": "ed25519", "public_key": k1})),
        )
        .await;
    assert_eq!(s, 201);
    let p = t.pair_phone(&[&a]).await;
    let (s, w) = t.phone(&p, "GET", "/v1/phone/workspaces", None).await;
    assert_eq!(s, 200, "{w}");
    assert_eq!(w["items"][0]["signing_key"]["public_key"], k1.as_str());
    assert!(w["items"][0]["signing_key"].get("fingerprint").is_none());
}

#[tokio::test]
async fn a_browser_pairing_ignores_a_key() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let (k1, _, _) = keys();
    let (s, v) = t
        .admin_json(
            "POST",
            "/admin/api/phones",
            Some(json!({"name": "Laptop", "kind": "browser", "workspaces": [a.id]})),
        )
        .await;
    assert_eq!(s, 201, "{v}");
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
        .header("Origin", "https://relay.test")
        .json(&json!({"code": code, "public_key": k1}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 201);
    let (_, d) = t.call(&a, "GET", "/v1/refresh", None).await;
    let any_key = d["workspaces"]["phones"]
        .as_array()
        .unwrap()
        .iter()
        .any(|p| !p["signing_key"].is_null());
    assert!(!any_key, "{d}");
}
