mod common;
use common::*;

async fn put(t: &T, ws: &(String, String), name: &str, extra: &str) -> Resp {
    let toml = format!("name = \"{name}\"\nstack = \"static\"\n{extra}\n");
    t.api(
        ws,
        "PUT",
        &format!("/v1/apps/{name}?days=7"),
        bundle(&[("app.toml", &toml), ("index.html", "<h1>hi</h1>")]),
    )
    .await
}

fn same(a: &Resp, b: &Resp) {
    assert_eq!(a.status, b.status);
    assert_eq!(a.headers, b.headers);
    assert_eq!(a.body, b.body);
}

#[tokio::test]
async fn four_modes_on_the_right_listener() {
    let t = setup_private();
    let ws = t.workspace("A", all_rights()).await;
    let modes = [
        ("pubauth", "reach = \"public\"\nauth = true", false, true),
        ("pubopen", "reach = \"public\"\nauth = false", false, false),
        ("privauth", "reach = \"private\"\nauth = true", true, true),
        ("privopen", "reach = \"private\"\nauth = false", true, false),
    ];
    for (name, extra, private, auth) in modes {
        let r = put(&t, &ws, name, extra).await;
        assert_eq!(r.status, 200, "{name}: {}", r.text());
        let j = r.json();
        let base = if private {
            "http://publish.internal"
        } else {
            "https://publish.test"
        };
        assert_eq!(j["url"], format!("{base}/a/{name}"));
        let (right, wrong) = if private {
            (&t.private, &t.public)
        } else {
            (&t.public, &t.private)
        };
        let uri = format!("/a/{name}/");
        let on = call(right, "GET", &uri, &[], vec![]).await;
        if auth {
            assert_eq!(on.status, 401, "{name}");
            let tok = j["view_token"].as_str().unwrap();
            let go = call(right, "GET", &format!("{uri}?token={tok}"), &[], vec![]).await;
            assert_eq!(go.status, 302, "{name}");
        } else {
            assert_eq!(on.status, 200, "{name}: {}", on.text());
            assert!(j["view_token"].is_null());
        }
        // on the other listener the app is missing, exactly like an app that never existed
        let off = call(wrong, "GET", &uri, &[], vec![]).await;
        let gone = call(wrong, "GET", "/a/nothere/", &[], vec![]).await;
        same(&off, &gone);
        assert_eq!(off.status, 404);
        // also without the trailing slash and with a token
        let off = call(wrong, "GET", &format!("/a/{name}?token=apv_x"), &[], vec![]).await;
        let gone = call(wrong, "GET", "/a/nothere?token=apv_x", &[], vec![]).await;
        same(&off, &gone);
    }
}

#[tokio::test]
async fn private_listener_serves_only_apps_assets_and_health() {
    let t = setup_private();
    let ws = t.workspace("A", all_rights()).await;
    put(&t, &ws, "priv", "reach = \"private\"\nauth = false").await;
    assert_eq!(
        call(&t.private, "GET", "/health", &[], vec![]).await.status,
        200
    );
    assert_eq!(
        call(&t.private, "GET", "/_/style.css", &[], vec![])
            .await
            .status,
        200
    );
    for p in [
        "/",
        "/v1/whoami",
        "/v1/apps",
        "/f/abc",
        "/onboarding.sh",
        "/admin",
    ] {
        let r = call(&t.private, "GET", p, &[], vec![]).await;
        assert_eq!(r.status, 404, "{p}");
    }
}

#[tokio::test]
async fn legacy_public_alias() {
    let t = setup_private();
    let ws = t.workspace("A", all_rights()).await;
    let r = put(&t, &ws, "old1", "public = true").await;
    assert_eq!(r.status, 200, "{}", r.text());
    assert_eq!(
        call(&t.public, "GET", "/a/old1/", &[], vec![]).await.status,
        200
    );
    let r = put(&t, &ws, "old2", "public = false").await;
    assert_eq!(r.status, 200);
    assert_eq!(
        call(&t.public, "GET", "/a/old2/", &[], vec![]).await.status,
        401
    );
    let l = t.api(&ws, "GET", "/v1/apps", vec![]).await.json();
    let item = |n: &str| {
        l["items"]
            .as_array()
            .unwrap()
            .iter()
            .find(|i| i["name"] == n)
            .unwrap()
            .clone()
    };
    assert_eq!(item("old1")["public"], true);
    assert_eq!(item("old1")["auth"], false);
    assert_eq!(item("old2")["public"], false);
    assert_eq!(item("old2")["auth"], true);
}

#[tokio::test]
async fn bad_manifests_are_refused() {
    let t = setup_private();
    let ws = t.workspace("A", all_rights()).await;
    let r = put(&t, &ws, "both", "public = true\nauth = true").await;
    assert_eq!(r.status, 422, "{}", r.text());
    assert_eq!(r.json()["error"], "invalid");
    let r = put(&t, &ws, "odd", "reach = \"lan\"").await;
    assert_eq!(r.status, 422);
    assert_eq!(r.json()["error"], "invalid");
}

#[tokio::test]
async fn private_reach_needs_a_private_address() {
    let t = setup();
    let ws = t.workspace("A", all_rights()).await;
    let r = put(&t, &ws, "priv", "reach = \"private\"").await;
    assert_eq!(r.status, 422);
    assert_eq!(r.json()["error"], "invalid");
    assert!(r
        .text()
        .contains("This server has no private-network address."));
}

