//! Workspace look (contracts/look.md): the contract vectors `look-v1.json` replayed against the real routes.
mod common;
use common::*;
use serde_json::{json, Value};

fn vectors() -> Value {
    serde_json::from_str(include_str!("../../contracts/vectors/look-v1.json")).unwrap()
}

fn store(t: &T, id: &str, s: &Value) {
    t.app
        .db
        .lock()
        .unwrap()
        .execute(
            "UPDATE workspaces SET icon=?2, color=?3, look_by=?4 WHERE id=?1",
            rusqlite::params![
                id,
                s["icon"].as_str(),
                s["color"].as_str(),
                s["look_by"].as_str()
            ],
        )
        .unwrap();
}

fn stored(t: &T, id: &str) -> Value {
    let (i, c, b): (Option<String>, Option<String>, Option<String>) = t
        .app
        .db
        .lock()
        .unwrap()
        .query_row(
            "SELECT icon,color,look_by FROM workspaces WHERE id=?1",
            [id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .unwrap();
    json!({"icon": i, "color": c, "look_by": b})
}

#[tokio::test]
async fn me_patch_vectors() {
    let t = start().await;
    let ws = t.add_ws("Finance").await;
    for v in vectors()["me_patch"].as_array().unwrap() {
        if v["service"] != "relay" {
            continue;
        }
        store(&t, &ws.id, &v["stored"]);
        let (s, body) = t
            .call(&ws, "PATCH", "/v1/me", Some(v["body"].clone()))
            .await;
        assert_eq!(
            s as u64,
            v["status"].as_u64().unwrap(),
            "{} {body}",
            v["name"]
        );
        assert_eq!(stored(&t, &ws.id), v["after"], "{}", v["name"]);
        if s == 200 {
            for k in ["icon", "color", "look_by"] {
                assert_eq!(body[k], v["after"][k], "{} whoami {k}", v["name"]);
            }
        }
    }
}

#[tokio::test]
async fn admin_patch_vectors() {
    let t = start().await;
    let ws = t.add_ws("Finance").await;
    for v in vectors()["admin_patch"].as_array().unwrap() {
        store(&t, &ws.id, &v["stored"]);
        let (s, body) = t
            .admin_json(
                "PATCH",
                &format!("/admin/api/workspaces/{}", ws.id),
                Some(v["body"].clone()),
            )
            .await;
        assert_eq!(
            s as u64,
            v["status"].as_u64().unwrap(),
            "{} {body}",
            v["name"]
        );
        assert_eq!(stored(&t, &ws.id), v["after"], "{}", v["name"]);
    }
}

#[tokio::test]
async fn admin_refusal_stores_nothing_from_the_body() {
    let t = start().await;
    let ws = t.add_ws("Finance").await;
    store(
        &t,
        &ws.id,
        &json!({"icon": "wallet", "color": "amber", "look_by": "workspace"}),
    );
    let (s, _) = t
        .admin_json(
            "PATCH",
            &format!("/admin/api/workspaces/{}", ws.id),
            Some(json!({"name": "Other", "icon": "code"})),
        )
        .await;
    assert_eq!(s, 409);
    let (_, l) = t.admin_json("GET", "/admin/api/workspaces", None).await;
    assert_eq!(l["items"][0]["name"], "Finance");
    assert_eq!(l["items"][0]["icon"], "wallet");
    assert_eq!(l["items"][0]["look_by"], "workspace");
}

#[tokio::test]
async fn create_with_look_whoami_list_and_phone() {
    let t = start().await;
    let (s, v) = t
        .admin_json(
            "POST",
            "/admin/api/workspaces",
            Some(json!({"name": "Home", "description": "d", "tags": [], "icon": "house", "color": "teal"})),
        )
        .await;
    assert_eq!(s, 201, "{v}");
    let ws = Ws {
        id: v["id"].as_str().unwrap().into(),
        token: v["token"].as_str().unwrap().into(),
    };
    let (_, who) = t.call(&ws, "GET", "/v1/whoami", None).await;
    assert_eq!(
        (
            who["icon"].clone(),
            who["color"].clone(),
            who["look_by"].clone()
        ),
        (json!("house"), json!("teal"), json!("admin"))
    );
    let (s, _) = t
        .admin_json(
            "POST",
            "/admin/api/workspaces",
            Some(json!({"name": "Bad", "description": "d", "tags": [], "icon": "unicorn"})),
        )
        .await;
    assert_eq!(s, 422);
    let p = t.pair_phone(&[&ws]).await;
    let (s, items) = t.phone(&p, "GET", "/v1/phone/workspaces", None).await;
    assert_eq!(s, 200);
    assert_eq!(items["items"][0]["icon"], "house");
    assert_eq!(items["items"][0]["color"], "teal");
    assert!(items["items"][0].get("look_by").is_none());
    // the workspace takes over; the admin is refused from then on
    let (s, _) = t
        .call(&ws, "PATCH", "/v1/me", Some(json!({"color": null})))
        .await;
    assert_eq!(s, 200);
    let (_, items) = t.phone(&p, "GET", "/v1/phone/workspaces", None).await;
    assert_eq!(items["items"][0]["color"], Value::Null);
    let (s, _) = t
        .admin_json(
            "PATCH",
            &format!("/admin/api/workspaces/{}", ws.id),
            Some(json!({"color": "blue"})),
        )
        .await;
    assert_eq!(s, 409);
}

#[tokio::test]
async fn look_patch_sends_no_refresh_hint() {
    let t = start().await;
    let ws = t.add_ws("Finance").await;
    let before = t.inbox(&ws).await.len();
    let (s, _) = t
        .call(&ws, "PATCH", "/v1/me", Some(json!({"icon": "wallet"})))
        .await;
    assert_eq!(s, 200);
    assert_eq!(t.inbox(&ws).await.len(), before);
}

#[tokio::test]
async fn create_with_null_look_keeps_look_by_null() {
    let t = start().await;
    let (s, v) = t
        .admin_json(
            "POST",
            "/admin/api/workspaces",
            Some(json!({"name": "N", "description": "d", "tags": [], "icon": null})),
        )
        .await;
    assert_eq!(s, 201, "{v}");
    assert_eq!(
        stored(&t, v["id"].as_str().unwrap())["look_by"],
        Value::Null
    );
}
