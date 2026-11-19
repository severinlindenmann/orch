//! Deleting a workspace leaves no row or file of it; the clean-up removes history of workspaces deleted earlier.
mod common;
use common::*;
use rusqlite::Connection;
use serde_json::{json, Value};

async fn upload(t: &T, w: &Ws, data: &[u8]) -> (String, String) {
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
    )
}

async fn share_problem(t: &T, w: &Ws, rf: &str) -> String {
    let data = b"pretend tar";
    let (b, sha) = upload(t, w, data).await;
    let body = json!({"ref": rf, "created_at": "2026-11-16T10:00:00Z", "scope": {"ticket": "t_abc123", "addon": null},
        "note": "n", "expected": "e", "more": "m", "problems": ["tickets-load"], "summary": "# S",
        "blob_id": b, "size": data.len(), "sha256": sha, "files": 1, "attachments": 0,
        "orch_version": "3.1.0", "os": "macOS 15"});
    let (s, v) = t.call(w, "POST", "/v1/problems", Some(body)).await;
    assert!(s == 200 || s == 201, "{s} {v}");
    b
}

fn raw_msg(c: &Connection, id: &str, from: &str, to: &str, typ: &str, blob: Option<&str>) {
    c.execute(
        "INSERT INTO messages(id,from_addr,to_addr,type,created_at,blob_id,digest,payload,stored_at)
         VALUES(?1,?2,?3,?4,'2026-11-04T10:00:00Z',?5,'d',x'00',strftime('%s','now'))",
        rusqlite::params![id, from, to, typ, blob],
    )
    .unwrap();
}

/// Every row of every table that names `id` in any text column (the payload is encrypted, so only addresses count).
fn rows_naming(c: &Connection, id: &str) -> Vec<String> {
    let tables: Vec<String> = c
        .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        .unwrap()
        .query_map([], |r| r.get(0))
        .unwrap()
        .map(|r| r.unwrap())
        .collect();
    let mut hits = vec![];
    for t in tables {
        let cols: Vec<String> = c
            .prepare(&format!("SELECT name FROM pragma_table_info('{t}')"))
            .unwrap()
            .query_map([], |r| r.get(0))
            .unwrap()
            .map(|r| r.unwrap())
            .collect();
        for col in cols {
            let n: i64 = c
                .query_row(
                    &format!("SELECT COUNT(*) FROM \"{t}\" WHERE typeof(\"{col}\")='text' AND instr(\"{col}\", ?1)>0"),
                    [id],
                    |r| r.get(0),
                )
                .unwrap();
            if n > 0 {
                hits.push(format!("{t}.{col}: {n}"));
            }
        }
    }
    hits
}

fn count(c: &Connection, sql: &str) -> i64 {
    c.query_row(sql, [], |r| r.get(0)).unwrap()
}

