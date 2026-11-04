mod common;
use common::*;

const STATIC_TOML: &str = "name = \"site\"\nstack = \"static\"\nabout = \"x\"\n";

async fn deploy(t: &T, ws: &(String, String), name: &str, files: &[(&str, &str)], q: &str) -> Resp {
    t.api(ws, "PUT", &format!("/v1/apps/{name}{q}"), bundle(files))
        .await
}

#[tokio::test]
async fn apps_static_private_token_flow() {
    let t = setup();
    let ws = t.workspace("A", basic_rights()).await;
    let r = deploy(
        &t,
        &ws,
        "site",
        &[
            ("app.toml", STATIC_TOML),
            ("index.html", "<h1>hi</h1>"),
            ("notes.md", "# Title\n\n- one\n- **two**\n"),
        ],
        "?days=7",
    )
    .await;
    assert_eq!(r.status, 200, "{}", r.text());
    let j = r.json();
    assert_eq!(j["status"], "running");
    assert_eq!(j["url"], "https://publish.test/a/site");
    let tok = j["view_token"].as_str().unwrap().to_string();
    assert!(tok.starts_with("apv_") && tok.len() == 26);

    // no token: private page 401
    let p = call(&t.public, "GET", "/a/site/", &[], vec![]).await;
    assert_eq!(p.status, 401);
    assert!(p.text().contains("This app is private"));
    // wrong token: 401
    assert_eq!(
        call(&t.public, "GET", "/a/site/?token=apv_nope", &[], vec![])
            .await
            .status,
        401
    );
    // token: cookie + redirect without token
    let r = call(
        &t.public,
        "GET",
        &format!("/a/site/?token={tok}"),
        &[],
        vec![],
    )
    .await;
    assert_eq!(r.status, 302);
    assert_eq!(r.headers["location"], "/a/site/");
    let cookie = r.headers["set-cookie"].to_str().unwrap().to_string();
    assert!(
        cookie.contains("HttpOnly")
            && cookie.contains("SameSite=Lax")
            && cookie.contains("Path=/a/site/")
    );
    let c = cookie.split(';').next().unwrap().to_string();
    let ok = call(&t.public, "GET", "/a/site/", &[("cookie", &c)], vec![]).await;
    assert_eq!(ok.status, 200);
    assert!(ok.text().contains("<h1>hi</h1>"));
    // markdown page rendered
    let md = call(
        &t.public,
        "GET",
        "/a/site/notes.md",
        &[("cookie", &c)],
        vec![],
    )
    .await;
    assert!(md.text().contains("<h1>Title</h1>") && md.text().contains("<strong>two</strong>"));
    // no traversal, app.toml hidden
    assert_eq!(
        call(
            &t.public,
            "GET",
            "/a/site/app.toml",
            &[("cookie", &c)],
            vec![]
        )
        .await
        .status,
        404
    );
    // slash redirect
    assert_eq!(
        call(&t.public, "GET", "/a/site", &[("cookie", &c)], vec![])
            .await
            .status,
        308
    );

    // redeploy keeps token (not returned again); ?new_token=1 makes a new one
    let r2 = deploy(
        &t,
        &ws,
        "site",
        &[("app.toml", STATIC_TOML), ("index.html", "v2")],
        "",
    )
    .await
    .json();
    assert!(r2["view_token"].is_null());
    assert_eq!(
        call(&t.public, "GET", "/a/site/", &[("cookie", &c)], vec![])
            .await
            .text(),
        "v2"
    );
    let r3 = deploy(
        &t,
        &ws,
        "site",
        &[("app.toml", STATIC_TOML), ("index.html", "v3")],
        "?new_token=1",
    )
    .await
    .json();
    assert!(r3["view_token"].as_str().unwrap().starts_with("apv_"));
    assert_eq!(
        call(&t.public, "GET", "/a/site/", &[("cookie", &c)], vec![])
            .await
            .status,
        401
    );
}

#[tokio::test]
async fn apps_public_needs_right() {
    let t = setup();
    let basic = t.workspace("A", basic_rights()).await;
    let toml = format!("{STATIC_TOML}public = true\n");
    let r = deploy(
        &t,
        &basic,
        "site",
        &[("app.toml", &toml), ("index.html", "open")],
        "",
    )
    .await;
    assert_eq!(r.status, 403);
    let all = t.workspace("B", all_rights()).await;
    let r = deploy(
        &t,
        &all,
        "site",
        &[("app.toml", &toml), ("index.html", "open")],
        "",
    )
    .await;
    assert_eq!(r.status, 200);
    assert!(r.json()["view_token"].is_null());
    assert_eq!(
        call(&t.public, "GET", "/a/site/", &[], vec![]).await.text(),
        "open"
    );
}

