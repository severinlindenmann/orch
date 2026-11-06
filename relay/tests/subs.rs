//! Subscribers (relay-api.md "Subscribers"): scope isolation, token hash, rotate/revoke, kinds, answer, files, SSE
//! resume, rate limits, push signing, retries and the address guard.
mod common;
use common::*;
use orch_relay::subs_push::{self, Deliver, Outcome};
use serde_json::{json, Value};
use std::sync::{Arc, Mutex};

struct Sub {
    id: String,
    token: String,
    secret: Option<String>,
}

async fn add_sub(t: &T, body: Value) -> Sub {
    let (s, v) = t
        .admin_json("POST", "/admin/api/subscribers", Some(body))
        .await;
    assert_eq!(s, 201, "{v}");
    let token = v["token"].as_str().unwrap().to_string();
    assert_eq!(v["link"], format!("https://relay.test/v1/sub/{token}"));
    Sub {
        id: v["subscriber"]["id"].as_str().unwrap().into(),
        token,
        secret: v["push_secret"].as_str().map(String::from),
    }
}

async fn get(t: &T, path: &str) -> (u16, Value) {
    let r = t
        .http
        .get(format!("{}{path}", t.base))
        .send()
        .await
        .unwrap();
    let s = r.status().as_u16();
    (s, r.json().await.unwrap_or(Value::Null))
}

async fn events(t: &T, s: &Sub, q: &str) -> (u16, Value) {
    get(t, &format!("/v1/sub/{}/events{q}", s.token)).await
}

async fn update(t: &T, w: &Ws, kind: &str, text: &str) -> String {
    let id = mid();
    let m = json!({"schema": "orch.msg/1", "id": id, "from": w.id, "to": "phones", "type": "text",
        "created_at": "2026-11-06T09:41:00Z", "ticket": "t_7k3f9q", "key": "DM1-12",
        "body": {"text": text, "update": {"kind": kind, "title": "March export"}}});
    let (s, v) = t.call(w, "POST", "/v1/messages", Some(m)).await;
    assert_eq!(s, 201, "{v}");
    id
}

async fn question(t: &T, w: &Ws) -> String {
    let id = mid();
    let m = json!({"schema": "orch.msg/1", "id": id, "from": w.id, "to": "phones", "type": "question",
        "created_at": "2026-11-06T09:41:00Z", "ticket": "t_7k3f9q", "key": "DM1-12",
        "body": {"question_id": "q1", "text": "Other or ask the bank?", "options": ["Other", "Ask the bank"]}});
    let (s, v) = t.call(w, "POST", "/v1/messages", Some(m)).await;
    assert_eq!(s, 201, "{v}");
    id
}

