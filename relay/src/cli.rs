//! Command line of `orch-relay`: help, version, the start checks (root, ports, data folder) and the admin commands
//! (`orch-relay admin ...`), which talk to the running server's admin port with the admin token.

use serde_json::Value;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

pub const VERSION: &str = env!("CARGO_PKG_VERSION");

pub const HELP: &str = "\
orch-relay: the orch relay server (messages between workspaces and phones).

Usage:
  orch-relay [--allow-root]          start the server (settings come from ORCH_RELAY_* environment variables)
  orch-relay admin <command>         manage a running server through its admin port
  orch-relay --help | -h             show this help
  orch-relay --version | -V          show the version

Admin commands:
  workspaces list                    list the workspaces
  workspaces remove <id> [--dry-run] delete a workspace with its messages, files and problem reports
  groups list                        list the groups
  groups remove <id> [--dry-run]     delete a group (its workspaces stay, outside any group)
  cleanup [--dry-run]                remove history (messages, files, problem reports, log lines) of workspaces
                                     that no longer exist; take a backup of relay.db first

Admin options:
  --env-file <path>                  read ORCH_RELAY_* settings from this file
                                     (default: /etc/orch-relay/env when it exists and can be read)
  --admin-url <url>                  admin address (default: http://<ORCH_RELAY_ADMIN_LISTEN>, 127.0.0.1:8412)
  --dry-run                          only say what would be removed

Start checks: the server refuses to start as root (pass --allow-root or set ORCH_RELAY_ALLOW_ROOT=1 to allow it),
when its ports are taken, or when another orch-relay uses the same data folder.
";

/// What the command line asks for.
#[derive(Debug, PartialEq, Eq)]
pub enum Cmd {
    Help,
    Version,
    Serve { allow_root: bool },
    Admin(Admin),
}

#[derive(Debug, PartialEq, Eq, Default)]
pub struct Admin {
    pub what: AdminWhat,
    pub dry_run: bool,
    pub env_file: Option<PathBuf>,
    pub admin_url: Option<String>,
}

#[derive(Debug, PartialEq, Eq, Default)]
pub enum AdminWhat {
    #[default]
    None,
    WorkspacesList,
    WorkspacesRemove(String),
    GroupsList,
    GroupsRemove(String),
    Cleanup,
}

fn unknown(a: &str) -> String {
    format!("unknown argument '{a}'. Try 'orch-relay --help'.")
}

/// Parse the arguments after the program name. Unknown arguments are refused.
pub fn parse(args: &[String]) -> Result<Cmd, String> {
    if args
        .iter()
        .any(|a| a == "--help" || a == "-h" || a == "help")
    {
        return Ok(Cmd::Help);
    }
    if args.iter().any(|a| a == "--version" || a == "-V") {
        return Ok(Cmd::Version);
    }
    match args.first().map(String::as_str) {
        None => Ok(Cmd::Serve { allow_root: false }),
        Some("--allow-root") if args.len() == 1 => Ok(Cmd::Serve { allow_root: true }),
        Some("admin") => parse_admin(&args[1..]).map(Cmd::Admin),
        Some(_) => Err(unknown(
            args.iter()
                .find(|a| *a != "--allow-root")
                .unwrap_or(&args[0]),
        )),
    }
}

fn parse_admin(args: &[String]) -> Result<Admin, String> {
    let mut a = Admin::default();
    let mut words = vec![];
    let mut it = args.iter();
    while let Some(x) = it.next() {
        match x.as_str() {
            "--dry-run" => a.dry_run = true,
            "--env-file" => {
                a.env_file = Some(it.next().ok_or("--env-file needs a path.")?.into());
            }
            "--admin-url" => {
                a.admin_url = Some(it.next().ok_or("--admin-url needs an address.")?.clone());
            }
            s if s.starts_with('-') => return Err(unknown(s)),
            s => words.push(s.to_string()),
        }
    }
    let w: Vec<&str> = words.iter().map(String::as_str).collect();
    a.what = match w.as_slice() {
        ["workspaces", "list"] => AdminWhat::WorkspacesList,
        ["workspaces", "remove", id] => AdminWhat::WorkspacesRemove(id.to_string()),
        ["groups", "list"] => AdminWhat::GroupsList,
        ["groups", "remove", id] => AdminWhat::GroupsRemove(id.to_string()),
        ["workspaces" | "groups", "remove"] => {
            return Err("remove needs an id (see the list command).".into())
        }
        ["cleanup"] => AdminWhat::Cleanup,
        [] => return Err("admin needs a command. Try 'orch-relay --help'.".into()),
        _ => {
            return Err(format!(
                "unknown admin command '{}'. Try 'orch-relay --help'.",
                w.join(" ")
            ))
        }
    };
    if a.dry_run && matches!(a.what, AdminWhat::WorkspacesList | AdminWhat::GroupsList) {
        return Err("--dry-run only goes with remove and cleanup.".into());
    }
    Ok(a)
}

// ---------- start checks ----------

#[cfg(unix)]
pub fn is_root() -> bool {
    unsafe extern "C" {
        fn geteuid() -> u32;
    }
    // SAFETY: geteuid has no preconditions and cannot fail.
    unsafe { geteuid() == 0 }
}

#[cfg(not(unix))]
pub fn is_root() -> bool {
    false
}

/// Refuse root unless the flag or ORCH_RELAY_ALLOW_ROOT=1 says so.
pub fn check_root(allow_flag: bool, root: bool) -> Result<(), String> {
    let allow_env = std::env::var("ORCH_RELAY_ALLOW_ROOT").is_ok_and(|v| v == "1");
    if root && !allow_flag && !allow_env {
        return Err(
            "refusing to run as root: files in the data folder would belong to root. \
                    Run it as the service user (orch-relay), or pass --allow-root."
                .into(),
        );
    }
    Ok(())
}

/// Keeps the data folder to this process while it lives.
pub struct DataLock(#[allow(dead_code)] std::fs::File);

/// Take the data folder for this process, or say which process has it.
pub fn lock_data_dir(dir: &Path, name: &str) -> Result<DataLock, String> {
    std::fs::create_dir_all(dir).map_err(|e| format!("data folder {}: {e}", dir.display()))?;
    let path = dir.join(format!(".{name}.lock"));
    let f = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(&path)
        .map_err(|e| format!("{}: {e}", path.display()))?;
    match f.try_lock() {
        Ok(()) => {
            let _ = f.set_len(0);
            let _ = std::io::Write::write_all(&mut &f, std::process::id().to_string().as_bytes());
            Ok(DataLock(f))
        }
        Err(std::fs::TryLockError::WouldBlock) => {
            let pid = std::fs::read_to_string(&path).unwrap_or_default();
            Err(format!(
                "the data folder {} is in use by another {name} (process {}). Stop it first.",
                dir.display(),
                pid.trim()
            ))
        }
        Err(std::fs::TryLockError::Error(e)) => Err(format!("{}: {e}", path.display())),
    }
}

// ---------- admin client ----------

/// Read KEY=VALUE lines of ORCH_RELAY_* settings (comments and blank lines skipped, quotes around the value removed).
pub fn read_env_file(path: &Path) -> Result<HashMap<String, String>, String> {
    let text = std::fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    let mut m = HashMap::new();
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let line = line.strip_prefix("export ").unwrap_or(line);
        let Some((k, v)) = line.split_once('=') else {
            continue;
        };
        let k = k.trim();
        if k.starts_with("ORCH_RELAY_") {
            m.insert(
                k.to_string(),
                v.trim().trim_matches('"').trim_matches('\'').to_string(),
            );
        }
    }
    Ok(m)
}

/// The admin address and token: the environment first, then the env file (`--env-file`, else /etc/orch-relay/env).
pub fn admin_target(a: &Admin) -> Result<(String, String), String> {
    let file = match &a.env_file {
        Some(p) => read_env_file(p)?,
        None => read_env_file(Path::new("/etc/orch-relay/env")).unwrap_or_default(),
    };
    let get = |k: &str| {
        std::env::var(k)
            .ok()
            .or_else(|| file.get(k).cloned())
            .filter(|v| !v.is_empty())
    };
    let token = match (
        get("ORCH_RELAY_ADMIN_TOKEN"),
        get("ORCH_RELAY_ADMIN_TOKEN_FILE"),
    ) {
        (Some(t), _) => t,
        (None, Some(f)) => std::fs::read_to_string(&f)
            .map_err(|e| {
                format!(
                    "admin token file {f}: {e}. Run it as the service user (sudo -u orch-relay)."
                )
            })?
            .trim()
            .to_string(),
        _ => {
            return Err(
                "no admin token: set ORCH_RELAY_ADMIN_TOKEN or ORCH_RELAY_ADMIN_TOKEN_FILE, \
                        or pass --env-file /etc/orch-relay/env."
                    .into(),
            )
        }
    };
    let url = match &a.admin_url {
        Some(u) => u.trim_end_matches('/').to_string(),
        None => {
            let listen = get("ORCH_RELAY_ADMIN_LISTEN").unwrap_or("127.0.0.1:8412".into());
            // the interface form (wt0:port) becomes that interface's address, never a host name lookup
            let addr = crate::listen::client_addr("ORCH_RELAY_ADMIN_LISTEN", &listen)?;
            format!("http://{addr}")
        }
    };
    Ok((url, token))
}

struct Client {
    http: reqwest::Client,
    url: String,
    token: String,
}

impl Client {
    async fn call(&self, method: reqwest::Method, path: &str) -> Result<(u16, Value), String> {
        let r = self
            .http
            .request(method, format!("{}{path}", self.url))
            .header("X-Orch-Admin", &self.token)
            .send()
            .await
            .map_err(|e| format!("cannot reach the relay admin port at {}: {e}", self.url))?;
        let s = r.status().as_u16();
        let v: Value = r.json().await.unwrap_or(Value::Null);
        if !(200..300).contains(&s) {
            let msg = v["message"]
                .as_str()
                .unwrap_or("the relay refused the request");
            return Err(format!("{msg} (HTTP {s})"));
        }
        Ok((s, v))
    }
}

fn n(v: &Value, k: &str) -> i64 {
    v[k].as_i64().unwrap_or(0)
}

fn plural(k: i64, one: &str, many: &str) -> String {
    format!("{k} {}", if k == 1 { one } else { many })
}

fn counts_line(v: &Value) -> String {
    [
        plural(n(v, "messages"), "message", "messages"),
        plural(n(v, "files"), "file", "files"),
        plural(n(v, "problems"), "problem report", "problem reports"),
        plural(
            n(v, "sub_log"),
            "subscriber log line",
            "subscriber log lines",
        ),
        plural(
            n(v, "subscribers"),
            "subscriber changed",
            "subscribers changed",
        ),
    ]
    .join(", ")
}

/// Run one admin command; returns the text to print.
pub async fn run_admin(a: Admin) -> Result<String, String> {
    let (url, token) = admin_target(&a)?;
    let c = Client {
        http: reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(300))
            // The admin token is a custom header: never let a redirect carry it to another host.
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|e| e.to_string())?,
        url,
        token,
    };
    run_with(&c, a).await
}

