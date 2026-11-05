mod common;
use common::*;
use serde_json::{json, Value};

#[tokio::test]
async fn admin_needs_token() {
    let t = setup();
    assert_eq!(
        call(&t.admin, "GET", "/admin/api/workspaces", &[], vec![])
            .await
            .status,
        401
    );
    assert_eq!(
        call(
            &t.admin,
            "GET",
            "/admin/api/workspaces",
            &[("x-orch-admin", "wrong")],
            vec![]
        )
        .await
        .status,
        401
    );
    // header only: the cookie is not accepted
    assert_eq!(
        call(
            &t.admin,
            "GET",
            "/admin/api/workspaces",
            &[("cookie", "orch_admin=admin-test-token")],
            vec![]
        )
        .await
        .status,
        401
    );
    // the portal shell itself loads without a token (it asks for one)
    let p = call(&t.admin, "GET", "/admin", &[], vec![]).await;
    assert_eq!(p.status, 200);
    assert_eq!(p.headers["x-frame-options"], "DENY");
    assert_eq!(
        call(&t.admin, "GET", "/admin/portal.js", &[], vec![])
            .await
            .status,
        200
    );
    assert_eq!(
        call(&t.admin, "GET", "/admin/style.css", &[], vec![])
            .await
            .status,
        200
    );
    // admin routes do not exist on the public listener
    assert_eq!(
        call(
            &t.public,
            "GET",
            "/admin/api/workspaces",
            &[("x-orch-admin", ADMIN)],
            vec![]
        )
        .await
        .status,
        404
    );
}

#[tokio::test]
async fn admin_create_shows_prompt_and_edit() {
    let t = setup();
    let r = t.adm("POST", "/admin/api/workspaces", json!({"name": "Pilatus", "description": "Jobs", "tags": ["data", " work "], "rights": {"files": true, "apps": true, "permanent": false, "public": false}})).await;
    assert_eq!(r.status, 201);
    let j = r.json();
    let (id, tok, prompt) = (
        j["id"].as_str().unwrap(),
        j["token"].as_str().unwrap(),
        j["prompt"].as_str().unwrap(),
    );
    assert!(id.starts_with("ws_") && id.len() == 13);
    assert!(prompt.contains("orch addon add publish --yes\n  orch publish connect"));
    assert!(prompt.contains(&format!(
        "orch publish connect https://publish.test --workspace {id} --token {tok}"
    )));
    assert!(prompt.contains("onboarding.sh") && prompt.contains("onboarding.ps1"));

    let l = t
        .adm("GET", "/admin/api/workspaces", Value::Null)
        .await
        .json();
    assert_eq!(l["items"][0]["tags"], json!(["data", "work"]));
    assert_eq!(l["items"][0]["files"], 0);
    assert!(l["items"][0].get("token").is_none());

    let p = t.adm("PATCH", &format!("/admin/api/workspaces/{id}"), json!({"name": "Pilatus 2", "rights": {"files": true, "apps": false, "permanent": true, "public": false}})).await;
    assert_eq!(p.status, 200);
    assert_eq!(p.json()["name"], "Pilatus 2");
    assert_eq!(p.json()["description"], "Jobs");
    let who = t
        .api(&(id.into(), tok.into()), "GET", "/v1/whoami", vec![])
        .await
        .json();
    assert_eq!(who["rights"]["permanent"], true);
    assert_eq!(
        t.adm("PATCH", "/admin/api/workspaces/ws_nope", json!({}))
            .await
            .status,
        404
    );
    assert_eq!(
        t.adm("POST", "/admin/api/workspaces", json!({"name": ""}))
            .await
            .status,
        422
    );
}

#[tokio::test]
async fn admin_new_token_replaces_old() {
    let t = setup();
    let ws = t.workspace("A", basic_rights()).await;
    let r = t
        .adm(
            "POST",
            &format!("/admin/api/workspaces/{}/token", ws.0),
            Value::Null,
        )
        .await;
    assert_eq!(r.status, 200);
    let new = r.json()["token"].as_str().unwrap().to_string();
    assert_eq!(t.api(&ws, "GET", "/v1/whoami", vec![]).await.status, 401);
    assert_eq!(
        t.api(&(ws.0.clone(), new), "GET", "/v1/whoami", vec![])
            .await
            .status,
        200
    );
}

