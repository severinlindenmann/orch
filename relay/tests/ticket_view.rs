//! body.ticket_view (mobile chat): the relay replays contracts/vectors/ticket-view-v1.json, enforces the 16 KB cap and
//! blob ownership, lists the snapshot on /v1/phone/updates and lets only the right phone read named blobs.
mod common;
use common::*;
use serde_json::{json, Value};

fn vector() -> Value {
    let p = format!(
        "{}/../contracts/vectors/ticket-view-v1.json",
        env!("CARGO_MANIFEST_DIR")
    );
    serde_json::from_str(&std::fs::read_to_string(p).unwrap()).unwrap()
}

async fn upload(t: &T, w: &Ws, data: Vec<u8>) -> String {
    let r = t
        .http
        .post(format!("{}/v1/blobs", t.base))
        .header("X-Orch-Workspace", &w.id)
        .header("Authorization", format!("Bearer {}", w.token))
        .body(data)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 201);
    r.json::<Value>().await.unwrap()["blob_id"]
        .as_str()
        .unwrap()
        .to_string()
}

/// A text update with this ticket_view from `w` to `to`.
async fn send_view(
    t: &T,
    w: &Ws,
    to: &str,
    ticket: &str,
    kind: &str,
    view: Option<Value>,
) -> (u16, Value) {
    let mut body = json!({"text": "progress", "update": {"kind": kind}});
    if let Some(v) = view {
        body["ticket_view"] = v;
    }
    let m = json!({"schema": "orch.msg/1", "id": mid(), "from": w.id, "to": to, "type": "text",
        "created_at": "2026-11-06T09:41:00Z", "ticket": ticket, "body": body});
    t.call(w, "POST", "/v1/messages", Some(m)).await
}

fn view(title: &str, attachments: Value) -> Value {
    json!({"title": title, "status": "active", "running": true, "checklist": [{"text": "a", "done": true}],
        "done": 1, "total": 1, "history_tail": [], "attachments": attachments})
}

fn file_att(bid: &str, size: usize) -> Value {
    json!({"kind": "file", "title": "report.pdf", "blob_id": bid, "name": "report.pdf", "size": size,
        "at": "2026-11-06T09:39:00Z"})
}

async fn phone_blob(t: &T, p: &(String, String), id: &str) -> (u16, Vec<u8>) {
    let r = t
        .http
        .get(format!("{}/v1/phone/blobs/{id}", t.base))
        .header("X-Orch-Phone", &p.0)
        .header("Authorization", format!("Bearer {}", p.1))
        .send()
        .await
        .unwrap();
    (r.status().as_u16(), r.bytes().await.unwrap().to_vec())
}

#[tokio::test]
async fn ticket_view_vector_cases_stored_or_refused() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    let v = vector();
    for case in v["cases"].as_array().unwrap() {
        let mut m = case["message"].clone();
        m["id"] = mid().into();
        m["from"] = a.id.clone().into();
        // the vector's blob ids become real uploads of A with the same size (ids keep their length)
        if let Some(atts) = m["body"]["ticket_view"]
            .get_mut("attachments")
            .and_then(|a| a.as_array_mut())
        {
            for att in atts.iter_mut() {
                if let (Some(_), Some(n)) = (att["blob_id"].as_str(), att["size"].as_u64()) {
                    att["blob_id"] = upload(&t, &a, vec![7u8; n as usize]).await.into();
                }
            }
        }
        let (s, body) = t.call(&a, "POST", "/v1/messages", Some(m)).await;
        let want = if case["ok"].as_bool().unwrap() {
            201
        } else {
            422
        };
        assert_eq!(s, want, "case {}: {body}", case["name"]);
    }
    // what was stored comes back unchanged on the phone's ticket view
    let (s, g) = t
        .phone(
            &p,
            "GET",
            &format!("/v1/phone/updates?workspace={}&ticket=t_q3sum1", a.id),
            None,
        )
        .await;
    assert_eq!(s, 200, "{g}");
    let stored: Vec<&Value> = g["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|i| &i["ticket_view"])
        .collect();
    assert_eq!(
        stored.len(),
        9,
        "full, minimal, at-cap, page-with-preview, preview-outside-list, ready-started, wont-do-step and the two light views are stored"
    );
    assert!(
        stored
            .iter()
            .any(|v| v["light"] == true && v.get("attachments").is_none()),
        "a light view is stored as sent, without placeholders"
    );
    let big = stored
        .iter()
        .find(|v| {
            v["title"] == "Q3 summary for the board" && v["history_tail"][1]["role"] == "person"
        })
        .expect("the at-cap view is stored unchanged");
    assert_eq!(big["history_tail"][1]["role"], "person");
    assert!(
        stored.iter().any(|v| v["started"] == true),
        "started is kept for the phone"
    );
}

