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
        "<title>site</title>v2"
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
        "<title>site</title>open"
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

#[tokio::test]
async fn static_html_gets_default_title_and_lang_only_when_missing() {
    let t = setup();
    let toml = format!("{STATIC_TOML}public = true\n");
    let ws = t.workspace("A", all_rights()).await;
    let r = deploy(
        &t,
        &ws,
        "site",
        &[
            ("app.toml", &toml),
            (
                "index.html",
                "<!doctype html><html><head></head><body>a</body></html>",
            ),
            (
                "full.html",
                "<html lang=\"de\"><head><title>Mine</title></head></html>",
            ),
        ],
        "",
    )
    .await;
    assert_eq!(r.status, 200, "{}", r.text());
    let a = call(&t.public, "GET", "/a/site/", &[], vec![]).await;
    let (st, body) = (a.status, a.text());
    if st == 200 {
        assert!(
            body.contains("<html lang=\"en\"><head><title>site</title>"),
            "{body}"
        );
        let b = call(&t.public, "GET", "/a/site/full.html", &[], vec![]).await;
        assert_eq!(
            b.text(),
            "<html lang=\"de\"><head><title>Mine</title></head></html>"
        );
    } else {
        panic!("status {st}: {body}");
    }
}

#[tokio::test]
async fn apps_delete_with_a_dotdot_name_touches_nothing() {
    let t = setup();
    let ws = t.workspace("A", basic_rights()).await;
    let marker = t.st.cfg.apps_dir.join("marker");
    std::fs::create_dir_all(&marker).unwrap();
    for n in ["%2e%2e", "..", "a%2Fb"] {
        let r = t.api(&ws, "DELETE", &format!("/v1/apps/{n}"), vec![]).await;
        assert!(
            r.status.as_u16() == 404 || r.status.as_u16() == 400,
            "{n}: {}",
            r.status
        );
    }
    assert!(marker.is_dir());
}

// ---- #614: apps are sandboxed from each other

fn csp_all(r: &Resp) -> Vec<String> {
    r.headers
        .get_all("content-security-policy")
        .iter()
        .map(|v| v.to_str().unwrap().to_string())
        .collect()
}

fn assert_sandboxed(r: &Resp, what: &str) {
    let all = csp_all(r);
    let ours = all
        .iter()
        .find(|c| c.starts_with("sandbox allow-scripts allow-forms"))
        .unwrap_or_else(|| panic!("{what}: no sandbox CSP in {all:?}"));
    assert_eq!(
        ours,
        "sandbox allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox allow-modals allow-downloads",
        "{what}"
    );
    for c in &all {
        assert!(!c.contains("allow-same-origin"), "{what}");
        assert!(!c.contains("allow-top-navigation"), "{what}");
    }
}

const CSP_APP: &str = r#"import os, json
from http.server import BaseHTTPRequestHandler, HTTPServer
HITS = []
class H(BaseHTTPRequestHandler):
    def _reply(self, extra=None):
        HITS.append(self.command)
        body = json.dumps(HITS).encode()
        self.send_response(200)
        self.send_header("Content-Security-Policy", "default-src 'self'")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self): self._reply()
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self._reply()
    def do_OPTIONS(self): self._reply()
    def log_message(self, *a):
        pass
HTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
"#;

