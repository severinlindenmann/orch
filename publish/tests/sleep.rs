//! Scale to zero: idle apps sleep, the next request wakes them (plain processes, no engine).
mod common;
use common::*;
use orch_publish::apps;
use std::time::Duration;

const APP_T: &str = r#"import os, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
with open(os.environ["DATA_DIR"] + "/starts", "a") as f:
    f.write("x\n")
time.sleep(DELAY)
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/slow":
            time.sleep(2.2)
        body = b"hi"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass
ThreadingHTTPServer.request_queue_size = 64
ThreadingHTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
"#;

fn app_src(delay: &str) -> String {
    APP_T.replace("DELAY", delay)
}

fn starts(t: &T, name: &str) -> usize {
    std::fs::read_to_string(t.dir.path().join(format!("apps/{name}/data/starts")))
        .map(|s| s.lines().count())
        .unwrap_or(0)
}

fn row(t: &T, name: &str) -> serde_json::Value {
    let st = t.st.clone();
    let a = orch_publish::db::get_app(&st.db.lock().unwrap(), name)
        .unwrap()
        .unwrap();
    apps::app_json(&st, &a)
}

async fn deploy_py(t: &T, ws: &(String, String), name: &str) {
    deploy_py_slow(t, ws, name, "0.3").await
}

async fn deploy_py_slow(t: &T, ws: &(String, String), name: &str, delay: &str) {
    let src = app_src(delay);
    let toml = py_toml(name, "public = true\nstore = \"json\"");
    let r = t
        .api(
            ws,
            "PUT",
            &format!("/v1/apps/{name}?days=7"),
            bundle(&[("app.toml", &toml), ("main.py", &src)]),
        )
        .await;
    assert_eq!(r.status, 200, "{}", r.text());
}

async fn idle_for(secs: f64) {
    tokio::time::sleep(Duration::from_millis((secs * 1000.0) as u64)).await;
}

#[tokio::test]
async fn sleep_idle_app_sleeps_and_wakes_on_request() {
    let t = setup_with(|c| c.idle_secs = 1);
    let ws = t.workspace("A", all_rights()).await;
    deploy_py(&t, &ws, "napper").await;
    assert_eq!(row(&t, "napper")["awake"], true);
    // a sweep right after the deploy does nothing
    apps::sleep_sweep(&t.st).await;
    assert_eq!(row(&t, "napper")["awake"], true);

    idle_for(1.3).await;
    apps::sleep_sweep(&t.st).await;
    let j = row(&t, "napper");
    assert_eq!(j["status"], "running");
    assert_eq!(j["awake"], false);
    let l = t.api(&ws, "GET", "/v1/apps", vec![]).await.json();
    assert_eq!(l["items"][0]["status"], "running");
    assert_eq!(l["items"][0]["awake"], false);
    let a = t
        .adm("GET", "/admin/api/apps", serde_json::Value::Null)
        .await;
    assert_eq!(a.json()["items"][0]["awake"], false, "{}", a.text());

    let g = call(&t.public, "GET", "/a/napper/", &[], vec![]).await;
    assert_eq!(g.status, 200, "{}", g.text());
    assert_eq!(g.text(), "hi");
    assert_eq!(row(&t, "napper")["awake"], true);
    assert_eq!(starts(&t, "napper"), 2);
    // the request counts as use: not asleep again right away
    apps::sleep_sweep(&t.st).await;
    assert_eq!(row(&t, "napper")["awake"], true);
}

#[tokio::test]
async fn sleep_request_in_flight_blocks_sleep() {
    let t = setup_with(|c| c.idle_secs = 1);
    let ws = t.workspace("A", all_rights()).await;
    deploy_py(&t, &ws, "busy").await;
    let router = t.public.clone();
    let slow = tokio::spawn(async move { call(&router, "GET", "/a/busy/slow", &[], vec![]).await });
    idle_for(1.5).await; // idle time passed, but the request is still running
    apps::sleep_sweep(&t.st).await;
    assert_eq!(row(&t, "busy")["awake"], true);
    assert_eq!(slow.await.unwrap().status, 200);
    idle_for(1.3).await;
    apps::sleep_sweep(&t.st).await;
    assert_eq!(row(&t, "busy")["awake"], false);
}

#[tokio::test]
async fn sleep_ten_concurrent_requests_start_once() {
    let t = setup_with(|c| c.idle_secs = 1);
    let ws = t.workspace("A", all_rights()).await;
    deploy_py(&t, &ws, "herd").await;
    idle_for(1.3).await;
    apps::sleep_sweep(&t.st).await;
    assert_eq!(row(&t, "herd")["awake"], false);
    let mut hs = vec![];
    for _ in 0..10 {
        let r = t.public.clone();
        hs.push(tokio::spawn(async move {
            call(&r, "GET", "/a/herd/", &[], vec![]).await
        }));
    }
    for h in hs {
        let r = h.await.unwrap();
        assert_eq!(r.status, 200, "{}", r.text());
    }
    assert_eq!(starts(&t, "herd"), 2); // deploy + exactly one wake
}