#[tokio::test]
async fn ticket_view_blobs_must_be_the_senders_with_their_size() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    let _p = t.pair_phone(&[&a, &b]).await;
    let mine = upload(&t, &a, b"mine".to_vec()).await;
    let theirs = upload(&t, &b, b"theirs".to_vec()).await;
    let (s, _) = send_view(
        &t,
        &a,
        "phones",
        "t_aaaaaa",
        "result",
        Some(view("T", json!([file_att(&mine, 4)]))),
    )
    .await;
    assert_eq!(s, 201);
    let (s, e) = send_view(
        &t,
        &a,
        "phones",
        "t_aaaaaa",
        "result",
        Some(view("T", json!([file_att(&theirs, 6)]))),
    )
    .await;
    assert_eq!(
        s, 404,
        "another workspace's blob answers like a missing one: {e}"
    );
    let (s, _) = send_view(
        &t,
        &a,
        "phones",
        "t_aaaaaa",
        "result",
        Some(view("T", json!([file_att("b_0000000000000000", 4)]))),
    )
    .await;
    assert_eq!(s, 404);
    let (s, _) = send_view(
        &t,
        &a,
        "phones",
        "t_aaaaaa",
        "result",
        Some(view("T", json!([file_att(&mine, 5)]))),
    )
    .await;
    assert_eq!(s, 422, "size must match the upload");
    // a ticket_view without an update is refused by the schema
    let m = json!({"schema": "orch.msg/1", "id": mid(), "from": a.id, "to": "phones", "type": "text",
        "created_at": "2026-11-06T09:41:00Z", "ticket": "t_aaaaaa", "body": {"text": "x", "ticket_view": view("T", json!([]))}});
    assert_eq!(t.call(&a, "POST", "/v1/messages", Some(m)).await.0, 422);
}

#[tokio::test]
async fn ticket_view_newest_wins_in_grouped_updates_and_rides_on_each_item() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let p = t.pair_phone(&[&a]).await;
    send_view(
        &t,
        &a,
        "phones",
        "t_aaaaaa",
        "note",
        Some(view("old", json!([]))),
    )
    .await;
    send_view(
        &t,
        &a,
        "phones",
        "t_aaaaaa",
        "result",
        Some(view("new", json!([]))),
    )
    .await;
    send_view(&t, &a, &p.0, "t_aaaaaa", "ack", None).await; // newest, without a snapshot
    send_view(&t, &a, "phones", "t_bbbbbb", "ack", None).await; // a ticket that never had one
    let (s, g) = t.phone(&p, "GET", "/v1/phone/updates", None).await;
    assert_eq!(s, 200, "{g}");
    let items = g["items"].as_array().unwrap();
    let one = items.iter().find(|i| i["ticket"] == "t_aaaaaa").unwrap();
    assert_eq!(one["kind"], "ack");
    assert_eq!(
        one["ticket_view"]["title"], "new",
        "grouped item keeps the newest snapshot"
    );
    let two = items.iter().find(|i| i["ticket"] == "t_bbbbbb").unwrap();
    assert_eq!(two["ticket_view"], Value::Null);
    let (_, g) = t
        .phone(
            &p,
            "GET",
            &format!("/v1/phone/updates?workspace={}&ticket=t_aaaaaa", a.id),
            None,
        )
        .await;
    let views: Vec<Value> = g["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|i| i["ticket_view"]["title"].clone())
        .collect();
    assert_eq!(
        views,
        vec![Value::Null, json!("new"), json!("old")],
        "one ticket: each item its own"
    );
}

