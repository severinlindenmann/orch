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
    json!({"mobile_mode": {"on": true, "since": orch_relay::util::fmt_time(orch_relay::util::now()), "ends_at": orch_relay::util::fmt_time(orch_relay::util::now() + 43_200), "machine": "Acme PC"}})
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
    for case in vectors()["heartbeat"].as_array().unwrap() {
        let a = t.add_ws("A").await;
        let p = t.pair_phone(&[&a]).await;
        let mut case = case.clone();
        // Preserve the vector shape while keeping its lease in the future.
        let future = orch_relay::util::fmt_time(orch_relay::util::now() + 43_200);
        if case["request"]["mobile_mode"]["ends_at"].is_string() {
            case["request"]["mobile_mode"]["ends_at"] = future.clone().into();
        }
        if case["stored"]["ends_at"].is_string() {
            case["stored"]["ends_at"] = future.into();
        }
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

#[tokio::test]
async fn authentication_precedes_body_validation() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    let mut bad_machine = on();
    bad_machine["mobile_mode"]["machine"] = "bad\nname".into();
    for body in [json!({}), bad_machine] {
        let response = t
            .http
            .post(format!("{}/v1/heartbeat", t.base))
            .json(&body)
            .send()
            .await
            .unwrap();
        assert_eq!(response.status().as_u16(), 401);
        let wrong = Ws {
            id: a.id.clone(),
            token: "wrong".into(),
        };
        assert_eq!(
            t.call(&wrong, "POST", "/v1/heartbeat", Some(body.clone()))
                .await
                .0,
            401
        );
        assert_eq!(
            t.phone(&p, "POST", "/v1/heartbeat", Some(body.clone()))
                .await
                .0,
            401
        );
        assert_eq!(t.call(&a, "POST", "/v1/heartbeat", Some(body)).await.0, 422);
    }
    let response = t
        .http
        .post(format!("{}/v1/heartbeat", t.base))
        .body("{")
        .send()
        .await
        .unwrap();
    assert_eq!(response.status().as_u16(), 401);
}

#[tokio::test]
async fn heartbeat_limit_is_rolling_and_per_workspace() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let b = t.add_ws("B").await;
    for _ in 0..7 {
        assert_eq!(t.call(&a, "POST", "/v1/heartbeat", Some(on())).await.0, 200);
    }
    let (status, body) = t.call(&a, "POST", "/v1/heartbeat", Some(on())).await;
    assert_eq!(status, 429);
    assert_eq!(body["error"], "rate_limited");
    assert_eq!(
        orch_relay::store::mobile_mode(&t.app.db.lock().unwrap(), &a.id)["on"],
        true
    );
    assert_eq!(t.call(&b, "POST", "/v1/heartbeat", Some(on())).await.0, 200);
    // Age just one request out: five recent requests still consume the window.
    let at = orch_relay::util::now();
    t.app
        .db
        .lock()
        .unwrap()
        .execute(
            "UPDATE workspaces SET mm_heartbeats=?2 WHERE id=?1",
            rusqlite::params![
                a.id,
                json!([[at - 60, 1], [at, 1], [at, 1], [at, 1], [at, 1], [at, 1]]).to_string()
            ],
        )
        .unwrap();
    assert_eq!(t.call(&a, "POST", "/v1/heartbeat", Some(on())).await.0, 200);
    assert_eq!(t.call(&a, "POST", "/v1/heartbeat", Some(on())).await.0, 429);
}

#[tokio::test]
async fn ended_cooldown_stores_off_and_is_per_workspace() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let b = t.add_ws("B").await;
    let p = t.pair_phone(&[&a, &b]).await;
    register_push(&t, &p, "abcdef0001").await;
    t.push.sent.lock().unwrap().clear();
    for w in [&a, &a, &b] {
        assert_eq!(t.call(w, "POST", "/v1/heartbeat", Some(on())).await.0, 200);
        let (status, body) = t
            .call(
                w,
                "POST",
                "/v1/heartbeat",
                Some(json!({"mobile_mode": {"on": false, "ended": "off"}})),
            )
            .await;
        assert_eq!(status, 200);
        assert_eq!(
            body["mobile_mode"],
            json!({"on": false, "since": null, "ends_at": null, "machine": null})
        );
    }
    assert_eq!(sent_kinds(&t).len(), 2);
    t.app
        .db
        .lock()
        .unwrap()
        .execute(
            "UPDATE workspaces SET mm_last_ended_push=?2 WHERE id=?1",
            rusqlite::params![a.id, orch_relay::util::now() - 600],
        )
        .unwrap();
    t.call(&a, "POST", "/v1/heartbeat", Some(on())).await;
    t.call(
        &a,
        "POST",
        "/v1/heartbeat",
        Some(json!({"mobile_mode": {"on": false}})),
    )
    .await;
    assert_eq!(
        sent_kinds(&t),
        vec![("abcdef0001".into(), "mobile_mode_ended".into()); 3]
    );
}