#[tokio::test]
async fn sleep_wake_failure_gives_503() {
    let t = setup_with(|c| {
        c.idle_secs = 1;
        c.health_secs = 3;
    });
    let ws = t.workspace("A", all_rights()).await;
    deploy_py(&t, &ws, "broken").await;
    idle_for(1.3).await;
    apps::sleep_sweep(&t.st).await;
    let dir = {
        let c = t.st.db.lock().unwrap();
        orch_publish::db::get_app(&c, "broken")
            .unwrap()
            .unwrap()
            .code_dir
    };
    std::fs::write(
        std::path::Path::new(&dir).join("main.py"),
        "import sys\nsys.exit(1)\n",
    )
    .unwrap();
    let g = call(&t.public, "GET", "/a/broken/", &[], vec![]).await;
    assert_eq!(g.status, 503);
    assert!(g.text().contains("This app could not start"));
    // still sleeping (not failed), the owner can see it as running
    let j = row(&t, "broken");
    assert_eq!(j["status"], "running");
    assert_eq!(j["awake"], false);
}

#[tokio::test]
async fn sleep_never_for_static_or_when_off() {
    // static apps never sleep
    let t = setup_with(|c| c.idle_secs = 1);
    let ws = t.workspace("A", all_rights()).await;
    let r = t
        .api(
            &ws,
            "PUT",
            "/v1/apps/site?days=7",
            bundle(&[
                (
                    "app.toml",
                    "name = \"site\"\nstack = \"static\"\nabout = \"x\"\npublic = true\n",
                ),
                ("index.html", "<h1>x</h1>"),
            ]),
        )
        .await;
    assert_eq!(r.status, 200, "{}", r.text());
    idle_for(1.3).await;
    apps::sleep_sweep(&t.st).await;
    let j = row(&t, "site");
    assert_eq!(
        (j["status"].as_str(), j["awake"].as_bool()),
        (Some("running"), Some(true))
    );
    assert_eq!(
        call(&t.public, "GET", "/a/site/", &[], vec![]).await.status,
        200
    );

    // idle_secs = 0: nothing sleeps
    let t = setup();
    let ws = t.workspace("A", all_rights()).await;
    deploy_py(&t, &ws, "always").await;
    idle_for(1.3).await;
    apps::sleep_sweep(&t.st).await;
    assert_eq!(row(&t, "always")["awake"], true);
}

#[tokio::test]
async fn sleep_stop_restart_delete_work_on_a_sleeping_app() {
    let t = setup_with(|c| c.idle_secs = 1);
    let ws = t.workspace("A", all_rights()).await;
    deploy_py(&t, &ws, "nap2").await;
    idle_for(1.3).await;
    apps::sleep_sweep(&t.st).await;
    assert_eq!(row(&t, "nap2")["awake"], false);
    // stop = just status
    let s = t.api(&ws, "POST", "/v1/apps/nap2/stop", vec![]).await;
    assert_eq!(s.json()["status"], "stopped");
    assert_eq!(row(&t, "nap2")["status"], "stopped");
    assert_eq!(
        call(&t.public, "GET", "/a/nap2/", &[], vec![]).await.status,
        503
    );
    // restart starts it for real
    let s = t.api(&ws, "POST", "/v1/apps/nap2/restart", vec![]).await;
    assert_eq!(s.json()["status"], "running");
    assert_eq!(row(&t, "nap2")["awake"], true);
    // sleep again, then delete
    idle_for(1.3).await;
    apps::sleep_sweep(&t.st).await;
    assert_eq!(row(&t, "nap2")["awake"], false);
    assert_eq!(
        t.api(&ws, "DELETE", "/v1/apps/nap2", vec![]).await.status,
        204
    );
    assert_eq!(
        call(&t.public, "GET", "/a/nap2/", &[], vec![]).await.status,
        404
    );
}

async fn sleep_app(t: &T, ws: &(String, String), name: &str, delay: &str) {
    deploy_py_slow(t, ws, name, delay).await;
    idle_for(1.3).await;
    apps::sleep_sweep(&t.st).await;
    assert_eq!(row(t, name)["awake"], false);
}

fn db_row(t: &T, name: &str) -> orch_publish::db::AppRow {
    orch_publish::db::get_app(&t.st.db.lock().unwrap(), name)
        .unwrap()
        .unwrap()
}

