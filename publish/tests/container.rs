//! Real-engine test (Kiri / Docker Engine). Ignored by default; run on a machine with the engine:
//! `ORCH_PUBLISH_TEST_ENGINE=1 cargo test --test container -- --ignored`
mod common;
use common::*;

const PY: &str = r#"import os
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = ("hello " + os.environ["BASE_PATH"] + " " + os.environ["HOST"]).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass
HTTPServer((os.environ["HOST"], int(os.environ["PORT"])), H).serve_forever()
"#;

const DOCKERFILE: &str =
    "FROM python:3.12-slim\nWORKDIR /srv\nCOPY main.py .\nCMD [\"python\", \"main.py\"]\n";

#[tokio::test]
#[ignore]
async fn container_python_and_docker_apps_deploy_redeploy_stop() {
    if std::env::var("ORCH_PUBLISH_TEST_ENGINE").is_err() {
        eprintln!("ORCH_PUBLISH_TEST_ENGINE not set; skipping");
        return;
    }
    std::env::set_var("ORCH_PUBLISH_SANDBOX", "container");
    std::env::set_var("ORCH_PUBLISH_DOCKER_APPS", "1");
    let t = setup_with(|c| {
        c.health_secs = 60;
        c.build_secs = 600;
    });
    let ws = t.workspace("A", basic_rights()).await;
    let py_toml =
        "name = \"cpy\"\nstack = \"python\"\nstart = \"python main.py\"\nhealth = \"/health\"\n";
    let dk_toml = "name = \"cdk\"\nstack = \"docker\"\nhealth = \"/health\"\n";
    for round in 0..2 {
        // second round = redeploy of both
        let r = t
            .api(
                &ws,
                "PUT",
                "/v1/apps/cpy",
                bundle(&[("app.toml", py_toml), ("main.py", PY)]),
            )
            .await;
        assert_eq!(r.status, 200, "round {round}: {}", r.text());
        let r = t
            .api(
                &ws,
                "PUT",
                "/v1/apps/cdk",
                bundle(&[
                    ("app.toml", dk_toml),
                    ("main.py", PY),
                    ("Dockerfile", DOCKERFILE),
                ]),
            )
            .await;
        assert_eq!(r.status, 200, "round {round}: {}", r.text());
    }
    for n in ["cpy", "cdk"] {
        let tok = t
            .api(
                &ws,
                "PUT",
                &format!("/v1/apps/{n}?new_token=1"),
                match n {
                    "cpy" => bundle(&[("app.toml", py_toml), ("main.py", PY)]),
                    _ => bundle(&[
                        ("app.toml", dk_toml),
                        ("main.py", PY),
                        ("Dockerfile", DOCKERFILE),
                    ]),
                },
            )
            .await
            .json()["view_token"]
            .as_str()
            .unwrap()
            .to_string();
        let g = call(
            &t.public,
            "GET",
            &format!("/a/{n}/?token={tok}"),
            &[],
            vec![],
        )
        .await;
        assert_eq!(g.status, 302);
        let cookie = g.headers["set-cookie"]
            .to_str()
            .unwrap()
            .split(';')
            .next()
            .unwrap()
            .to_string();
        let b = call(
            &t.public,
            "GET",
            &format!("/a/{n}/"),
            &[("cookie", &cookie)],
            vec![],
        )
        .await;
        assert!(b.text().contains("0.0.0.0"), "{n}: {}", b.text());
        let s = t
            .api(&ws, "POST", &format!("/v1/apps/{n}/stop"), vec![])
            .await;
        assert_eq!(s.json()["status"], "stopped");
    }
    let left = std::process::Command::new("docker")
        .env(
            "DOCKER_HOST",
            format!(
                "unix://{}",
                std::env::var("ORCH_PUBLISH_ENGINE_SOCKET")
                    .unwrap_or("/run/kiri/docker.sock".into())
            ),
        )
        .args(["ps", "-a", "--filter", "label=orch.publish.app", "-q"])
        .output()
        .unwrap();
    assert!(
        String::from_utf8_lossy(&left.stdout).trim().is_empty(),
        "containers left"
    );
    std::env::remove_var("ORCH_PUBLISH_SANDBOX");
}