#[tokio::test]
async fn right_public_only_for_public_without_auth() {
    let t = setup_private();
    let ws = t.workspace("A", basic_rights()).await;
    let r = put(&t, &ws, "pubopen", "auth = false").await;
    assert_eq!(r.status, 403, "{}", r.text());
    let r = put(&t, &ws, "pubopen2", "reach = \"public\"\nauth = false").await;
    assert_eq!(r.status, 403);
    assert_eq!(put(&t, &ws, "pubauth", "").await.status, 200);
    assert_eq!(
        put(&t, &ws, "privopen", "reach = \"private\"\nauth = false")
            .await
            .status,
        200
    );
    assert_eq!(
        put(&t, &ws, "privauth", "reach = \"private\"").await.status,
        200
    );
}

#[tokio::test]
async fn cookie_secure_follows_the_listener_url() {
    let t = setup_with(|c| {
        c.public_url = "http://publish.test".into();
        c.private_listen = Some("x".into());
        c.private_url = Some("https://publish.internal".into());
    });
    let ws = t.workspace("A", all_rights()).await;
    let a = put(&t, &ws, "pa", "").await.json();
    let b = put(&t, &ws, "pb", "reach = \"private\"").await.json();
    let cookie = |r: &Resp| {
        r.headers
            .get("set-cookie")
            .unwrap()
            .to_str()
            .unwrap()
            .to_string()
    };
    let ra = call(
        &t.public,
        "GET",
        &format!("/a/pa/?token={}", a["view_token"].as_str().unwrap()),
        &[],
        vec![],
    )
    .await;
    assert!(!cookie(&ra).contains("Secure"), "{}", cookie(&ra));
    let rb = call(
        &t.private,
        "GET",
        &format!("/a/pb/?token={}", b["view_token"].as_str().unwrap()),
        &[],
        vec![],
    )
    .await;
    assert!(cookie(&rb).contains("Secure"), "{}", cookie(&rb));
    // the redirect goes to the secret address on the same listener
    assert!(rb.headers["location"]
        .to_str()
        .unwrap()
        .starts_with("/a/pb/~"));
}

#[tokio::test]
async fn cookie_has_no_secure_on_an_http_private_url() {
    let t = setup_private();
    let ws = t.workspace("A", all_rights()).await;
    let b = put(&t, &ws, "pb", "reach = \"private\"").await.json();
    let r = call(
        &t.private,
        "GET",
        &format!("/a/pb/?token={}", b["view_token"].as_str().unwrap()),
        &[],
        vec![],
    )
    .await;
    let c = r.headers["set-cookie"].to_str().unwrap();
    assert!(c.contains("HttpOnly") && !c.contains("Secure"), "{c}");
    // the secret address works on the private listener
    let loc = r.headers["location"].to_str().unwrap().to_string();
    assert_eq!(call(&t.private, "GET", &loc, &[], vec![]).await.status, 200);
    assert_eq!(call(&t.public, "GET", &loc, &[], vec![]).await.status, 404);
}

#[tokio::test]
async fn list_fields_and_reach_change_on_redeploy() {
    let t = setup_private();
    let ws = t.workspace("A", all_rights()).await;
    let first = put(&t, &ws, "moves", "auth = false").await;
    assert_eq!(first.status, 200);
    let l = t.api(&ws, "GET", "/v1/apps", vec![]).await.json();
    let i = &l["items"][0];
    assert_eq!(i["reach"], "public");
    assert_eq!(i["auth"], false);
    assert_eq!(i["public"], true);
    assert_eq!(i["url"], "https://publish.test/a/moves");
    // redeploy as private-network app: moves to the other listener
    let r = put(&t, &ws, "moves", "reach = \"private\"\nauth = false").await;
    assert_eq!(r.status, 200, "{}", r.text());
    assert_eq!(r.json()["url"], "http://publish.internal/a/moves");
    assert_eq!(
        call(&t.public, "GET", "/a/moves/", &[], vec![])
            .await
            .status,
        404
    );
    assert_eq!(
        call(&t.private, "GET", "/a/moves/", &[], vec![])
            .await
            .status,
        200
    );
    let l = t.api(&ws, "GET", "/v1/apps", vec![]).await.json();
    assert_eq!(l["items"][0]["reach"], "private");
    assert_eq!(l["items"][0]["url"], "http://publish.internal/a/moves");
    let all = t
        .adm("GET", "/admin/api/apps", serde_json::Value::Null)
        .await
        .json();
    assert_eq!(all["items"][0]["reach"], "private");
}

#[tokio::test]
async fn reach_change_rechecks_access() {
    use orch_publish::db;
    let t = setup_private();
    let ws = t.workspace("A", all_rights()).await;
    put(&t, &ws, "rr", "").await;
    let mut row = db::get_app(&t.st.db.lock().unwrap(), "rr")
        .unwrap()
        .unwrap();
    // an app row whose reach differs from the one a request was authorized against
    let old = row.clone();
    row.reach = "private".into();
    assert!(orch_publish::apps::access_changed(&old, &row).is_some());
}
