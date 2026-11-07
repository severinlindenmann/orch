//! Workspace look (contracts/look.md): the contract vectors `look-v1.json` replayed against the real routes.
mod common;
use common::*;
use serde_json::{json, Value};

fn vectors() -> Value {
    serde_json::from_str(include_str!("../../contracts/vectors/look-v1.json")).unwrap()
}

fn store(t: &T, id: &str, s: &Value) {
    t.st.db
        .lock()
        .unwrap()
        .execute(
            "UPDATE workspaces SET icon=?2, color=?3, look_by=?4, show_on_shared_pages=?5 WHERE id=?1",
            rusqlite::params![
                id,
                s["icon"].as_str(),
                s["color"].as_str(),
                s["look_by"].as_str(),
                s["show_on_shared_pages"].as_bool().unwrap_or(true) as i64
            ],
        )
        .unwrap();
}

fn stored(t: &T, id: &str) -> Value {
    t.st.db
        .lock()
        .unwrap()
        .query_row(
            "SELECT icon,color,look_by,show_on_shared_pages FROM workspaces WHERE id=?1",
            [id],
            |r| {
                Ok(json!({"icon": r.get::<_, Option<String>>(0)?, "color": r.get::<_, Option<String>>(1)?,
                  "look_by": r.get::<_, Option<String>>(2)?, "show_on_shared_pages": r.get::<_, i64>(3)? != 0}))
            },
        )
        .unwrap()
}

#[tokio::test]
async fn me_patch_vectors() {
    let t = setup();
    let ws = t.workspace("Finance", basic_rights()).await;
    for v in vectors()["me_patch"].as_array().unwrap() {
        if v["service"] == "relay" {
            continue;
        }
        let mut s = v["stored"].clone();
        if s.get("show_on_shared_pages").is_none() {
            s["show_on_shared_pages"] = json!(true);
        }
        store(&t, &ws.0, &s);
        let r = t
            .api(&ws, "PATCH", "/v1/me", v["body"].to_string().into_bytes())
            .await;
        assert_eq!(
            r.status.as_u16() as u64,
            v["status"].as_u64().unwrap(),
            "{} {}",
            v["name"],
            r.text()
        );
        let mut after = v["after"].clone();
        if after.get("show_on_shared_pages").is_none() {
            after["show_on_shared_pages"] = json!(true);
        }
        assert_eq!(stored(&t, &ws.0), after, "{}", v["name"]);
        if r.status == 200 {
            let j = r.json();
            for k in ["icon", "color", "look_by", "show_on_shared_pages"] {
                assert_eq!(j[k], after[k], "{} whoami {k}", v["name"]);
            }
        }
    }
}

#[tokio::test]
async fn admin_patch_vectors() {
    let t = setup();
    let ws = t.workspace("Finance", basic_rights()).await;
    for v in vectors()["admin_patch"].as_array().unwrap() {
        let mut s = v["stored"].clone();
        s["show_on_shared_pages"] = json!(true);
        store(&t, &ws.0, &s);
        let r = t
            .adm(
                "PATCH",
                &format!("/admin/api/workspaces/{}", ws.0),
                v["body"].clone(),
            )
            .await;
        assert_eq!(
            r.status.as_u16() as u64,
            v["status"].as_u64().unwrap(),
            "{} {}",
            v["name"],
            r.text()
        );
        let mut after = v["after"].clone();
        after["show_on_shared_pages"] = json!(true);
        assert_eq!(stored(&t, &ws.0), after, "{}", v["name"]);
    }
}

#[tokio::test]
async fn admin_refusal_stores_nothing_from_the_body() {
    let t = setup();
    let ws = t.workspace("Finance", basic_rights()).await;
    store(
        &t,
        &ws.0,
        &json!({"icon": "wallet", "color": "amber", "look_by": "workspace"}),
    );
    let r = t
        .adm(
            "PATCH",
            &format!("/admin/api/workspaces/{}", ws.0),
            json!({"name": "Other", "icon": "code"}),
        )
        .await;
    assert_eq!(r.status, 409);
    let l = t
        .adm("GET", "/admin/api/workspaces", Value::Null)
        .await
        .json();
    assert_eq!(l["items"][0]["name"], "Finance");
    assert_eq!(l["items"][0]["icon"], "wallet");
}

