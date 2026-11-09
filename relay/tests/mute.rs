//! Mute all + group mute (relay-api.md "Muted"; contracts/vectors/mute-v1.json is replayed).
mod common;
use common::*;
use orch_relay::{store, util};
use serde_json::{json, Value};

fn vector() -> Value {
    serde_json::from_str(include_str!("../../contracts/vectors/mute-v1.json")).unwrap()
}

fn at(s: &str) -> i64 {
    time::OffsetDateTime::parse(s, &time::format_description::well_known::Rfc3339)
        .unwrap()
        .unix_timestamp()
}

fn until(v: &Value) -> i64 {
    match v.as_str() {
        Some("forever") => store::MUTE_FOREVER,
        Some(s) => at(s),
        None => panic!("no time"),
    }
}

#[tokio::test]
async fn vector_push_decisions() {
    let t = start().await;
    let c = t.app.db.lock().unwrap();
    for case in vector()["cases"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        // a fresh phone id per case, so the mutes of one case never leak into the next
        let pid = format!("ph_case_{name}");
        let ph = &case["phone"];
        if !ph["mute_all_until"].is_null() {
            c.execute(
                "INSERT INTO phone_mute_all(phone,until) VALUES(?1,?2)",
                rusqlite::params![pid, until(&ph["mute_all_until"])],
            )
            .unwrap();
        }
        for (ws, u) in ph["workspace_mutes"].as_object().into_iter().flatten() {
            c.execute(
                "INSERT INTO phone_mutes(phone,ws,until) VALUES(?1,?2,?3)",
                rusqlite::params![pid, ws, until(u)],
            )
            .unwrap();
        }
        for g in ph["group_mutes"].as_array().into_iter().flatten() {
            c.execute(
                "INSERT INTO phone_group_mutes(phone,host,grp,until) VALUES(?1,?2,?3,?4)",
                rusqlite::params![
                    pid,
                    g["host"].as_str().unwrap(),
                    g["id"].as_str().unwrap(),
                    until(&g["muted_until"])
                ],
            )
            .unwrap();
        }
        let m = &case["message"];
        let muted = store::push_muted_at(
            &c,
            &pid,
            m["from"].as_str().unwrap(),
            &m["body"],
            at(case["now"].as_str().unwrap()),
        );
        assert_eq!(!muted, case["push"].as_bool().unwrap(), "case {name}");
    }
}