#[tokio::test]
async fn admin_files_apps_and_delete_workspace() {
    let t = setup();
    let ws = t.workspace("A", basic_rights()).await;
    let id = t.api(&ws, "POST", "/v1/files", vector_blob()).await.json()["id"]
        .as_str()
        .unwrap()
        .to_string();
    t.api(
        &ws,
        "PUT",
        "/v1/apps/site",
        bundle(&[("app.toml", "name = \"site\"\nstack = \"static\"\n")]),
    )
    .await;

    let f = t.adm("GET", "/admin/api/files", Value::Null).await.json();
    assert_eq!(f["items"][0]["id"], id.as_str());
    assert_eq!(f["items"][0]["workspace"], ws.0.as_str());
    assert!(f["items"][0].get("name").is_none());
    let a = t.adm("GET", "/admin/api/apps", Value::Null).await.json();
    assert_eq!(a["items"][0]["workspace"], ws.0.as_str());
    let l = t
        .adm("GET", "/admin/api/workspaces", Value::Null)
        .await
        .json();
    assert_eq!(
        (
            l["items"][0]["files"].as_i64(),
            l["items"][0]["apps"].as_i64()
        ),
        (Some(1), Some(1))
    );

    assert_eq!(
        t.adm("POST", "/admin/api/apps/site/stop", Value::Null)
            .await
            .json()["status"],
        "stopped"
    );
    assert_eq!(
        t.adm("POST", "/admin/api/apps/site/restart", Value::Null)
            .await
            .json()["status"],
        "running"
    );

    assert_eq!(
        t.adm(
            "DELETE",
            &format!("/admin/api/workspaces/{}", ws.0),
            Value::Null
        )
        .await
        .status,
        204
    );
    assert_eq!(
        call(&t.public, "GET", &format!("/f/{id}/blob"), &[], vec![])
            .await
            .status,
        404
    );
    assert_eq!(
        t.adm("GET", "/admin/api/apps", Value::Null).await.json()["items"]
            .as_array()
            .unwrap()
            .len(),
        0
    );
    assert_eq!(t.api(&ws, "GET", "/v1/whoami", vec![]).await.status, 401);

    let ws2 = t.workspace("B", basic_rights()).await;
    let id2 = t.api(&ws2, "POST", "/v1/files", vector_blob()).await.json()["id"]
        .as_str()
        .unwrap()
        .to_string();
    assert_eq!(
        t.adm("DELETE", &format!("/admin/api/files/{id2}"), Value::Null)
            .await
            .status,
        204
    );
    t.api(
        &ws2,
        "PUT",
        "/v1/apps/other",
        bundle(&[("app.toml", "name = \"other\"\nstack = \"static\"\n")]),
    )
    .await;
    assert_eq!(
        t.adm("DELETE", "/admin/api/apps/other", Value::Null)
            .await
            .status,
        204
    );
}

#[tokio::test]
async fn admin_onboarding_scripts() {
    let t = setup();
    let sh = call(&t.public, "GET", "/onboarding.sh", &[], vec![]).await;
    assert_eq!(sh.status, 200);
    assert!(
        sh.text().starts_with("#!/bin/sh")
            && sh.text().contains("https://publish.test")
            && sh
                .text()
                .contains("orch addon add publish --yes\nexec orch publish connect")
    );
    assert!(!sh.text().contains("__PUBLISH_URL__"));
    // test config uses the default ref
    assert!(sh.text().contains("orch/main/install.sh") && sh.text().contains("ORCH_REF=\"main\""));
    let ps = call(&t.public, "GET", "/onboarding.ps1", &[], vec![]).await;
    assert!(
        ps.text().contains("param(")
            && ps.text().contains("orch publish connect")
            && !ps.text().contains("__INSTALL_URL__")
    );
    assert_eq!(
        call(&t.public, "GET", "/health", &[], vec![]).await.text(),
        "ok"
    );
}