fn ids(v: &Value) -> Vec<String> {
    v["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|i| i["id"].as_str().unwrap().to_string())
        .collect()
}

fn schema() -> jsonschema::JSONSchema {
    let p = format!(
        "{}/../contracts/subscriber-event.schema.json",
        env!("CARGO_MANIFEST_DIR")
    );
    let s: Value = serde_json::from_str(&std::fs::read_to_string(p).unwrap()).unwrap();
    jsonschema::JSONSchema::compile(&s).unwrap()
}

#[tokio::test]
async fn scope_by_workspace_and_group_is_read_at_call_time() {
    let t = start().await;
    let (a, b, c) = (
        t.add_ws("A").await,
        t.add_ws("B").await,
        t.add_ws("C").await,
    );
    let (_, g) = t
        .admin_json(
            "POST",
            "/admin/api/groups",
            Some(json!({"name": "Finance"})),
        )
        .await;
    let gid = g["id"].as_str().unwrap();
    t.admin_json(
        "PATCH",
        &format!("/admin/api/workspaces/{}", b.id),
        Some(json!({"group": gid})),
    )
    .await;
    let s = add_sub(
        &t,
        json!({"name": "Bot", "workspaces": [a.id], "groups": [gid]}),
    )
    .await;
    let ea = update(&t, &a, "result", "a done").await;
    let eb = update(&t, &b, "result", "b done").await;
    let _ec = update(&t, &c, "result", "c done").await;
    // workspace-to-workspace and to one phone never show
    t.rules(json!([rule(&a, &c, [true, false, false, false])]))
        .await;
    let (st, _) = t
        .send(
            &a,
            &c.id,
            "text",
            json!({"text": "private between workspaces"}),
        )
        .await;
    assert_eq!(st, 201);
    let (st, v) = events(&t, &s, "").await;
    assert_eq!(st, 200, "{v}");
    assert_eq!(
        ids(&v),
        vec![ea.clone(), eb.clone()],
        "only A and the group member B, oldest first"
    );
    let sc = schema();
    for e in v["items"].as_array().unwrap() {
        assert!(sc.is_valid(e), "event matches the schema: {e}");
        assert_eq!(e["kind"], "result");
        assert_eq!(e["key"], "DM1-12");
    }
    // B leaves the group (group deleted): its events disappear at once, catch-up included
    t.admin_json("DELETE", &format!("/admin/api/groups/{gid}"), None)
        .await;
    assert_eq!(ids(&events(&t, &s, "").await.1), vec![ea]);
}

#[tokio::test]
async fn kinds_filter_and_history_before_creation_is_hidden() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let old = update(&t, &a, "result", "before the subscriber").await;
    // stored_at has a 1 s resolution: make the old one clearly older
    t.app
        .db
        .lock()
        .unwrap()
        .execute(
            "UPDATE messages SET stored_at=stored_at-10 WHERE id=?1",
            [&old],
        )
        .unwrap();
    let s = add_sub(&t, json!({"name": "Bot", "workspaces": [a.id]})).await;
    let _ack = update(&t, &a, "ack", "started").await;
    let res = update(&t, &a, "result", "done").await;
    let q = question(&t, &a).await;
    let (_, v) = events(&t, &s, "").await;
    assert_eq!(
        ids(&v),
        vec![res.clone(), q.clone()],
        "default kinds: results and questions"
    );
    let qe = &v["items"][1];
    assert_eq!(qe["type"], "question");
    assert_eq!(qe["question_id"], q);
    assert_eq!(qe["answerable"], false, "read-only by default");
    assert_eq!(qe["answered"], Value::Null);
    t.admin_json(
        "PATCH",
        &format!("/admin/api/subscribers/{}", s.id),
        Some(json!({"kinds": {"updates": true, "questions": false, "results": false}})),
    )
    .await;
    let (_, v) = events(&t, &s, "").await;
    assert_eq!(v["items"].as_array().unwrap().len(), 1);
    assert_eq!(v["items"][0]["kind"], "started");
}

#[tokio::test]
async fn paging_with_after_and_next() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let s = add_sub(&t, json!({"name": "Bot", "workspaces": [a.id]})).await;
    let mut all = vec![];
    for i in 0..5 {
        all.push(update(&t, &a, "result", &format!("r{i}")).await);
    }
    let (_, p1) = events(&t, &s, "?limit=2").await;
    assert_eq!(ids(&p1), all[..2]);
    let next = p1["next"].as_str().unwrap();
    let (_, p2) = events(&t, &s, &format!("?limit=2&after={next}")).await;
    assert_eq!(ids(&p2), all[2..4]);
    let (_, p3) = events(
        &t,
        &s,
        &format!("?limit=2&after={}", p2["next"].as_str().unwrap()),
    )
    .await;
    assert_eq!(ids(&p3), all[4..]);
    assert_eq!(p3["next"], Value::Null);
    assert_eq!(events(&t, &s, "?after=m_nosuchmessage000").await.0, 422);
}

