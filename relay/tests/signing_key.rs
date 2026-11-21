//! Workspace signing keys (ORCH-1200, relay-api.md "Signing key"): PUT /v1/me/signing-key stores a workspace's
//! public key once; whoami and the directory show it as a hint. Replays contracts/vectors/signing-key-v1.json.
mod common;
use common::*;
use serde_json::{json, Value};

fn vectors() -> Value {
    serde_json::from_str(include_str!("../../contracts/vectors/signing-key-v1.json")).unwrap()
}

fn put(pk: &str) -> Option<Value> {
    Some(json!({"alg": "ed25519", "public_key": pk}))
}

#[test]
fn key_id_and_parse_match_vectors() {
    let v = vectors();
    for g in v["good"].as_array().unwrap() {
        let raw = orch_relay::signkeys::parse_public(g["public_key"].as_str().unwrap())
            .unwrap_or_else(|e| panic!("{}: {e}", g["name"]));
        assert_eq!(
            orch_relay::signkeys::key_id(&raw),
            g["key_id"],
            "{}",
            g["name"]
        );
    }
    for b in v["bad"].as_array().unwrap() {
        assert!(
            orch_relay::signkeys::parse_public(b["public_key"].as_str().unwrap()).is_err(),
            "not refused: {}",
            b["name"]
        );
    }
}

#[tokio::test]
async fn stores_once_shows_in_whoami_and_directory() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    t.rules(json!([rule(&a, &b, [true, false, false, false])]))
        .await;
    let g = &vectors()["good"][0];
    let pk = g["public_key"].as_str().unwrap();

    let (_, w) = t.call(&a, "GET", "/v1/whoami", None).await;
    assert_eq!(w["signing_key"], Value::Null, "none before");

    let (s, v) = t.call(&a, "PUT", "/v1/me/signing-key", put(pk)).await;
    assert_eq!(s, 201, "{v}");
    assert_eq!(v["status"], "stored");
    assert_eq!(v["key_id"], g["key_id"]);
    assert_eq!(v["public_key"], pk);
    assert!(
        v.get("fingerprint").is_none(),
        "the relay never names the fingerprint people compare"
    );

    let (s, v) = t.call(&a, "PUT", "/v1/me/signing-key", put(pk)).await;
    assert_eq!((s, v["status"].as_str()), (200, Some("unchanged")), "{v}");

    // A different key is never swapped in with the token alone.
    let other = vectors()["good"][1]["public_key"]
        .as_str()
        .unwrap()
        .to_string();
    let (s, v) = t.call(&a, "PUT", "/v1/me/signing-key", put(&other)).await;
    assert_eq!((s, v["error"].as_str()), (409, Some("key_exists")), "{v}");

    let (_, w) = t.call(&a, "GET", "/v1/whoami", None).await;
    assert_eq!(w["signing_key"]["public_key"], pk);
    assert_eq!(w["signing_key"]["alg"], "ed25519");

    let (_, snap) = t.call(&b, "GET", "/v1/refresh", None).await;
    let item = &snap["workspaces"]["workspaces"][0];
    assert_eq!(item["id"], a.id.as_str());
    assert_eq!(item["signing_key"]["public_key"], pk);
    assert_eq!(item["signing_key"]["key_id"], g["key_id"]);
}

#[tokio::test]
async fn refuses_bad_keys_and_bodies() {
    let t = start().await;
    let a = t.add_ws("A").await;
    for b in vectors()["bad"].as_array().unwrap() {
        let (s, v) = t
            .call(
                &a,
                "PUT",
                "/v1/me/signing-key",
                put(b["public_key"].as_str().unwrap()),
            )
            .await;
        assert_eq!(s, 422, "{}: {v}", b["name"]);
    }
    let pk = vectors()["good"][0]["public_key"].clone();
    for body in [
        json!({"public_key": pk}),
        json!({"alg": "rsa", "public_key": pk}),
        json!({"alg": "ed25519"}),
        json!({"alg": "ed25519", "public_key": pk, "private_key": "x"}),
        json!(["ed25519"]),
    ] {
        let (s, v) = t
            .call(&a, "PUT", "/v1/me/signing-key", Some(body.clone()))
            .await;
        assert_eq!(s, 422, "{body}: {v}");
    }
    let (_, w) = t.call(&a, "GET", "/v1/whoami", None).await;
    assert_eq!(
        w["signing_key"],
        Value::Null,
        "nothing stored by a refused call"
    );

    let bad = Ws {
        id: a.id.clone(),
        token: "orn_wrongwrongwrongwrong".into(),
    };
    let (s, _) = t
        .call(&bad, "PUT", "/v1/me/signing-key", put(pk.as_str().unwrap()))
        .await;
    assert_eq!(s, 401);
}
