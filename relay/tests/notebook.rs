mod common;
use common::*;
use serde_json::{json, Value};
use std::time::{Duration, Instant};

type Nb = (String, String);

fn later(secs: i64) -> String {
    orch_relay::util::fmt_time(orch_relay::util::now() + secs)
}

async fn add(t: &T, w: &Ws) -> (String, String) {
    let (s, v) = t
        .admin_json(
            "POST",
            "/admin/api/notebooks",
            Some(json!({"name": "Work notebook", "workspace": w.id})),
        )
        .await;
    assert_eq!(s, 201, "{v}");
    let code = v["code"].as_str().unwrap().to_string();
    assert_eq!(
        v["line"],
        format!("orch notebook connect https://relay.test {code}")
    );
    (v["notebook_id"].as_str().unwrap().into(), code)
}

async fn pair(t: &T, code: &str) -> (u16, Value) {
    let r = t
        .http
        .post(format!("{}/v1/notebook/pair", t.base))
        .json(&json!({"code": code, "name": "MacBook"}))
        .send()
        .await
        .unwrap();
    let s = r.status().as_u16();
    (s, r.json().await.unwrap_or(Value::Null))
}

async fn connect(t: &T, w: &Ws) -> Nb {
    let (_, code) = add(t, w).await;
    let (s, v) = pair(t, &code).await;
    assert_eq!(s, 201, "{v}");
    (
        v["notebook_id"].as_str().unwrap().into(),
        v["token"].as_str().unwrap().into(),
    )
}

async fn nb(t: &T, n: &Nb, method: &str, path: &str, body: Option<Value>) -> (u16, Value) {
    let m = reqwest::Method::from_bytes(method.as_bytes()).unwrap();
    let mut r = t
        .http
        .request(m, format!("{}{}", t.base, path))
        .header("X-Orch-Notebook", &n.0)
        .header("Authorization", format!("Bearer {}", n.1));
    if let Some(b) = body {
        r = r.json(&b);
    }
    let resp = r.send().await.unwrap();
    let s = resp.status().as_u16();
    (s, resp.json().await.unwrap_or(Value::Null))
}

fn ask_msg(from: &Ws, to: &str, way: &str, action: &str, expires: &str) -> Value {
    json!({"schema": "orch.msg/1", "id": mid(), "from": from.id, "to": to, "type": "notebook",
        "created_at": "2026-11-18T10:00:00Z",
        "body": {"notebook": {"kind": "ask", "way": way, "action": action, "args": {"q": "budget"}, "expires_at": expires}}})
}

async fn ask(t: &T, w: &Ws, to: &str) -> (u16, Value, String) {
    let m = ask_msg(w, to, "notebook", "ping", &later(3600));
    let id = m["id"].as_str().unwrap().to_string();
    let (s, v) = t.call(w, "POST", "/v1/messages", Some(m)).await;
    (s, v, id)
}

fn notebook_items(items: &[Value]) -> Vec<Value> {
    items
        .iter()
        .filter(|m| m["type"] == "notebook")
        .cloned()
        .collect()
}

#[tokio::test]
async fn ask_waits_while_asleep_then_reply_reaches_the_workspace() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let n = connect(&t, &a).await;
    // The notebook sleeps: the ask is stored and waits.
    let (s, v, aid) = ask(&t, &a, &n.0).await;
    assert_eq!(s, 201, "{v}");
    let (s, l) = t.call(&a, "GET", "/v1/notebooks", None).await;
    assert_eq!(s, 200);
    assert_eq!(l["items"][0]["waiting"], 1);
    assert_eq!(l["items"][0]["paired"], true);
    // It wakes and fetches.
    let (s, r) = nb(&t, &n, "GET", "/v1/notebook/requests?wait=0", None).await;
    assert_eq!(s, 200, "{r}");
    let items = r["items"].as_array().unwrap();
    assert_eq!(items.len(), 1);
    assert_eq!(items[0]["id"], aid.as_str());
    assert_eq!(items[0]["body"]["notebook"]["action"], "ping");
    // Not acked yet: handed out again (at least once).
    let (_, r) = nb(&t, &n, "GET", "/v1/notebook/requests", None).await;
    assert_eq!(r["items"].as_array().unwrap().len(), 1);
    // Reply, then ack.
    let rid = mid();
    let reply = json!({"id": rid, "reply_to": aid, "notebook": {"kind": "reply", "ok": true, "text": "Notebook here"}});
    let (s, v) = nb(&t, &n, "POST", "/v1/notebook/send", Some(reply.clone())).await;
    assert_eq!(s, 201, "{v}");
    // The same reply again (a retry) is a no-op; another reply to the same ask is refused.
    let (s, v) = nb(&t, &n, "POST", "/v1/notebook/send", Some(reply)).await;
    assert_eq!(s, 200, "{v}");
    assert_eq!(v["duplicate"], true);
    let (s, _) = nb(&t, &n, "POST", "/v1/notebook/send",
        Some(json!({"id": mid(), "reply_to": aid, "notebook": {"kind": "reply", "ok": true, "text": "again"}}))).await;
    assert_eq!(s, 409);
    let (s, _) = nb(
        &t,
        &n,
        "POST",
        "/v1/notebook/ack",
        Some(json!({"ids": [aid]})),
    )
    .await;
    assert_eq!(s, 204);
    let (_, r) = nb(&t, &n, "GET", "/v1/notebook/requests", None).await;
    assert!(r["items"].as_array().unwrap().is_empty());
    let got = notebook_items(&t.inbox(&a).await);
    assert_eq!(got.len(), 1);
    assert_eq!(got[0]["from"], n.0.as_str());
    assert_eq!(got[0]["reply_to"], aid.as_str());
    assert_eq!(got[0]["body"]["notebook"]["text"], "Notebook here");
}