#[tokio::test]
async fn apps_validation_and_ownership() {
    let t = setup();
    let a = t.workspace("A", basic_rights()).await;
    let b = t.workspace("B", basic_rights()).await;
    assert_eq!(t.api(&a, "PUT", "/v1/apps/X", vec![]).await.status, 422);
    assert_eq!(
        deploy(&t, &a, "site", &[("index.html", "x")], "")
            .await
            .status,
        422
    );
    assert_eq!(
        deploy(
            &t,
            &a,
            "site",
            &[("app.toml", "name = \"other\"\nstack = \"static\"\n")],
            ""
        )
        .await
        .status,
        422
    );
    assert_eq!(
        deploy(
            &t,
            &a,
            "site",
            &[("app.toml", "name = \"site\"\nstack = \"python\"\n")],
            ""
        )
        .await
        .status,
        422
    );
    assert_eq!(
        t.api(&a, "PUT", "/v1/apps/site", b"junk".to_vec())
            .await
            .status,
        422
    );
    assert_eq!(
        deploy(&t, &a, "site", &[("app.toml", STATIC_TOML)], "")
            .await
            .status,
        200
    );
    // name taken by another workspace
    assert_eq!(
        deploy(&t, &b, "site", &[("app.toml", STATIC_TOML)], "")
            .await
            .status,
        409
    );
    assert_eq!(
        t.api(&b, "POST", "/v1/apps/site/stop", vec![]).await.status,
        404
    );
    assert_eq!(
        t.api(&b, "DELETE", "/v1/apps/site", vec![]).await.status,
        404
    );
    assert_eq!(
        t.api(&b, "GET", "/v1/apps", vec![]).await.json()["items"]
            .as_array()
            .unwrap()
            .len(),
        0
    );
    // bundle inside one top folder works
    let r = t
        .api(
            &a,
            "PUT",
            "/v1/apps/boxed",
            bundle(&[
                ("dir/app.toml", "name = \"boxed\"\nstack = \"static\"\n"),
                ("dir/index.html", "boxed"),
            ]),
        )
        .await;
    assert_eq!(r.status, 200, "{}", r.text());
}

#[tokio::test]
async fn apps_python_runs_behind_proxy() {
    let t = setup();
    let ws = t.workspace("A", all_rights()).await;
    let toml = py_toml("pyapp", "public = true\nstore = \"json\"");
    let r = deploy(
        &t,
        &ws,
        "pyapp",
        &[("app.toml", &toml), ("main.py", PY_APP)],
        "?days=7",
    )
    .await;
    assert_eq!(r.status, 200, "{}", r.text());
    let g = call(&t.public, "GET", "/a/pyapp/some/path?x=1", &[], vec![]).await;
    assert_eq!(g.status, 200);
    assert_eq!(g.text(), "hello /some/path?x=1 /a/pyapp");
    let l = t.api(&ws, "GET", "/v1/apps", vec![]).await.json();
    assert_eq!(l["items"][0]["status"], "running");
    assert_eq!(l["items"][0]["stack"], "python");
    assert_eq!(l["items"][0]["store"], "json");
    assert!(t.dir.path().join("apps/pyapp/data").is_dir());

    // stop / restart
    let s = t.api(&ws, "POST", "/v1/apps/pyapp/stop", vec![]).await;
    assert_eq!(s.json()["status"], "stopped");
    let paused = call(&t.public, "GET", "/a/pyapp/", &[], vec![]).await;
    assert_eq!(paused.status, 503);
    assert!(paused.text().contains("This app is paused"));
    let s = t.api(&ws, "POST", "/v1/apps/pyapp/restart", vec![]).await;
    assert_eq!(s.json()["status"], "running");
    assert_eq!(
        call(&t.public, "GET", "/a/pyapp/x", &[], vec![])
            .await
            .text(),
        "hello /x /a/pyapp"
    );

    // delete removes code and data
    assert_eq!(
        t.api(&ws, "DELETE", "/v1/apps/pyapp", vec![]).await.status,
        204
    );
    assert_eq!(
        call(&t.public, "GET", "/a/pyapp/", &[], vec![])
            .await
            .status,
        404
    );
    assert!(!t.dir.path().join("apps/pyapp").exists());
}

