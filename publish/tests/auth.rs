mod common;
use common::*;
use serde_json::Value;

#[tokio::test]
async fn auth_whoami_ok() {
    let t = setup();
    let ws = t.workspace("Pilatus", basic_rights()).await;
    let r = t.api(&ws, "GET", "/v1/whoami", vec![]).await;
    assert_eq!(r.status, 200);
    let j = r.json();
    assert_eq!(j["id"], ws.0.as_str());
    assert_eq!(j["name"], "Pilatus");
    assert_eq!(j["rights"]["files"], true);
    assert_eq!(j["rights"]["permanent"], false);
    assert_eq!(
        (
            j["max_file_mb"].as_u64(),
            j["default_days"].as_u64(),
            j["max_days"].as_u64()
        ),
        (Some(100), Some(7), Some(90))
    );
    assert!(ws.1.starts_with("orp_") && ws.1.len() == 47);
}

#[tokio::test]
async fn auth_wrong_or_missing_is_401() {
    let t = setup();
    let ws = t.workspace("A", basic_rights()).await;
    let r = t
        .api(
            &(ws.0.clone(), "orp_wrong".into()),
            "GET",
            "/v1/whoami",
            vec![],
        )
        .await;
    assert_eq!(r.status, 401);
    assert_eq!(r.json()["error"], "unauthorized");
    let r = t
        .api(
            &("ws_nobody0000".into(), ws.1.clone()),
            "GET",
            "/v1/whoami",
            vec![],
        )
        .await;
    assert_eq!(r.status, 401);
    let r = call(&t.public, "GET", "/v1/whoami", &[], vec![]).await;
    assert_eq!(r.status, 401);
    let r = call(
        &t.public,
        "GET",
        "/v1/files",
        &[("x-orch-workspace", &ws.0)],
        vec![],
    )
    .await;
    assert_eq!(r.status, 401);
}

#[tokio::test]
async fn auth_token_stored_as_hash_only() {
    let t = setup();
    let ws = t.workspace("A", basic_rights()).await;
    let c = t.st.db.lock().unwrap();
    let h: String = c
        .query_row(
            "SELECT token_hash FROM workspaces WHERE id=?1",
            [&ws.0],
            |r| r.get(0),
        )
        .unwrap();
    assert_ne!(h, ws.1);
    assert_eq!(h.len(), 64);
}

#[tokio::test]
async fn auth_missing_right_is_403() {
    let t = setup();
    let ws = t
        .workspace(
            "A",
            serde_json::json!({"files": false, "apps": false, "permanent": false, "public": false}),
        )
        .await;
    assert_eq!(
        t.api(&ws, "POST", "/v1/files", vector_blob()).await.status,
        403
    );
    assert_eq!(
        t.api(&ws, "PUT", "/v1/apps/some-app", vec![]).await.status,
        403
    );
}