#[tokio::test]
async fn long_poll_wakes_on_a_new_ask() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let n = connect(&t, &a).await;
    let t0 = Instant::now();
    let poll = nb(&t, &n, "GET", "/v1/notebook/requests?wait=10", None);
    let send = async {
        tokio::time::sleep(Duration::from_millis(300)).await;
        ask(&t, &a, &n.0).await
    };
    let ((s, r), (s2, ..)) = tokio::join!(poll, send);
    assert_eq!((s, s2), (200, 201));
    assert_eq!(r["items"].as_array().unwrap().len(), 1);
    assert!(t0.elapsed() < Duration::from_secs(5));
}

#[tokio::test]
async fn code_works_once_and_tokens_do_not_cross() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let (_, code) = add(&t, &a).await;
    let (s, v) = pair(&t, &code).await;
    assert_eq!(s, 201);
    assert_eq!(v["workspace"]["name"], "A");
    assert_eq!(pair(&t, &code).await.0, 410, "one use only");
    assert_eq!(pair(&t, "nc_wrong").await.0, 401);
    let n: Nb = (
        v["notebook_id"].as_str().unwrap().into(),
        v["token"].as_str().unwrap().into(),
    );
    // A wrong token, a workspace token and a phone token never work on notebook routes, and the reverse.
    assert_eq!(
        nb(
            &t,
            &(n.0.clone(), "orn_wrong".into()),
            "GET",
            "/v1/notebook/requests",
            None
        )
        .await
        .0,
        401
    );
    assert_eq!(
        nb(
            &t,
            &(a.id.clone(), a.token.clone()),
            "GET",
            "/v1/notebook/requests",
            None
        )
        .await
        .0,
        401
    );
    let p = t.pair_phone(&[&a]).await;
    assert_eq!(
        nb(&t, &p, "GET", "/v1/notebook/requests", None).await.0,
        401
    );
    assert_eq!(
        t.phone(&n, "GET", "/v1/phone/workspaces", None).await.0,
        401
    );
    let r = t
        .http
        .get(format!("{}/v1/whoami", t.base))
        .header("X-Orch-Workspace", &a.id)
        .header("Authorization", format!("Bearer {}", n.1))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
    // One notebook per workspace.
    let (s, _) = t
        .admin_json(
            "POST",
            "/admin/api/notebooks",
            Some(json!({"name": "Second", "workspace": a.id})),
        )
        .await;
    assert_eq!(s, 409);
}

