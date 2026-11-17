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

/// GET on the private listener with its own Host.
/// Same Host on either listener (the public one ignores it).
async fn any_get(r: &axum::Router, uri: &str) -> Resp {
    pget(r, uri).await
}

async fn with_host(r: &axum::Router, h: &str) -> Resp {
    call(r, "GET", "/a/priv/", &[("host", h)], vec![]).await
}

async fn pget(r: &axum::Router, uri: &str) -> Resp {
    call(r, "GET", uri, &[("host", "publish.internal")], vec![]).await
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
        let on = any_get(right, &uri).await;
        if auth {
            assert_eq!(on.status, 401, "{name}");
            let tok = j["view_token"].as_str().unwrap();
            let go = any_get(right, &format!("{uri}?token={tok}")).await;
            assert_eq!(go.status, 302, "{name}");
        } else {
            // open apps on the private network first move to their secret address
            let want = if private { 302 } else { 200 };
            assert_eq!(on.status, want, "{name}: {}", on.text());
            assert!(j["view_token"].is_null());
        }
        // on the other listener the app is missing, exactly like an app that never existed
        let off = any_get(wrong, &uri).await;
        let gone = any_get(wrong, "/a/nothere/").await;
        same(&off, &gone);
        assert_eq!(off.status, 404);
        // also without the trailing slash and with a token
        let off = any_get(wrong, &format!("/a/{name}?token=apv_x")).await;
        let gone = any_get(wrong, "/a/nothere?token=apv_x").await;
        same(&off, &gone);
    }
}

