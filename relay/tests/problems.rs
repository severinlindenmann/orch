mod common;
use common::*;
use serde_json::{json, Value};

const TAR: &[u8] = b"pretend this is a plain tar archive of a problem report";

async fn upload(t: &T, w: &Ws, data: &[u8]) -> (String, String, usize) {
    let r = t
        .http
        .post(format!("{}/v1/blobs", t.base))
        .header("X-Orch-Workspace", &w.id)
        .header("Authorization", format!("Bearer {}", w.token))
        .body(data.to_vec())
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 201);
    let v: Value = r.json().await.unwrap();
    (
        v["blob_id"].as_str().unwrap().into(),
        v["sha256"].as_str().unwrap().into(),
        data.len(),
    )
}

fn body(rf: &str, blob: &(String, String, usize)) -> Value {
    json!({"ref": rf, "created_at": "2026-11-16T10:00:00Z", "scope": {"ticket": "t_abc123", "addon": null},
        "note": "The page stayed empty", "expected": "A list", "more": "Happened twice",
        "problems": ["tickets-load", "relay-link"], "summary": "# Summary\nthings broke <b>bold</b>",
        "blob_id": blob.0, "size": blob.2, "sha256": blob.1, "files": 7, "attachments": 1,
        "orch_version": "3.1.0", "os": "macOS 15"})
}

async fn share(t: &T, w: &Ws, rf: &str) -> (u16, Value) {
    let b = upload(t, w, TAR).await;
    t.call(w, "POST", "/v1/problems", Some(body(rf, &b))).await
}

async fn readers(t: &T, ws: &[&Ws]) {
    let ids: Vec<&str> = ws.iter().map(|w| w.id.as_str()).collect();
    let (s, v) = t
        .admin_json(
            "PUT",
            "/admin/api/problems/readers",
            Some(json!({"workspaces": ids})),
        )
        .await;
    assert_eq!(s, 200, "{v}");
}

async fn raw_get(t: &T, w: &Ws, path: &str) -> (u16, Vec<u8>) {
    let r = t
        .http
        .get(format!("{}{}", t.base, path))
        .header("X-Orch-Workspace", &w.id)
        .header("Authorization", format!("Bearer {}", w.token))
        .send()
        .await
        .unwrap();
    (r.status().as_u16(), r.bytes().await.unwrap().to_vec())
}

#[tokio::test]
async fn share_is_idempotent_and_listed_for_readers_only() {
    let t = start().await;
    let (a, b, c) = (
        t.add_ws("A").await,
        t.add_ws("B").await,
        t.add_ws("C").await,
    );
    let (s, v) = share(&t, &a, "r-1116-1000-dash").await;
    assert_eq!(s, 201, "{v}");
    let id = v["id"].as_str().unwrap().to_string();
    assert!(id.starts_with("pb_") && id.len() == 19);
    // the same ref again: 200 and the same id, nothing new stored
    let (s, v) = share(&t, &a, "r-1116-1000-dash").await;
    assert_eq!((s, v["id"].as_str().unwrap()), (200, id.as_str()));
    let (_, l) = t.admin_json("GET", "/admin/api/problems", None).await;
    assert_eq!(l["items"].as_array().unwrap().len(), 1);
    // not a reader: 403 on all four routes, also the sharer
    for (m, p) in [
        ("GET", "/v1/problems".to_string()),
        ("GET", format!("/v1/problems/{id}")),
        ("GET", format!("/v1/problems/{id}/file")),
        ("POST", format!("/v1/problems/{id}/status")),
    ] {
        let (s, v) = t.call(&b, m, &p, Some(json!({"status": "taken"}))).await;
        assert_eq!(s, 403, "{m} {p}");
        assert_eq!(v["error"], "forbidden");
    }
    readers(&t, &[&b, &c]).await;
    let (s, l) = t.call(&b, "GET", "/v1/problems", None).await;
    assert_eq!(s, 200);
    assert_eq!(l["next"], Value::Null);
    let p = &l["items"][0];
    assert_eq!(p["id"], id.as_str());
    assert_eq!(p["from"], a.id.as_str());
    assert_eq!(p["from_name"], "A");
    assert_eq!(p["status"], "new");
    assert_eq!(p["taken_by"], Value::Null);
    assert_eq!(p["note"], "The page stayed empty");
    assert_eq!(p["scope"]["ticket"], "t_abc123");
    assert_eq!(p["problems"], json!(["tickets-load", "relay-link"]));
    assert_eq!(
        (p["files"].clone(), p["attachments"].clone()),
        (json!(7), json!(1))
    );
    assert!(p.get("summary").is_none());
    let (s, one) = t.call(&b, "GET", &format!("/v1/problems/{id}"), None).await;
    assert_eq!(s, 200);
    assert_eq!(one["summary"], "# Summary\nthings broke <b>bold</b>");
    let (s, bytes) = raw_get(&t, &b, &format!("/v1/problems/{id}/file")).await;
    assert_eq!((s, bytes.as_slice()), (200, TAR));
    let (s, v) = t.call(&b, "GET", "/v1/problems/pb_nothere", None).await;
    assert_eq!((s, v["error"].as_str().unwrap()), (404, "not_found"));
    let (s, _) = t.call(&b, "GET", "/v1/problems?status=bogus", None).await;
    assert_eq!(s, 422);
    let (_, l) = t.call(&b, "GET", "/v1/problems?status=done", None).await;
    assert!(l["items"].as_array().unwrap().is_empty());
    // the stored text is sealed, not plain
    let raw: Vec<u8> = t
        .app
        .db
        .lock()
        .unwrap()
        .query_row("SELECT data FROM problems", [], |r| r.get(0))
        .unwrap();
    assert!(!String::from_utf8_lossy(&raw).contains("stayed empty"));
}

