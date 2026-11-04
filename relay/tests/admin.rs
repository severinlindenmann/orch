mod common;
use common::*;
use serde_json::json;

#[tokio::test]
async fn admin_requires_token_and_rejects_cookie_accepts_header() {
    let t = start().await;
    let r = t
        .http
        .get(format!("{}/admin/api/workspaces", t.admin))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
    let r = t
        .http
        .get(format!("{}/admin/api/workspaces", t.admin))
        .header("X-Orch-Admin", "wrong")
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
    let r = t
        .http
        .get(format!("{}/admin/api/workspaces", t.admin))
        .header("Cookie", format!("orch_admin={ADMIN}"))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 401);
    let r = t
        .http
        .get(format!("{}/admin/api/workspaces", t.admin))
        .header("X-Orch-Admin", ADMIN)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 200);
    // the portal page itself is public (it asks for the token)
    let r = t
        .http
        .get(format!("{}/admin", t.admin))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 200);
    assert!(r.text().await.unwrap().contains("<html"));
    // admin routes do not exist on the public listener
    assert_eq!(
        t.http
            .get(format!("{}/admin/api/workspaces", t.base))
            .header("X-Orch-Admin", ADMIN)
            .send()
            .await
            .unwrap()
            .status(),
        404
    );
    assert_eq!(
        t.http
            .get(format!("{}/health", t.base))
            .send()
            .await
            .unwrap()
            .text()
            .await
            .unwrap(),
        "ok"
    );
}

#[tokio::test]
async fn admin_add_workspace_prompt_token_stored_hashed() {
    let t = start().await;
    let (s, v) = t
        .admin_json(
            "POST",
            "/admin/api/workspaces",
            Some(json!({"name": "Pilatus", "description": "Jobs", "tags": ["data", "work"]})),
        )
        .await;
    assert_eq!(s, 201);
    let (id, token) = (v["id"].as_str().unwrap(), v["token"].as_str().unwrap());
    assert!(token.starts_with("orn_") && token.len() == 47);
    let p = v["prompt"].as_str().unwrap();
    assert!(p.contains(&format!(
        "orch relay connect https://relay.test --workspace {id} --token {token}"
    )));
    assert!(p.contains("onboarding.sh") && p.contains("onboarding.ps1"));
    let hash: String = t
        .app
        .db
        .lock()
        .unwrap()
        .query_row("SELECT token_hash FROM workspaces", [], |r| r.get(0))
        .unwrap();
    assert_ne!(hash, token);
    let w = Ws {
        id: id.into(),
        token: token.into(),
    };
    let (s, me) = t.call(&w, "GET", "/v1/whoami", None).await;
    assert_eq!(
        (
            s,
            me["name"].as_str(),
            me["tags"].clone(),
            me["phones"].clone()
        ),
        (200, Some("Pilatus"), json!(["data", "work"]), json!(0))
    );
    // new token invalidates the old one
    let (_, nv) = t
        .admin_json("POST", &format!("/admin/api/workspaces/{id}/token"), None)
        .await;
    assert_eq!(t.call(&w, "GET", "/v1/whoami", None).await.0, 401);
    let w2 = Ws {
        id: id.into(),
        token: nv["token"].as_str().unwrap().into(),
    };
    assert_eq!(t.call(&w2, "GET", "/v1/whoami", None).await.0, 200);
    // online after a call, listed with unread count
    let (_, l) = t.admin_json("GET", "/admin/api/workspaces", None).await;
    assert_eq!(
        (
            l["items"][0]["online"].clone(),
            l["items"][0]["unread"].clone()
        ),
        (json!(true), json!(0))
    );
    assert_eq!(
        t.admin_json(
            "POST",
            "/admin/api/workspaces",
            Some(json!({"name": " ", "tags": []}))
        )
        .await
        .0,
        422
    );
}

#[tokio::test]
async fn admin_reads_messages_decrypted_and_filters() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    t.rules(json!([rule(&a, &b, [true, false, false, false])]))
        .await;
    t.send(&a, &b.id, "text", json!({"text": "read me"})).await;
    let (_, v) = t
        .admin_json(
            "GET",
            &format!("/admin/api/messages?workspace={}&type=text", a.id),
            None,
        )
        .await;
    assert_eq!(v["items"].as_array().unwrap().len(), 1);
    assert_eq!(v["items"][0]["body"]["text"], "read me");
    assert_eq!(v["items"][0]["acked"], false);
    let (_, v) = t
        .admin_json("GET", "/admin/api/messages?type=question", None)
        .await;
    assert_eq!(v["items"].as_array().unwrap().len(), 0);
    let tid = t
        .inbox(&b)
        .await
        .into_iter()
        .find(|m| m["type"] == "text")
        .unwrap()["id"]
        .clone();
    t.call(&b, "POST", "/v1/inbox/ack", Some(json!({"ids": [tid]})))
        .await;
    let (_, v) = t
        .admin_json("GET", "/admin/api/messages?type=text", None)
        .await;
    assert_eq!(v["items"][0]["acked"], true);
    // cursor pagination (newest first)
    for i in 0..3 {
        t.send(&a, &b.id, "text", json!({"text": format!("n{i}")}))
            .await;
    }
    let (_, p1) = t
        .admin_json("GET", "/admin/api/messages?type=text&limit=2", None)
        .await;
    assert_eq!(p1["items"][0]["body"]["text"], "n2");
    let (_, p2) = t
        .admin_json(
            "GET",
            &format!(
                "/admin/api/messages?type=text&limit=2&after={}",
                p1["next"].as_str().unwrap()
            ),
            None,
        )
        .await;
    assert_eq!(p2["items"].as_array().unwrap().len(), 2);
    assert!(p2["next"].is_null());
}