#[tokio::test]
async fn expired_lease_is_off_before_sweep_and_pushes_lease_once() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    register_push(&t, &p, "abcdef0001").await;
    t.push.sent.lock().unwrap().clear();
    t.call(&a, "POST", "/v1/heartbeat", Some(on())).await;
    let at = orch_relay::util::now();
    t.app
        .db
        .lock()
        .unwrap()
        .execute(
            "UPDATE workspaces SET mm_ends_at=?2,last_seen=?3 WHERE id=?1",
            rusqlite::params![a.id, orch_relay::util::fmt_time(at - 1), at - 400],
        )
        .unwrap();
    let off = json!({"on": false, "since": null, "ends_at": null, "machine": null});
    assert_eq!(mm(&t, &a, &p).await, off);
    assert!(sent_kinds(&t).is_empty());
    orch_relay::mobile::sweep(&t.app, at).await;
    orch_relay::mobile::sweep(&t.app, at + 60).await;
    assert_eq!(
        sent_kinds(&t),
        vec![("abcdef0001".into(), "mobile_mode_ended".into())]
    );
    assert_eq!(
        t.push.sent.lock().unwrap()[0].2["aps"]["alert"]["body"],
        "Mobile mode ended: the time ran out."
    );
    let cleared: bool = t.app.db.lock().unwrap().query_row(
        "SELECT mm_on=0 AND mm_since IS NULL AND mm_ends_at IS NULL AND mm_machine IS NULL AND mm_unreach=0 FROM workspaces WHERE id=?1",
        [&a.id], |r| r.get(0),
    ).unwrap();
    assert!(cleared);
    // A second expiry in the cooldown is cleared without another push, even after an outage.
    t.call(&a, "POST", "/v1/heartbeat", Some(on())).await;
    t.app
        .db
        .lock()
        .unwrap()
        .execute(
            "UPDATE workspaces SET mm_ends_at=?2,mm_unreach=1 WHERE id=?1",
            rusqlite::params![a.id, orch_relay::util::fmt_time(at)],
        )
        .unwrap();
    orch_relay::mobile::sweep(&t.app, at + 599).await;
    assert_eq!(mm(&t, &a, &p).await, off);
    assert_eq!(sent_kinds(&t).len(), 1);
    // Heartbeat transitions share the same cooldown with the sweeper.
    t.call(&a, "POST", "/v1/heartbeat", Some(on())).await;
    t.call(
        &a,
        "POST",
        "/v1/heartbeat",
        Some(json!({"mobile_mode": {"on": false}})),
    )
    .await;
    assert_eq!(sent_kinds(&t).len(), 1);
}

#[tokio::test]
async fn state_changes_have_their_own_limit() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let off = || json!({"mobile_mode": {"on": false}});
    // five quick toggles, then an off is still accepted
    for _ in 0..2 {
        assert_eq!(t.call(&a, "POST", "/v1/heartbeat", Some(on())).await.0, 200);
        assert_eq!(
            t.call(&a, "POST", "/v1/heartbeat", Some(off())).await.0,
            200
        );
    }
    assert_eq!(t.call(&a, "POST", "/v1/heartbeat", Some(on())).await.0, 200);
    assert_eq!(
        t.call(&a, "POST", "/v1/heartbeat", Some(off())).await.0,
        200
    );
    // 25 alternating toggles: changes 1..=20 pass (6 already used), the 21st change is refused
    let b = t.add_ws("B").await;
    let mut codes = vec![];
    for i in 0..25 {
        let body = if i % 2 == 0 { on() } else { off() };
        codes.push(t.call(&b, "POST", "/v1/heartbeat", Some(body)).await.0);
    }
    assert!(codes[..20].iter().all(|c| *c == 200), "{codes:?}");
    assert_eq!(codes[20], 429, "{codes:?}");
}