#[tokio::test]
async fn token_is_stored_hashed_and_rotate_and_remove_stop_it() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let s = add_sub(&t, json!({"name": "Bot", "workspaces": [a.id]})).await;
    assert!(s.token.starts_with("sub_") && s.token.len() == 4 + 43);
    let stored: String = t
        .app
        .db
        .lock()
        .unwrap()
        .query_row(
            "SELECT token_hash FROM subscribers WHERE id=?1",
            [&s.id],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(stored, orch_relay::util::token_hash(&s.token));
    let (_, list) = t.admin_json("GET", "/admin/api/subscribers", None).await;
    assert!(
        !list.to_string().contains(&s.token),
        "the token is never listed"
    );
    // Bearer form with "-"
    let r = t
        .http
        .get(format!("{}/v1/sub/-/events", t.base))
        .bearer_auth(&s.token)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 200);
    assert_eq!(get(&t, "/v1/sub/-/events").await.0, 401);
    assert_eq!(get(&t, "/v1/sub/sub_wrong/events").await.0, 401);
    // rotate: old stops, new works
    let (st, v) = t
        .admin_json(
            "POST",
            &format!("/admin/api/subscribers/{}/token", s.id),
            None,
        )
        .await;
    assert_eq!(st, 200);
    let new = Sub {
        id: s.id.clone(),
        token: v["token"].as_str().unwrap().into(),
        secret: None,
    };
    assert_eq!(events(&t, &s, "").await.0, 401);
    assert_eq!(events(&t, &new, "").await.0, 200);
    // remove: gone
    let (st, _) = t
        .admin_json("DELETE", &format!("/admin/api/subscribers/{}", s.id), None)
        .await;
    assert_eq!(st, 204);
    assert_eq!(events(&t, &new, "").await.0, 401);
    // admin routes need the admin header
    let r = t
        .http
        .get(format!("{}/admin/api/subscribers", t.admin))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
}

#[tokio::test]
async fn admin_input_is_checked() {
    let t = start().await;
    let a = t.add_ws("A").await;
    for (body, want) in [
        (json!({"name": "Bot"}), 422),
        (json!({"name": "", "workspaces": [a.id]}), 422),
        (json!({"name": "Bot", "workspaces": ["ws_nosuchwork"]}), 422),
        (json!({"name": "Bot", "groups": ["grp_nosuchgrp"]}), 422),
        (
            json!({"name": "Bot", "workspaces": [a.id], "push_url": "http://hooks.example.com/x"}),
            422,
        ),
        (
            json!({"name": "Bot", "workspaces": [a.id], "push_url": "https://127.0.0.1/x"}),
            422,
        ),
        (
            json!({"name": "Bot", "workspaces": [a.id], "push_url": "https://10.0.0.8/x"}),
            422,
        ),
        (
            json!({"name": "Bot", "workspaces": [a.id], "push_url": "https://u:p@hooks.example.com/"}),
            422,
        ),
        (
            json!({"name": "Bot", "workspaces": [a.id], "kinds": {"files": "yes"}}),
            422,
        ),
        (
            json!({"name": "Bot", "workspaces": [a.id], "kinds": {"questions": false}, "can_answer": true}),
            422,
        ),
    ] {
        let (s, v) = t
            .admin_json("POST", "/admin/api/subscribers", Some(body.clone()))
            .await;
        assert_eq!(s, want, "{body} -> {v}");
    }
}