#[tokio::test]
async fn share_checks_blob_size_hash_and_limit() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    // a blob of another workspace, or none: 404
    let theirs = upload(&t, &b, TAR).await;
    let (s, _) = t
        .call(
            &a,
            "POST",
            "/v1/problems",
            Some(body("r-1116-1000-x", &theirs)),
        )
        .await;
    assert_eq!(s, 404);
    let mut missing = theirs.clone();
    missing.0 = "b_doesnotexist0000".into();
    let (s, _) = t
        .call(
            &a,
            "POST",
            "/v1/problems",
            Some(body("r-1116-1000-x", &missing)),
        )
        .await;
    assert_eq!(s, 404);
    // wrong size / hash: 422
    let mine = upload(&t, &a, TAR).await;
    let mut bad = body("r-1116-1000-x", &mine);
    bad["size"] = json!(mine.2 + 1);
    assert_eq!(t.call(&a, "POST", "/v1/problems", Some(bad)).await.0, 422);
    let mut bad = body("r-1116-1000-x", &mine);
    bad["sha256"] = json!("0".repeat(64));
    assert_eq!(t.call(&a, "POST", "/v1/problems", Some(bad)).await.0, 422);
    // bad fields: 422
    for edit in [
        json!({"ref": "i-1116-1000-x"}),
        json!({"ref": "r-1116-1000-../x"}),
        json!({"note": "x".repeat(601)}),
        json!({"summary": ""}),
        json!({"files": 0}),
        json!({"attachments": 11}),
        json!({"problems": vec!["c"; 21]}),
    ] {
        let mut v = body("r-1116-1000-x", &mine);
        for (k, x) in edit.as_object().unwrap() {
            v[k] = x.clone();
        }
        assert_eq!(
            t.call(&a, "POST", "/v1/problems", Some(v)).await.0,
            422,
            "{edit}"
        );
    }
    // nothing was stored by the failures, and 20 a day are allowed, the 21st is not
    for i in 0..20 {
        let (s, v) = share(&t, &a, &format!("r-1116-10{i:02}-x")).await;
        assert_eq!(s, 201, "{i} {v}");
    }
    let (s, v) = share(&t, &a, "r-1116-1099-x").await;
    assert_eq!((s, v["error"].as_str().unwrap()), (429, "rate_limited"));
    // another workspace is not limited, and a retry of a stored ref still answers 200
    assert_eq!(share(&t, &b, "r-1116-1000-x").await.0, 201);
    assert_eq!(share(&t, &a, "r-1116-1000-x").await.0, 200);
}

#[tokio::test]
async fn problem_blob_is_not_readable_by_readers_through_blobs() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    readers(&t, &[&b]).await;
    let bl = upload(&t, &a, TAR).await;
    let (s, _) = t
        .call(&a, "POST", "/v1/problems", Some(body("r-1116-1000-x", &bl)))
        .await;
    assert_eq!(s, 201);
    assert_eq!(raw_get(&t, &b, &format!("/v1/blobs/{}", bl.0)).await.0, 404);
    assert_eq!(raw_get(&t, &a, &format!("/v1/blobs/{}", bl.0)).await.0, 200);
}

