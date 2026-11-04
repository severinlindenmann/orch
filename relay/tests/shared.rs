mod common;
use base64::Engine;
use common::*;
use serde_json::json;

fn skill_tar(prefix: &str, text: &str) -> Vec<u8> {
    let mut tar = tar::Builder::new(Vec::new());
    let mut h = tar::Header::new_gnu();
    h.set_size(text.len() as u64);
    h.set_mode(0o644);
    h.set_cksum();
    tar.append_data(&mut h, format!("{prefix}SKILL.md"), text.as_bytes())
        .unwrap();
    let raw = tar.into_inner().unwrap();
    let mut gz = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::fast());
    std::io::Write::write_all(&mut gz, &raw).unwrap();
    gz.finish().unwrap()
}

#[tokio::test]
async fn shared_assign_refresh_snapshot_and_hint() {
    let t = start().await;
    let (a, b) = (t.add_ws("Pilatus").await, t.add_ws("Home").await);
    t.rules(json!([rule(&a, &b, [true, false, false, false])]))
        .await;
    let r = t
        .http
        .put(format!("{}/admin/api/shared/skills/acme-sql", t.admin))
        .header("X-Orch-Admin", ADMIN)
        .body(skill_tar("acme-sql/", "---\nname: acme-sql\n---\n"))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 200);
    let v: serde_json::Value = r.json().await.unwrap();
    assert_eq!(v, json!({"name": "acme-sql", "version": 1}));
    assert_eq!(
        t.admin_json(
            "PUT",
            "/admin/api/shared/mcp/acme-docs",
            Some(json!({"config": {"command": "npx"}}))
        )
        .await
        .0,
        200
    );
    assert_eq!(
        t.admin_json(
            "PUT",
            "/admin/api/shared/credentials/ACME_TOKEN",
            Some(json!({"value": "s3cret"}))
        )
        .await
        .0,
        200
    );
    // not assigned yet: nothing for Home, no hint
    let (_, snap) = t.call(&b, "GET", "/v1/refresh", None).await;
    assert_eq!(snap["skills"], json!([]));
    assert!(t.inbox(&b).await.is_empty());

    let (s, _) = t.admin_json("PUT", &format!("/admin/api/shared/assign/{}", b.id),
        Some(json!({"skills": ["acme-sql"], "mcp": ["acme-docs"], "credentials": ["ACME_TOKEN"]}))).await;
    assert_eq!(s, 200);
    let hint = t.inbox(&b).await;
    assert_eq!(hint.len(), 1);
    assert_eq!(hint[0]["type"], "refresh-hint");
    let (_, snap) = t.call(&b, "GET", "/v1/refresh", None).await;
    assert_eq!(snap["version"], hint[0]["body"]["version"]);
    assert_eq!(snap["skills"][0]["name"], "acme-sql");
    let f = snap["skills"][0]["files"]["SKILL.md"].as_str().unwrap();
    assert!(
        String::from_utf8(base64::engine::general_purpose::STANDARD.decode(f).unwrap())
            .unwrap()
            .contains("acme-sql")
    );
    assert_eq!(snap["mcp"]["acme-docs"]["command"], "npx");
    assert_eq!(snap["credentials"]["ACME_TOKEN"], "s3cret");
    // directory: Home sees Pilatus (rule Pilatus -> Home)
    let d = &snap["workspaces"];
    assert_eq!(d["schema"], "orch.workspaces/1");
    assert_eq!(d["self"], b.id.as_str());
    assert_eq!(d["workspaces"][0]["id"], a.id.as_str());
    assert_eq!(d["workspaces"][0]["can_send"]["text"], false);
    assert_eq!(d["workspaces"][0]["accepts_from"]["text"], true);
    // admin overview never shows credential values
    let (_, ov) = t.admin_json("GET", "/admin/api/shared", None).await;
    assert_eq!(ov["credentials"], json!(["ACME_TOKEN"]));
    assert!(!ov.to_string().contains("s3cret"));
    // unassigned items disappear from the snapshot; new skill version bumps
    t.admin_json(
        "PUT",
        &format!("/admin/api/shared/assign/{}", b.id),
        Some(json!({"skills": [], "mcp": [], "credentials": []})),
    )
    .await;
    let (_, snap) = t.call(&b, "GET", "/v1/refresh", None).await;
    assert_eq!(
        (snap["skills"].clone(), snap["mcp"].clone()),
        (json!([]), json!({}))
    );
}

#[tokio::test]
async fn shared_skill_version_and_bad_archives() {
    let t = start().await;
    for expect in [1, 2] {
        let r = t
            .http
            .put(format!("{}/admin/api/shared/skills/s", t.admin))
            .header("X-Orch-Admin", ADMIN)
            .body(skill_tar("", "x"))
            .send()
            .await
            .unwrap();
        assert_eq!(
            r.json::<serde_json::Value>().await.unwrap()["version"],
            expect
        );
    }
    let r = t
        .http
        .put(format!("{}/admin/api/shared/skills/s", t.admin))
        .header("X-Orch-Admin", ADMIN)
        .body("not a tar")
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 422);
    // no SKILL.md
    let r = t
        .http
        .put(format!("{}/admin/api/shared/skills/s", t.admin))
        .header("X-Orch-Admin", ADMIN)
        .body(skill_tar("a/b/", "x"))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 422);
}

#[tokio::test]
async fn shared_workspace_edit_hints_related_and_stored_encrypted() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    t.rules(json!([rule(&a, &b, [true, false, false, false])]))
        .await;
    let v0 = t.admin_json("GET", "/admin/api/shared", None).await.1["version"]
        .as_i64()
        .unwrap();
    let (s, _) = t
        .admin_json(
            "PATCH",
            &format!("/admin/api/workspaces/{}", b.id),
            Some(json!({"tags": ["new"]})),
        )
        .await;
    assert_eq!(s, 200);
    let v1 = t.admin_json("GET", "/admin/api/shared", None).await.1["version"]
        .as_i64()
        .unwrap();
    assert_eq!(v1, v0 + 1);
    // a (related) has exactly one unread hint carrying the newest version
    let h = t.inbox(&a).await;
    assert_eq!(h.len(), 1);
    assert_eq!(h[0]["body"]["version"], v1);
    t.admin_json(
        "PUT",
        "/admin/api/shared/credentials/KEY",
        Some(json!({"value": "PLAIN-CRED-VALUE"})),
    )
    .await;
    let c = t.app.db.lock().unwrap();
    let raw: Vec<u8> = c
        .query_row("SELECT value FROM creds", [], |r| r.get(0))
        .unwrap();
    assert!(!String::from_utf8_lossy(&raw).contains("PLAIN-CRED"));
}