#[tokio::test]
async fn answer_only_when_allowed_first_answer_wins() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let ro = add_sub(&t, json!({"name": "Reader", "workspaces": [a.id]})).await;
    let rw = add_sub(
        &t,
        json!({"name": "Night monitor", "workspaces": [a.id], "can_answer": true}),
    )
    .await;
    let other = t.add_ws("Other").await;
    let q = question(&t, &a).await;
    let q_other = question(&t, &other).await;
    let ans = |s: &Sub, qid: &str, text: &str| {
        let (t, url, body) = (
            &t,
            format!("/v1/sub/{}/answer", s.token),
            json!({"question_id": qid, "answer": text}),
        );
        async move {
            let r = t
                .http
                .post(format!("{}{url}", t.base))
                .json(&body)
                .send()
                .await
                .unwrap();
            let s = r.status().as_u16();
            (s, r.json::<Value>().await.unwrap_or(Value::Null))
        }
    };
    let (s, v) = ans(&ro, &q, "Other").await;
    assert_eq!((s, v["error"].as_str()), (403, Some("not_allowed")));
    assert_eq!(
        ans(&rw, &q_other, "Other").await.0,
        404,
        "outside its scope"
    );
    assert_eq!(ans(&rw, &q, "").await.0, 422);
    let (s, v) = ans(&rw, &q, "Other").await;
    assert_eq!(s, 201, "{v}");
    assert_eq!(ans(&rw, &q, "Ask the bank").await.0, 409);
    // the workspace gets an answer from the subscriber, as that system
    let inbox = t.inbox(&a).await;
    let m = inbox.iter().find(|m| m["type"] == "answer").unwrap();
    assert_eq!(m["from"], rw.id);
    assert_eq!(m["reply_to"], q);
    assert_eq!(m["key"], "DM1-12");
    assert_eq!(m["body"]["question_id"], "q1");
    assert_eq!(m["body"]["answered_by"], "agent:Night monitor (system)");
    // a phone is too late now, and the readers see it answered
    let p = t.pair_phone(&[&a]).await;
    let (s, _) = t
        .phone(
            &p,
            "POST",
            "/v1/phone/answer",
            Some(json!({"question_message_id": q, "answer": "x"})),
        )
        .await;
    assert_eq!(s, 409);
    let (_, v) = events(&t, &ro, "").await;
    let qe = v["items"]
        .as_array()
        .unwrap()
        .iter()
        .find(|e| e["id"] == q)
        .unwrap()
        .clone();
    assert_eq!(
        qe["answered"],
        json!({"answer": "Other", "answered_by": "Night monitor (system)"})
    );
    let ae = v["items"]
        .as_array()
        .unwrap()
        .iter()
        .find(|e| e["type"] == "answered")
        .unwrap()
        .clone();
    assert_eq!(
        (ae["question_id"].clone(), ae["answer"].clone()),
        (json!(q), json!("Other"))
    );
    assert!(schema().is_valid(&ae));
    // turning Questions off while it may answer is refused; a row that has it anyway cannot answer
    let (st, _) = t
        .admin_json(
            "PATCH",
            &format!("/admin/api/subscribers/{}", rw.id),
            Some(json!({"kinds": {"questions": false}})),
        )
        .await;
    assert_eq!(st, 422);
    t.app
        .db
        .lock()
        .unwrap()
        .execute(
            "UPDATE subscribers SET kinds='{\"results\":true}' WHERE id=?1",
            [&rw.id],
        )
        .unwrap();
    let q2 = question(&t, &a).await;
    let (s, v) = ans(&rw, &q2, "Other").await;
    assert_eq!(
        (s, v["error"].as_str()),
        (403, Some("not_allowed")),
        "no Questions, no answers"
    );
}