#[tokio::test]
async fn apps_static_responses_are_sandboxed() {
    let t = setup();
    let ws = t.workspace("A", all_rights()).await;
    let r = deploy(
        &t,
        &ws,
        "site",
        &[
            ("app.toml", STATIC_TOML),
            ("index.html", "<h1>hi</h1>"),
            ("a.css", "body{}"),
            ("notes.md", "# T\n"),
        ],
        "?days=7",
    )
    .await;
    let tok = r.json()["view_token"].as_str().unwrap().to_string();
    // private notice (no cookie), wrong-token notice
    assert_sandboxed(
        &call(&t.public, "GET", "/a/site/", &[], vec![]).await,
        "private notice",
    );
    // missing app
    assert_sandboxed(
        &call(&t.public, "GET", "/a/nope/", &[], vec![]).await,
        "unknown app",
    );
    // token redirect
    let red = call(
        &t.public,
        "GET",
        &format!("/a/site/?token={tok}"),
        &[],
        vec![],
    )
    .await;
    assert_sandboxed(&red, "token redirect");
    let c = red.headers["set-cookie"]
        .to_str()
        .unwrap()
        .split(';')
        .next()
        .unwrap()
        .to_string();
    for (path, what) in [
        ("/a/site/", "html"),
        ("/a/site/a.css", "css"),
        ("/a/site/notes.md", "md"),
    ] {
        let r = call(&t.public, "GET", path, &[("cookie", &c)], vec![]).await;
        assert_eq!(r.status, 200, "{what}");
        assert_sandboxed(&r, what);
        // private app: no CORS at all, even for a null origin
        let r = call(
            &t.public,
            "GET",
            path,
            &[("cookie", &c), ("origin", "null")],
            vec![],
        )
        .await;
        assert!(
            r.headers.get("access-control-allow-origin").is_none(),
            "{what}"
        );
    }
    // private app preflight is not answered with CORS
    let pf = call(
        &t.public,
        "OPTIONS",
        "/a/site/",
        &[
            ("origin", "null"),
            ("access-control-request-method", "POST"),
        ],
        vec![],
    )
    .await;
    assert!(pf.headers.get("access-control-allow-origin").is_none());
    assert_sandboxed(&pf, "private preflight");
    // paused
    t.api(&ws, "POST", "/v1/apps/site/stop", vec![]).await;
    let r = call(&t.public, "GET", "/a/site/", &[("cookie", &c)], vec![]).await;
    assert_eq!(r.status, 503);
    assert_sandboxed(&r, "paused notice");
    // expired
    t.st.db
        .lock()
        .unwrap()
        .execute("UPDATE apps SET expires_at='2000-01-01T00:00:00Z'", [])
        .unwrap();
    let r = call(&t.public, "GET", "/a/site/", &[("cookie", &c)], vec![]).await;
    assert_eq!(r.status, 410);
    assert_sandboxed(&r, "expired notice");
}

#[tokio::test]
async fn apps_public_proxy_sandbox_and_cors_for_null_origin() {
    let t = setup();
    let ws = t.workspace("A", all_rights()).await;
    let toml = py_toml("poll", "public = true");
    assert_eq!(
        deploy(
            &t,
            &ws,
            "poll",
            &[("app.toml", &toml), ("main.py", CSP_APP)],
            ""
        )
        .await
        .status,
        200
    );
    // backend sends its own CSP: ours is added next to it, never replaced
    let r = call(&t.public, "GET", "/a/poll/", &[], vec![]).await;
    assert_eq!(r.status, 200);
    assert!(csp_all(&r).iter().any(|c| c == "default-src 'self'"));
    assert_sandboxed(&r, "proxied");
    // null origin gets ACAO null (overriding the backend's wildcard), no credentials
    let r = call(
        &t.public,
        "POST",
        "/a/poll/vote",
        &[("origin", "null")],
        b"{}".to_vec(),
    )
    .await;
    assert_eq!(r.headers["access-control-allow-origin"], "null");
    assert!(r.headers.get("access-control-allow-credentials").is_none());
    assert_sandboxed(&r, "proxied post");
    // preflight: answered here, backend never sees OPTIONS
    let pf = call(
        &t.public,
        "OPTIONS",
        "/a/poll/vote",
        &[
            ("origin", "null"),
            ("access-control-request-method", "POST"),
            ("access-control-request-headers", "content-type"),
        ],
        vec![],
    )
    .await;
    assert_eq!(pf.status, 204);
    assert_eq!(pf.headers["access-control-allow-origin"], "null");
    assert_eq!(
        pf.headers["access-control-allow-methods"],
        "GET, POST, PUT, PATCH, DELETE"
    );
    assert_eq!(pf.headers["access-control-allow-headers"], "content-type");
    assert_eq!(pf.headers["access-control-max-age"], "600");
    assert_sandboxed(&pf, "preflight");
    let hits = call(&t.public, "GET", "/a/poll/", &[], vec![]).await.json();
    assert!(!hits.to_string().contains("OPTIONS"), "{hits}");
}

#[tokio::test]
async fn apps_public_static_null_origin_gets_cors() {
    let t = setup();
    let ws = t.workspace("A", all_rights()).await;
    let toml = format!("{STATIC_TOML}public = true\n");
    deploy(
        &t,
        &ws,
        "site",
        &[("app.toml", &toml), ("index.html", "x")],
        "",
    )
    .await;
    let r = call(&t.public, "GET", "/a/site/", &[("origin", "null")], vec![]).await;
    assert_eq!(r.headers["access-control-allow-origin"], "null");
    // other origins get nothing
    let r = call(
        &t.public,
        "GET",
        "/a/site/",
        &[("origin", "https://evil.test")],
        vec![],
    )
    .await;
    assert!(r.headers.get("access-control-allow-origin").is_none());
}
