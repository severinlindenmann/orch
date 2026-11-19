//! Command line of `orch-publish`: help, version, the start checks (root, ports, data folder) and the admin commands
//! (`orch-publish admin ...`), which talk to the running server's admin port with the admin token.

use http_body_util::BodyExt;
use serde_json::Value;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

pub const VERSION: &str = env!("CARGO_PKG_VERSION");

pub const HELP: &str = "\
orch-publish: the orch publish server (private file links and small apps).

Usage:
  orch-publish [--allow-root]          start the server (settings come from ORCH_PUBLISH_* environment variables)
  orch-publish admin <command>         manage a running server through its admin port
  orch-publish --help | -h             show this help
  orch-publish --version | -V          show the version

Admin commands:
  workspaces list                      list the workspaces with their file and app counts
  workspaces remove <id> [--dry-run]   delete a workspace with its files and apps
  (publish has no groups; groups live on the relay: orch-relay admin groups ...)

Admin options:
  --env-file <path>                    read ORCH_PUBLISH_* settings from this file
                                       (default: /etc/orch-publish/env when it exists and can be read)
  --admin-url <url>                    admin address (default: http://<ORCH_PUBLISH_ADMIN_LISTEN>, 127.0.0.1:8411)
  --dry-run                            only say what would be removed

The admin token comes from ORCH_PUBLISH_ADMIN_TOKEN, ORCH_PUBLISH_ADMIN_TOKEN_FILE, /etc/orch-publish/admin-token or
<data folder>/admin-token; the admin commands only read it, never make one.

Start checks: the server refuses to start as root (pass --allow-root or set ORCH_PUBLISH_ALLOW_ROOT=1 to allow it),
when its ports are taken, or when another orch-publish uses the same data folder.
";

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
}

fn unknown(a: &str) -> String {
    format!("unknown argument '{a}'. Try 'orch-publish --help'.")
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
            "--env-file" => a.env_file = Some(it.next().ok_or("--env-file needs a path.")?.into()),
            "--admin-url" => {
                a.admin_url = Some(it.next().ok_or("--admin-url needs an address.")?.clone())
            }
            s if s.starts_with('-') => return Err(unknown(s)),
            s => words.push(s.to_string()),
        }
    }
    let w: Vec<&str> = words.iter().map(String::as_str).collect();
    a.what = match w.as_slice() {
        ["workspaces", "list"] => AdminWhat::WorkspacesList,
        ["workspaces", "remove", id] => AdminWhat::WorkspacesRemove(id.to_string()),
        ["workspaces", "remove"] => {
            return Err("remove needs a workspace id (see 'workspaces list').".into())
        }
        ["groups", ..] => {
            return Err(
                "publish has no groups; use 'orch-relay admin groups ...' on the relay.".into(),
            )
        }
        [] => return Err("admin needs a command. Try 'orch-publish --help'.".into()),
        _ => {
            return Err(format!(
                "unknown admin command '{}'. Try 'orch-publish --help'.",
                w.join(" ")
            ))
        }
    };
    if a.dry_run && a.what == AdminWhat::WorkspacesList {
        return Err("--dry-run only goes with remove.".into());
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

/// Refuse root unless the flag or ORCH_PUBLISH_ALLOW_ROOT=1 says so.
pub fn check_root(allow_flag: bool, root: bool) -> Result<(), String> {
    let allow_env = std::env::var("ORCH_PUBLISH_ALLOW_ROOT").is_ok_and(|v| v == "1");
    if root && !allow_flag && !allow_env {
        return Err(
            "refusing to run as root: files in the data folder would belong to root. \
                    Run it as the service user, or pass --allow-root."
                .into(),
        );
    }
    Ok(())
}

/// The data folder from the environment, without reading or writing anything.
pub fn data_dir_from_env() -> PathBuf {
    PathBuf::from(crate::config::var("DATA_DIR").unwrap_or_else(|| "/var/lib/orch-publish".into()))
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

/// Read KEY=VALUE lines of ORCH_PUBLISH_* / PUBLISH_* settings (comments and blank lines skipped, quotes removed).
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
        if k.starts_with("ORCH_PUBLISH_") || k.starts_with("PUBLISH_") {
            m.insert(
                k.to_string(),
                v.trim().trim_matches('"').trim_matches('\'').to_string(),
            );
        }
    }
    Ok(m)
}