#[tokio::test]
async fn files_metadata_only_unless_downloads_allowed() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let r = t
        .http
        .post(format!("{}/v1/blobs", t.base))
        .header("X-Orch-Workspace", &a.id)
        .header("Authorization", format!("Bearer {}", a.token))
        .body(vec![9u8; 5])
        .send()
        .await
        .unwrap();
    let bid = r.json::<Value>().await.unwrap()["blob_id"]
        .as_str()
        .unwrap()
        .to_string();
    let no_files = add_sub(&t, json!({"name": "A", "workspaces": [a.id]})).await;
    let meta = add_sub(
        &t,
        json!({"name": "B", "workspaces": [a.id], "kinds": {"files": true}}),
    )
    .await;
    let dl = add_sub(
        &t,
        json!({"name": "C", "workspaces": [a.id], "kinds": {"files": true}, "can_download": true}),
    )
    .await;
    let view = json!({"title": "T", "status": "done", "running": false, "checklist": [{"text": "x", "done": true}],
        "done": 1, "total": 1, "history_tail": [{"at": "2026-11-06T09:00:00Z", "who": "Claude", "role": "agent", "text": "secret-ish history"}],
        "attachments": [{"kind": "file", "title": "r.csv", "blob_id": bid, "name": "r.csv", "size": 5, "at": "2026-11-06T09:39:00Z"},
                        {"kind": "pr", "title": "PR 1", "url": "https://github.com/a/b/pull/1", "at": "2026-11-06T09:39:00Z"}]});
    let m = json!({"schema": "orch.msg/1", "id": mid(), "from": a.id, "to": "phones", "type": "text",
        "created_at": "2026-11-06T09:41:00Z", "ticket": "t_7k3f9q",
        "body": {"text": "done", "update": {"kind": "result"}, "ticket_view": view}});
    assert_eq!(t.call(&a, "POST", "/v1/messages", Some(m)).await.0, 201);
    let tv = |v: &Value| v["items"][0]["ticket_view"].clone();
    let v0 = tv(&events(&t, &no_files, "").await.1);
    assert_eq!(v0["files"], json!([]));
    assert_eq!(v0["links"][0]["url"], "https://github.com/a/b/pull/1");
    assert!(v0.get("history_tail").is_none() && v0.get("checklist").is_none());
    assert!(!v0.to_string().contains("secret-ish"));
    let v1 = tv(&events(&t, &meta, "").await.1);
    assert_eq!(
        v1["files"],
        json!([{"name": "r.csv", "size": 5, "blob_id": bid}])
    );
    assert_eq!(
        get(&t, &format!("/v1/sub/{}/files/{bid}", no_files.token))
            .await
            .0,
        404
    );
    assert_eq!(
        get(&t, &format!("/v1/sub/{}/files/{bid}", meta.token))
            .await
            .0,
        404,
        "metadata only"
    );
    let r = t
        .http
        .get(format!("{}/v1/sub/{}/files/{bid}", t.base, dl.token))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 200);
    assert_eq!(r.bytes().await.unwrap().to_vec(), vec![9u8; 5]);
    assert_eq!(
        get(&t, &format!("/v1/sub/{}/files/../../master.key", dl.token))
            .await
            .0,
        404
    );
}

#[tokio::test]
async fn rate_limit_60_a_minute() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let s = add_sub(&t, json!({"name": "Bot", "workspaces": [a.id]})).await;
    for _ in 0..60 {
        assert_eq!(events(&t, &s, "").await.0, 200);
    }
    let (st, v) = events(&t, &s, "").await;
    assert_eq!((st, v["error"].as_str()), (429, Some("rate_limited")));
}

/// Reads Server-Sent Events frames from a response.
struct SseReader {
    s: std::pin::Pin<
        Box<dyn futures_util::Stream<Item = reqwest::Result<axum::body::Bytes>> + Send>,
    >,
    buf: String,
}

impl SseReader {
    fn new(r: reqwest::Response) -> Self {
        SseReader {
            s: Box::pin(r.bytes_stream()),
            buf: String::new(),
        }
    }

    /// The next `n` events as (id, event, data).
    async fn take(&mut self, n: usize) -> Vec<(String, String, Value)> {
        use futures_util::StreamExt;
        let mut out = vec![];
        while out.len() < n {
            while let Some(i) = self.buf.find("\n\n") {
                let frame: String = self.buf.drain(..i + 2).collect();
                let (mut id, mut ev, mut data) = (String::new(), String::new(), String::new());
                for l in frame.lines() {
                    if let Some(x) = l.strip_prefix("id:") {
                        id = x.trim_start().to_string();
                    } else if let Some(x) = l.strip_prefix("event:") {
                        ev = x.trim_start().to_string();
                    } else if let Some(x) = l.strip_prefix("data:") {
                        data.push_str(x.trim_start());
                    }
                }
                if !id.is_empty() {
                    out.push((id, ev, serde_json::from_str(&data).unwrap()));
                }
            }
            if out.len() >= n {
                break;
            }
            let chunk = tokio::time::timeout(std::time::Duration::from_secs(5), self.s.next())
                .await
                .expect("an event within 5 s")
                .expect("the stream is open")
                .unwrap();
            self.buf.push_str(&String::from_utf8_lossy(&chunk));
        }
        out
    }