#[tokio::test]
async fn workspaces_reach_only_their_own_notebook() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    t.rules(json!([rule(&a, &b, [true; 4]), rule(&b, &a, [true; 4])]))
        .await;
    let na = connect(&t, &a).await;
    let nbb = connect(&t, &b).await;
    // B may not ask A's notebook (answers like an unknown one), even with a full pair rule.
    let (s, _, _) = ask(&t, &b, &na.0).await;
    assert_eq!(s, 404);
    // No other type goes to a notebook; no notebook message goes to a workspace or a phone.
    assert_eq!(
        t.send(&a, &na.0, "text", json!({"text": "hi"})).await.0,
        403
    );
    let (s, _) = t
        .call(
            &a,
            "POST",
            "/v1/messages",
            Some(ask_msg(&a, &b.id, "notebook", "ping", &later(60))),
        )
        .await;
    assert_eq!(s, 403);
    // A workspace cannot send a reply or status in the notebook's name.
    let mut fake = ask_msg(&a, &na.0, "notebook", "ping", &later(60));
    fake["body"]["notebook"] = json!({"kind": "status", "ways": []});
    assert_eq!(t.call(&a, "POST", "/v1/messages", Some(fake)).await.0, 403);
    // B's notebook cannot answer A's ask, nor ack it.
    let (_, _, aid) = ask(&t, &a, &na.0).await;
    let (s, _) = nb(&t, &nbb, "POST", "/v1/notebook/send",
        Some(json!({"id": mid(), "reply_to": aid, "notebook": {"kind": "reply", "ok": true, "text": "x"}}))).await;
    assert_eq!(s, 403);
    nb(
        &t,
        &nbb,
        "POST",
        "/v1/notebook/ack",
        Some(json!({"ids": [aid]})),
    )
    .await;
    let (_, r) = nb(&t, &na, "GET", "/v1/notebook/requests", None).await;
    assert_eq!(
        r["items"].as_array().unwrap().len(),
        1,
        "B's ack did not touch A's ask"
    );
    // B's notebook sees nothing of A.
    let (_, r) = nb(&t, &nbb, "GET", "/v1/notebook/requests", None).await;
    assert!(r["items"].as_array().unwrap().is_empty());
    // A notebook sends only reply or status, and its message always goes to its own workspace.
    let (s, _) = nb(&t, &na, "POST", "/v1/notebook/send",
        Some(json!({"id": mid(), "notebook": {"kind": "ask", "way": "x", "action": "y", "expires_at": later(60)}}))).await;
    assert_eq!(s, 422);
    let (s, _) = nb(
        &t,
        &na,
        "POST",
        "/v1/notebook/send",
        Some(json!({"id": mid(), "to": b.id, "notebook": {"kind": "status", "ways": []}})),
    )
    .await;
    assert_eq!(s, 201);
    assert!(notebook_items(&t.inbox(&b).await).is_empty());
    assert_eq!(notebook_items(&t.inbox(&a).await).len(), 1);
}

#[tokio::test]
async fn expired_asks_are_never_handed_out_and_limits_hold() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let n = connect(&t, &a).await;
    // Past or too far away: refused.
    let (s, _) = t
        .call(
            &a,
            "POST",
            "/v1/messages",
            Some(ask_msg(&a, &n.0, "notebook", "ping", &later(-5))),
        )
        .await;
    assert_eq!(s, 422);
    let (s, _) = t
        .call(
            &a,
            "POST",
            "/v1/messages",
            Some(ask_msg(&a, &n.0, "notebook", "ping", &later(8 * 86400))),
        )
        .await;
    assert_eq!(s, 422);
    // An ask that expires while the notebook sleeps is dropped.
    let (s, _) = t
        .call(
            &a,
            "POST",
            "/v1/messages",
            Some(ask_msg(&a, &n.0, "notebook", "ping", &later(1))),
        )
        .await;
    assert_eq!(s, 201);
    tokio::time::sleep(Duration::from_millis(2100)).await;
    let (_, r) = nb(&t, &n, "GET", "/v1/notebook/requests", None).await;
    assert!(r["items"].as_array().unwrap().is_empty());
    // Bad slugs and too-long replies fail the contract.
    let (s, _) = t
        .call(
            &a,
            "POST",
            "/v1/messages",
            Some(ask_msg(&a, &n.0, "../etc", "ping", &later(60))),
        )
        .await;
    assert_eq!(s, 422);
    let (_, _, aid) = ask(&t, &a, &n.0).await;
    let big = "x".repeat(65537);
    let (s, _) = nb(&t, &n, "POST", "/v1/notebook/send",
        Some(json!({"id": mid(), "reply_to": aid, "notebook": {"kind": "reply", "ok": true, "text": big}}))).await;
    assert_eq!(s, 422);
    // Body limit before parsing.
    let huge = "y".repeat(300 * 1024);
    let (s, _) = nb(&t, &n, "POST", "/v1/notebook/send",
        Some(json!({"id": mid(), "reply_to": aid, "notebook": {"kind": "reply", "ok": true, "text": huge}}))).await;
    assert_eq!(s, 413);
    // Too many acks at once.
    let ids: Vec<String> = (0..101).map(|_| mid()).collect();
    assert_eq!(
        nb(
            &t,
            &n,
            "POST",
            "/v1/notebook/ack",
            Some(json!({"ids": ids}))
        )
        .await
        .0,
        422
    );
}

#[tokio::test]
async fn waiting_cap_and_rate_limit() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let n = connect(&t, &a).await;
    let mut last = 0;
    for _ in 0..61 {
        last = ask(&t, &a, &n.0).await.0;
    }
    assert_eq!(last, 429, "60 per minute");
    // The waiting cap: fill to 100 with older rows.
    {
        let c = t.app.db.lock().unwrap();
        c.execute(
            "UPDATE messages SET stored_at=stored_at-120 WHERE to_addr=?1",
            [&n.0],
        )
        .unwrap();
    }
    let mut s = 0;
    for _ in 0..41 {
        s = ask(&t, &a, &n.0).await.0;
    }
    assert_eq!(s, 429, "at most 100 waiting");
}