#[tokio::test]
async fn private_listener_serves_only_apps_assets_and_health() {
    let t = setup_private();
    let ws = t.workspace("A", all_rights()).await;
    put(&t, &ws, "priv", "reach = \"private\"\nauth = false").await;
    assert_eq!(pget(&t.private, "/health").await.status, 200);
    assert_eq!(pget(&t.private, "/_/style.css").await.status, 200);
    for p in [
        "/",
        "/v1/whoami",
        "/v1/apps",
        "/f/abc",
        "/onboarding.sh",
        "/admin",
    ] {
        let r = pget(&t.private, p).await;
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
    let rb = pget(
        &t.private,
        &format!("/a/pb/?token={}", b["view_token"].as_str().unwrap()),
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
    let r = pget(
        &t.private,
        &format!("/a/pb/?token={}", b["view_token"].as_str().unwrap()),
    )
    .await;
    let c = r.headers["set-cookie"].to_str().unwrap();
    assert!(c.contains("HttpOnly") && !c.contains("Secure"), "{c}");
    // the secret address works on the private listener
    let loc = r.headers["location"].to_str().unwrap().to_string();
    assert_eq!(pget(&t.private, &loc).await.status, 200);
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
    assert_eq!(pget(&t.private, "/a/moves/").await.status, 302);
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
    let r = orch_publish::apps::access_changed(&old, &row).unwrap();
    // answers like a missing app, not like the private-link page
    assert_eq!(r.status(), 404);
}

#[tokio::test]
async fn private_listener_refuses_a_foreign_host() {
    let t = setup_private();
    let ws = t.workspace("A", all_rights()).await;
    put(&t, &ws, "priv", "reach = \"private\"\nauth = false").await;
    let r = &t.private;
    let evil = with_host(r, "evil.example").await;
    assert_eq!(evil.status, 404);
    same(
        &evil,
        &call(
            &t.private,
            "GET",
            "/nope",
            &[("host", "publish.internal")],
            vec![],
        )
        .await,
    );
    assert_eq!(with_host(r, "publish.internal").await.status, 302);
    assert_eq!(with_host(r, "Publish.Internal:80").await.status, 302);
    assert_eq!(with_host(r, "publish.internal:81").await.status, 404);
    assert_eq!(
        call(&t.private, "GET", "/a/priv/", &[], vec![])
            .await
            .status,
        404
    );
    // /health is exempt
    let h = call(
        &t.private,
        "GET",
        "/health",
        &[("host", "evil.example")],
        vec![],
    )
    .await;
    assert_eq!(h.status, 200);
}

#[test]
fn private_listen_must_be_a_private_ip() {
    let mk = |l: Option<&str>, u: Option<&str>| {
        let mut c = orch_publish::Config::new(std::path::PathBuf::from("/x"), "t".into());
        c.private_listen = l.map(Into::into);
        c.private_url = u.map(Into::into);
        c.validate()
    };
    let u = Some("http://publish.internal");
    assert!(mk(None, None).is_ok());
    for ok in [
        "100.64.1.2:80",
        "10.1.2.3:80",
        "172.16.0.1:80",
        "192.168.1.1:80",
        "[fd00::1]:80",
        "127.0.0.1:8080",
    ] {
        assert!(mk(Some(ok), u).is_ok(), "{ok}");
    }
    for bad in [
        "0.0.0.0:80",
        "[::]:80",
        "8.8.8.8:80",
        "172.32.0.1:80",
        "100.128.0.1:80",
        "publish.internal:80",
        "10.1.2.3",
    ] {
        assert!(mk(Some(bad), u).is_err(), "{bad}");
    }
    assert!(mk(Some("10.1.2.3:80"), None).is_err());
    assert!(mk(Some("10.1.2.3:80"), Some("https://publish.severin.io/")).is_err());
}

#[tokio::test]
async fn moving_between_reaches_issues_a_new_link() {
    let t = setup_private();
    let ws = t.workspace("A", all_rights()).await;
    let first = put(&t, &ws, "mv", "reach = \"private\"").await.json();
    let tok1 = first["view_token"].as_str().unwrap().to_string();
    // same reach: token kept (no new one returned)
    assert!(put(&t, &ws, "mv", "reach = \"private\"").await.json()["view_token"].is_null());
    let moved = put(&t, &ws, "mv", "reach = \"public\"").await.json();
    let tok2 = moved["view_token"].as_str().unwrap();
    assert_ne!(tok1, tok2);
    assert_eq!(
        call(
            &t.public,
            "GET",
            &format!("/a/mv/?token={tok1}"),
            &[],
            vec![]
        )
        .await
        .status,
        401
    );
    assert_eq!(
        call(
            &t.public,
            "GET",
            &format!("/a/mv/?token={tok2}"),
            &[],
            vec![]
        )
        .await
        .status,
        302
    );
}

#[tokio::test]
async fn private_open_app_has_no_cors_but_a_cap_address() {
    let t = setup_private();
    let ws = t.workspace("A", all_rights()).await;
    put(&t, &ws, "po", "reach = \"private\"\nauth = false").await;
    put(&t, &ws, "pu", "reach = \"public\"\nauth = false").await;
    let hd = [("host", "publish.internal"), ("origin", "null")];
    // cross-origin fetch of the plain address: redirect, no ACAO
    let r = call(&t.private, "GET", "/a/po/", &hd, vec![]).await;
    assert_eq!(r.status, 302);
    assert!(r.headers.get("access-control-allow-origin").is_none());
    let loc = r.headers["location"].to_str().unwrap().to_string();
    assert!(loc.starts_with("/a/po/~"), "{loc}");
    let pre = call(
        &t.private,
        "OPTIONS",
        "/a/po/x",
        &[
            ("host", "publish.internal"),
            ("origin", "null"),
            ("access-control-request-method", "GET"),
        ],
        vec![],
    )
    .await;
    assert!(pre.headers.get("access-control-allow-origin").is_none());
    // navigation works, and the app's own fetch under ~cap gets CORS
    let nav = pget(&t.private, "/a/po/").await;
    assert_eq!(nav.status, 302);
    let page = pget(&t.private, &loc).await;
    assert_eq!(page.status, 200);
    let own = call(&t.private, "GET", &loc, &hd, vec![]).await;
    assert_eq!(own.status, 200);
    assert_eq!(own.headers["access-control-allow-origin"], "null");
    // public open apps are unchanged
    let p = call(&t.public, "GET", "/a/pu/", &[("origin", "null")], vec![]).await;
    assert_eq!(p.status, 200);
    assert_eq!(p.headers["access-control-allow-origin"], "null");
}

#[tokio::test]
async fn moved_app_answers_missing_even_when_stopped() {
    use orch_publish::db;
    let t = setup_private();
    let ws = t.workspace("A", all_rights()).await;
    put(&t, &ws, "mm", "").await;
    let old = db::get_app(&t.st.db.lock().unwrap(), "mm")
        .unwrap()
        .unwrap();
    let mut new = old.clone();
    new.reach = "private".into();
    new.status = "stopped".into();
    assert_eq!(
        orch_publish::apps::access_changed(&old, &new)
            .unwrap()
            .status(),
        404
    );
}

/// The `~cap` an open private-network app currently answers with.
async fn open_cap(t: &T, name: &str) -> String {
    let r = pget(&t.private, &format!("/a/{name}/")).await;
    assert_eq!(r.status, 302);
    r.headers["location"].to_str().unwrap().to_string()
}

#[tokio::test]
async fn open_cap_rotates_on_reach_auth_change_and_recreate() {
    let t = setup_private();
    let ws = t.workspace("A", all_rights()).await;
    let open = "reach = \"private\"\nauth = false";
    put(&t, &ws, "rc", open).await;
    let cap1 = open_cap(&t, "rc").await;
    // same settings: the address stays
    put(&t, &ws, "rc", open).await;
    assert_eq!(open_cap(&t, "rc").await, cap1);
    assert_eq!(pget(&t.private, &cap1).await.status, 200);
    // auth change and back: new address, old one is gone
    put(&t, &ws, "rc", "reach = \"private\"").await;
    put(&t, &ws, "rc", open).await;
    let cap2 = open_cap(&t, "rc").await;
    assert_ne!(cap1, cap2);
    assert_eq!(pget(&t.private, &cap1).await.status, 404);
    assert_eq!(pget(&t.private, &cap2).await.status, 200);
    // reach move and back
    put(&t, &ws, "rc", "reach = \"public\"\nauth = false").await;
    put(&t, &ws, "rc", open).await;
    let cap3 = open_cap(&t, "rc").await;
    assert_ne!(cap2, cap3);
    assert_eq!(pget(&t.private, &cap2).await.status, 404);
    // delete + recreate (even by another workspace): new address
    let del = t.api(&ws, "DELETE", "/v1/apps/rc", vec![]).await;
    assert!(del.status.is_success(), "{}", del.status);
    let ws2 = t.workspace("B", all_rights()).await;
    put(&t, &ws2, "rc", open).await;
    let cap4 = open_cap(&t, "rc").await;
    assert_ne!(cap3, cap4);
    assert_eq!(pget(&t.private, &cap3).await.status, 404);
    assert_eq!(pget(&t.private, &cap4).await.status, 200);
}

/// A python app that answers every request with `word`.
fn word_app(word: &str) -> String {
    format!(
        "import os\nfrom http.server import BaseHTTPRequestHandler, HTTPServer\nclass H(BaseHTTPRequestHandler):\n    def do_GET(self):\n        self.send_response(200)\n        self.end_headers()\n        self.wfile.write(b\"{word}\")\n    def log_message(self, *a):\n        pass\nHTTPServer((\"127.0.0.1\", int(os.environ[\"PORT\"])), H).serve_forever()\n"
    )
}

async fn put_py(t: &T, ws: &(String, String), name: &str, extra: &str, word: &str) -> Resp {
    let toml = py_toml(name, extra);
    t.api(
        ws,
        "PUT",
        &format!("/v1/apps/{name}?days=7"),
        bundle(&[("app.toml", &toml), ("main.py", &word_app(word))]),
    )
    .await
}

/// Redeploy private-open -> public: the OLD process (private-only content) is never served on the
/// public listener, at any moment of the swap.
#[tokio::test]
async fn redeploy_never_serves_old_process_under_new_access() {
    let t = setup_private();
    let ws = t.workspace("A", all_rights()).await;
    let r = put_py(&t, &ws, "rr", "reach = \"private\"\nauth = false", "old").await;
    assert_eq!(r.status, 200, "{}", r.text());
    let done = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let (pub_r, flag) = (t.public.clone(), done.clone());
    let poller = tokio::spawn(async move {
        let mut seen = vec![];
        while !flag.load(std::sync::atomic::Ordering::SeqCst) {
            let g = call(&pub_r, "GET", "/a/rr/", &[], vec![]).await;
            seen.push((g.status.as_u16(), g.text()));
            tokio::task::yield_now().await;
        }
        seen
    });
    let r = put_py(&t, &ws, "rr", "reach = \"public\"\nauth = false", "new").await;
    assert_eq!(r.status, 200, "{}", r.text());
    done.store(true, std::sync::atomic::Ordering::SeqCst);
    for (status, body) in poller.await.unwrap() {
        assert!(
            !(status == 200 && body == "old"),
            "old process served under the new access"
        );
    }
    let g = call(&t.public, "GET", "/a/rr/", &[], vec![]).await;
    assert_eq!((g.status.as_u16(), g.text()), (200, "new".to_string()));
}

#[tokio::test]
async fn redeploy_writes_the_row_before_the_new_process_is_live() {
    use orch_publish::db;
    let t = setup_private();
    let ws = t.workspace("A", all_rights()).await;
    put(&t, &ws, "rd", "reach = \"private\"\nauth = false").await;
    let before = db::get_app(&t.st.db.lock().unwrap(), "rd")
        .unwrap()
        .unwrap();
    put(&t, &ws, "rd", "reach = \"public\"\nauth = false").await;
    let after = db::get_app(&t.st.db.lock().unwrap(), "rd")
        .unwrap()
        .unwrap();
    assert_eq!(after.reach, "public");
    assert_ne!(before.cap_nonce, after.cap_nonce);
    assert!(!after.cap_nonce.is_empty());
    // the old private address is not served any more, the new reach answers at once
    assert_eq!(pget(&t.private, "/a/rd/").await.status, 404);
    assert_eq!(
        call(&t.public, "GET", "/a/rd/", &[], vec![]).await.status,
        200
    );
}

/// Same swap with a slow stop (as a container or unit that takes its time): while the old process stops,
/// no request reaches it under the new access. Fails when the row is written while the old process is
/// still routable (e.g. `put_app` then `stop(name)`).
#[tokio::test]
async fn redeploy_with_a_slow_stop_never_serves_old_process_under_new_access() {
    let t = setup_private();
    let ws = t.workspace("A", all_rights()).await;
    let r = put_py(&t, &ws, "rs", "reach = \"private\"\nauth = false", "old").await;
    assert_eq!(r.status, 200, "{}", r.text());
    t.st.runner
        .set_stop_delay(std::time::Duration::from_millis(1500));
    let done = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let (pub_r, flag) = (t.public.clone(), done.clone());
    let poller = tokio::spawn(async move {
        let mut seen = vec![];
        while !flag.load(std::sync::atomic::Ordering::SeqCst) {
            let g = call(&pub_r, "GET", "/a/rs/", &[], vec![]).await;
            seen.push((g.status.as_u16(), g.text()));
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        seen
    });
    let r = put_py(&t, &ws, "rs", "reach = \"public\"\nauth = false", "new").await;
    assert_eq!(r.status, 200, "{}", r.text());
    done.store(true, std::sync::atomic::Ordering::SeqCst);
    let seen = poller.await.unwrap();
    assert!(
        !seen.iter().any(|(s, b)| *s == 200 && b == "old"),
        "old process served under the new access"
    );
    // requests really ran while the old process was stopping: the new one already answered then
    assert!(
        seen.iter().any(|(s, b)| *s == 200 && b == "new"),
        "no request ran during the slow stop"
    );
}

/// The client goes away while the old process stops: the deploy still runs to the end, the old process
/// is stopped and its version folder removed.
#[tokio::test]
async fn redeploy_finishes_when_the_client_goes_away() {
    use orch_publish::db;
    let t = setup();
    let ws = t.workspace("A", all_rights()).await;
    let open = "reach = \"public\"\nauth = false";
    let r = put_py(&t, &ws, "rg", open, "old").await;
    assert_eq!(r.status, 200, "{}", r.text());
    let old = db::get_app(&t.st.db.lock().unwrap(), "rg")
        .unwrap()
        .unwrap();
    let root = t.st.cfg.app_root("rg");
    let old_v = std::path::Path::new(&old.code_dir)
        .ancestors()
        .find(|a| a.parent() == Some(root.as_path()))
        .unwrap()
        .to_path_buf();
    assert!(old_v.is_dir());
    t.st.runner
        .set_stop_delay(std::time::Duration::from_millis(1500));
    let (pub_r, toml) = (t.public.clone(), py_toml("rg", open));
    let (wid, tok) = ws.clone();
    let deploy = tokio::spawn(async move {
        call(
            &pub_r,
            "PUT",
            "/v1/apps/rg?days=7",
            &[
                ("x-orch-workspace", &wid),
                ("authorization", &format!("Bearer {tok}")),
            ],
            bundle(&[("app.toml", &toml), ("main.py", &word_app("new"))]),
        )
        .await
    });
    // the new process took the name: the deploy is now waiting for the old one to stop
    let t0 = std::time::Instant::now();
    loop {
        let g = call(&t.public, "GET", "/a/rg/", &[], vec![]).await;
        if g.status == 200 && g.text() == "new" {
            break;
        }
        if t0.elapsed().as_secs() > 30 {
            let r = deploy.await.unwrap();
            panic!(
                "new version never answered: last {} {} / deploy {} {}",
                g.status,
                g.text(),
                r.status,
                r.text()
            );
        }
        tokio::time::sleep(std::time::Duration::from_millis(20)).await;
    }
    deploy.abort();
    let t1 = std::time::Instant::now();
    while old_v.exists() {
        assert!(
            t1.elapsed().as_secs() < 10,
            "deploy stopped with the client: old version left behind"
        );
        tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    }
    let g = call(&t.public, "GET", "/a/rg/", &[], vec![]).await;
    assert_eq!((g.status.as_u16(), g.text()), (200, "new".to_string()));
}

/// A request authorized just before a redeploy switched the stack (static <-> process) gets the
/// try-again page, not the private-link page: its access did not change.
#[tokio::test]
async fn stack_change_alone_answers_try_again_not_private() {
    use orch_publish::db;
    let t = setup();
    let ws = t.workspace("A", all_rights()).await;
    put(&t, &ws, "sc", "").await;
    let old = db::get_app(&t.st.db.lock().unwrap(), "sc")
        .unwrap()
        .unwrap();
    let mut new = old.clone();
    new.stack = if old.stack == "static" {
        "python"
    } else {
        "static"
    }
    .into();
    let r = orch_publish::apps::access_changed(&old, &new).unwrap();
    assert_eq!(r.status(), 503);
    // an access change together with the stack change still answers private
    new.public = !old.public;
    let r = orch_publish::apps::access_changed(&old, &new).unwrap();
    assert_eq!(r.status(), 401);
}