/// The admin address and token: the environment first, then the env file. Reads the token, never makes one.
pub fn admin_target(a: &Admin) -> Result<(String, String), String> {
    let file = match &a.env_file {
        Some(p) => read_env_file(p)?,
        None => read_env_file(Path::new("/etc/orch-publish/env")).unwrap_or_default(),
    };
    let get = |k: &str| {
        [format!("ORCH_PUBLISH_{k}"), format!("PUBLISH_{k}")]
            .iter()
            .find_map(|n| std::env::var(n).ok().or_else(|| file.get(n).cloned()))
            .filter(|v| !v.trim().is_empty())
    };
    let data_dir = PathBuf::from(get("DATA_DIR").unwrap_or_else(|| "/var/lib/orch-publish".into()));
    let token = match get("ADMIN_TOKEN") {
        Some(t) => t.trim().to_string(),
        None => {
            let files = [
                get("ADMIN_TOKEN_FILE")
                    .map(PathBuf::from)
                    .unwrap_or_else(|| PathBuf::from("/etc/orch-publish/admin-token")),
                data_dir.join("admin-token"),
            ];
            files
                .iter()
                .find_map(|f| std::fs::read_to_string(f).ok())
                .map(|t| t.trim().to_string())
                .filter(|t| !t.is_empty())
                .ok_or_else(|| {
                    format!(
                        "no admin token found (ORCH_PUBLISH_ADMIN_TOKEN, {}, {}). \
                         Run it as the service user, or pass --env-file.",
                        files[0].display(),
                        files[1].display()
                    )
                })?
        }
    };
    let url = match &a.admin_url {
        Some(u) => u.trim_end_matches('/').to_string(),
        None => {
            let listen = get("ADMIN_LISTEN").unwrap_or("127.0.0.1:8411".into());
            let listen = listen
                .replace("0.0.0.0:", "127.0.0.1:")
                .replace("[::]:", "[::1]:");
            format!("http://{listen}")
        }
    };
    Ok((url, token))
}

struct Client {
    http: crate::Http,
    url: String,
    token: String,
}

impl Client {
    async fn call(&self, method: &str, path: &str) -> Result<Value, String> {
        let req = axum::http::Request::builder()
            .method(method)
            .uri(format!("{}{path}", self.url))
            .header("x-orch-admin", &self.token)
            .body(axum::body::Body::empty())
            .map_err(|e| e.to_string())?;
        let r = self
            .http
            .request(req)
            .await
            .map_err(|e| format!("cannot reach the publish admin port at {}: {e}", self.url))?;
        let s = r.status().as_u16();
        let body = r
            .into_body()
            .collect()
            .await
            .map_err(|e| e.to_string())?
            .to_bytes();
        let v: Value = serde_json::from_slice(&body).unwrap_or(Value::Null);
        if !(200..300).contains(&s) {
            let msg = v["message"]
                .as_str()
                .unwrap_or("the server refused the request");
            return Err(format!("{msg} (HTTP {s})"));
        }
        Ok(v)
    }
}

fn plural(k: i64, one: &str, many: &str) -> String {
    format!("{k} {}", if k == 1 { one } else { many })
}

/// Run one admin command against the configured server; returns the text to print.
pub async fn run_admin(a: Admin) -> Result<String, String> {
    let (url, token) = admin_target(&a)?;
    run_admin_at(a, &url, &token).await
}

fn enc(s: &str) -> String {
    s.bytes()
        .map(|b| {
            if b.is_ascii_alphanumeric() || b == b'_' || b == b'-' {
                (b as char).to_string()
            } else {
                format!("%{b:02X}")
            }
        })
        .collect()
}