#[tokio::test]
async fn apps_failed_test_keeps_old_version() {
    let t = setup();
    let ws = t.workspace("A", all_rights()).await;
    let ok = py_toml("keep", "public = true");
    assert_eq!(
        deploy(
            &t,
            &ws,
            "keep",
            &[("app.toml", &ok), ("main.py", PY_APP)],
            ""
        )
        .await
        .status,
        200
    );
    let bad = py_toml("keep", "public = true\ntest = \"echo boom-output; exit 1\"");
    let r = deploy(
        &t,
        &ws,
        "keep",
        &[("app.toml", &bad), ("main.py", "raise SystemExit(0)")],
        "",
    )
    .await;
    assert_eq!(r.status, 422);
    let j = r.json();
    assert_eq!(j["error"], "test_failed");
    assert!(j["output"].as_str().unwrap().contains("boom-output"));
    // old version still answers
    assert_eq!(
        call(&t.public, "GET", "/a/keep/", &[], vec![]).await.text(),
        "hello / /a/keep"
    );
}

#[tokio::test]
async fn apps_failed_health_keeps_old_version() {
    let t = setup_with(|c| c.health_secs = 3);
    let ws = t.workspace("A", all_rights()).await;
    let ok = py_toml("hk", "public = true");
    assert_eq!(
        deploy(&t, &ws, "hk", &[("app.toml", &ok), ("main.py", PY_APP)], "")
            .await
            .status,
        200
    );
    let r = deploy(
        &t,
        &ws,
        "hk",
        &[
            ("app.toml", &ok),
            ("main.py", "import sys\nprint('crash-output')\nsys.exit(3)"),
        ],
        "",
    )
    .await;
    assert_eq!(r.status, 422);
    assert_eq!(r.json()["error"], "health_failed");
    assert!(r.json()["output"]
        .as_str()
        .unwrap()
        .contains("crash-output"));
    assert_eq!(
        call(&t.public, "GET", "/a/hk/", &[], vec![]).await.text(),
        "hello / /a/hk"
    );
}

#[tokio::test]
async fn apps_sweep_removes_expired() {
    let t = setup();
    let ws = t.workspace("A", basic_rights()).await;
    deploy(&t, &ws, "site", &[("app.toml", STATIC_TOML)], "").await;
    t.st.db
        .lock()
        .unwrap()
        .execute("UPDATE apps SET expires_at='2000-01-01T00:00:00Z'", [])
        .unwrap();
    let c = "orch_app_site=x";
    assert_eq!(
        call(&t.public, "GET", "/a/site/", &[("cookie", c)], vec![])
            .await
            .status,
        410
    );
    orch_publish::sweep::sweep(&t.st).await;
    assert_eq!(
        call(&t.public, "GET", "/a/site/", &[], vec![]).await.status,
        404
    );
    assert!(!t.dir.path().join("apps/site").exists());
}

const ECHO_APP: &str = r#"import os, json
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({k.lower(): v for k, v in self.headers.items()}).encode()
        self.send_response(200)
        self.send_header("Service-Worker-Allowed", "/")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass
HTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
"#;

#[tokio::test]
async fn apps_proxy_strips_orch_credentials() {
    let t = setup();
    let ws = t.workspace("A", all_rights()).await;
    let toml = py_toml("echo", "public = true");
    assert_eq!(
        deploy(
            &t,
            &ws,
            "echo",
            &[("app.toml", &toml), ("main.py", ECHO_APP)],
            ""
        )
        .await
        .status,
        200
    );
    let r = call(
        &t.public,
        "GET",
        "/a/echo/",
        &[
            ("authorization", "Bearer orp_secret"),
            ("x-orch-workspace", "ws_x"),
            ("x-orch-admin", "adm"),
            ("cookie", "orch_admin=a; orch_app_other=tok; mine=1"),
        ],
        vec![],
    )
    .await;
    assert_eq!(r.status, 200);
    assert!(r.headers.get("service-worker-allowed").is_none());
    let h = r.json();
    assert!(
        h.get("authorization").is_none()
            && h.get("x-orch-workspace").is_none()
            && h.get("x-orch-admin").is_none()
    );
    assert_eq!(h["cookie"], "mine=1");
}