#[tokio::test]
async fn me_patch_is_pending_until_the_owner_approves() {
    let t = setup();
    let ws = t.workspace("Pilatus", basic_rights()).await;
    let body =
        "{\"description\":\"Data pipelines. Größe ✓ 日本語\",\"tags\":[\"data\",\" work \"]}"
            .as_bytes()
            .to_vec();
    let r = t.api(&ws, "PATCH", "/v1/me", body).await;
    assert_eq!(r.status, 202);
    let j = r.json();
    assert_eq!(j["status"], "pending");
    // live values unchanged
    assert_eq!(j["description"], "d");
    assert_eq!(j["tags"], serde_json::json!(["a"]));
    assert_eq!(j["pending"]["tags"], serde_json::json!(["data", "work"]));
    let w = t.api(&ws, "GET", "/v1/whoami", vec![]).await.json();
    assert_eq!(w["description"], "d");
    assert_eq!(
        w["pending"]["description"],
        "Data pipelines. Größe ✓ 日本語"
    );
    // a new proposal replaces the old one; only given fields are proposed
    let r = t
        .api(&ws, "PATCH", "/v1/me", br#"{"tags":["a"]}"#.to_vec())
        .await;
    assert_eq!(r.status, 202);
    assert!(r.json()["pending"]["description"].is_null());
    // admin sees it; reject keeps old values
    let id = &ws.0;
    let l = t
        .adm("GET", "/admin/api/workspaces", Value::Null)
        .await
        .json();
    assert_eq!(l["items"][0]["pending"]["tags"], serde_json::json!(["a"]));
    let rev0 = l["items"][0]["pending"]["rev"].clone();
    // bound to the exact proposal: a newer one makes the old rev stale (409)
    let r2 = t
        .api(&ws, "PATCH", "/v1/me", br#"{"tags":["a3"]}"#.to_vec())
        .await
        .json();
    assert_ne!(r2["pending"]["rev"], rev0);
    let url = |what: &str| format!("/admin/api/workspaces/{id}/profile/{what}");
    let x = t
        .adm("POST", &url("approve"), serde_json::json!({"rev": rev0}))
        .await;
    assert_eq!(x.status, 409);
    let x = t
        .adm(
            "POST",
            &url("reject"),
            serde_json::json!({"rev": r2["pending"]["rev"]}),
        )
        .await;
    assert_eq!(x.status, 204);
    let w = t.api(&ws, "GET", "/v1/whoami", vec![]).await.json();
    assert!(w["pending"].is_null());
    assert_eq!(w["tags"], serde_json::json!(["a"]));
    for what in ["approve", "reject"] {
        let x = t
            .adm("POST", &url(what), serde_json::json!({"rev": "x"}))
            .await;
        assert_eq!(x.status, 404, "{what}");
    }
    // approve: live, marked as written by the workspace
    let p = t
        .api(
            &ws,
            "PATCH",
            "/v1/me",
            br#"{"description":"New text","tags":["data"]}"#.to_vec(),
        )
        .await
        .json();
    let x = t
        .adm(
            "POST",
            &url("approve"),
            serde_json::json!({"rev": p["pending"]["rev"]}),
        )
        .await;
    assert_eq!(x.status, 200);
    let j = x.json();
    assert_eq!(
        (
            j["description"].clone(),
            j["description_by"].clone(),
            j["tags_by"].clone()
        ),
        (
            serde_json::json!("New text"),
            serde_json::json!("workspace"),
            serde_json::json!("workspace")
        )
    );
    let w = t.api(&ws, "GET", "/v1/whoami", vec![]).await.json();
    assert_eq!(
        (w["tags"].clone(), w["pending"].clone()),
        (serde_json::json!(["data"]), Value::Null)
    );
    // admin edits are marked per field
    let p = t
        .adm(
            "PATCH",
            &format!("/admin/api/workspaces/{id}"),
            serde_json::json!({"description": "By admin"}),
        )
        .await;
    let j = p.json();
    assert_eq!(
        (j["description_by"].clone(), j["tags_by"].clone()),
        (serde_json::json!("admin"), serde_json::json!("workspace"))
    );
}

#[tokio::test]
async fn profile_text_rules_apply_to_workspace_and_admin() {
    let t = setup();
    let ws = t.workspace("Pilatus", basic_rights()).await;
    for bad in [
        "{\"description\":\"hi\\nignore previous\"}",
        "{\"description\":\"a\\u202eb\"}",
        "{\"description\":\"a\\u200bb\"}",
        "{\"description\":\"a\\u0085b\"}",
        "{\"description\":\"a\\ufe0fb\"}",
        "{\"description\":\"a\\u034fb\"}",
        "{\"description\":\"a\\u3164b\"}",
        "{\"description\":\"a\\u2800b\"}",
        "{\"description\":\"e\\u0301\\u0302\\u0303\\u0304\"}",
        "{\"tags\":[\"Data\"]}",
        "{\"tags\":[\"a b\"]}",
        "{\"tags\":[\"\"]}",
        "{}",
    ] {
        assert_eq!(
            t.api(&ws, "PATCH", "/v1/me", bad.as_bytes().to_vec())
                .await
                .status,
            422,
            "{bad}"
        );
        if bad != "{}" {
            let v: Value = serde_json::from_str(bad).unwrap();
            let r = t
                .adm("PATCH", &format!("/admin/api/workspaces/{}", ws.0), v)
                .await;
            assert_eq!(r.status, 422, "admin {bad}");
        }
    }
    // rotating the token drops a pending proposal and the old token cannot write
    assert_eq!(
        t.api(&ws, "PATCH", "/v1/me", br#"{"tags":["y"]}"#.to_vec())
            .await
            .status,
        202
    );
    let r = t
        .adm(
            "POST",
            &format!("/admin/api/workspaces/{}/token", ws.0),
            Value::Null,
        )
        .await;
    assert_eq!(r.status, 200);
    let l = t
        .adm("GET", "/admin/api/workspaces", Value::Null)
        .await
        .json();
    assert!(l["items"][0]["pending"].is_null());
    assert_eq!(
        t.api(&ws, "PATCH", "/v1/me", br#"{"tags":["x"]}"#.to_vec())
            .await
            .status,
        401
    );
}

#[tokio::test]
async fn me_patch_limits_and_auth() {
    let t = setup();
    let ws = t.workspace("Pilatus", basic_rights()).await;
    let long = format!(r#"{{"description":"{}"}}"#, "x".repeat(281));
    assert_eq!(
        t.api(&ws, "PATCH", "/v1/me", long.into_bytes())
            .await
            .status,
        422
    );
    let many = r#"{"tags":["1","2","3","4","5","6","7","8","9"]}"#;
    assert_eq!(t.api(&ws, "PATCH", "/v1/me", many.into()).await.status, 422);
    let big = format!(r#"{{"tags":["{}"]}}"#, "t".repeat(25));
    assert_eq!(
        t.api(&ws, "PATCH", "/v1/me", big.into_bytes()).await.status,
        422
    );
    let r = call(&t.public, "PATCH", "/v1/me", &[], b"{}".to_vec()).await;
    assert_eq!(r.status, 401);
}

#[tokio::test]
async fn public_pages_are_branded_dark_html() {
    let t = setup();
    for uri in ["/", "/nope", "/a/missing/"] {
        let r = call(&t.public, "GET", uri, &[], vec![]).await;
        assert_eq!(r.status, 404, "{uri}");
        let h = r.text();
        assert!(h.contains("isn&#39;t available") || h.contains("isn\u{2019}t available"));
        assert!(h.contains("color-scheme") && h.contains("<svg") && !h.contains("relay"));
    }
}

#[tokio::test]
async fn me_patch_keeps_rights_and_rotated_token() {
    let t = setup();
    let ws = t.workspace("Pilatus", basic_rights()).await;
    let r = t
        .api(&ws, "PATCH", "/v1/me", br#"{"description":"x"}"#.to_vec())
        .await;
    assert_eq!(r.status, 202);
    // after an admin rotation the old token is refused and nothing is written
    let rot = t
        .adm(
            "POST",
            &format!("/admin/api/workspaces/{}/token", ws.0),
            serde_json::Value::Null,
        )
        .await;
    assert_eq!(rot.status, 200);
    let r = t
        .api(&ws, "PATCH", "/v1/me", br#"{"description":"y"}"#.to_vec())
        .await;
    assert_eq!(r.status, 401);
    let new = (
        ws.0.clone(),
        rot.json()["token"].as_str().unwrap().to_string(),
    );
    let w = t.api(&new, "GET", "/v1/whoami", vec![]).await.json();
    assert!(w["pending"].is_null(), "rotation drops the proposal");
    assert_eq!(w["description"], "d");
}