    /// True when the relay ends the stream within 5 s.
    async fn ends(&mut self) -> bool {
        use futures_util::StreamExt;
        tokio::time::timeout(std::time::Duration::from_secs(5), async {
            while let Some(x) = self.s.next().await {
                if x.is_err() {
                    break;
                }
            }
        })
        .await
        .is_ok()
    }
}

#[tokio::test]
async fn stream_live_and_resume_with_last_event_id_and_two_stream_cap() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let s = add_sub(
        &t,
        json!({"name": "Bot", "workspaces": [a.id], "kinds": {"updates": true}}),
    )
    .await;
    let first = update(&t, &a, "result", "one").await;
    let url = format!("{}/v1/sub/{}/stream", t.base, s.token);
    // without Last-Event-ID: only new events
    let r = t.http.get(&url).send().await.unwrap();
    assert_eq!(r.status(), 200);
    assert!(r.headers()["content-type"]
        .to_str()
        .unwrap()
        .starts_with("text/event-stream"));
    let mut live = SseReader::new(r);
    let second = update(&t, &a, "note", "two").await;
    let got = live.take(1).await;
    assert_eq!(
        (got[0].0.clone(), got[0].1.clone()),
        (second.clone(), "update".to_string())
    );
    assert_eq!(got[0].2["text"], "two");
    assert!(schema().is_valid(&got[0].2));
    // resume after the first (Bearer form): replays the second, then stays live
    let r = t
        .http
        .get(format!("{}/v1/sub/-/stream", t.base))
        .bearer_auth(&s.token)
        .header("Last-Event-ID", &first)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 200);
    let mut resumed = SseReader::new(r);
    // two are open: a third is refused
    let (st, v) = get(&t, &format!("/v1/sub/{}/stream", s.token)).await;
    assert_eq!((st, v["error"].as_str()), (429, Some("too_many_streams")));
    let (_, card) = t.admin_json("GET", "/admin/api/subscribers", None).await;
    assert_eq!(card["items"][0]["streams"], 2);
    let third = update(&t, &a, "result", "three").await;
    let got = resumed.take(2).await;
    assert_eq!(
        vec![got[0].0.clone(), got[1].0.clone()],
        vec![second, third.clone()]
    );
    assert_eq!(live.take(1).await[0].0, third);
    // an unknown Last-Event-ID is refused before the stream opens
    let r = t
        .http
        .get(&url)
        .header("Last-Event-ID", "m_nosuchmessage000")
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 422);
    // rotating the link closes the open streams
    t.admin_json(
        "POST",
        &format!("/admin/api/subscribers/{}/token", s.id),
        None,
    )
    .await;
    assert!(live.ends().await, "the stream ends after rotate");
    assert!(resumed.ends().await);
}

// ---------- push ----------

#[derive(Default)]
struct FakeReceiver {
    got: Mutex<Vec<(String, Vec<(String, String)>, Vec<u8>)>>,
    status: Mutex<u16>,
}

#[async_trait::async_trait]
impl Deliver for FakeReceiver {
    async fn post(
        &self,
        url: &str,
        headers: Vec<(&'static str, String)>,
        body: Vec<u8>,
    ) -> Outcome {
        self.got.lock().unwrap().push((
            url.to_string(),
            headers
                .into_iter()
                .map(|(k, v)| (k.to_string(), v))
                .collect(),
            body,
        ));
        Outcome {
            status: Some(*self.status.lock().unwrap()),
            detail: String::new(),
        }
    }
}

fn header<'a>(h: &'a [(String, String)], k: &str) -> &'a str {
    &h.iter().find(|(n, _)| n == k).unwrap().1
}

