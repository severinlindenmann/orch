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
    /// app name (its network and label)
    pub app: &'a str,
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

/// uid every app container runs as (never the server's own uid); the gid is the server's group.
const APP_UID: u32 = 61000;

/// `docker` with DOCKER_HOST pointing at the engine socket.
fn docker_std() -> std::process::Command {
    let bin = crate::config::var("DOCKER").unwrap_or_else(|| "docker".into());
    let sock =
        crate::config::var("ENGINE_SOCKET").unwrap_or_else(|| "/run/kiri/docker.sock".into());
    let mut c = std::process::Command::new(bin);
    c.env("DOCKER_HOST", format!("unix://{sock}"));
    c
}

/// "61000:<gid>" the app and step containers run as. The gid is the server's group, so the
/// group-writable (2770) data and code folders are writable for the container.
fn app_user() -> String {
    static G: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    let gid = G.get_or_init(|| {
        std::process::Command::new("id")
            .arg("-g")
            .output()
            .ok()
            .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
            .filter(|s| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit()))
            .unwrap_or_else(|| "65534".into())
    });
    format!("{APP_UID}:{gid}")
}

/// Creates the folder (if needed) with mode 2770: the server's group owns it, so the container can write.
pub fn group_writable_dir(p: &Path) {
    use std::os::unix::fs::PermissionsExt;
    let _ = std::fs::create_dir_all(p);
    let _ = std::fs::set_permissions(p, std::fs::Permissions::from_mode(0o2770));
}

/// One docker network per app, so apps cannot reach each other.
pub fn network_name(app: &str) -> String {
    format!("orch-net-{}", &crate::util::sha256_hex(app_of(app))[..24])
}

fn known_networks() -> &'static Mutex<HashSet<String>> {
    static N: std::sync::OnceLock<Mutex<HashSet<String>>> = std::sync::OnceLock::new();
    N.get_or_init(Default::default)
}

fn parse_cidr(c: &str) -> Option<(u32, u32)> {
    let (ip, len) = c.trim().split_once('/')?;
    let ip: std::net::Ipv4Addr = ip.parse().ok()?;
    let len: u32 = len.parse().ok()?;
    (len <= 32).then_some((u32::from(ip), len))
}

/// First free /28 of `pool` (e.g. `10.213.0.0/16`) that overlaps none of the `used` subnets.
fn pick_subnet(pool: &str, used: &[String]) -> Option<String> {
    let (base, plen) = parse_cidr(pool)?;
    if plen > 28 {
        return None;
    }
    let ranges: Vec<(u64, u64)> = used
        .iter()
        .filter_map(|u| parse_cidr(u))
        .map(|(ip, l)| {
            let size = 1u64 << (32 - l);
            (ip as u64 & !(size - 1), size)
        })
        .collect();
    let base = base as u64 & !((1u64 << (32 - plen)) - 1);
    (0..(1u64 << (28 - plen)))
        .map(|i| base + i * 16)
        .find(|start| {
            ranges
                .iter()
                .all(|(r, size)| start + 16 <= *r || *start >= r + size)
        })
        .map(|s| format!("{}/28", std::net::Ipv4Addr::from(s as u32)))
}

/// Subnets of the existing per-app networks.
fn used_app_subnets() -> Vec<String> {
    let names = docker_std()
        .args([
            "network",
            "ls",
            "--format",
            "{{.Name}}",
            "--filter",
            "name=orch-net-",
        ])
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).to_string())
        .unwrap_or_default();
    names
        .lines()
        .filter(|n| n.starts_with("orch-net-"))
        .filter_map(|n| {
            docker_std()
                .args([
                    "network",
                    "inspect",
                    "-f",
                    "{{range .IPAM.Config}}{{.Subnet}} {{end}}",
                    n,
                ])
                .output()
                .ok()
        })
        .flat_map(|o| {
            String::from_utf8_lossy(&o.stdout)
                .split_whitespace()
                .map(String::from)
                .collect::<Vec<_>>()
        })
        .collect()
}

