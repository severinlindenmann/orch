//! Every example in contracts/review is accepted/answered as specified.
mod common;
use common::*;
use orch_relay::{crypto, rules};
use serde_json::{json, Value};

fn examples(name: &str) -> Vec<Value> {
    let p = format!("{}/../contracts/review/{name}", env!("CARGO_MANIFEST_DIR"));
    serde_json::from_str(&std::fs::read_to_string(p).unwrap()).unwrap()
}

#[test]
fn schema_message_examples_validate() {
    let ex = examples("message.examples.json");
    assert!(!ex.is_empty());
    for mut m in ex {
        m.as_object_mut().unwrap().remove("_note");
        rules::validate_schema(&m).unwrap_or_else(|e| panic!("{m}: {e}"));
    }
}

#[test]
fn schema_rejects_bad_message() {
    assert!(rules::validate_schema(&json!({"schema": "orch.msg/1", "id": "x"})).is_err());
}

#[test]
fn crypto_roundtrip_aad_and_tamper() {
    let k = [3u8; 32];
    let c = crypto::seal(&k, "m_1", b"hello");
    assert_eq!(crypto::open(&k, "m_1", &c).unwrap(), b"hello");
    assert!(
        crypto::open(&k, "m_2", &c).is_none(),
        "AAD binds the item id"
    );
    assert!(crypto::open(&[4u8; 32], "m_1", &c).is_none());
    let mut bad = c.clone();
    *bad.last_mut().unwrap() ^= 1;
    assert!(crypto::open(&k, "m_1", &bad).is_none());
    assert_ne!(
        crypto::seal(&k, "m_1", b"hello"),
        c,
        "fresh nonce each time"
    );
}

/// The recorded relay-api examples that need no state: health, onboarding, error shapes.
#[tokio::test]
async fn schema_whoami_shape_matches_example() {
    let t = start().await;
    let w = t.add_ws("Pilatus Workspace").await;
    let (_, v) = t.call(&w, "GET", "/v1/whoami", None).await;
    let ex = examples("relay-api.examples.json");
    let want = ex
        .iter()
        .find(|e| e["request"]["path"] == "/v1/whoami")
        .unwrap()["response"]["body"]
        .as_object()
        .unwrap()
        .clone();
    // The recorded example predates the look fields (relay-api.md whoami: icon, color, look_by); contracts/review is
    // the contract author's file, so the three keys are added here until the example is updated.
    let mut a: Vec<_> = want.keys().cloned().collect();
    a.extend(["icon", "color", "look_by"].map(String::from));
    let mut b: Vec<_> = v.as_object().unwrap().keys().cloned().collect();
    a.sort();
    b.sort();
    assert_eq!(a, b);
}

#[tokio::test]
async fn schema_refresh_directory_matches_workspaces_schema() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    t.rules(json!([rule(&a, &b, [true, false, true, false])]))
        .await;
    let (_, snap) = t.call(&a, "GET", "/v1/refresh", None).await;
    let schema: Value = serde_json::from_str(
        &std::fs::read_to_string(format!(
            "{}/../contracts/workspaces.schema.json",
            env!("CARGO_MANIFEST_DIR")
        ))
        .unwrap(),
    )
    .unwrap();
    let c = jsonschema::JSONSchema::options()
        .should_validate_formats(true)
        .compile(&schema)
        .unwrap();
    assert!(c.is_valid(&snap["workspaces"]), "{}", snap["workspaces"]);
    assert_eq!(
        snap["workspaces"]["workspaces"][0]["can_send"],
        json!({"text": true, "files": false, "delegate": true, "start": false})
    );
}
