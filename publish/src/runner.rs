//! The only place that starts and stops app processes. On the VPS this can later be swapped for
//! systemd units (`orch-app@<name>.service`); the rest of the server only uses these functions.
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::Mutex;
use std::time::Duration;
use tokio::process::{Child, Command};

pub struct Spec {
    pub dir: PathBuf,
    pub start: String,
    pub port: u16,
    pub base_path: String,
    pub data_dir: PathBuf,
    pub store: String,
    pub log: PathBuf,
    /// python | node | docker | static (decides the image in container mode)
    pub stack: String,
    /// docker stack: the built image (`orch-app-<name>:<version>`)
    pub image: Option<String>,
}

/// What a build/test step runs in, in container mode.
pub struct StepCtx<'a> {
    pub stack: &'a str,
    pub image: Option<&'a str>,
    /// code folder mounted read-write (the build step), else read-only
    pub writable: bool,
}

struct Proc {
    child: Child,
    port: u16,
    unit: String,
}

#[derive(Default)]
pub struct Runner {
    procs: Mutex<HashMap<String, Proc>>,
}

fn env_list(
    dir: &Path,
    port: u16,
    base_path: &str,
    data_dir: &Path,
    store: &str,
) -> Vec<(String, String)> {
    let path = std::env::var("PATH").unwrap_or_default();
    let venv = dir.join(".venv/bin");
    let path = if venv.is_dir() {
        format!("{}:{path}", venv.display())
    } else {
        path
    };
    vec![
        ("PATH".into(), path),
        ("HOME".into(), data_dir.display().to_string()),
        ("LANG".into(), "C.UTF-8".into()),
        ("HOST".into(), "127.0.0.1".into()),
        ("PORT".into(), port.to_string()),
        ("BASE_PATH".into(), base_path.into()),
        ("DATA_DIR".into(), data_dir.display().to_string()),
        ("STORE".into(), store.into()),
    ]
}

/// ORCH_PUBLISH_SANDBOX=systemd: apps and their build/test steps run as transient systemd units.
fn sandboxed() -> bool {
    std::env::var("ORCH_PUBLISH_SANDBOX").is_ok_and(|v| v == "systemd")
}

/// ORCH_PUBLISH_SANDBOX=container: apps run as containers on the Kiri engine (Docker Engine API).
pub fn container_mode() -> bool {
    std::env::var("ORCH_PUBLISH_SANDBOX").is_ok_and(|v| v == "container")
}

// ---- container mode (driven with the `docker` CLI; the attached `docker run` is the Child)

const NETWORK: &str = "orch-apps";

/// `docker` with DOCKER_HOST pointing at the engine socket.
fn docker_std() -> std::process::Command {
    let bin = crate::config::var("DOCKER").unwrap_or_else(|| "docker".into());
    let sock =
        crate::config::var("ENGINE_SOCKET").unwrap_or_else(|| "/run/kiri/docker.sock".into());
    let mut c = std::process::Command::new(bin);
    c.env("DOCKER_HOST", format!("unix://{sock}"));
    c
}

/// "<uid>:<gid>" of this server process (the container runs as the same user).
fn server_user() -> String {
    static U: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    U.get_or_init(|| {
        let id = |f: &str| {
            std::process::Command::new("id")
                .arg(f)
                .output()
                .ok()
                .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
                .filter(|s| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit()))
                .unwrap_or_else(|| "65534".into())
        };
        format!("{}:{}", id("-u"), id("-g"))
    })
    .clone()
}

/// Creates the `orch-apps` network once (best effort: a real error shows up when the app starts).
fn ensure_network() {
    static DONE: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
    if DONE.load(std::sync::atomic::Ordering::Relaxed) {
        return;
    }
    let exists = docker_std()
        .args(["network", "inspect", NETWORK])
        .output()
        .is_ok_and(|o| o.status.success());
    if exists
        || docker_std()
            .args(["network", "create", NETWORK])
            .output()
            .is_ok_and(|o| o.status.success())
    {
        DONE.store(true, std::sync::atomic::Ordering::Relaxed);
    }
}

