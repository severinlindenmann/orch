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
