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
        let mut cmd = make_cmd(
            &format!("exec {}", s.start),
            &unit,
            &s.dir,
            s.port,
            &s.base_path,
            &s.data_dir,
            &s.store,
            None,
        );
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
pub async fn run_step(
    cmd: &str,
    dir: &Path,
    port: u16,
    base_path: &str,
    data_dir: &Path,
    store: &str,
    secs: u64,
) -> (bool, String) {
    let _ = std::fs::create_dir_all(data_dir);
    let unit = format!("orch-step-{}", crate::util::rand_id(8));
    let mut c = make_cmd(
        cmd,
        &unit,
        dir,
        port,
        base_path,
        data_dir,
        store,
        Some(secs),
    );
    c.stdin(Stdio::null()).kill_on_drop(true);
    match tokio::time::timeout(Duration::from_secs(secs), c.output()).await {
        Err(_) => {
            stop_unit(&unit).await;
            (false, format!("timed out after {secs} s"))
        }
        Ok(Err(e)) => {
            stop_unit(&unit).await;
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
        std::env::remove_var("ORCH_PUBLISH_SANDBOX");
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
}