/// Run against a given address and token (tests).
pub async fn run_admin_at(a: Admin, url: &str, token: &str) -> Result<String, String> {
    let c = Client {
        http: reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|e| e.to_string())?,
        url: url.trim_end_matches('/').to_string(),
        token: token.to_string(),
    };
    run_with(&c, a).await
}

fn enc(s: &str) -> String {
    percent_encoding::utf8_percent_encode(s, percent_encoding::NON_ALPHANUMERIC).to_string()
}

async fn run_with(c: &Client, a: Admin) -> Result<String, String> {
    use reqwest::Method;
    let mut out = String::new();
    match a.what {
        AdminWhat::None => return Err("admin needs a command.".into()),
        AdminWhat::WorkspacesList => {
            let (_, v) = c.call(Method::GET, "/admin/api/workspaces").await?;
            let items = v["items"].as_array().cloned().unwrap_or_default();
            out.push_str(&format!(
                "{}\n",
                plural(items.len() as i64, "workspace", "workspaces")
            ));
            for w in items {
                out.push_str(&format!(
                    "{}  {}  group: {}  last seen: {}\n",
                    w["id"].as_str().unwrap_or(""),
                    w["name"].as_str().unwrap_or(""),
                    w["group"].as_str().unwrap_or("-"),
                    match &w["last_seen"] {
                        Value::Null => "never".to_string(),
                        Value::String(t) => t.clone(),
                        x => x.to_string(),
                    },
                ));
            }
        }
        AdminWhat::WorkspacesRemove(id) => {
            let p = format!("/admin/api/workspaces/{}", enc(&id));
            let (_, v) = c.call(Method::GET, &format!("{p}/removal")).await?;
            if v["dry_run"] != Value::Bool(true) {
                return Err(
                    "the server gave no preview; nothing was removed (is it an older version?)"
                        .into(),
                );
            }
            let name = v["name"].as_str().unwrap_or("").to_string();
            let what = counts_line(&v["removes"]);
            if a.dry_run {
                out.push_str(&format!(
                    "Dry run: removing {id} ({name}) would delete {what}.\n"
                ));
            } else {
                c.call(Method::DELETE, &p).await?;
                out.push_str(&format!("Removed {id} ({name}): {what}.\n"));
            }
        }
        AdminWhat::GroupsList => {
            let (_, v) = c.call(Method::GET, "/admin/api/groups").await?;
            let items = v["items"]
                .as_array()
                .or_else(|| v.as_array())
                .cloned()
                .unwrap_or_default();
            out.push_str(&format!(
                "{}\n",
                plural(items.len() as i64, "group", "groups")
            ));
            for g in items {
                let members = g["members"].as_array().map(|m| m.len()).unwrap_or(0);
                out.push_str(&format!(
                    "{}  {}  {}\n",
                    g["id"].as_str().unwrap_or(""),
                    g["name"].as_str().unwrap_or(""),
                    plural(members as i64, "workspace", "workspaces")
                ));
            }
        }
        AdminWhat::GroupsRemove(id) => {
            let (_, v) = c.call(Method::GET, "/admin/api/groups").await?;
            let items = v["items"]
                .as_array()
                .or_else(|| v.as_array())
                .cloned()
                .unwrap_or_default();
            let Some(g) = items.iter().find(|g| g["id"].as_str() == Some(id.as_str())) else {
                return Err(format!("No such group: {id}."));
            };
            let name = g["name"].as_str().unwrap_or("");
            let members = g["members"].as_array().map(|m| m.len()).unwrap_or(0);
            if a.dry_run {
                out.push_str(&format!(
                    "Dry run: removing group {id} ({name}) would take {} out of it; they stay.\n",
                    plural(members as i64, "workspace", "workspaces")
                ));
            } else {
                c.call(Method::DELETE, &format!("/admin/api/groups/{}", enc(&id)))
                    .await?;
                out.push_str(&format!(
                    "Removed group {id} ({name}); its {} stay, outside any group.\n",
                    plural(members as i64, "workspace", "workspaces")
                ));
            }
        }
        AdminWhat::Cleanup => {
            if a.dry_run {
                let (_, v) = c.call(Method::POST, "/admin/api/cleanup?dry_run=1").await?;
                out.push_str(&format!(
                    "Dry run: the clean-up would delete {}.\n",
                    counts_line(&v["removes"])
                ));
            } else {
                let (_, v) = c.call(Method::POST, "/admin/api/cleanup").await?;
                out.push_str(&format!("Cleaned up: {}.\n", counts_line(&v["removed"])));
            }
        }
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn p(a: &[&str]) -> Result<Cmd, String> {
        parse(&a.iter().map(|s| s.to_string()).collect::<Vec<_>>())
    }

    #[test]
    fn help_and_version_never_serve() {
        for a in [
            &["--help"][..],
            &["-h"],
            &["help"],
            &["admin", "--help"],
            &["--allow-root", "-h"],
        ] {
            assert_eq!(p(a), Ok(Cmd::Help), "{a:?}");
        }
        assert_eq!(p(&["--version"]), Ok(Cmd::Version));
        assert_eq!(p(&["-V"]), Ok(Cmd::Version));
        assert!(HELP.contains("--help") && HELP.contains("workspaces remove"));
    }

    #[test]
    fn serve_and_unknown() {
        assert_eq!(p(&[]), Ok(Cmd::Serve { allow_root: false }));
        assert_eq!(p(&["--allow-root"]), Ok(Cmd::Serve { allow_root: true }));
        for a in [
            &["--hepl"][..],
            &["serve"],
            &["-x"],
            &["--allow-root", "x"],
            &["admin", "x"],
            &["admin"],
            &["admin", "workspaces", "list", "--force"],
            &["admin", "workspaces", "remove"],
            &["admin", "workspaces", "list", "--dry-run"],
        ] {
            assert!(p(a).is_err(), "{a:?}");
        }
        assert!(p(&["--hepl"]).unwrap_err().contains("--hepl"));
    }

    #[test]
    fn admin_commands() {
        let a = |x: &[&str]| match p(x).unwrap() {
            Cmd::Admin(a) => a,
            c => panic!("{c:?}"),
        };
        assert_eq!(
            a(&["admin", "workspaces", "list"]).what,
            AdminWhat::WorkspacesList
        );
        let r = a(&["admin", "workspaces", "remove", "ws_abc", "--dry-run"]);
        assert_eq!(
            (r.what, r.dry_run),
            (AdminWhat::WorkspacesRemove("ws_abc".into()), true)
        );
        assert_eq!(
            a(&["admin", "groups", "remove", "g1"]).what,
            AdminWhat::GroupsRemove("g1".into())
        );
        let c = a(&["admin", "--env-file", "/x/env", "cleanup", "--dry-run"]);
        assert_eq!(
            (c.what, c.dry_run, c.env_file),
            (AdminWhat::Cleanup, true, Some("/x/env".into()))
        );
    }

    #[test]
    fn root_is_refused_unless_allowed() {
        assert!(check_root(false, true).is_err());
        assert!(check_root(true, true).is_ok());
        assert!(check_root(false, false).is_ok());
    }

    #[test]
    fn data_folder_lock_is_exclusive() {
        let d = tempfile::tempdir().unwrap();
        let first = lock_data_dir(d.path(), "orch-relay").unwrap();
        let e = lock_data_dir(d.path(), "orch-relay").err().unwrap();
        assert!(e.contains("in use by another orch-relay"), "{e}");
        assert!(e.contains(&std::process::id().to_string()), "{e}");
        drop(first);
        assert!(lock_data_dir(d.path(), "orch-relay").is_ok());
    }
}