#[tokio::test]
async fn routes_and_end_to_end_push() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    let p = t.pair_phone(&[&a]).await;
    let q = t.pair_phone(&[&a, &b]).await;
    for (ph, tok) in [(&p, "ab12"), (&q, "cd34")] {
        let r = t
            .phone(
                ph,
                "POST",
                "/v1/phone/push",
                Some(json!({"apns_token": tok, "sandbox": true})),
            )
            .await;
        assert_eq!(r.0, 204);
    }
    let gid = "grp_t_7k3f9q";
    let gp = format!("/v1/phone/groups/{}/{gid}", a.id);
    // settings default
    let (s, v) = t.phone(&p, "GET", "/v1/phone/settings", None).await;
    assert_eq!(
        (s, v["mute_all_until"].clone(), v["group_mutes"].clone()),
        (200, Value::Null, json!([]))
    );
    // host not on the phone's list -> 404; bad id -> 422; no token -> 401
    let other = format!("/v1/phone/groups/{}/{gid}", b.id);
    assert_eq!(
        t.phone(&p, "PATCH", &other, Some(json!({"muted_until": "forever"})))
            .await
            .0,
        404
    );
    let bad = format!("/v1/phone/groups/{}/grp_x", a.id);
    assert_eq!(
        t.phone(&p, "PATCH", &bad, Some(json!({"muted_until": "forever"})))
            .await
            .0,
        422
    );
    assert_eq!(
        t.phone(&p, "PATCH", &gp, Some(json!({"muted_until": "tomorrow"})))
            .await
            .0,
        422
    );
    let r = t
        .http
        .patch(format!("{}{gp}", t.base))
        .json(&json!({"muted_until": "forever"}))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status().as_u16(), 401);
    // phone p mutes the group; phone q is unaffected (per-phone isolation)
    let (s, v) = t
        .phone(&p, "PATCH", &gp, Some(json!({"muted_until": "forever"})))
        .await;
    assert_eq!(
        (s, v),
        (
            200,
            json!({"host": a.id, "id": gid, "muted_until": "forever"})
        )
    );
    let (_, v) = t.phone(&p, "GET", "/v1/phone/settings", None).await;
    assert_eq!(
        v["group_mutes"],
        json!([{"host": a.id, "id": gid, "muted_until": "forever"}])
    );
    let (_, v) = t.phone(&q, "GET", "/v1/phone/settings", None).await;
    assert_eq!(v["group_mutes"], json!([]));
    // group text: p gets no push, q does; stored for both
    let qn = |n: &str| {
        json!({"schema": "orch.msg/1", "id": mid(), "from": a.id, "to": "phones", "type": "question", "ticket": "t_7k3f9q",
        "created_at": "2026-11-06T10:00:00Z", "body": {"question_id": n, "text": "?", "options": ["A"], "recommended": null}})
    };
    let m = |body: Value| {
        json!({"schema": "orch.msg/1", "id": mid(), "from": a.id, "to": "phones", "type": "text",
        "created_at": "2026-11-06T10:00:00Z", "body": body})
    };
    let grp = json!({"id": gid, "host": a.id, "title": "T", "members": []});
    assert_eq!(
        t.call(
            &a,
            "POST",
            "/v1/messages",
            Some(m(json!({"text": "hi", "group": grp})))
        )
        .await
        .0,
        201
    );
    tokio::time::sleep(std::time::Duration::from_millis(300)).await;
    assert_eq!(t.push.sent.lock().unwrap().len(), 1, "only q is pushed");
    // an unrelated message of the same host still pushes to p
    t.call(&a, "POST", "/v1/messages", Some(qn("q2"))).await;
    tokio::time::sleep(std::time::Duration::from_millis(300)).await;
    assert_eq!(t.push.sent.lock().unwrap().len(), 3);
    // mute all on p: nothing for p, q unaffected
    let future = util::fmt_time(util::now() + 3600);
    let (s, v) = t
        .phone(
            &p,
            "PATCH",
            "/v1/phone/settings",
            Some(json!({"mute_all_until": future})),
        )
        .await;
    assert_eq!((s, v["mute_all_until"].clone()), (200, json!(future)));
    t.call(&a, "POST", "/v1/messages", Some(qn("q3"))).await;
    tokio::time::sleep(std::time::Duration::from_millis(300)).await;
    assert_eq!(t.push.sent.lock().unwrap().len(), 4);
    // off again (null) and group unmuted
    let (_, v) = t
        .phone(
            &p,
            "PATCH",
            "/v1/phone/settings",
            Some(json!({"mute_all_until": null})),
        )
        .await;
    assert_eq!(v["mute_all_until"], Value::Null);
    let (_, v) = t
        .phone(&p, "PATCH", &gp, Some(json!({"muted_until": null})))
        .await;
    assert_eq!(v["muted_until"], Value::Null);
    // cap: 100 distinct groups ok, the 101st -> 422
    for i in 0..100 {
        let path = format!("/v1/phone/groups/{}/grp_t_cap{i:03}", a.id);
        let r = t
            .phone(&p, "PATCH", &path, Some(json!({"muted_until": "forever"})))
            .await;
        assert_eq!(r.0, 200, "{i}");
    }
    let path = format!("/v1/phone/groups/{}/grp_t_cap999", a.id);
    assert_eq!(
        t.phone(&p, "PATCH", &path, Some(json!({"muted_until": "forever"})))
            .await
            .0,
        422
    );
}
