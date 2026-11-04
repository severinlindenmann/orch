mod common;
use common::*;

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
async fn me_patch_changes_own_description_and_tags() {
    let t = setup();
    let ws = t.workspace("Pilatus", basic_rights()).await;
    let body = br#"{"description":"Data pipelines.","tags":["data"," work ",""]}"#.to_vec();
    let r = t.api(&ws, "PATCH", "/v1/me", body).await;
    assert_eq!(r.status, 200);
    let j = r.json();
    assert_eq!(j["description"], "Data pipelines.");
    assert_eq!(j["tags"], serde_json::json!(["data", "work"]));
    assert_eq!(j["name"], "Pilatus");
    // only the given fields change; whoami shows the same
    let r = t
        .api(&ws, "PATCH", "/v1/me", br#"{"tags":["a"]}"#.to_vec())
        .await;
    assert_eq!(r.json()["description"], "Data pipelines.");
    let w = t.api(&ws, "GET", "/v1/whoami", vec![]).await.json();
    assert_eq!(w["tags"], serde_json::json!(["a"]));
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
