//! Push with the workspace's signature (ORCH-1296, design ORCH-1198 section 7): the relay starts the phone's
//! notification extension and passes the signed message unchanged when it fits the APNs limit.
use orch_relay::phone::{add_signed, PUSH_MAX_BYTES};
use serde_json::{json, Value};

fn base(kind: &str) -> Value {
    let mut p = json!({"aps": {"alert": {"title": "Dev", "body": "hello"}, "sound": "default"}, "workspace": "ws_abcdefghij"});
    if kind == "question" {
        p["message_id"] = "m_aaaaaaaaaaaaaaaa".into();
    } else {
        p["type"] = "text".into();
        p["text_id"] = "m_aaaaaaaaaaaaaaaa".into();
    }
    p
}

fn envelope(signed_len: usize) -> Value {
    json!({"sig_v": 1, "key_id": "0123456789abcdef", "signed": "A".repeat(signed_len), "sig": "B".repeat(86)})
}

#[test]
fn a_signed_question_rides_along_unchanged() {
    let mut p = base("question");
    let env = envelope(400);
    add_signed(
        &mut p,
        &json!({"type": "question", "envelope": env.clone()}),
    );
    assert_eq!(p["aps"]["mutable-content"], 1);
    assert_eq!(p["envelope"], env);
    assert!(p.get("msg_type").is_none());
}

#[test]
fn a_text_push_names_its_type() {
    let mut p = base("text");
    add_signed(&mut p, &json!({"type": "file", "envelope": envelope(100)}));
    assert_eq!(p["msg_type"], "file");
    assert_eq!(p["type"], "text", "the tap still opens the chat");
}

#[test]
fn too_long_or_unsigned_goes_without_an_envelope_but_still_starts_the_check() {
    let mut p = base("question");
    add_signed(
        &mut p,
        &json!({"type": "question", "envelope": envelope(5000)}),
    );
    assert!(p.get("envelope").is_none());
    assert_eq!(
        p["aps"]["mutable-content"], 1,
        "the phone then shows only New message from <workspace>"
    );
    assert!(serde_json::to_vec(&p).unwrap().len() <= PUSH_MAX_BYTES);

    let mut u = base("text");
    add_signed(&mut u, &json!({"type": "text"}));
    assert!(u.get("envelope").is_none());
    assert_eq!(u["aps"]["mutable-content"], 1);
}