fn stack_image(stack: &str) -> &'static str {
    if stack == "node" {
        "node:22-slim"
    } else {
        "python:3.12-slim"
    }
}

/// App name of a runner key / unit name label.
fn app_of(key: &str) -> &str {
    key.strip_suffix("~new").unwrap_or(key)
}

struct RunOpts<'a> {
    name: &'a str,
    /// label value; None for steps
    app: Option<&'a str>,
    stack: &'a str,
    image: Option<&'a str>,
    code: &'a Path,
    code_rw: bool,
    data: &'a Path,
    port: u16,
    base_path: &'a str,
    store: &'a str,
    /// run as `sh -c <script>`; None = the image's CMD (docker stack)
    script: Option<&'a str>,
    step: bool,
    user: &'a str,
}

/// Arguments of `docker run` for one app or step container.
fn container_run_args(o: &RunOpts) -> Vec<String> {
    let docker = o.stack == "docker";
    let mut a: Vec<String> = ["run", "--rm", "--name", o.name].map(String::from).into();
    macro_rules! kv {
        ($k:expr, $v:expr $(,)?) => {{
            a.push($k.into());
            a.push($v);
        }};
    }
    if let Some(app) = o.app {
        kv!("--label", format!("orch.publish.app={app}"));
        kv!("--label", format!("dev.kiri.domain={app}"));
    }
    kv!("--network", NETWORK.into());
    kv!("-p", format!("127.0.0.1:{p}:{p}", p = o.port));
    kv!("--memory", if o.step { "512m" } else { "128m" }.into());
    kv!("--cpus", if o.step { "1" } else { "0.5" }.into());
    kv!("--pids-limit", if o.step { "256" } else { "64" }.into());
    a.push("--read-only".into());
    kv!("--tmpfs", "/tmp".into());
    kv!("--cap-drop", "ALL".into());
    kv!("--security-opt", "no-new-privileges".into());
    kv!("--user", o.user.into());
    if !docker {
        kv!(
            "-v",
            format!(
                "{}:/app{}",
                o.code.display(),
                if o.code_rw { "" } else { ":ro" }
            ),
        );
        kv!("-w", "/app".into());
    }
    kv!("-v", format!("{}:/data", o.data.display()));
    let mut env = vec![
        ("HOST", "0.0.0.0".to_string()),
        ("PORT", o.port.to_string()),
        ("BASE_PATH", o.base_path.to_string()),
        ("DATA_DIR", "/data".to_string()),
        ("STORE", o.store.to_string()),
        ("HOME", "/data".to_string()),
    ];
    if o.stack == "python" {
        env.push((
            "PATH",
            "/app/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin".into(),
        ));
    }
    for (k, v) in env {
        kv!("-e", format!("{k}={v}"));
    }
    a.push(
        o.image
            .map(String::from)
            .unwrap_or_else(|| stack_image(o.stack).into()),
    );
    if let Some(s) = o.script {
        a.extend(["sh".into(), "-c".into(), s.into()]);
    }
    a
}

/// Container names in `docker ps -a --format {{.Names}}` output that are not in `live`.
fn leftover_containers(listed: &str, live: &HashSet<String>) -> Vec<String> {
    listed
        .lines()
        .map(str::trim)
        .filter(|n| !n.is_empty() && !live.contains(*n))
        .map(String::from)
        .collect()
}

async fn rm_container(name: &str) {
    let _ = Command::from(docker_std())
        .args(["rm", "-f", name])
        .output()
        .await;
}