#[tokio::test]
async fn admin_delete_workspace_cleans_up_and_rules_validate() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    t.rules(json!([rule(&a, &b, [true, true, true, true])]))
        .await;
    let (s, _) = t
        .admin_json(
            "PUT",
            "/admin/api/rules",
            Some(json!({"rules": [{"from": a.id, "to": "ws_nope000001", "text": true}]})),
        )
        .await;
    assert_eq!(s, 422);
    let (_, r) = t.admin_json("GET", "/admin/api/rules", None).await;
    assert_eq!(r["rules"].as_array().unwrap().len(), 1);
    assert_eq!(
        t.admin_json("DELETE", &format!("/admin/api/workspaces/{}", b.id), None)
            .await
            .0,
        204
    );
    assert_eq!(t.call(&b, "GET", "/v1/whoami", None).await.0, 401);
    let (_, r) = t.admin_json("GET", "/admin/api/rules", None).await;
    assert_eq!(r["rules"].as_array().unwrap().len(), 0);
    assert_eq!(
        t.admin_json("DELETE", &format!("/admin/api/workspaces/{}", b.id), None)
            .await
            .0,
        404
    );
}

#[tokio::test]
async fn admin_onboarding_scripts_are_served() {
    let t = start().await;
    let sh = t
        .http
        .get(format!("{}/onboarding.sh", t.base))
        .send()
        .await
        .unwrap()
        .text()
        .await
        .unwrap();
    assert!(
        sh.starts_with("#!/bin/sh")
            && sh.contains("https://relay.test")
            && !sh.contains("__RELAY_URL__")
            && sh.contains("orch/develop/install.sh")
            && sh.contains("ORCH_REF=develop")
            && !sh.contains("__INSTALL_REF__")
    );
    let ps = t
        .http
        .get(format!("{}/onboarding.ps1", t.base))
        .send()
        .await
        .unwrap()
        .text()
        .await
        .unwrap();
    assert!(ps.contains("orch relay connect") && !ps.contains("__RELAY_URL__"));
}

#[tokio::test]
async fn me_patch_updates_profile_validates_and_hints() {
    let t = start().await;
    let a = t.add_ws("Alpha").await;
    let b = t.add_ws("Beta").await;
    t.rules(json!([rule(&a, &b, [true, false, false, false])]))
        .await;
    let (s, v) = t
        .call(
            &a,
            "PATCH",
            "/v1/me",
            Some(json!({"description": "Builds reports.", "tags": ["data", "work"]})),
        )
        .await;
    assert_eq!(s, 200, "{v}");
    assert_eq!(v["description"], "Builds reports.");
    assert_eq!(v["tags"], json!(["data", "work"]));
    assert_eq!(v["id"], json!(a.id));
    assert!(v.get("phones").is_some());
    // same body as whoami
    let (_, w) = t.call(&a, "GET", "/v1/whoami", None).await;
    assert_eq!(v, w);
    // the partner gets a refresh-hint
    assert!(t
        .inbox(&b)
        .await
        .iter()
        .any(|m| m["type"] == "refresh-hint"));
    // partial update keeps the rest
    let (s, v) = t
        .call(&a, "PATCH", "/v1/me", Some(json!({"tags": ["x"]})))
        .await;
    assert_eq!(
        (s, v["description"].clone()),
        (200, json!("Builds reports."))
    );
    // limits
    for bad in [
        json!({"description": "x".repeat(281)}),
        json!({"tags": ["a","b","c","d","e","f","g","h","i"]}),
        json!({"tags": ["x".repeat(25)]}),
        json!({"tags": [""]}),
        json!({"tags": "a"}),
    ] {
        assert_eq!(t.call(&a, "PATCH", "/v1/me", Some(bad)).await.0, 422);
    }
    let bad = Ws {
        id: a.id.clone(),
        token: "nope".into(),
    };
    assert_eq!(
        t.call(&bad, "PATCH", "/v1/me", Some(json!({}))).await.0,
        401
    );
}

#[tokio::test]
async fn admin_list_shows_last_seen_and_prompt_asks_for_profile() {
    let t = start().await;
    let w = t.add_ws("Alpha").await;
    let (_, l) = t.admin_json("GET", "/admin/api/workspaces", None).await;
    assert_eq!(
        (
            l["items"][0]["online"].clone(),
            l["items"][0]["last_seen"].clone()
        ),
        (json!(false), serde_json::Value::Null)
    );
    t.inbox(&w).await;
    let (_, l) = t.admin_json("GET", "/admin/api/workspaces", None).await;
    assert_eq!(l["items"][0]["online"], json!(true));
    assert!(l["items"][0]["last_seen"].is_string());
    let (_, v) = t
        .admin_json("POST", "/admin/api/workspaces", Some(json!({"name": "B"})))
        .await;
    assert!(v["prompt"]
        .as_str()
        .unwrap()
        .contains("orch relay profile --description"));
}

#[tokio::test]
async fn public_root_and_unknown_pages_are_branded_dark_pages() {
    let t = start().await;
    let r = t.http.get(format!("{}/", t.base)).send().await.unwrap();
    assert_eq!(r.status(), 200);
    let body = r.text().await.unwrap();
    assert!(body.contains("This page isn't available") && !body.to_lowercase().contains("relay"));
    let r = t.http.get(format!("{}/nope", t.base)).send().await.unwrap();
    assert_eq!(r.status(), 404);
    assert!(r.text().await.unwrap().contains("isn't available"));
    let r = t
        .http
        .get(format!("{}/v1/nope", t.base))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 404);
    assert_eq!(
        r.json::<serde_json::Value>().await.unwrap()["error"],
        "not_found"
    );
}