#[tokio::test]
async fn create_with_look() {
    let t = setup();
    let r = t
        .adm(
            "POST",
            "/admin/api/workspaces",
            json!({"name": "Home", "icon": "house", "color": "teal", "rights": basic_rights()}),
        )
        .await;
    assert_eq!(r.status, 201, "{}", r.text());
    let id = r.json()["id"].as_str().unwrap().to_string();
    assert_eq!(stored(&t, &id)["look_by"], "admin");
    let bad = t
        .adm(
            "POST",
            "/admin/api/workspaces",
            json!({"name": "Bad", "icon": "unicorn"}),
        )
        .await;
    assert_eq!(bad.status, 422);
}

#[tokio::test]
async fn meta_vectors_and_headers() {
    let t = setup();
    let ws = t.workspace("Finance", basic_rights()).await;
    let up = t.api(&ws, "POST", "/v1/files?days=7", vector_blob()).await;
    assert_eq!(up.status, 201);
    let id = up.json()["id"].as_str().unwrap().to_string();
    for v in vectors()["meta"].as_array().unwrap() {
        let rec = &v["record"];
        store(
            &t,
            &ws.0,
            &json!({"icon": rec["icon"], "color": rec["color"], "look_by": "workspace",
                    "show_on_shared_pages": rec["show_on_shared_pages"]}),
        );
        let r = call(&t.public, "GET", &format!("/f/{id}/meta"), &[], vec![]).await;
        assert_eq!(r.status, 200);
        assert_eq!(r.json(), v["meta"], "{}", v["name"]);
        assert_eq!(r.headers["cache-control"], "no-store");
        assert_eq!(r.headers["referrer-policy"], "no-referrer");
    }
    // unknown and expired links answer like the blob
    let r = call(&t.public, "GET", "/f/f_nope/meta", &[], vec![]).await;
    assert_eq!(r.status, 404);
    assert!(!r.text().contains("Finance"));
    t.st.db
        .lock()
        .unwrap()
        .execute(
            "UPDATE files SET expires_at='2000-01-01T00:00:00Z' WHERE id=?1",
            [&id],
        )
        .unwrap();
    let r = call(&t.public, "GET", &format!("/f/{id}/meta"), &[], vec![]).await;
    assert_eq!(r.status, 410);
    assert!(!r.text().contains("Finance"));
}

#[tokio::test]
async fn only_own_switch_and_no_refresh_of_pending() {
    let t = setup();
    let ws = t.workspace("Finance", basic_rights()).await;
    let r = t
        .api(
            &ws,
            "PATCH",
            "/v1/me",
            json!({"show_on_shared_pages": false})
                .to_string()
                .into_bytes(),
        )
        .await;
    assert_eq!(r.status, 200);
    assert_eq!(r.json()["pending"], Value::Null);
    assert_eq!(stored(&t, &ws.0)["show_on_shared_pages"], false);
}

#[tokio::test]
async fn file_page_loads_look_scripts() {
    let t = setup();
    let p = call(&t.public, "GET", "/f/f_x", &[], vec![]).await;
    assert!(p.text().contains("/_/look.js") && p.text().contains("/_/look-data.js"));
    for path in ["/_/look.js", "/_/look-data.js"] {
        let r = call(&t.public, "GET", path, &[], vec![]).await;
        assert_eq!(r.status, 200, "{path}");
        assert!(r.headers["content-type"]
            .to_str()
            .unwrap()
            .starts_with("text/javascript"));
    }
    // the name is only ever inserted as text
    let js = call(&t.public, "GET", "/_/look.js", &[], vec![])
        .await
        .text();
    assert!(!js.contains("innerHTML") && !js.contains("insertAdjacentHTML"));
}