#[tokio::test]
async fn status_keeps_only_the_newest_and_remove_ends_everything() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let n = connect(&t, &a).await;
    for ok in [true, false] {
        let (s, _) = nb(&t, &n, "POST", "/v1/notebook/send", Some(json!({"id": mid(),
            "notebook": {"kind": "status", "app_version": "0.1", "ways": [{"way": "teams", "name": "Teams", "ok": ok, "checked_at": later(0), "problem": "The page changed"}]}}))).await;
        assert_eq!(s, 201);
    }
    let got = notebook_items(&t.inbox(&a).await);
    assert_eq!(got.len(), 1);
    assert_eq!(got[0]["body"]["notebook"]["ways"][0]["ok"], false);
    // Online while it polls; the admin list shows it.
    let (_, l) = t.call(&a, "GET", "/v1/notebooks", None).await;
    assert_eq!(l["items"][0]["online"], true);
    let (_, al) = t.admin_json("GET", "/admin/api/notebooks", None).await;
    assert_eq!(al["items"][0]["workspace"], a.id.as_str());
    // A waiting ask and an open long-poll: remove ends both.
    ask(&t, &a, &n.0).await;
    let (s, _) = t
        .admin_json("DELETE", &format!("/admin/api/notebooks/{}", n.0), None)
        .await;
    assert_eq!(s, 204);
    assert_eq!(
        nb(&t, &n, "GET", "/v1/notebook/requests", None).await.0,
        401
    );
    let left: i64 = {
        let c = t.app.db.lock().unwrap();
        c.query_row(
            "SELECT COUNT(*) FROM messages WHERE to_addr=?1 AND acked_at IS NULL",
            [&n.0],
            |r| r.get(0),
        )
        .unwrap()
    };
    assert_eq!(left, 0);
    let (_, l) = t.call(&a, "GET", "/v1/notebooks", None).await;
    assert!(l["items"].as_array().unwrap().is_empty());
}

#[tokio::test]
async fn removal_during_a_long_poll_is_refused() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let n = connect(&t, &a).await;
    let poll = nb(&t, &n, "GET", "/v1/notebook/requests?wait=10", None);
    let remove = async {
        tokio::time::sleep(Duration::from_millis(300)).await;
        t.admin_json("DELETE", &format!("/admin/api/notebooks/{}", n.0), None)
            .await
    };
    let ((s, _), (s2, _)) = tokio::join!(poll, remove);
    assert_eq!((s, s2), (401, 204));
}

#[tokio::test]
async fn two_open_polls_at_most() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let n = connect(&t, &a).await;
    let p1 = nb(&t, &n, "GET", "/v1/notebook/requests?wait=2", None);
    let p2 = nb(&t, &n, "GET", "/v1/notebook/requests?wait=2", None);
    let p3 = async {
        tokio::time::sleep(Duration::from_millis(300)).await;
        nb(&t, &n, "GET", "/v1/notebook/requests?wait=0", None).await
    };
    let ((s1, _), (s2, _), (s3, _)) = tokio::join!(p1, p2, p3);
    assert_eq!((s1, s2, s3), (200, 200, 429));
    // Slots are freed afterwards.
    assert_eq!(
        nb(&t, &n, "GET", "/v1/notebook/requests?wait=0", None)
            .await
            .0,
        200
    );
}

#[tokio::test]
async fn removing_the_workspace_removes_its_notebook() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let n = connect(&t, &a).await;
    let (s, _) = t
        .admin_json("DELETE", &format!("/admin/api/workspaces/{}", a.id), None)
        .await;
    assert_eq!(s, 204);
    assert_eq!(
        nb(&t, &n, "GET", "/v1/notebook/requests", None).await.0,
        401
    );
}

#[test]
fn contract_vectors_replay() {
    let v: Value =
        serde_json::from_str(include_str!("../../contracts/vectors/notebook-v1.json")).unwrap();
    for c in v["valid"].as_array().unwrap() {
        assert!(
            orch_relay::rules::validate_schema(&c["message"]).is_ok(),
            "{}",
            c["name"]
        );
    }
    for c in v["invalid"].as_array().unwrap() {
        let mut m = c["message"].clone();
        if let Some(n) = c["long_text"].as_u64() {
            m["body"]["notebook"]["text"] = "x".repeat(n as usize).into();
        }
        assert!(
            orch_relay::rules::validate_schema(&m).is_err(),
            "{}",
            c["name"]
        );
    }
}