/// Scale to zero on the real engine: the idle container is stopped, the next request starts it again.
#[tokio::test]
#[ignore]
async fn container_idle_app_sleeps_and_wakes_on_request() {
    if std::env::var("ORCH_PUBLISH_TEST_ENGINE").is_err() {
        eprintln!("ORCH_PUBLISH_TEST_ENGINE not set; skipping");
        return;
    }
    std::env::set_var("ORCH_PUBLISH_SANDBOX", "container");
    let t = setup_with(|c| {
        c.health_secs = 60;
        c.idle_secs = 2;
        c.sleep_sweep_secs = 1;
    });
    let ws = t.workspace("A", basic_rights()).await;
    let toml = "name = \"nap\"\nstack = \"python\"\nstart = \"python main.py\"\nhealth = \"/health\"\npublic = true\n";
    let r = t
        .api(
            &ws,
            "PUT",
            "/v1/apps/nap",
            bundle(&[("app.toml", toml), ("main.py", PY)]),
        )
        .await;
    assert_eq!(r.status, 200, "{}", r.text());
    let running = || {
        let o = std::process::Command::new("docker")
            .env(
                "DOCKER_HOST",
                format!(
                    "unix://{}",
                    std::env::var("ORCH_PUBLISH_ENGINE_SOCKET")
                        .unwrap_or("/run/kiri/docker.sock".into())
                ),
            )
            .args(["ps", "--filter", "label=orch.publish.app=nap", "-q"])
            .output()
            .unwrap();
        !String::from_utf8_lossy(&o.stdout).trim().is_empty()
    };
    assert!(running());
    // the fast sweep (the same call the server's background task makes) puts it to sleep
    let t0 = std::time::Instant::now();
    while running() {
        assert!(t0.elapsed().as_secs() < 30, "container still running");
        orch_publish::apps::sleep_sweep(&t.st).await;
        tokio::time::sleep(std::time::Duration::from_millis(500)).await;
    }
    let l = t.api(&ws, "GET", "/v1/apps", vec![]).await.json();
    assert_eq!(l["items"][0]["status"], "running");
    assert_eq!(l["items"][0]["awake"], false);
    let w = std::time::Instant::now();
    let g = call(&t.public, "GET", "/a/nap/", &[], vec![]).await;
    println!("wake time: {} ms", w.elapsed().as_millis());
    assert_eq!(g.status, 200, "{}", g.text());
    assert!(g.text().contains("hello /a/nap"));
    assert!(running());
    t.api(&ws, "DELETE", "/v1/apps/nap", vec![]).await;
    std::env::remove_var("ORCH_PUBLISH_SANDBOX");
}

/// A build step that plants links where the server later cleans up must not make it touch the target.
#[tokio::test]
#[ignore]
async fn container_build_cannot_aim_the_cleanup_at_another_folder() {
    if std::env::var("ORCH_PUBLISH_TEST_ENGINE").is_err() {
        return;
    }
    std::env::set_var("ORCH_PUBLISH_SANDBOX", "container");
    let t = setup_with(|c| {
        c.health_secs = 60;
        c.build_secs = 600;
    });
    let ws = t.workspace("A", basic_rights()).await;
    let victim = t.dir.path().join("victim");
    std::fs::create_dir_all(&victim).unwrap();
    std::fs::write(victim.join("keep.txt"), "x").unwrap();
    let setup_py = format!(
        "import os\nfrom setuptools import setup\nfor l in ('/app/.test-data', '/app/.step-x', '/app/data'):\n    try:\n        os.symlink({:?}, l)\n    except OSError:\n        pass\nsetup(name='pkg', version='1', py_modules=[])\n",
        victim.display().to_string()
    );
    let toml =
        "name = \"cpl\"\nstack = \"python\"\nstart = \"python main.py\"\nhealth = \"/health\"\n";
    let r = t
        .api(
            &ws,
            "PUT",
            "/v1/apps/cpl",
            bundle(&[
                ("app.toml", toml),
                ("main.py", PY),
                ("requirements.txt", "./pkg\n"),
                ("pkg/setup.py", &setup_py),
            ]),
        )
        .await;
    eprintln!("deploy: {} {}", r.status, r.text());
    assert!(victim.join("keep.txt").is_file(), "victim folder survived");
    let _ = t.api(&ws, "DELETE", "/v1/apps/cpl", vec![]).await;
    assert!(
        victim.join("keep.txt").is_file(),
        "victim survived the delete too"
    );
    std::env::remove_var("ORCH_PUBLISH_SANDBOX");
}
