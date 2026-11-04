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
}

#[derive(Default)]
pub struct Runner {
    procs: Mutex<HashMap<String, Proc>>,
}

fn base_env(
    cmd: &mut Command,
    dir: &Path,
    port: u16,
    base_path: &str,
    data_dir: &Path,
    store: &str,
) {
    let path = std::env::var("PATH").unwrap_or_default();
    let venv = dir.join(".venv/bin");
    let path = if venv.is_dir() {
        format!("{}:{path}", venv.display())
    } else {
        path
    };
    cmd.env_clear()
        .env("PATH", path)
        .env("HOME", data_dir)
        .env("LANG", "C.UTF-8")
        .env("PORT", port.to_string())
        .env("BASE_PATH", base_path)
        .env("DATA_DIR", data_dir)
        .env("STORE", store)
        .current_dir(dir);
}

impl Runner {
    pub fn spawn(&self, name: &str, s: &Spec) -> std::io::Result<()> {
        if let Some(p) = s.log.parent() {
            std::fs::create_dir_all(p)?;
        }
        std::fs::create_dir_all(&s.data_dir)?;
        let log = std::fs::File::create(&s.log)?;
        let log2 = log.try_clone()?;
        let mut cmd = Command::new("sh");
        cmd.arg("-c").arg(format!("exec {}", s.start));
        base_env(
            &mut cmd,
            &s.dir,
            s.port,
            &s.base_path,
            &s.data_dir,
            &s.store,
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
            },
        );
        Ok(())
    }

    /// Kill the process (if any). Returns when it is gone.
    pub async fn stop(&self, name: &str) {
        let p = self.procs.lock().unwrap().remove(name);
        if let Some(mut p) = p {
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
    let mut c = Command::new("sh");
    c.arg("-c").arg(cmd);
    base_env(&mut c, dir, port, base_path, data_dir, store);
    c.stdin(Stdio::null()).kill_on_drop(true);
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