#[tokio::test]
async fn delete_workspace_leaves_no_row_or_file_of_it() {
    let t = start().await;
    let a = t.add_ws("Gone").await;
    let b = t.add_ws("Stays").await;
    t.rules(json!([
        rule(&a, &b, [true, true, false, false]),
        rule(&b, &a, [true, true, false, false])
    ]))
    .await;
    // Real traffic: texts both ways, a file each, a problem report from the one that goes.
    assert_eq!(
        t.send(&a, &b.id, "text", json!({"text": "hi"})).await.0,
        201
    );
    assert_eq!(
        t.send(&b, &a.id, "text", json!({"text": "hello"})).await.0,
        201
    );
    let (blob_a, _) = upload(&t, &a, b"file of A").await;
    let (blob_b_to_a, _) = upload(&t, &b, b"file B sent only to A").await;
    let (blob_b_own, _) = upload(&t, &b, b"file B keeps").await;
    let prob_blob = share_problem(&t, &a, "r-0102-1530-ticket").await;
    let (sub_status, sub) = t
        .admin_json(
            "POST",
            "/admin/api/subscribers",
            Some(json!({"name": "Bot", "workspaces": [a.id, b.id]})),
        )
        .await;
    assert_eq!(sub_status, 201, "{sub}");
    let sub_id = sub["subscriber"]["id"].as_str().map(str::to_string);
    let dir = t.app.cfg.data_dir.clone();
    std::fs::create_dir_all(dir.join("tts")).unwrap();
    {
        let c = t.app.db.lock().unwrap();
        raw_msg(&c, "m_a_file", &a.id, &b.id, "file", Some(&blob_a));
        raw_msg(&c, "m_b_file", &b.id, &a.id, "file", Some(&blob_b_to_a));
        raw_msg(&c, "m_b_keep", &b.id, "phones", "text", None);
        raw_msg(&c, "m_a_phone", &a.id, "phones", "text", None);
        raw_msg(&c, "m_phone_a", "ph_0123456789", &a.id, "answer", None);
        c.execute(
            "INSERT INTO view_blobs(blob_id,msg_id) VALUES(?1,'m_a_phone')",
            [&blob_a],
        )
        .unwrap();
        c.execute(
            "INSERT INTO phone_blobs(blob_id,msg_id) VALUES(?1,'m_b_keep')",
            [&blob_b_own],
        )
        .unwrap();
        c.execute("INSERT INTO phone_client_ids(phone,client_id,msg_id) VALUES('ph_0123456789','c1','m_phone_a')", []).unwrap();
        c.execute(
            "INSERT INTO question_taken_back(question_id,msg_id) VALUES('q1','m_a_phone')",
            [],
        )
        .unwrap();
        if let Some(s) = &sub_id {
            c.execute(
                "INSERT INTO sub_log(sub,at,what,event,result,ok) VALUES(?1,1,'file',NULL,?2,1)",
                rusqlite::params![s, blob_a],
            )
            .unwrap();
        }
    }
    std::fs::write(dir.join("tts").join("m_a_phone.en.mp3"), b"x").unwrap();
    std::fs::write(dir.join("tts").join("m_b_keep.en.mp3"), b"x").unwrap();

    // The count the admin page shows before the person confirms.
    let (s, v) = t
        .admin_json(
            "DELETE",
            &format!("/admin/api/workspaces/{}?dry_run=1", a.id),
            None,
        )
        .await;
    assert_eq!(s, 200, "{v}");
    assert_eq!(v["name"], "Gone");
    let pre = v["removes"].clone();
    assert!(pre["messages"].as_i64().unwrap() >= 5, "{pre}");
    assert!(pre["files"].as_i64().unwrap() >= 3, "{pre}");
    assert_eq!(pre["problems"], 1, "{pre}");
    // A dry run changes nothing.
    {
        let c = t.app.db.lock().unwrap();
        assert!(!rows_naming(&c, &a.id).is_empty());
    }
    assert!(dir.join("blobs").join(&blob_a).exists());

    let (s, _) = t
        .admin_json("DELETE", &format!("/admin/api/workspaces/{}", a.id), None)
        .await;
    assert_eq!(s, 204);
    let c = t.app.db.lock().unwrap();
    assert_eq!(rows_naming(&c, &a.id), Vec::<String>::new());
    for m in ["m_a_file", "m_b_file", "m_a_phone", "m_phone_a"] {
        assert!(rows_naming(&c, m).is_empty(), "{m} left");
    }
    for blob in [&blob_a, &blob_b_to_a, &prob_blob] {
        assert!(
            !dir.join("blobs").join(blob).exists(),
            "blob file {blob} left"
        );
        assert!(rows_naming(&c, blob).is_empty(), "blob row {blob} left");
    }
    assert!(!dir.join("tts").join("m_a_phone.en.mp3").exists());
    // What belongs to the other workspace stays.
    assert!(dir.join("blobs").join(&blob_b_own).exists());
    assert!(dir.join("tts").join("m_b_keep.en.mp3").exists());
    assert_eq!(
        count(&c, "SELECT COUNT(*) FROM messages WHERE id='m_b_keep'"),
        1
    );
    assert!(store_ws_exists(&c, &b.id));
    {
        let ws: String = c
            .query_row(
                "SELECT workspaces FROM subscribers WHERE id=?1",
                [sub_id.unwrap()],
                |r| r.get(0),
            )
            .unwrap();
        assert!(ws.contains(&b.id) && !ws.contains(&a.id), "{ws}");
    }
}

fn store_ws_exists(c: &Connection, id: &str) -> bool {
    count(
        c,
        &format!("SELECT COUNT(*) FROM workspaces WHERE id='{id}'"),
    ) == 1
}