#[tokio::test]
async fn phone_reads_only_blobs_named_in_a_view_sent_to_it() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    t.rules(json!([rule(&a, &b, [true, true, false, false])]))
        .await;
    let pa = t.pair_phone(&[&a]).await;
    let pb = t.pair_phone(&[&b]).await;
    let shown = upload(&t, &a, b"proof bytes".to_vec()).await;
    let unnamed = upload(&t, &a, b"not shown".to_vec()).await;
    let to_ws = upload(&t, &a, b"to a workspace".to_vec()).await;
    let (s, _) = send_view(
        &t,
        &a,
        "phones",
        "t_aaaaaa",
        "result",
        Some(view("T", json!([file_att(&shown, 11)]))),
    )
    .await;
    assert_eq!(s, 201);
    let (s, _) = send_view(
        &t,
        &a,
        &b.id,
        "t_aaaaaa",
        "result",
        Some(view("T", json!([file_att(&to_ws, 14)]))),
    )
    .await;
    assert_eq!(s, 201);
    assert_eq!(
        phone_blob(&t, &pa, &shown).await,
        (200, b"proof bytes".to_vec())
    );
    assert_eq!(
        phone_blob(&t, &pa, &unnamed).await.0,
        404,
        "never named in a view"
    );
    assert_eq!(
        phone_blob(&t, &pa, &to_ws).await.0,
        404,
        "named only in a text to a workspace"
    );
    assert_eq!(
        phone_blob(&t, &pb, &shown).await.0,
        404,
        "A is not on this phone's list"
    );
    assert_eq!(phone_blob(&t, &pa, "../../master.key").await.0, 404);
    let r = t
        .http
        .get(format!("{}/v1/phone/blobs/{shown}", t.base))
        .header("X-Orch-Phone", &pa.0)
        .header("Authorization", "Bearer orn_wrong")
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
}

#[tokio::test]
async fn phone_blob_other_phone_and_workspace_removed_from_the_list_get_404() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    let mine = t.pair_phone(&[&a, &b]).await;
    let other = t.pair_phone(&[&b]).await; // paired, but A is not on its list
    let bid = upload(&t, &a, b"chart".to_vec()).await;
    // sent to this phone directly and to every phone
    let (s, _) = send_view(
        &t,
        &a,
        &mine.0,
        "t_aaaaaa",
        "result",
        Some(view("T", json!([file_att(&bid, 5)]))),
    )
    .await;
    assert_eq!(s, 201);
    let (s, _) = send_view(
        &t,
        &a,
        "phones",
        "t_aaaaaa",
        "result",
        Some(view("T", json!([file_att(&bid, 5)]))),
    )
    .await;
    assert_eq!(s, 201);
    assert_eq!(phone_blob(&t, &mine, &bid).await, (200, b"chart".to_vec()));
    assert_eq!(phone_blob(&t, &other, &bid).await.0, 404, "another phone");
    // the admin takes A off this phone's list after the texts were sent: gone at once
    let (s, v) = t
        .admin_json(
            "PATCH",
            &format!("/admin/api/phones/{}", mine.0),
            Some(json!({"workspaces": [b.id]})),
        )
        .await;
    assert!(s < 300, "{s} {v}");
    assert_eq!(
        phone_blob(&t, &mine, &bid).await.0,
        404,
        "A is no longer on the list"
    );
}
