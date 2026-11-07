//! Mobile mode (contracts/relay-api.md "Mobile mode"): heartbeat flag, phone view, three pushes (mute respected),
//! the phone's `control` request and who may make it. The vector `mobile-mode-v1.json` is replayed.
mod common;
use common::*;
use serde_json::{json, Value};

type P = (String, String);

fn vectors() -> Value {
    serde_json::from_str(include_str!("../../contracts/vectors/mobile-mode-v1.json")).unwrap()
}

async fn register_push(t: &T, p: &P, token: &str) {
    let (s, _) = t
        .phone(
            p,
            "POST",
            "/v1/phone/push",
            Some(json!({"apns_token": token, "sandbox": true})),
        )
        .await;
    assert_eq!(s, 204);
}

async fn mm(t: &T, w: &Ws, p: &P) -> Value {
    let (_, v) = t.phone(p, "GET", "/v1/phone/workspaces", None).await;
    v["items"]
        .as_array()
        .unwrap()
        .iter()
        .find(|i| i["id"] == w.id)
        .unwrap()["mobile_mode"]
        .clone()
}

fn on() -> Value {
    json!({"mobile_mode": {"on": true, "since": "2026-11-07T14:02:00Z", "ends_at": "2026-11-08T02:02:00Z", "machine": "Acme PC"}})
}

fn sent_kinds(t: &T) -> Vec<(String, String)> {
    t.push
        .sent
        .lock()
        .unwrap()
        .iter()
        .map(|(_, tok, p)| (tok.clone(), p["kind"].as_str().unwrap_or("").to_string()))
        .collect()
}

#[tokio::test]
async fn vector_heartbeat_cases() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    for case in vectors()["heartbeat"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let (s, v) = t
            .call(&a, "POST", "/v1/heartbeat", Some(case["request"].clone()))
            .await;
        if case["ok"] == true {
            assert_eq!(s, 200, "{name}: {v}");
            assert_eq!(v["mobile_mode"], case["stored"], "{name}");
            assert_eq!(mm(&t, &a, &p).await, case["stored"], "{name}");
        } else {
            assert_eq!(s, 422, "{name}: {v}");
        }
    }
}

#[tokio::test]
async fn off_by_default_and_workspace_auth_only() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    assert_eq!(mm(&t, &a, &p).await["on"], false);
    // a phone token cannot send a heartbeat
    let (s, _) = t.phone(&p, "POST", "/v1/heartbeat", Some(on())).await;
    assert_eq!(s, 401);
    let (s, _) = t.call(&a, "POST", "/v1/heartbeat", Some(on())).await;
    assert_eq!(s, 200);
    assert_eq!(mm(&t, &a, &p).await["machine"], "Acme PC");
}

#[tokio::test]
async fn pushes_unreachable_back_ended_and_mute() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let other = t.add_ws("B").await;
    let p = t.pair_phone(&[&a]).await; // paired with A only
    let q = t.pair_phone(&[&a, &other]).await; // will mute A
    register_push(&t, &p, "abcdef0001").await;
    register_push(&t, &q, "abcdef0002").await;
    let (s, _) = t
        .phone(
            &q,
            "PATCH",
            &format!("/v1/phone/workspaces/{}", a.id),
            Some(json!({"muted_until": "forever"})),
        )
        .await;
    assert_eq!(s, 200);
    t.push.sent.lock().unwrap().clear();

    // turning on pushes nothing
    t.call(&a, "POST", "/v1/heartbeat", Some(on())).await;
    assert!(sent_kinds(&t).is_empty());

    // 5 minutes of silence: one push to the unmuted phone only, and only once
    let later = orch_relay::util::now() + 400;
    orch_relay::mobile::sweep(&t.app, later).await;
    orch_relay::mobile::sweep(&t.app, later + 60).await;
    assert_eq!(
        sent_kinds(&t),
        vec![("abcdef0001".into(), "mobile_mode_unreachable".into())]
    );
    {
        let sent = t.push.sent.lock().unwrap();
        let pl = &sent[0].2;
        assert_eq!(
            pl["aps"]["alert"]["body"],
            "Can't reach Acme PC. Your answers wait until it is back."
        );
        assert_eq!(pl["type"], "mobile_mode");
        assert_eq!(pl["workspace"], a.id);
    }

    // heard again: back
    t.call(&a, "POST", "/v1/heartbeat", Some(on())).await;
    // a normal heartbeat afterwards pushes nothing more
    t.call(&a, "POST", "/v1/heartbeat", Some(on())).await;
    // ended by the lease
    t.call(
        &a,
        "POST",
        "/v1/heartbeat",
        Some(json!({"mobile_mode": {"on": false, "ended": "lease"}})),
    )
    .await;
    // off again while off: nothing
    t.call(
        &a,
        "POST",
        "/v1/heartbeat",
        Some(json!({"mobile_mode": {"on": false}})),
    )
    .await;
    assert_eq!(
        sent_kinds(&t),
        vec![
            ("abcdef0001".into(), "mobile_mode_unreachable".into()),
            ("abcdef0001".into(), "mobile_mode_back".into()),
            ("abcdef0001".into(), "mobile_mode_ended".into()),
        ]
    );
    let sent = t.push.sent.lock().unwrap();
    assert_eq!(
        sent[2].2["aps"]["alert"]["body"],
        "Mobile mode ended: the time ran out."
    );
}