/// `docker build` of a docker-stack bundle. Returns (success, output).
pub async fn build_image(tag: &str, dir: &Path, secs: u64) -> (bool, String) {
    let mut c = Command::from(docker_std());
    c.args(["build", "-t", tag])
        .arg(dir)
        .stdin(Stdio::null())
        .kill_on_drop(true);
    match tokio::time::timeout(Duration::from_secs(secs), c.output()).await {
        Err(_) => (false, format!("timed out after {secs} s")),
        Ok(Err(e)) => (false, e.to_string()),
        Ok(Ok(o)) => {
            let mut out = String::from_utf8_lossy(&o.stdout).to_string();
            out.push_str(&String::from_utf8_lossy(&o.stderr));
            (o.status.success(), out)
        }
    }
}

/// Builds the image unless the engine already has it.
pub async fn ensure_image(tag: &str, dir: &Path, secs: u64) -> bool {
    let have = Command::from(docker_std())
        .args(["image", "inspect", tag])
        .output()
        .await
        .is_ok_and(|o| o.status.success());
    have || build_image(tag, dir, secs).await.0
}

/// Removes an image (best effort).
pub async fn remove_image(tag: &str) {
    let _ = Command::from(docker_std())
        .args(["rmi", tag])
        .output()
        .await;
}

/// Hex of the app name (the `~new` suffix of a version being deployed is dropped): injective.
fn unit_prefix(key: &str) -> String {
    let name = key.strip_suffix("~new").unwrap_or(key);
    let hex: String = name.bytes().map(|b| format!("{b:02x}")).collect();
    format!("orch-app-{hex}-")
}

/// One unit per running version: the port is unique among live versions, so a new version never
/// shares (and never stops) the unit of the version it replaces.
fn unit_name(key: &str, port: u16) -> String {
    format!("{}{port}", unit_prefix(key))
}

/// Unit names in `systemctl list-units` output that start with `prefix` and are not in `live`.
fn leftover_units(listed: &str, prefix: &str, live: &HashSet<String>) -> Vec<String> {
    listed
        .lines()
        .filter_map(|l| l.split_whitespace().next())
        .filter_map(|u| u.strip_suffix(".service").or(Some(u)))
        .filter(|u| u.starts_with(prefix) && !live.contains(*u))
        .map(String::from)
        .collect()
}

/// Group-write a freshly extracted bundle so the unit's dynamic user (primary group orch-publish)
/// can use it. Called once at extraction (the bundle has no links, nobody else writes there yet).
pub fn prep_perms(p: &Path) {
    use std::os::unix::fs::PermissionsExt;
    let Ok(md) = std::fs::symlink_metadata(p) else {
        return;
    };
    if md.file_type().is_symlink() {
        return;
    }
    let mode = md.permissions().mode();
    if md.is_dir() {
        let _ = std::fs::set_permissions(p, std::fs::Permissions::from_mode(mode | 0o2770));
        if let Ok(rd) = std::fs::read_dir(p) {
            for e in rd.flatten() {
                prep_perms(&e.path());
            }
        }
    } else {
        let _ = std::fs::set_permissions(p, std::fs::Permissions::from_mode(mode | 0o660));
    }
}