/// Run against a given address and token.
pub async fn run_admin_at(a: Admin, url: &str, token: &str) -> Result<String, String> {
    let c = Client {
        http: hyper_util::client::legacy::Client::builder(hyper_util::rt::TokioExecutor::new())
            .build_http(),
        url: url.trim_end_matches('/').to_string(),
        token: token.to_string(),
    };
    let mut out = String::new();
    match a.what {
        AdminWhat::None => return Err("admin needs a command.".into()),
        AdminWhat::WorkspacesList => {
            let mut items = vec![];
            let mut after: Option<String> = None;
            loop {
                let p = match &after {
                    Some(n) => format!("/admin/api/workspaces?limit=100&after={}", enc(n)),
                    None => "/admin/api/workspaces?limit=100".to_string(),
                };
                let v = c.call("GET", &p).await?;
                items.extend(v["items"].as_array().cloned().unwrap_or_default());
                match v["next"].as_str() {
                    Some(n) if !n.is_empty() && items.len() < 100_000 => {
                        after = Some(n.to_string())
                    }
                    _ => break,
                }
            }
            out.push_str(&format!(
                "{}\n",
                plural(items.len() as i64, "workspace", "workspaces")
            ));
            for w in items {
                out.push_str(&format!(
                    "{}  {}  {}  {}\n",
                    w["id"].as_str().unwrap_or(""),
                    w["name"].as_str().unwrap_or(""),
                    plural(w["files"].as_i64().unwrap_or(0), "file", "files"),
                    plural(w["apps"].as_i64().unwrap_or(0), "app", "apps"),
                ));
            }
        }
        AdminWhat::WorkspacesRemove(id) => {
            let p = format!("/admin/api/workspaces/{}", enc(&id));
            let v = c.call("DELETE", &format!("{p}?dry_run=1")).await?;
            let name = v["name"].as_str().unwrap_or("").to_string();
            let what = format!(
                "{}, {}",
                plural(v["removes"]["files"].as_i64().unwrap_or(0), "file", "files"),
                plural(v["removes"]["apps"].as_i64().unwrap_or(0), "app", "apps")
            );
            if a.dry_run {
                out.push_str(&format!(
                    "Dry run: removing {id} ({name}) would delete {what}.\n"
                ));
            } else {
                c.call("DELETE", &p).await?;
                out.push_str(&format!("Removed {id} ({name}): {what}.\n"));
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
    fn help_version_serve_unknown() {
        for a in [&["--help"][..], &["-h"], &["help"], &["admin", "-h"]] {
            assert_eq!(p(a), Ok(Cmd::Help), "{a:?}");
        }
        assert_eq!(p(&["-V"]), Ok(Cmd::Version));
        assert_eq!(p(&[]), Ok(Cmd::Serve { allow_root: false }));
        assert_eq!(p(&["--allow-root"]), Ok(Cmd::Serve { allow_root: true }));
        for a in [
            &["--hepl"][..],
            &["x"],
            &["admin"],
            &["admin", "groups", "list"],
            &["admin", "workspaces", "list", "--dry-run"],
            &["admin", "workspaces", "remove", "a", "--yes"],
        ] {
            assert!(p(a).is_err(), "{a:?}");
        }
    }

    #[test]
    fn admin_commands() {
        match p(&["admin", "workspaces", "remove", "ws_1", "--dry-run"]).unwrap() {
            Cmd::Admin(a) => {
                assert_eq!(a.what, AdminWhat::WorkspacesRemove("ws_1".into()));
                assert!(a.dry_run);
            }
            c => panic!("{c:?}"),
        }
    }

    #[test]
    fn root_and_lock() {
        assert!(check_root(false, true).is_err());
        assert!(check_root(true, true).is_ok());
        let d = tempfile::tempdir().unwrap();
        let l = lock_data_dir(d.path(), "orch-publish").unwrap();
        assert!(lock_data_dir(d.path(), "orch-publish").is_err());
        drop(l);
        assert!(lock_data_dir(d.path(), "orch-publish").is_ok());
    }

    #[test]
    fn enc_keeps_ids_and_escapes_the_rest() {
        assert_eq!(enc("ws_ab-1"), "ws_ab-1");
        assert_eq!(enc("a/b?c"), "a%2Fb%3Fc");
    }
}