#[tokio::test]
async fn silent_workspace_that_is_off_is_not_announced() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    register_push(&t, &p, "abcdef0001").await;
    t.push.sent.lock().unwrap().clear();
    orch_relay::mobile::sweep(&t.app, orch_relay::util::now() + 10_000).await;
    assert!(sent_kinds(&t).is_empty());
}

#[tokio::test]
async fn control_is_built_by_the_relay_for_listed_workspaces_only() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let b = t.add_ws("B").await;
    let p = t.pair_phone(&[&a]).await;
    for case in vectors()["control"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let mut req = case["request"].clone();
        if req["to"].as_str().is_some_and(|x| x.starts_with("ws_")) {
            req["to"] = a.id.clone().into();
        }
        let (s, v) = t.phone(&p, "POST", "/v1/phone/control", Some(req)).await;
        if case["ok"] == true {
            // the vector reuses one client_id: the second ok case without it is a fresh message
            assert!(s == 201 || s == 200, "{name}: {s} {v}");
        } else {
            assert_eq!(s, 422, "{name}: {v}");
        }
    }
    let inbox = t.inbox(&a).await;
    let c: Vec<&Value> = inbox.iter().filter(|m| m["type"] == "control").collect();
    assert_eq!(c.len(), 2);
    for m in &c {
        assert_eq!(m["from"], p.0);
        assert_eq!(m["body"]["control"], "mobile_mode_off");
    }
    // not on the phone's list: refused, nothing stored
    let (s, _) = t
        .phone(
            &p,
            "POST",
            "/v1/phone/control",
            Some(json!({"to": b.id, "control": "mobile_mode_off"})),
        )
        .await;
    assert_eq!(s, 403);
    assert!(t.inbox(&b).await.iter().all(|m| m["type"] != "control"));
    // same client_id again: duplicate, no second message
    let req = json!({"to": a.id, "control": "mobile_mode_off", "client_id": "0b7a4c1e-9d2f-4e6a-8b3c-5d6e7f809a1b"});
    let (s1, v1) = t
        .phone(&p, "POST", "/v1/phone/control", Some(req.clone()))
        .await;
    let (s2, v2) = t.phone(&p, "POST", "/v1/phone/control", Some(req)).await;
    assert_eq!((s1, s2), (201, 200));
    assert_eq!(v1["id"], v2["id"]);
    // a control is not a chat message
    let (_, msgs) = t.phone(&p, "GET", "/v1/phone/messages", None).await;
    assert!(msgs["items"].as_array().unwrap().is_empty());
}

#[tokio::test]
async fn workspaces_and_other_phones_cannot_forge_a_control() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let b = t.add_ws("B").await;
    t.rules(json!([rule(&b, &a, [true, true, true, true])]))
        .await;
    // a workspace posting type control → 403, whoever the sender
    let (s, _) = t
        .send(&b, &a.id, "control", json!({"control": "mobile_mode_off"}))
        .await;
    assert_eq!(s, 403);
    let (s, _) = t
        .send(
            &a,
            "phones",
            "control",
            json!({"control": "mobile_mode_off"}),
        )
        .await;
    assert_eq!(s, 403);
    // a phone not paired with A cannot reach A
    let other = t.pair_phone(&[&b]).await;
    let (s, _) = t
        .phone(
            &other,
            "POST",
            "/v1/phone/control",
            Some(json!({"to": a.id, "control": "mobile_mode_off"})),
        )
        .await;
    assert_eq!(s, 403);
    assert!(t.inbox(&a).await.iter().all(|m| m["type"] != "control"));
}