#[allow(clippy::too_many_arguments)]
/// The command for `sh -c <script>` in `dir`: a plain child process, or a sandboxed transient unit.
fn make_cmd(
    script: &str,
    unit: &str,
    dir: &Path,
    port: u16,
    base_path: &str,
    data_dir: &Path,
    store: &str,
    max_secs: Option<u64>,
) -> Command {
    let env = env_list(dir, port, base_path, data_dir, store);
    if sandboxed() {
        use std::os::unix::fs::PermissionsExt;
        std::fs::create_dir_all(data_dir).ok();
        // only the dir itself; what the unit creates inside has UMask 0002
        let _ = std::fs::set_permissions(data_dir, std::fs::Permissions::from_mode(0o2770));
        // the server's own data (db, files, logs, admin token) must be 0700 and invisible to apps
        let server_data = std::env::var("ORCH_PUBLISH_DATA_DIR")
            .or_else(|_| std::env::var("PUBLISH_DATA_DIR"))
            .unwrap_or_else(|_| "/var/lib/orch-publish".into());
        let server_data = Path::new(&server_data);
        let _ = std::fs::set_permissions(server_data, std::fs::Permissions::from_mode(0o700));
        let apps = dir.parent().and_then(|p| p.parent()).unwrap_or(dir);
        let mut c = Command::new("systemd-run");
        c.args(["--quiet", "--collect", "--pipe", "--wait", "--unit", unit]);
        let mut props = vec![
            "DynamicUser=yes".to_string(),
            "Group=orch-publish".into(),
            "UMask=0002".into(),
            "ProtectSystem=strict".into(),
            "ProtectHome=yes".into(),
            "PrivateTmp=yes".into(),
            "NoNewPrivileges=yes".into(),
            "MemoryMax=256M".into(),
            format!("WorkingDirectory={}", dir.display()),
            // other apps and the server's own data stay invisible; only this app's dirs are bound back in
            format!("TemporaryFileSystem={}:ro", apps.display()),
            format!("BindPaths={} {}", dir.display(), data_dir.display()),
            format!("ReadWritePaths={} {}", dir.display(), data_dir.display()),
        ];
        // keep the order: TemporaryFileSystem first, then the bind mounts
        // (skipped when the apps live inside the data dir: then the tmpfs over `apps` is the only hiding)
        if !dir.starts_with(server_data) {
            props.push(format!("InaccessiblePaths={}", server_data.display()));
        }
        if let Some(n) = max_secs {
            props.push(format!("RuntimeMaxSec={n}"));
        }
        // the same app keeps the same user across versions (its data files stay writable);
        // systemd limits user names to 31 characters, so the name is a short hash
        if let Some(i) = unit.strip_prefix("orch-app-").and_then(|u| u.rfind('-')) {
            let h = crate::util::sha256_hex(&unit["orch-app-".len()..][..i]);
            props.push(format!("User=oa-{}", &h[..16]));
        }
        for p in props.drain(..) {
            c.arg("-p").arg(p);
        }
        for (k, v) in env {
            c.arg("-E").arg(format!("{k}={v}"));
        }
        c.args(["--", "sh", "-c", script]);
        c
    } else {
        let mut c = Command::new("sh");
        c.arg("-c").arg(script);
        c.env_clear().current_dir(dir);
        for (k, v) in env {
            c.env(k, v);
        }
        c
    }
}

impl Runner {
    pub fn spawn(&self, name: &str, s: &Spec) -> std::io::Result<()> {
        if let Some(p) = s.log.parent() {
            std::fs::create_dir_all(p)?;
        }
        std::fs::create_dir_all(&s.data_dir)?;
        let log = std::fs::File::create(&s.log)?;
        let log2 = log.try_clone()?;
        let unit = unit_name(name, s.port);
        if sandboxed() {
            // leftover units of this app (after a crash/restart of the server) must go first,
            // but never the units of versions this server is running
            let live: HashSet<String> = self
                .procs
                .lock()
                .unwrap()
                .values()
                .map(|p| p.unit.clone())
                .collect();
            let prefix = unit_prefix(name);
            let listed = std::process::Command::new("systemctl")
                .args([
                    "list-units",
                    "--plain",
                    "--no-legend",
                    "--all",
                    &format!("{prefix}*"),
                ])
                .output()
                .map(|o| String::from_utf8_lossy(&o.stdout).to_string())
                .unwrap_or_default();
            for u in leftover_units(&listed, &prefix, &live) {
                let _ = std::process::Command::new("systemctl")
                    .args(["stop", &u])
                    .output();
            }
        }
        let mut cmd = if container_mode() {
            ensure_network();
            let live: HashSet<String> = self
                .procs
                .lock()
                .unwrap()
                .values()
                .map(|p| p.unit.clone())
                .collect();
            let label = format!("label=orch.publish.app={}", app_of(name));
            let listed = docker_std()
                .args(["ps", "-a", "--filter", &label, "--format", "{{.Names}}"])
                .output()
                .map(|o| String::from_utf8_lossy(&o.stdout).to_string())
                .unwrap_or_default();
            for n in leftover_containers(&listed, &live) {
                let _ = docker_std().args(["rm", "-f", &n]).output();
            }
            let script = (!s.start.is_empty()).then(|| format!("exec {}", s.start));
            let args = container_run_args(&RunOpts {
                name: &unit,
                app: Some(app_of(name)),
                stack: &s.stack,
                image: s.image.as_deref(),
                code: &s.dir,
                code_rw: false,
                data: &s.data_dir,
                port: s.port,
                base_path: &s.base_path,
                store: &s.store,
                script: script.as_deref(),
                step: false,
                user: &server_user(),
            });
            let mut c = Command::from(docker_std());
            c.args(args);
            c
        } else {
            make_cmd(
                &format!("exec {}", s.start),
                &unit,
                &s.dir,
                s.port,
                &s.base_path,
                &s.data_dir,
                &s.store,
                None,
            )
        };
        cmd.stdin(Stdio::null())
            .stdout(Stdio::from(log))
            .stderr(Stdio::from(log2))
            .kill_on_drop(true);
        let child = cmd.spawn()?;
        self.procs.lock().unwrap().insert(
            name.to_string(),
            Proc {
                child,
                port: s.port,
                unit,
            },
        );
        Ok(())
    }

