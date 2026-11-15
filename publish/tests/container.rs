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