#[tokio::test]
async fn take_done_and_give_back_rules() {
    let t = start().await;
    let (a, b, c) = (
        t.add_ws("A").await,
        t.add_ws("B").await,
        t.add_ws("C").await,
    );
    readers(&t, &[&b, &c]).await;
    let id = share(&t, &a, "r-1116-1000-x").await.1["id"]
        .as_str()
        .unwrap()
        .to_string();
    let st = |w: &Ws, s: &'static str| {
        let (t, id) = (&t, id.clone());
        let w = Ws {
            id: w.id.clone(),
            token: w.token.clone(),
        };
        async move {
            t.call(
                &w,
                "POST",
                &format!("/v1/problems/{id}/status"),
                Some(json!({"status": s})),
            )
            .await
        }
    };
    // done or new before it is taken: 409
    assert_eq!(st(&b, "done").await.0, 409);
    assert_eq!(st(&b, "new").await.0, 409);
    assert_eq!(st(&b, "bogus").await.0, 422);
    let (s, v) = st(&b, "taken").await;
    assert_eq!(
        (s, v["status"].clone(), v["taken_by"].clone()),
        (200, json!("taken"), json!(b.id))
    );
    assert_eq!(v["taken_by_name"], "B");
    // taking again by the holder is fine; another reader: 409 on every change
    assert_eq!(st(&b, "taken").await.0, 200);
    let (s, v) = st(&c, "taken").await;
    assert_eq!((s, v["error"].as_str().unwrap()), (409, "conflict"));
    assert_eq!(v["message"], "Another workspace already took this problem.");
    assert_eq!(st(&c, "done").await.0, 409);
    assert_eq!(st(&c, "new").await.0, 409);
    // lists by state
    let (_, l) = t.call(&c, "GET", "/v1/problems", None).await;
    assert!(l["items"].as_array().unwrap().is_empty());
    let (_, l) = t.call(&c, "GET", "/v1/problems?status=taken", None).await;
    assert_eq!(l["items"].as_array().unwrap().len(), 1);
    // done by the holder; give back clears the holder
    assert_eq!(st(&b, "done").await.1["status"], "done");
    let (_, l) = t.call(&c, "GET", "/v1/problems?status=all", None).await;
    assert_eq!(l["items"][0]["status"], "done");
    let (s, v) = st(&b, "new").await;
    assert_eq!(
        (s, v["status"].clone(), v["taken_by"].clone()),
        (200, json!("new"), Value::Null)
    );
    assert_eq!(st(&c, "taken").await.0, 200);
}

#[tokio::test]
async fn admin_readers_patch_delete() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    let (s, v) = t
        .admin_json(
            "PUT",
            "/admin/api/problems/readers",
            Some(json!({"workspaces": ["ws_nope"]})),
        )
        .await;
    assert_eq!((s, v["error"].as_str().unwrap()), (422, "invalid"));
    let ver0 = orch_relay::store::version(&t.app.db.lock().unwrap());
    readers(&t, &[&b]).await;
    let ver1 = orch_relay::store::version(&t.app.db.lock().unwrap());
    assert_eq!(ver0, ver1);
    let (_, l) = t.admin_json("GET", "/admin/api/problems", None).await;
    assert_eq!(l["readers"], json!([b.id]));
    let bl = upload(&t, &a, TAR).await;
    let id = t
        .call(&a, "POST", "/v1/problems", Some(body("r-1116-1000-x", &bl)))
        .await
        .1["id"]
        .as_str()
        .unwrap()
        .to_string();
    let p = format!("/admin/api/problems/{id}");
    let (s, v) = t.admin_json("GET", &p, None).await;
    assert_eq!((s, v["summary"].as_str().is_some()), (200, true));
    // the archive downloads under <ref>.tar
    let r = t
        .http
        .get(format!("{}{}/file", t.admin, p))
        .header("X-Orch-Admin", ADMIN)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 200);
    assert_eq!(
        r.headers()["content-disposition"],
        "attachment; filename=\"r-1116-1000-x.tar\""
    );
    assert_eq!(r.headers()["x-content-type-options"], "nosniff");
    assert_eq!(r.bytes().await.unwrap().as_ref(), TAR);
    // any state; taken by the admin has no holder
    let (s, v) = t
        .admin_json("PATCH", &p, Some(json!({"status": "taken"})))
        .await;
    assert_eq!(
        (s, v["status"].clone(), v["taken_by"].clone()),
        (200, json!("taken"), Value::Null)
    );
    assert_eq!(
        t.admin_json("PATCH", &p, Some(json!({"status": "done"})))
            .await
            .1["status"],
        "done"
    );
    assert_eq!(
        t.admin_json("PATCH", &p, Some(json!({"status": "x"})))
            .await
            .0,
        422
    );
    // a reader took it: admin new clears the holder
    t.admin_json("PATCH", &p, Some(json!({"status": "new"})))
        .await;
    t.call(
        &b,
        "POST",
        &format!("/v1/problems/{id}/status"),
        Some(json!({"status": "taken"})),
    )
    .await;
    let (_, v) = t
        .admin_json("PATCH", &p, Some(json!({"status": "new"})))
        .await;
    assert_eq!(v["taken_by"], Value::Null);
    // deleting a workspace keeps its problems and drops it from readers
    t.call(
        &b,
        "POST",
        &format!("/v1/problems/{id}/status"),
        Some(json!({"status": "taken"})),
    )
    .await;
    assert_eq!(
        t.admin_json("DELETE", &format!("/admin/api/workspaces/{}", b.id), None)
            .await
            .0,
        204
    );
    assert_eq!(
        t.admin_json("DELETE", &format!("/admin/api/workspaces/{}", a.id), None)
            .await
            .0,
        204
    );
    let (_, l) = t.admin_json("GET", "/admin/api/problems", None).await;
    assert_eq!(l["readers"], json!([]));
    assert_eq!(l["items"][0]["from_name"], "A");
    assert_eq!(l["items"][0]["taken_by_name"], "B");
    // delete removes the row and the blob file
    let file = t.app.blob_path(&bl.0);
    assert!(file.exists());
    assert_eq!(t.admin_json("DELETE", &p, None).await.0, 204);
    assert!(!file.exists());
    assert_eq!(t.admin_json("GET", &p, None).await.0, 404);
    assert_eq!(t.admin_json("DELETE", &p, None).await.0, 404);
    assert_eq!(
        t.admin_json("PATCH", &p, Some(json!({"status": "new"})))
            .await
            .0,
        404
    );
    // admin routes need the admin token
    let r = t
        .http
        .get(format!("{}/admin/api/problems", t.admin))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
}