#[tokio::test]
async fn push_signs_retries_with_backoff_and_stops_after_the_last_retry() {
    let t = start().await;
    let recv = Arc::new(FakeReceiver::default());
    *recv.status.lock().unwrap() = 200;
    t.app.subs.set_deliver(recv.clone());
    let a = t.add_ws("A").await;
    let before = update(&t, &a, "result", "before push").await;
    let s = add_sub(
        &t,
        json!({"name": "Hook", "workspaces": [a.id], "push_url": "https://hooks.example.com/orch"}),
    )
    .await;
    let secret = s.secret.clone().unwrap();
    assert!(secret.starts_with("whsec_") && secret.len() == 6 + 43);
    let e1 = update(&t, &a, "result", "one").await;
    subs_push::tick(&t.app).await;
    {
        let got = recv.got.lock().unwrap();
        assert_eq!(got.len(), 1, "only events after push was turned on");
        let (url, h, body) = &got[0];
        assert_eq!(url, "https://hooks.example.com/orch");
        assert_eq!(header(h, "x-orch-event-id"), e1);
        let ts: i64 = header(h, "x-orch-timestamp").parse().unwrap();
        assert_eq!(
            header(h, "x-orch-signature"),
            subs_push::sign(&secret, ts, body)
        );
        let v: Value = serde_json::from_slice(body).unwrap();
        assert_eq!(v["id"], e1);
        assert_ne!(v["id"], before);
    }
    // failures: retry after 1 min, 5 min, 30 min, 2 h, 6 h, then failing
    *recv.status.lock().unwrap() = 502;
    let e2 = update(&t, &a, "result", "two").await;
    let state =
        |t: &T| {
            t.app
            .db
            .lock()
            .unwrap()
            .query_row(
                "SELECT push_state,push_fails,push_next_at-strftime('%s','now') FROM subscribers",
                [],
                |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?, r.get::<_, Option<i64>>(2)?)),
            )
            .unwrap()
        };
    for (i, wait) in subs_push::BACKOFF.iter().enumerate() {
        subs_push::tick(&t.app).await;
        let (st, fails, next) = state(&t);
        assert_eq!((st.as_str(), fails), ("retrying", i as i64 + 1));
        assert!(
            (next.unwrap() - wait).abs() <= 2,
            "wait {wait}, got {next:?}"
        );
        // not due yet: nothing is sent
        let n = recv.got.lock().unwrap().len();
        subs_push::tick(&t.app).await;
        assert_eq!(recv.got.lock().unwrap().len(), n);
        t.app
            .db
            .lock()
            .unwrap()
            .execute("UPDATE subscribers SET push_next_at=0", [])
            .unwrap();
    }
    subs_push::tick(&t.app).await;
    assert_eq!(state(&t).0, "failing");
    let n = recv.got.lock().unwrap().len();
    assert_eq!(n, 1 + 6, "1 ok + the first try and 5 retries");
    subs_push::tick(&t.app).await;
    assert_eq!(recv.got.lock().unwrap().len(), n, "failing: no more tries");
    // the log shows it; pull still works
    let (_, log) = t
        .admin_json(
            "GET",
            &format!("/admin/api/subscribers/{}/log?failed=1", s.id),
            None,
        )
        .await;
    assert!(
        log["items"][0]["result"]
            .as_str()
            .unwrap()
            .contains("stopped"),
        "{log}"
    );
    assert_eq!(log["items"][0]["event"], "DM1-12 result");
    assert!(ids(&events(&t, &s, "").await.1).contains(&e2));
    // Try again now: delivered, back to ok
    *recv.status.lock().unwrap() = 204;
    let (st, v) = t
        .admin_json(
            "POST",
            &format!("/admin/api/subscribers/{}/push/retry", s.id),
            None,
        )
        .await;
    assert_eq!((st, v["push"]["state"].as_str()), (200, Some("ok")));
    subs_push::tick(&t.app).await;
    let got = recv.got.lock().unwrap();
    assert_eq!(header(&got.last().unwrap().1, "x-orch-event-id"), e2);
    drop(got);
    let (_, list) = t.admin_json("GET", "/admin/api/subscribers", None).await;
    assert_eq!(list["items"][0]["push"]["state"], "ok");
    assert!(list["items"][0]["push"]["last_ok_at"].is_string());
}