/// A request authorized for the old row is not served when the app changed during the wake.
#[tokio::test]
async fn sleep_access_change_during_wake_is_refused() {
    for case in ["private", "deleted", "expired"] {
        let t = setup_with(|c| c.idle_secs = 1);
        let ws = t.workspace("A", all_rights()).await;
        sleep_app(&t, &ws, "chg", "1.0").await;
        let r = t.public.clone();
        let h = tokio::spawn(async move { call(&r, "GET", "/a/chg/", &[], vec![]).await });
        idle_for(0.3).await; // the wake is running
        match case {
            "private" => {
                let mut a = db_row(&t, "chg");
                a.public = false;
                a.view_token_hash = Some("x".into());
                orch_publish::db::put_app(&t.st.db.lock().unwrap(), &a, &a.updated_at).unwrap();
            }
            "expired" => {
                let mut a = db_row(&t, "chg");
                a.expires_at = Some("2000-01-01T00:00:00Z".into());
                orch_publish::db::put_app(&t.st.db.lock().unwrap(), &a, &a.updated_at).unwrap();
            }
            _ => {
                assert_eq!(
                    t.api(&ws, "DELETE", "/v1/apps/chg", vec![]).await.status,
                    204
                );
            }
        }
        let g = h.await.unwrap();
        let want = match case {
            "private" => 401,
            "expired" => 410,
            _ => 404,
        };
        assert_eq!(g.status, want, "{case}: {}", g.text());
        assert_ne!(g.text(), "hi", "{case}");
    }
}

/// The wake does not hold the global app lock: another app deploys while one is waking.
#[tokio::test]
async fn sleep_wake_does_not_block_other_deploys() {
    let t = setup_with(|c| c.idle_secs = 1);
    let ws = t.workspace("A", all_rights()).await;
    sleep_app(&t, &ws, "slowa", "2.0").await;
    let r = t.public.clone();
    let h = tokio::spawn(async move { call(&r, "GET", "/a/slowa/", &[], vec![]).await });
    idle_for(0.3).await;
    let t0 = std::time::Instant::now();
    deploy_py_slow(&t, &ws, "fastb", "0.1").await;
    assert!(
        t0.elapsed() < Duration::from_millis(1500),
        "deploy of B waited for the wake of A: {:?}",
        t0.elapsed()
    );
    assert!(!h.is_finished(), "A should still be waking");
    assert_eq!(h.await.unwrap().status, 200);
}

/// A failing app is started once per cooldown window, later requests get the 503 at once.
#[tokio::test]
async fn sleep_failed_wake_cooldown() {
    let t = setup_with(|c| {
        c.idle_secs = 1;
        c.health_secs = 3;
    });
    let ws = t.workspace("A", all_rights()).await;
    sleep_app(&t, &ws, "flaky", "0.1").await;
    let dir = db_row(&t, "flaky").code_dir;
    std::fs::write(
        std::path::Path::new(&dir).join("main.py"),
        "import os, sys\nopen(os.environ[\"DATA_DIR\"] + \"/starts\", \"a\").write(\"x\\n\")\nsys.exit(1)\n",
    )
    .unwrap();
    for _ in 0..3 {
        let g = call(&t.public, "GET", "/a/flaky/", &[], vec![]).await;
        assert_eq!(g.status, 503);
    }
    assert_eq!(starts(&t, "flaky"), 2); // deploy + one failed wake
                                        // a restart by the owner clears the cooldown (fix the app first)
    std::fs::write(std::path::Path::new(&dir).join("main.py"), app_src("0.1")).unwrap();
    let s = t.api(&ws, "POST", "/v1/apps/flaky/restart", vec![]).await;
    assert_eq!(s.json()["status"], "running");
}

/// After a server restart apps are not started; the first request wakes them.
#[tokio::test]
async fn sleep_resume_all_leaves_apps_asleep() {
    let t = setup_with(|c| c.idle_secs = 1);
    let ws = t.workspace("A", all_rights()).await;
    deploy_py(&t, &ws, "back").await;
    assert_eq!(starts(&t, "back"), 1);
    // a second server on the same data folder (the first one keeps its process, on its own port)
    let st2 = orch_publish::new_state(t.st.cfg.clone()).unwrap();
    apps::resume_all(&st2).await;
    let a = orch_publish::db::get_app(&st2.db.lock().unwrap(), "back")
        .unwrap()
        .unwrap();
    let j = apps::app_json(&st2, &a);
    assert_eq!(
        (j["status"].as_str(), j["awake"].as_bool()),
        (Some("running"), Some(false))
    );
    assert_eq!(starts(&t, "back"), 1, "resume_all must not start the app");
    let pub2 = orch_publish::public_router(st2.clone());
    let g = call(&pub2, "GET", "/a/back/", &[], vec![]).await;
    assert_eq!(g.status, 200, "{}", g.text());
    assert_eq!(starts(&t, "back"), 2);
}