#[tokio::test]
async fn phone_and_subscriber_tokens_do_not_work() {
    let t = start().await;
    let a = t.add_ws("A").await;
    readers(&t, &[&a]).await;
    let ph = t.pair_phone(&[&a]).await;
    let (s, _) = t.phone(&ph, "GET", "/v1/problems", None).await;
    assert_eq!(s, 401);
    let (s, v) = t
        .admin_json(
            "POST",
            "/admin/api/subscribers",
            Some(json!({"name": "S", "workspaces": [a.id]})),
        )
        .await;
    assert_eq!(s, 201, "{v}");
    let tok = v["token"].as_str().unwrap();
    for (m, p) in [("GET", "/v1/problems"), ("POST", "/v1/problems")] {
        let r = t
            .http
            .request(m.parse().unwrap(), format!("{}{p}", t.base))
            .header("Authorization", format!("Bearer {tok}"))
            .header("X-Orch-Workspace", &a.id)
            .json(&json!({}))
            .send()
            .await
            .unwrap();
        assert_eq!(r.status(), 401, "{m} {p}");
    }
    assert_eq!(
        t.http
            .get(format!("{}/v1/problems", t.base))
            .send()
            .await
            .unwrap()
            .status(),
        401
    );
}

#[tokio::test]
async fn purge_after_90_days_removes_row_and_blob() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let old = upload(&t, &a, TAR).await;
    let fresh = upload(&t, &a, b"another report").await;
    let id_old = t
        .call(
            &a,
            "POST",
            "/v1/problems",
            Some(body("r-1116-1000-old", &old)),
        )
        .await
        .1["id"]
        .as_str()
        .unwrap()
        .to_string();
    let id_new = t
        .call(
            &a,
            "POST",
            "/v1/problems",
            Some(body("r-1116-1001-new", &fresh)),
        )
        .await
        .1["id"]
        .as_str()
        .unwrap()
        .to_string();
    let day = 86400;
    {
        let c = t.app.db.lock().unwrap();
        // the first problem is 91 days old; the second one was uploaded 91 days ago but shared just now
        c.execute(
            "UPDATE problems SET shared_at=?2 WHERE id=?1",
            rusqlite::params![id_old, orch_relay::util::now() - 91 * day],
        )
        .unwrap();
        c.execute(
            "UPDATE blobs SET created_at=?2 WHERE id=?1",
            rusqlite::params![old.0, orch_relay::util::now() - 91 * day],
        )
        .unwrap();
        c.execute(
            "UPDATE blobs SET created_at=?2 WHERE id=?1",
            rusqlite::params![fresh.0, orch_relay::util::now() - 91 * day],
        )
        .unwrap();
        orch_relay::store::purge(&c, t.dir.path(), orch_relay::util::now()).unwrap();
    }
    let (_, l) = t.admin_json("GET", "/admin/api/problems", None).await;
    let ids: Vec<&str> = l["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| p["id"].as_str().unwrap())
        .collect();
    assert_eq!(ids, vec![id_new.as_str()]);
    assert!(!t.app.blob_path(&old.0).exists());
    assert!(t.app.blob_path(&fresh.0).exists());
    let n: i64 = t
        .app
        .db
        .lock()
        .unwrap()
        .query_row("SELECT COUNT(*) FROM blobs WHERE id=?1", [&old.0], |r| {
            r.get(0)
        })
        .unwrap();
    assert_eq!(n, 0);
}
