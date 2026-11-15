//! Scale to zero: idle apps sleep, the next request wakes them (plain processes, no engine).
mod common;
use common::*;
use orch_publish::apps;
use std::time::Duration;

const APP: &str = r#"import os, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
with open(os.environ["DATA_DIR"] + "/starts", "a") as f:
    f.write("x\n")
time.sleep(0.3)
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
    let toml = py_toml(name, "public = true\nstore = \"json\"");
    let r = t
        .api(
            ws,
            "PUT",
            &format!("/v1/apps/{name}?days=7"),
            bundle(&[("app.toml", &toml), ("main.py", APP)]),
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