    /// Kill the process (if any). Returns when it is gone.
    pub async fn stop(&self, name: &str) {
        let p = self.procs.lock().unwrap().remove(name);
        if let Some(mut p) = p {
            if sandboxed() {
                let _ = Command::new("systemctl")
                    .args(["stop", &p.unit])
                    .output()
                    .await;
            }
            if container_mode() {
                let _ = Command::from(docker_std())
                    .args(["stop", "-t", "5", &p.unit])
                    .output()
                    .await;
            }
            let _ = p.child.kill().await;
        }
    }

    /// Moves a process to another key (used when a new version replaces the old one).
    pub fn rename(&self, from: &str, to: &str) {
        let mut g = self.procs.lock().unwrap();
        if let Some(p) = g.remove(from) {
            g.insert(to.to_string(), p);
        }
    }

    pub fn is_alive(&self, name: &str) -> bool {
        let mut g = self.procs.lock().unwrap();
        match g.get_mut(name) {
            Some(p) => matches!(p.child.try_wait(), Ok(None)),
            None => false,
        }
    }

    pub fn used_ports(&self) -> HashSet<u16> {
        self.procs
            .lock()
            .unwrap()
            .values()
            .map(|p| p.port)
            .collect()
    }
}

async fn stop_unit(unit: &str) {
    if sandboxed() {
        let _ = Command::new("systemctl")
            .args(["stop", unit])
            .output()
            .await;
    }
}

