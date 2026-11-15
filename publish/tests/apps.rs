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
    let loc = r.headers["location"].to_str().unwrap().to_string();
    assert!(
        loc.starts_with("/a/site/~") && loc.ends_with('/') && loc.len() == "/a/site/~/".len() + 32
    );
    let cap_base = loc.clone();
    let cookie = r.headers["set-cookie"].to_str().unwrap().to_string();
    assert!(
        cookie.contains("HttpOnly")
            && cookie.contains("SameSite=Lax")
            && cookie.contains("Path=/a/site/")
    );
    let c = cookie.split(';').next().unwrap().to_string();
    // cookie navigation moves to the capability path
    let nav = call(&t.public, "GET", "/a/site/?x=1", &[("cookie", &c)], vec![]).await;
    assert_eq!(nav.status, 302);
    assert_eq!(
        nav.headers["location"].to_str().unwrap(),
        format!("{cap_base}?x=1")
    );
    // the capability path serves without any cookie
    let ok = call(&t.public, "GET", &cap_base, &[], vec![]).await;
    assert_eq!(ok.status, 200);
    assert!(ok.text().contains("<h1>hi</h1>"));
    assert_eq!(ok.headers["referrer-policy"], "no-referrer");
    assert_eq!(ok.headers["cache-control"], "private, no-store");
    // no slash after the cap: redirect
    assert_eq!(
        call(
            &t.public,
            "GET",
            cap_base.trim_end_matches('/'),
            &[],
            vec![]
        )
        .await
        .status,
        308
    );
    // wrong cap, no cookie: private page; wrong cap with cookie: not served from the cap
    let bad = format!("/a/site/~{}/", "0".repeat(32));
    let r = call(&t.public, "GET", &bad, &[], vec![]).await;
    assert_eq!(r.status, 401);
    assert!(r.text().contains("This app is private"));
    assert_eq!(
        call(&t.public, "GET", "/a/site/~/", &[], vec![])
            .await
            .status,
        401
    );
    // markdown page rendered
    let md = call(
        &t.public,
        "GET",
        &format!("{cap_base}notes.md"),
        &[],
        vec![],
    )
    .await;
    assert!(md.text().contains("<h1>Title</h1>") && md.text().contains("<strong>two</strong>"));
    // no traversal, app.toml hidden
    assert_eq!(
        call(
            &t.public,
            "GET",
            &format!("{cap_base}app.toml"),
            &[],
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
        call(&t.public, "GET", &cap_base, &[], vec![]).await.text(),
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
    // a rotated token kills the old capability too
    assert_eq!(
        call(&t.public, "GET", &cap_base, &[], vec![]).await.status,
        401
    );
    // and the new token yields a different cap
    let nt = r3["view_token"].as_str().unwrap();
    let r = call(
        &t.public,
        "GET",
        &format!("/a/site/?token={nt}"),
        &[],
        vec![],
    )
    .await;
    let new_loc = r.headers["location"].to_str().unwrap().to_string();
    assert_ne!(new_loc, cap_base);
    assert_eq!(
        call(&t.public, "GET", &new_loc, &[], vec![]).await.text(),
        "<title>site</title>v3"
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
    let cap = red.headers["location"].to_str().unwrap().to_string();
    for (path, what) in [
        (cap.clone(), "html"),
        (format!("{cap}a.css"), "css"),
        (format!("{cap}notes.md"), "md"),
    ] {
        let r = call(&t.public, "GET", &path, &[], vec![]).await;
        assert_eq!(r.status, 200, "{what}");
        assert_eq!(r.headers["referrer-policy"], "no-referrer", "{what}");
        assert_sandboxed(&r, what);
        // private app: a null origin gets CORS only because the path carries the capability
        let r = call(&t.public, "GET", &path, &[("origin", "null")], vec![]).await;
        assert_eq!(r.headers["access-control-allow-origin"], "null", "{what}");
        assert!(r.headers.get("access-control-allow-credentials").is_none());
        // the same request without the capability (cookie path) gets none
        let r = call(
            &t.public,
            "GET",
            &path.replacen(&cap, "/a/site/", 1),
            &[("origin", "null"), ("cookie", &c)],
            vec![],
        )
        .await;
        assert!(
            r.headers.get("access-control-allow-origin").is_none(),
            "{what}"
        );
    }
    // preflight on the capability path is answered, without it is not
    let pf = call(
        &t.public,
        "OPTIONS",
        &cap,
        &[
            ("origin", "null"),
            ("access-control-request-method", "POST"),
        ],
        vec![],
    )
    .await;
    assert_eq!(pf.status, 204);
    assert_eq!(pf.headers["access-control-allow-origin"], "null");
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
    let r = call(&t.public, "GET", &cap, &[], vec![]).await;
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
    assert_eq!(
        pf.headers["access-control-allow-headers"],
        "content-type, accept, x-requested-with"
    );
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

const PATH_APP: &str = r#"import os
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = self.path.encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass
HTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
"#;

#[tokio::test]
async fn apps_private_proxy_strips_the_cap_before_forwarding() {
    let t = setup();
    let ws = t.workspace("A", all_rights()).await;
    let toml = py_toml("priv", "");
    let r = deploy(
        &t,
        &ws,
        "priv",
        &[("app.toml", &toml), ("main.py", PATH_APP)],
        "",
    )
    .await;
    assert_eq!(r.status, 200, "{}", r.text());
    let tok = r.json()["view_token"].as_str().unwrap().to_string();
    let red = call(
        &t.public,
        "GET",
        &format!("/a/priv/some/x?token={tok}&a=1"),
        &[],
        vec![],
    )
    .await;
    assert_eq!(red.status, 302);
    let loc = red.headers["location"].to_str().unwrap().to_string();
    assert!(loc.contains("/~") && loc.ends_with("/some/x?a=1"), "{loc}");
    let g = call(&t.public, "GET", &loc, &[], vec![]).await;
    assert_eq!(g.status, 200);
    assert_eq!(g.text(), "/some/x?a=1");
    assert_eq!(g.headers["referrer-policy"], "no-referrer");
    assert!(g.headers.get("access-control-allow-origin").is_none());
    let gn = call(&t.public, "GET", &loc, &[("origin", "null")], vec![]).await;
    assert_eq!(gn.headers["access-control-allow-origin"], "null");
    // wrong cap: private page, nothing forwarded
    let bad = call(
        &t.public,
        "GET",
        &format!("/a/priv/~{}/x", "1".repeat(32)),
        &[],
        vec![],
    )
    .await;
    assert_eq!(bad.status, 401);
}

const COOKIE_APP: &str = r#"import os
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        for c in ["orch_app_other=1; Path=/a/ck/", "ORCH_admin=x; Path=/a/ck/", "o=1; Path=/a/other/", "d=1; Path=/a/ck/; Domain=x.test",
                  "nopath=1", "mine=1; Path=/a/ck/", "mine2=1; path=/a/ck/sub; HttpOnly", "dot=1; Path=/a/ck/../other/"]:
            self.send_header("Set-Cookie", c)
        self.send_header("Clear-Site-Data", '"cookies"')
        self.send_header("Refresh", "0; url=http://evil.test/")
        self.send_header("Link", "<http://evil.test/>; rel=preload")
        self.send_header("Content-Length", "0")
        self.end_headers()
    def log_message(self, *a):
        pass
HTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
"#;

#[tokio::test]
async fn apps_proxy_drops_dangerous_cookies_and_headers() {
    let t = setup();
    let ws = t.workspace("A", all_rights()).await;
    let toml = py_toml("ck", "public = true");
    assert_eq!(
        deploy(
            &t,
            &ws,
            "ck",
            &[("app.toml", &toml), ("main.py", COOKIE_APP)],
            ""
        )
        .await
        .status,
        200
    );
    let r = call(&t.public, "GET", "/a/ck/", &[], vec![]).await;
    let cookies: Vec<String> = r
        .headers
        .get_all("set-cookie")
        .iter()
        .map(|v| v.to_str().unwrap().to_string())
        .collect();
    assert_eq!(
        cookies,
        vec!["mine=1; Path=/a/ck/", "mine2=1; path=/a/ck/sub; HttpOnly"],
        "{cookies:?}"
    );
    assert!(r.headers.get("clear-site-data").is_none());
    // public apps keep Refresh and Link, private ones lose them
    assert!(r.headers.get("refresh").is_some());
    let toml = py_toml("ckp", "");
    let body = COOKIE_APP.replace("/a/ck/", "/a/ckp/");
    let d = deploy(
        &t,
        &ws,
        "ckp",
        &[("app.toml", &toml), ("main.py", &body)],
        "",
    )
    .await;
    let tok = d.json()["view_token"].as_str().unwrap().to_string();
    let red = call(
        &t.public,
        "GET",
        &format!("/a/ckp/?token={tok}"),
        &[],
        vec![],
    )
    .await;
    let loc = red.headers["location"].to_str().unwrap().to_string();
    let r = call(&t.public, "GET", &loc, &[], vec![]).await;
    assert_eq!(r.status, 200);
    assert!(r.headers.get("refresh").is_none() && r.headers.get("link").is_none());
}

#[tokio::test]
async fn apps_expired_or_paused_private_app_ignores_its_cap_for_cors() {
    let t = setup();
    let ws = t.workspace("A", all_rights()).await;
    let r = deploy(
        &t,
        &ws,
        "site",
        &[("app.toml", STATIC_TOML), ("index.html", "x")],
        "",
    )
    .await;
    let tok = r.json()["view_token"].as_str().unwrap().to_string();
    let red = call(
        &t.public,
        "GET",
        &format!("/a/site/?token={tok}"),
        &[],
        vec![],
    )
    .await;
    let cap = red.headers["location"].to_str().unwrap().to_string();
    let pf = [
        ("origin", "null"),
        ("access-control-request-method", "POST"),
        ("access-control-request-headers", "x-evil"),
    ];
    let ok = call(&t.public, "OPTIONS", &cap, &pf, vec![]).await;
    assert_eq!(ok.status, 204);
    // fixed list, never a reflection
    assert_eq!(
        ok.headers["access-control-allow-headers"],
        "content-type, accept, x-requested-with"
    );
    assert!(ok.headers.get_all("vary").iter().any(|v| v == "Origin"));
    // paused
    t.api(&ws, "POST", "/v1/apps/site/stop", vec![]).await;
    let r = call(&t.public, "GET", &cap, &[("origin", "null")], vec![]).await;
    assert_eq!(r.status, 503);
    assert!(r.headers.get("access-control-allow-origin").is_none());
    assert_ne!(
        call(&t.public, "OPTIONS", &cap, &pf, vec![]).await.status,
        204
    );
    t.api(&ws, "POST", "/v1/apps/site/restart", vec![]).await;
    // expired
    t.st.db
        .lock()
        .unwrap()
        .execute("UPDATE apps SET expires_at='2000-01-01T00:00:00Z'", [])
        .unwrap();
    let r = call(&t.public, "GET", &cap, &[("origin", "null")], vec![]).await;
    assert_eq!(r.status, 410);
    assert!(r.headers.get("access-control-allow-origin").is_none());
    let p = call(&t.public, "OPTIONS", &cap, &pf, vec![]).await;
    assert_eq!(p.status, 410);
    assert!(p.headers.get("access-control-allow-origin").is_none());
}

#[tokio::test]
async fn apps_private_without_a_view_token_hash_has_no_cap() {
    let t = setup();
    let ws = t.workspace("A", all_rights()).await;
    let r = deploy(
        &t,
        &ws,
        "site",
        &[("app.toml", STATIC_TOML), ("index.html", "x")],
        "",
    )
    .await;
    let tok = r.json()["view_token"].as_str().unwrap().to_string();
    let red = call(
        &t.public,
        "GET",
        &format!("/a/site/?token={tok}"),
        &[],
        vec![],
    )
    .await;
    let cap = red.headers["location"].to_str().unwrap().to_string();
    assert_eq!(call(&t.public, "GET", &cap, &[], vec![]).await.status, 200);
    t.st.db
        .lock()
        .unwrap()
        .execute("UPDATE apps SET view_token_hash=NULL", [])
        .unwrap();
    let r = call(&t.public, "GET", &cap, &[("origin", "null")], vec![]).await;
    assert_eq!(r.status, 401);
    assert!(r.text().contains("This app is private"));
    assert!(r.headers.get("access-control-allow-origin").is_none());
}