/// Creates the app's network once, with its own /28 from the pool (best effort: a real error
/// shows up when the app starts).
///
/// A per-app network is NEVER removed (not when the app is removed either): Kiri 0.2.0 keeps its DNS
/// listener on the old gateway after `docker network rm`, and a new network with the same subnet
/// then fails every `docker run` with "dns bind: Address in use". The next deploy of the same app
/// name reuses the network. (Upstream Kiri issue to be filed.)
fn ensure_network(app: &str) {
    let net = network_name(app);
    if known_networks().lock().unwrap().contains(&net) {
        return;
    }
    let exists = docker_std()
        .args(["network", "inspect", &net])
        .output()
        .is_ok_and(|o| o.status.success());
    let pool = crate::config::var("APP_SUBNETS").unwrap_or_else(|| "10.213.0.0/16".into());
    let created = exists
        || pick_subnet(&pool, &used_app_subnets()).is_some_and(|subnet| {
            docker_std()
                .args(["network", "create", "--subnet", &subnet, &net])
                .output()
                .is_ok_and(|o| o.status.success())
        });
    if created {
        known_networks().lock().unwrap().insert(net);
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
    /// label value and network owner
    app: &'a str,
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
    /// seconds for the in-container `timeout` backstop (steps)
    timeout_secs: Option<u64>,
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
    kv!("--label", format!("orch.publish.app={}", o.app));
    if o.step {
        kv!("--label", "orch.publish.step=1".into());
    }
    kv!("--network", network_name(o.app));
    kv!("-p", format!("127.0.0.1:{p}:{p}", p = o.port));
    let mem = if o.step { "512m" } else { "128m" };
    kv!("--memory", mem.into());
    kv!("--memory-swap", mem.into());
    kv!("--cpus", if o.step { "1" } else { "0.5" }.into());
    kv!("--pids-limit", if o.step { "256" } else { "64" }.into());
    a.push("--read-only".into());
    kv!("--tmpfs", "/tmp:size=32m".into());
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
    // store = none: nothing to keep, so /data is read-only for the running app
    let ro = if !o.step && o.store == "none" {
        ":ro"
    } else {
        ""
    };
    kv!("-v", format!("{}:/data{ro}", o.data.display()));
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
    // an image ENTRYPOINT must not swallow `start` / `test`: scripts run through sh
    if docker && o.script.is_some() {
        kv!("--entrypoint", "sh".into());
    }
    a.push(
        o.image
            .map(String::from)
            .unwrap_or_else(|| stack_image(o.stack).into()),
    );
    if let Some(s) = o.script {
        if let (false, Some(n)) = (docker, o.timeout_secs) {
            a.extend(["timeout".into(), n.to_string()]);
        }
        if !docker {
            a.push("sh".into());
        }
        a.extend(["-c".into(), s.into()]);
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

/// Removes the container when dropped (a step or deploy future that is cancelled).
struct RmOnDrop {
    name: String,
    armed: bool,
}

impl Drop for RmOnDrop {
    fn drop(&mut self) {
        if self.armed {
            let mut c = docker_std();
            c.args(["rm", "-f", &self.name]);
            std::thread::spawn(move || {
                let _ = c.output();
            });
        }
    }
}

/// `app<TAB>name` lines of `docker ps -a`: the containers whose app is not in `known`.
fn orphan_containers(listed: &str, known: &HashSet<String>) -> Vec<String> {
    listed
        .lines()
        .filter_map(|l| l.split_once('\t'))
        .filter(|(app, n)| !n.trim().is_empty() && !known.contains(app.trim()))
        .map(|(_, n)| n.trim().to_string())
        .collect()
}

/// At server start: removes every leftover step container and every app container whose app
/// is not in the database.
pub async fn sweep_containers(known_apps: &HashSet<String>) {
    let list = |filter: &'static str| async move {
        Command::from(docker_std())
            .args([
                "ps",
                "-a",
                "--filter",
                filter,
                "--format",
                "{{.Label \"orch.publish.app\"}}\t{{.Names}}",
            ])
            .output()
            .await
            .map(|o| String::from_utf8_lossy(&o.stdout).to_string())
            .unwrap_or_default()
    };
    for l in list("label=orch.publish.step").await.lines() {
        if let Some((_, n)) = l.split_once('\t') {
            rm_container(n.trim()).await;
        }
    }
    for n in orphan_containers(&list("label=orch.publish.app").await, known_apps) {
        rm_container(&n).await;
    }
}

/// Reject Dockerfiles that could reach outside the build: any parser directive (`syntax`, `escape`,
/// `check`: a frontend image, or a changed line-continuation character), any `--mount` (host
/// cache/secret/ssh mounts), any non-ASCII byte. `--mount` is looked for in the raw text and in the
/// text with every backslash/backtick line continuation removed (no space inserted).
pub fn check_dockerfile(text: &str) -> Result<(), &'static str> {
    let text = text.strip_prefix('\u{feff}').unwrap_or(text);
    if !text.is_ascii() {
        return Err("The Dockerfile must use plain ASCII only.");
    }
    let lower = text.to_ascii_lowercase();
    for l in lower.lines() {
        if let Some(rest) = l.trim_start().strip_prefix('#') {
            let rest = rest.trim_start();
            for d in ["syntax", "escape", "check"] {
                if rest
                    .strip_prefix(d)
                    .is_some_and(|r| r.trim_start().starts_with('='))
                {
                    return Err(
                        "The Dockerfile must not have a parser directive (# syntax=, # escape=).",
                    );
                }
            }
        }
    }
    // Deliberately stricter than BuildKit's own line joining (trailing blanks after `\`, comment and
    // empty lines inside a continuation): drop comment lines, then every blank and continuation
    // character, so `--mount` can't be assembled across lines in any way. False alarms are fine.
    let squashed: String = lower
        .lines()
        .filter(|l| !l.trim_start().starts_with('#'))
        .flat_map(str::chars)
        .filter(|c| !c.is_ascii_whitespace() && *c != '\\' && *c != '`')
        .collect();
    if lower.contains("--mount") || squashed.contains("--mount") {
        return Err("The Dockerfile must not use `--mount=`.");
    }
    Ok(())
}

fn build_gate() -> &'static tokio::sync::Semaphore {
    static S: std::sync::OnceLock<tokio::sync::Semaphore> = std::sync::OnceLock::new();
    S.get_or_init(|| tokio::sync::Semaphore::new(1))
}