/// Runs `sh -c <cmd>` in `dir` and waits (build and test steps). Returns (success, output).
#[allow(clippy::too_many_arguments)]
pub async fn run_step(
    cmd: &str,
    dir: &Path,
    port: u16,
    base_path: &str,
    data_dir: &Path,
    store: &str,
    secs: u64,
    ctx: &StepCtx<'_>,
) -> (bool, String) {
    let _ = std::fs::create_dir_all(data_dir);
    let unit = format!("orch-step-{}", crate::util::rand_id(8));
    let container = container_mode();
    let mut c = if container {
        let _ = tokio::task::spawn_blocking(ensure_network).await;
        let args = container_run_args(&RunOpts {
            name: &unit,
            app: None,
            stack: ctx.stack,
            image: ctx.image,
            code: dir,
            code_rw: ctx.writable,
            data: data_dir,
            port,
            base_path,
            store,
            script: Some(cmd),
            step: true,
            user: &server_user(),
        });
        let mut c = Command::from(docker_std());
        c.args(args);
        c
    } else {
        make_cmd(
            cmd,
            &unit,
            dir,
            port,
            base_path,
            data_dir,
            store,
            Some(secs),
        )
    };
    c.stdin(Stdio::null()).kill_on_drop(true);
    let cleanup = |unit: String| async move {
        if container {
            rm_container(&unit).await;
        } else {
            stop_unit(&unit).await;
        }
    };
    match tokio::time::timeout(Duration::from_secs(secs), c.output()).await {
        Err(_) => {
            cleanup(unit).await;
            (false, format!("timed out after {secs} s"))
        }
        Ok(Err(e)) => {
            cleanup(unit).await;
            (false, e.to_string())
        }
        Ok(Ok(o)) => {
            let mut out = String::from_utf8_lossy(&o.stdout).to_string();
            out.push_str(&String::from_utf8_lossy(&o.stderr));
            (o.status.success(), out)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_new_version_gets_its_own_unit_and_live_units_are_never_leftovers() {
        let old = unit_name("demo", 9100);
        let new = unit_name("demo~new", 9101);
        assert_ne!(old, new);
        assert!(new.starts_with(&unit_prefix("demo")));
        assert_ne!(unit_prefix("a-b"), unit_prefix("a~b"));
        let listed = format!("{old}.service loaded active running x\n{new}.service loaded active running y\nother.service loaded\n");
        let live: HashSet<String> = [old.clone()].into();
        assert_eq!(
            leftover_units(&listed, &unit_prefix("demo"), &live),
            vec![new]
        );
    }

    #[test]
    fn sandbox_env_builds_a_systemd_run_command() {
        let d = std::env::temp_dir().join(format!("orch-runner-test-{}", std::process::id()));
        let dir = d.join("apps/demo/v1");
        let data = d.join("apps/demo/data");
        std::fs::create_dir_all(&dir).unwrap();
        std::env::set_var("ORCH_PUBLISH_SANDBOX", "systemd");
        let c = make_cmd(
            "exec true",
            "orch-app-demo",
            &dir,
            9100,
            "/a/demo",
            &data,
            "files",
            Some(60),
        );
        let user_of = |u: &str| {
            let c = make_cmd("true", u, &dir, 1, "/a/x", &data, "files", None);
            c.as_std()
                .get_args()
                .map(|a| a.to_string_lossy().into_owned())
                .find(|a| a.starts_with("User="))
        };
        let (ua, ub) = (
            user_of(&unit_name("demo", 9100)),
            user_of(&unit_name("demo~new", 9101)),
        );
        std::env::remove_var("ORCH_PUBLISH_SANDBOX");
        assert!(ua.is_some() && ua == ub, "versions of one app share a user");
        let std_cmd = c.as_std();
        assert_eq!(std_cmd.get_program(), "systemd-run");
        let args: Vec<String> = std_cmd
            .get_args()
            .map(|a| a.to_string_lossy().into_owned())
            .collect();
        for want in [
            "DynamicUser=yes",
            "ProtectSystem=strict",
            "ProtectHome=yes",
            "PrivateTmp=yes",
            "NoNewPrivileges=yes",
            "MemoryMax=256M",
            "RuntimeMaxSec=60",
        ] {
            assert!(args.iter().any(|a| a == want), "missing {want}");
        }
        let rw = args
            .iter()
            .find(|a| a.starts_with("ReadWritePaths="))
            .unwrap();
        assert!(
            rw.contains(&dir.display().to_string()) && rw.contains(&data.display().to_string())
        );
        assert!(args.iter().any(|a| a == "PORT=9100"));
        let _ = std::fs::remove_dir_all(&d);
        // default: plain sh
        let c = make_cmd("true", "u", &dir, 1, "/a/x", &data, "files", None);
        assert_eq!(c.as_std().get_program(), "sh");
    }

    fn opts<'a>(stack: &'a str, image: Option<&'a str>, d: &'a Path) -> RunOpts<'a> {
        RunOpts {
            name: "orch-app-6465-9100",
            app: Some("de"),
            stack,
            image,
            code: d,
            code_rw: false,
            data: d,
            port: 9100,
            base_path: "/a/de",
            store: "json",
            script: Some("exec python3 main.py"),
            step: false,
            user: "1001:1002",
        }
    }

    fn pair(a: &[String], k: &str, v: &str) -> bool {
        a.windows(2).any(|w| w[0] == k && w[1] == v)
    }

    #[test]
    fn container_run_args_are_locked_down() {
        let d = PathBuf::from("/srv/code");
        let a = container_run_args(&opts("python", None, &d));
        assert_eq!(&a[..2], ["run", "--rm"]);
        for (k, v) in [
            ("--name", "orch-app-6465-9100"),
            ("--label", "orch.publish.app=de"),
            ("--label", "dev.kiri.domain=de"),
            ("--network", "orch-apps"),
            ("-p", "127.0.0.1:9100:9100"),
            ("--memory", "128m"),
            ("--cpus", "0.5"),
            ("--pids-limit", "64"),
            ("--tmpfs", "/tmp"),
            ("--cap-drop", "ALL"),
            ("--security-opt", "no-new-privileges"),
            ("--user", "1001:1002"),
            ("-v", "/srv/code:/app:ro"),
            ("-v", "/srv/code:/data"),
            ("-w", "/app"),
            ("-e", "HOST=0.0.0.0"),
            ("-e", "PORT=9100"),
            ("-e", "BASE_PATH=/a/de"),
            ("-e", "DATA_DIR=/data"),
            ("-e", "STORE=json"),
            ("-e", "HOME=/data"),
        ] {
            assert!(pair(&a, k, v), "missing {k} {v}: {a:?}");
        }
        assert!(a.contains(&"--read-only".to_string()));
        assert!(a.iter().any(|x| x.starts_with("PATH=/app/.venv/bin:")));
        // the port is published on loopback only
        assert!(a
            .iter()
            .all(|x| x != "9100:9100" && x != "0.0.0.0:9100:9100"));
        let tail = &a[a.len() - 4..];
        assert_eq!(
            tail,
            ["python:3.12-slim", "sh", "-c", "exec python3 main.py"]
        );
    }

    #[test]
    fn container_steps_and_docker_stack_args() {
        let d = PathBuf::from("/srv/code");
        let mut o = opts("node", None, &d);
        o.step = true;
        o.code_rw = true;
        o.app = None;
        let a = container_run_args(&o);
        assert!(pair(&a, "-v", "/srv/code:/app"), "build mounts code rw");
        assert!(a.iter().all(|x| !x.starts_with("orch.publish.app")));
        assert!(a.contains(&"node:22-slim".to_string()));
        assert!(!a.iter().any(|x| x.starts_with("PATH=")));
        // docker stack: own image, no code mount, no workdir, optional start
        let mut o = opts("docker", Some("orch-app-de:v1"), &d);
        o.script = None;
        let a = container_run_args(&o);
        assert!(!a
            .iter()
            .any(|x| x.ends_with(":/app") || x.ends_with(":/app:ro")));
        assert!(!a.contains(&"-w".to_string()));
        assert!(pair(&a, "-v", "/srv/code:/data"));
        assert_eq!(a.last().unwrap(), "orch-app-de:v1");
        o.script = Some("./run");
        assert_eq!(
            &container_run_args(&o)[container_run_args(&o).len() - 3..],
            ["sh", "-c", "./run"]
        );
    }

    #[test]
    fn leftover_containers_skip_live_ones() {
        let live: HashSet<String> = ["a-1".to_string()].into();
        assert_eq!(leftover_containers("a-1\na-2\n\n", &live), vec!["a-2"]);
        assert_eq!(app_of("demo~new"), "demo");
    }

    #[test]
    fn plain_env_has_host_loopback() {
        let e = env_list(
            Path::new("/nonexistent"),
            9100,
            "/a/x",
            Path::new("/d"),
            "none",
        );
        assert!(e.contains(&("HOST".into(), "127.0.0.1".into())));
    }
}