#[tokio::test]
async fn push_test_event_and_turning_push_on_later() {
    let t = start().await;
    let recv = Arc::new(FakeReceiver::default());
    *recv.status.lock().unwrap() = 200;
    t.app.subs.set_deliver(recv.clone());
    let a = t.add_ws("A").await;
    let s = add_sub(&t, json!({"name": "Hook", "workspaces": [a.id]})).await;
    assert!(s.secret.is_none());
    let (st, _) = t
        .admin_json(
            "POST",
            &format!("/admin/api/subscribers/{}/push/test", s.id),
            None,
        )
        .await;
    assert_eq!(st, 422, "push is off");
    let _old = update(&t, &a, "result", "before").await;
    let (st, v) = t
        .admin_json(
            "PATCH",
            &format!("/admin/api/subscribers/{}", s.id),
            Some(json!({"push_url": "https://hooks.example.com/a"})),
        )
        .await;
    assert_eq!(st, 200, "{v}");
    let secret = v["push_secret"].as_str().unwrap().to_string();
    let (st, v) = t
        .admin_json(
            "POST",
            &format!("/admin/api/subscribers/{}/push/test", s.id),
            None,
        )
        .await;
    assert_eq!(
        (st, v["ok"].as_bool(), v["status"].as_u64()),
        (200, Some(true), Some(200))
    );
    {
        let got = recv.got.lock().unwrap();
        let (_, h, body) = got.last().unwrap();
        let ev: Value = serde_json::from_slice(body).unwrap();
        assert_eq!(ev["type"], "test");
        assert!(schema().is_valid(&ev));
        let ts: i64 = header(h, "x-orch-timestamp").parse().unwrap();
        assert_eq!(
            header(h, "x-orch-signature"),
            subs_push::sign(&secret, ts, body)
        );
    }
    subs_push::tick(&t.app).await;
    assert_eq!(
        recv.got.lock().unwrap().len(),
        1,
        "older events are not pushed"
    );
    // same URL again: the secret stays (no new one shown)
    let (_, v) = t
        .admin_json(
            "PATCH",
            &format!("/admin/api/subscribers/{}", s.id),
            Some(json!({"push_url": "https://hooks.example.com/a"})),
        )
        .await;
    assert_eq!(v["push_secret"], Value::Null);
    // off: nothing more is pushed
    t.admin_json(
        "PATCH",
        &format!("/admin/api/subscribers/{}", s.id),
        Some(json!({"push_url": null})),
    )
    .await;
    update(&t, &a, "result", "after off").await;
    subs_push::tick(&t.app).await;
    assert_eq!(recv.got.lock().unwrap().len(), 1);
}

#[test]
fn signature_vectors_match_the_contract() {
    let p = format!(
        "{}/../contracts/vectors/subscriber-v1.json",
        env!("CARGO_MANIFEST_DIR")
    );
    let v: Value = serde_json::from_str(&std::fs::read_to_string(p).unwrap()).unwrap();
    let sc = schema();
    for e in v["valid_events"].as_array().unwrap() {
        assert!(sc.is_valid(e), "{e}");
    }
    for c in v["invalid_events"].as_array().unwrap() {
        assert!(!sc.is_valid(&c["event"]), "{}", c["name"]);
    }
    for c in v["signatures"].as_array().unwrap() {
        let got = subs_push::sign(
            c["secret"].as_str().unwrap(),
            c["timestamp"].as_i64().unwrap(),
            c["body"].as_str().unwrap().as_bytes(),
        );
        assert_eq!(got, c["signature"].as_str().unwrap(), "{}", c["name"]);
    }
}