/// Tag of a new image: unique even after an app name is reused.
pub fn new_image_tag(app: &str, vdir: &str) -> String {
    format!("orch-app-{app}:{vdir}-{}", crate::util::rand_id(8))
}

/// `docker build` of a docker-stack bundle (one build at a time on this server). Returns (success, output).
pub async fn build_image(tag: &str, dir: &Path, secs: u64) -> (bool, String) {
    let _permit = build_gate().acquire().await;
    let mut c = Command::from(docker_std());
    // --load: with a buildx docker-container driver the image would stay in the build cache only
    c.args(["build", "--load", "-t", tag])
        .arg(dir)
        .stdin(Stdio::null())
        .kill_on_drop(true);
    let r = match tokio::time::timeout(Duration::from_secs(secs), c.output()).await {
        Err(_) => (false, format!("timed out after {secs} s")),
        Ok(Err(e)) => (false, e.to_string()),
        Ok(Ok(o)) => {
            let mut out = String::from_utf8_lossy(&o.stdout).to_string();
            out.push_str(&String::from_utf8_lossy(&o.stderr));
            (o.status.success(), out)
        }
    };
    let _ = Command::from(docker_std())
        .args(["builder", "prune", "-f", "--keep-storage", "2GB"])
        .output()
        .await;
    r
}