#[tokio::test]
async fn cleanup_removes_history_of_deleted_workspaces_after_a_dry_run() {
    let t = start().await;
    let live = t.add_ws("Live").await;
    let dir = t.app.cfg.data_dir.clone();
    std::fs::create_dir_all(dir.join("blobs")).unwrap();
    let (live_blob, _) = upload(&t, &live, b"live file").await;
    // History left behind by an older delete (before this fix): rows of ws_gone0000 with no workspace row.
    {
        let c = t.app.db.lock().unwrap();
        c.execute(
            "INSERT INTO blobs(id,uploader,size,sha256,created_at) VALUES('b_orphan','ws_gone00000',3,'x',strftime('%s','now'))",
            [],
        )
        .unwrap();
        raw_msg(
            &c,
            "m_o1",
            "ws_gone00000",
            &live.id,
            "file",
            Some("b_orphan"),
        );
        raw_msg(&c, "m_o2", &live.id, "ws_gone00000", "text", None);
        raw_msg(&c, "m_o3", "ws_gone00000", "phones", "text", None);
        raw_msg(&c, "m_live", &live.id, "phones", "text", Some(&live_blob));
        raw_msg(&c, "m_hint", "relay", &live.id, "refresh-hint", None);
        c.execute(
            "INSERT INTO problems(id,ref,from_ws,from_name,created_at,shared_at,blob_id,files,attachments,size,sha256,data)
             VALUES('p_o','r','ws_gone00000','Gone','2026-11-01T00:00:00Z',strftime('%s','now'),'b_orphan',1,0,3,'x',x'00')",
            [],
        )
        .unwrap();
        c.execute(
            "INSERT INTO sub_log(sub,at,what,event,result,ok) VALUES('sub_nolonger',1,'push',NULL,'ok',1)",
            [],
        )
        .unwrap();
    }
    std::fs::write(dir.join("blobs").join("b_orphan"), b"old").unwrap();

    let (s, v) = t
        .admin_json("POST", "/admin/api/cleanup?dry_run=1", None)
        .await;
    assert_eq!(s, 200, "{v}");
    assert_eq!(v["dry_run"], true);
    assert_eq!(v["removes"]["messages"], 3, "{v}");
    assert_eq!(v["removes"]["files"], 1, "{v}");
    assert_eq!(v["removes"]["problems"], 1, "{v}");
    assert_eq!(v["removes"]["sub_log"], 1, "{v}");
    {
        let c = t.app.db.lock().unwrap();
        assert_eq!(
            count(&c, "SELECT COUNT(*) FROM messages WHERE id LIKE 'm_o%'"),
            3
        );
    }
    assert!(dir.join("blobs").join("b_orphan").exists());

    let (s, v) = t.admin_json("POST", "/admin/api/cleanup", None).await;
    assert_eq!(s, 200, "{v}");
    assert_eq!(v["removed"]["messages"], 3, "{v}");
    {
        let c = t.app.db.lock().unwrap();
        assert!(
            rows_naming(&c, "ws_gone00000").is_empty(),
            "{:?}",
            rows_naming(&c, "ws_gone00000")
        );
        assert!(rows_naming(&c, "b_orphan").is_empty());
        assert!(!dir.join("blobs").join("b_orphan").exists());
        assert_eq!(
            count(&c, "SELECT COUNT(*) FROM sub_log WHERE sub='sub_nolonger'"),
            0
        );
        // Live history stays, and so do system messages that are not from a workspace.
        assert_eq!(
            count(
                &c,
                "SELECT COUNT(*) FROM messages WHERE id IN ('m_live','m_hint')"
            ),
            2
        );
        assert!(dir.join("blobs").join(&live_blob).exists());
    }
    // A second run finds nothing.
    let (_, v) = t
        .admin_json("POST", "/admin/api/cleanup?dry_run=1", None)
        .await;
    assert_eq!(v["removes"]["messages"], 0, "{v}");
}

#[tokio::test]
async fn delete_and_cleanup_need_the_admin_token() {
    let t = start().await;
    let a = t.add_ws("A").await;
    for (m, p) in [
        (
            "DELETE",
            format!("/admin/api/workspaces/{}?dry_run=1", a.id),
        ),
        ("POST", "/admin/api/cleanup?dry_run=1".to_string()),
    ] {
        let r = t
            .http
            .request(
                reqwest::Method::from_bytes(m.as_bytes()).unwrap(),
                format!("{}{}", t.admin, p),
            )
            .send()
            .await
            .unwrap();
        assert_eq!(r.status(), 401, "{m} {p}");
    }
}