/// Images of an app (`vdir` = only that version).
async fn find_images(app: &str, vdir: Option<&str>) -> Vec<String> {
    let pat = match vdir {
        Some(v) => format!("orch-app-{app}:{v}-*"),
        None => format!("orch-app-{app}:*"),
    };
    Command::from(docker_std())
        .args([
            "images",
            "--format",
            "{{.Repository}}:{{.Tag}}",
            "--filter",
            &format!("reference={pat}"),
        ])
        .output()
        .await
        .map(|o| {
            String::from_utf8_lossy(&o.stdout)
                .lines()
                .map(|l| l.trim().to_string())
                .filter(|l| !l.is_empty())
                .collect()
        })
        .unwrap_or_default()
}

/// The image of this version, built now if the engine does not have it. None = could not build.
pub async fn ensure_image(app: &str, vdir: &str, dir: &Path, secs: u64) -> Option<String> {
    if let Some(t) = find_images(app, Some(vdir)).await.into_iter().next() {
        return Some(t);
    }
    let tag = new_image_tag(app, vdir);
    build_image(&tag, dir, secs).await.0.then_some(tag)
}

/// Removes the images of an app: one version (`vdir`) or all of them (best effort).
pub async fn remove_images(app: &str, vdir: Option<&str>) {
    for t in find_images(app, vdir).await {
        let _ = Command::from(docker_std())
            .args(["rmi", "-f", &t])
            .output()
            .await;
    }
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
            ensure_network(name);
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
            group_writable_dir(&s.data_dir);
            let script = (!s.start.is_empty()).then(|| format!("umask 002; exec {}", s.start));
            let args = container_run_args(&RunOpts {
                name: &unit,
                app: app_of(name),
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
                user: &app_user(),
                timeout_secs: None,
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
        let app = ctx.app.to_string();
        let _ = tokio::task::spawn_blocking(move || ensure_network(&app)).await;
        group_writable_dir(data_dir);
        let script = format!("umask 002; {cmd}");
        let args = container_run_args(&RunOpts {
            name: &unit,
            app: ctx.app,
            stack: ctx.stack,
            image: ctx.image,
            code: dir,
            code_rw: ctx.writable,
            data: data_dir,
            port,
            base_path,
            store,
            script: Some(&script),
            step: true,
            user: &app_user(),
            timeout_secs: Some(secs + 5),
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
    let mut guard = RmOnDrop {
        name: unit.clone(),
        armed: container,
    };
    let cleanup = |unit: String| async move {
        if container {
            rm_container(&unit).await;
        } else {
            stop_unit(&unit).await;
        }
    };
    let res = tokio::time::timeout(Duration::from_secs(secs), c.output()).await;
    guard.armed = false;
    match res {
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
            app: "de",
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
            user: "61000:1002",
            timeout_secs: None,
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
            ("--network", network_name("de").as_str()),
            ("--memory-swap", "128m"),
            ("-p", "127.0.0.1:9100:9100"),
            ("--memory", "128m"),
            ("--cpus", "0.5"),
            ("--pids-limit", "64"),
            ("--tmpfs", "/tmp:size=32m"),
            ("--cap-drop", "ALL"),
            ("--security-opt", "no-new-privileges"),
            ("--user", "61000:1002"),
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
        o.timeout_secs = Some(65);
        let a = container_run_args(&o);
        assert!(pair(&a, "-v", "/srv/code:/app"), "build mounts code rw");
        assert!(pair(&a, "--label", "orch.publish.step=1"));
        assert!(pair(&a, "--label", "orch.publish.app=de"));
        assert!(
            pair(&a, "-v", "/srv/code:/data"),
            "steps keep /data writable"
        );
        assert!(!a.iter().any(|x| x.contains("dev.kiri")));
        let n = a.len();
        assert_eq!(
            &a[n - 6..n - 1],
            ["node:22-slim", "timeout", "65", "sh", "-c"].map(String::from)
        );
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
            ["orch-app-de:v1", "-c", "./run"]
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

    #[test]
    fn per_app_networks_and_store_none_is_read_only() {
        assert_ne!(network_name("a-b"), network_name("a-c"));
        assert_eq!(network_name("demo"), network_name("demo~new"));
        let d = PathBuf::from("/srv/code");
        let mut o = opts("python", None, &d);
        o.store = "none";
        assert!(pair(&container_run_args(&o), "-v", "/srv/code:/data:ro"));
    }

    #[test]
    fn docker_stack_scripts_go_through_sh_entrypoint() {
        let d = PathBuf::from("/srv/code");
        let mut o = opts("docker", Some("orch-app-de:v1-abcd1234"), &d);
        o.script = Some("./run");
        o.timeout_secs = Some(60);
        let a = container_run_args(&o);
        assert!(pair(&a, "--entrypoint", "sh"));
        let n = a.len();
        assert_eq!(
            &a[n - 3..],
            ["orch-app-de:v1-abcd1234", "-c", "./run"].map(String::from)
        );
        o.script = None;
        assert!(!container_run_args(&o).contains(&"--entrypoint".to_string()));
    }

    #[test]
    fn dockerfile_checks() {
        assert!(check_dockerfile("FROM x\nRUN a \\\n  && b\n").is_ok());
        assert!(check_dockerfile("# syntax=docker/dockerfile:1\nFROM x\n").is_err());
        assert!(check_dockerfile("#syntax = evil/frontend\nFROM x\n").is_err());
        assert!(check_dockerfile("FROM x\nRUN \\\n  --mount=type=cache,target=/c make\n").is_err());
        assert!(check_dockerfile("FROM x\n# just a comment about syntax\n").is_ok());
        // bypasses
        assert!(
            check_dockerfile("\u{feff}# syntax=evil/x\nFROM x\n").is_err(),
            "BOM"
        );
        assert!(check_dockerfile("# escape=`\nFROM x\nRUN --mo`\nunt=type=cache x\n").is_err());
        assert!(
            check_dockerfile("FROM x\nRUN --mo\\\r\nunt=type=cache x\n").is_err(),
            "CRLF"
        );
        assert!(check_dockerfile("FROM x\nRUN --MOUNT=type=cache x\n").is_err());
        assert!(
            check_dockerfile("FROM x\nRUN --mo\\  \t\nunt=type=cache x\n").is_err(),
            "blanks after the backslash"
        );
        assert!(
            check_dockerfile("FROM x\nRUN --mo\\\n# note\n\nunt=type=cache x\n").is_err(),
            "comment and empty line inside a continuation"
        );
        assert!(check_dockerfile("FROM x\nRUN - - m o u n t = x\n").is_err());
        assert!(check_dockerfile("FROM x\n  # Check=skip=all\n").is_err());
        assert!(
            check_dockerfile("FROM x\nLABEL a=\"\u{e9}\"\n").is_err(),
            "non-ASCII"
        );
    }

    #[test]
    fn subnet_picker_takes_the_first_free_28() {
        let pool = "10.213.0.0/16";
        assert_eq!(pick_subnet(pool, &[]).unwrap(), "10.213.0.0/28");
        let used = vec!["10.213.0.0/28".to_string(), "10.213.0.16/28".to_string()];
        assert_eq!(pick_subnet(pool, &used).unwrap(), "10.213.0.32/28");
        assert_eq!(
            pick_subnet(pool, &["10.213.0.0/24".to_string()]).unwrap(),
            "10.213.1.0/28"
        );
        assert!(pick_subnet("10.213.0.0/28", &["10.213.0.0/28".into()]).is_none());
        assert!(pick_subnet("garbage", &[]).is_none());
        let all: Vec<String> = (0..4096u32)
            .map(|i| format!("10.213.{}.{}/28", i / 16, (i % 16) * 16))
            .collect();
        assert!(pick_subnet(pool, &all).is_none());
    }

    #[test]
    fn orphan_containers_of_unknown_apps() {
        let known: HashSet<String> = ["keep".to_string()].into();
        let listed = "keep\torch-app-a-1\ngone\torch-app-b-2\n";
        assert_eq!(orphan_containers(listed, &known), vec!["orch-app-b-2"]);
    }

    #[test]
    fn image_tags_are_unique() {
        let a = new_image_tag("demo", "v1abc");
        assert!(a.starts_with("orch-app-demo:v1abc-"));
        assert_ne!(a, new_image_tag("demo", "v1abc"));
    }
}
