//! The orch-relay program: help never starts a server, start checks, and the admin commands.
mod common;
use common::*;
use orch_relay::cli::{self, Admin, AdminWhat};
use serde_json::json;
use std::process::{Command, Output};

const BIN: &str = env!("CARGO_BIN_EXE_orch-relay");

/// Run the program in an empty environment whose settings point at `dir`.
fn run(dir: &std::path::Path, args: &[&str], extra: &[(&str, &str)]) -> Output {
    let mut c = Command::new(BIN);
    c.args(args)
        .env_clear()
        .env("HOME", dir)
        .env("ORCH_RELAY_DATA_DIR", dir.join("data"))
        .env("ORCH_RELAY_ADMIN_TOKEN", ADMIN)
        .env("ORCH_RELAY_MASTER_KEY_FILE", dir.join("master.key"));
    for (k, v) in extra {
        c.env(k, v);
    }
    c.output().unwrap()
}

fn text(o: &Output) -> String {
    format!(
        "{}{}",
        String::from_utf8_lossy(&o.stdout),
        String::from_utf8_lossy(&o.stderr)
    )
}

fn free_port() -> u16 {
    std::net::TcpListener::bind("127.0.0.1:0")
        .unwrap()
        .local_addr()
        .unwrap()
        .port()
}

#[test]
fn help_and_version_print_and_never_start_a_server() {
    let d = tempfile::tempdir().unwrap();
    for a in ["--help", "-h"] {
        let o = run(d.path(), &[a], &[]);
        assert_eq!(o.status.code(), Some(0), "{}", text(&o));
        let out = String::from_utf8_lossy(&o.stdout);
        assert!(
            out.contains("Usage:") && out.contains("admin <command>"),
            "{out}"
        );
    }
    let o = run(d.path(), &["--version"], &[]);
    assert_eq!(o.status.code(), Some(0));
    assert!(String::from_utf8_lossy(&o.stdout).starts_with("orch-relay "));
    // Nothing was written: no data folder, no lock, no database.
    assert!(!d.path().join("data").exists());
}

#[test]
fn unknown_arguments_are_refused_without_starting() {
    let d = tempfile::tempdir().unwrap();
    for a in [&["--hepl"][..], &["serve"], &["admin", "nope"]] {
        let o = run(d.path(), a, &[]);
        assert_eq!(o.status.code(), Some(2), "{a:?} {}", text(&o));
        assert!(text(&o).contains("--help"), "{}", text(&o));
    }
    assert!(!d.path().join("data").exists());
}

#[test]
fn a_taken_port_stops_the_start_before_the_data_folder() {
    let d = tempfile::tempdir().unwrap();
    let taken = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = taken.local_addr().unwrap().to_string();
    let o = run(
        d.path(),
        &["--allow-root"],
        &[
            ("ORCH_RELAY_LISTEN", &addr),
            (
                "ORCH_RELAY_ADMIN_LISTEN",
                &format!("127.0.0.1:{}", free_port()),
            ),
        ],
    );
    assert_eq!(o.status.code(), Some(1), "{}", text(&o));
    assert!(text(&o).contains("cannot listen on"), "{}", text(&o));
    assert!(!d.path().join("data").exists());
}

#[test]
fn a_data_folder_in_use_stops_the_start() {
    let d = tempfile::tempdir().unwrap();
    let _held = cli::lock_data_dir(&d.path().join("data"), "orch-relay").unwrap();
    std::fs::write(d.path().join("master.key"), [7u8; 32]).unwrap();
    let o = run(
        d.path(),
        &["--allow-root"],
        &[
            ("ORCH_RELAY_LISTEN", &format!("127.0.0.1:{}", free_port())),
            (
                "ORCH_RELAY_ADMIN_LISTEN",
                &format!("127.0.0.1:{}", free_port()),
            ),
        ],
    );
    assert_eq!(o.status.code(), Some(1), "{}", text(&o));
    assert!(
        text(&o).contains("in use by another orch-relay"),
        "{}",
        text(&o)
    );
    assert!(!d.path().join("data").join("relay.db").exists());
}

#[test]
fn root_is_refused_unless_allowed() {
    // The check itself (this test does not run as root).
    assert!(cli::check_root(false, true)
        .unwrap_err()
        .contains("--allow-root"));
}

fn admin(what: AdminWhat, dry_run: bool) -> Admin {
    Admin {
        what,
        dry_run,
        ..Default::default()
    }
}

#[tokio::test]
async fn admin_commands_list_and_remove_with_a_dry_run() {
    let t = start().await;
    let a = t.add_ws("Alpha").await;
    let b = t.add_ws("Beta").await;
    t.rules(json!([rule(&a, &b, [true, false, false, false])]))
        .await;
    assert_eq!(
        t.send(&a, &b.id, "text", json!({"text": "hi"})).await.0,
        201
    );
    let (s, g) = t
        .admin_json(
            "POST",
            "/admin/api/groups",
            Some(json!({"name": "Team", "colour": "blue"})),
        )
        .await;
    assert_eq!(s, 201, "{g}");
    let gid = g["id"].as_str().unwrap().to_string();
    t.admin_json(
        "PATCH",
        &format!("/admin/api/workspaces/{}", b.id),
        Some(json!({"group": gid})),
    )
    .await;
    let go = |w, d| cli::run_admin_at(admin(w, d), &t.admin, ADMIN);

    let out = go(AdminWhat::WorkspacesList, false).await.unwrap();
    assert!(out.starts_with("2 workspaces"), "{out}");
    assert!(
        out.contains(&a.id) && out.contains("Alpha") && out.contains("Beta"),
        "{out}"
    );
    let out = go(AdminWhat::GroupsList, false).await.unwrap();
    assert!(
        out.contains(&gid) && out.contains("Team  1 workspace"),
        "{out}"
    );

    let out = go(AdminWhat::WorkspacesRemove(a.id.clone()), true)
        .await
        .unwrap();
    assert!(
        out.starts_with("Dry run:") && !out.contains(" 0 messages"),
        "{out}"
    );
    assert!(go(AdminWhat::WorkspacesList, false)
        .await
        .unwrap()
        .contains(&a.id));
    let out = go(AdminWhat::WorkspacesRemove(a.id.clone()), false)
        .await
        .unwrap();
    assert!(
        out.starts_with(&format!("Removed {} (Alpha)", a.id)),
        "{out}"
    );
    assert!(!go(AdminWhat::WorkspacesList, false)
        .await
        .unwrap()
        .contains(&a.id));
    let e = go(AdminWhat::WorkspacesRemove(a.id.clone()), false)
        .await
        .unwrap_err();
    assert!(e.contains("No such workspace"), "{e}");

    let out = go(AdminWhat::GroupsRemove(gid.clone()), true)
        .await
        .unwrap();
    assert!(out.starts_with("Dry run:"), "{out}");
    assert!(go(AdminWhat::GroupsList, false)
        .await
        .unwrap()
        .contains(&gid));
    go(AdminWhat::GroupsRemove(gid.clone()), false)
        .await
        .unwrap();
    assert!(go(AdminWhat::GroupsList, false)
        .await
        .unwrap()
        .starts_with("0 groups"));
    assert!(go(AdminWhat::WorkspacesList, false)
        .await
        .unwrap()
        .contains(&b.id));

    let out = go(AdminWhat::Cleanup, true).await.unwrap();
    assert!(
        out.starts_with("Dry run: the clean-up would delete 0 messages"),
        "{out}"
    );
    let out = go(AdminWhat::Cleanup, false).await.unwrap();
    assert!(out.starts_with("Cleaned up:"), "{out}");

    // A wrong token is refused.
    let e = cli::run_admin_at(
        admin(AdminWhat::WorkspacesList, false),
        &t.admin,
        "wrong-token-0123456789abcdef",
    )
    .await
    .unwrap_err();
    assert!(e.contains("401"), "{e}");
}

#[test]
fn admin_reads_the_env_file() {
    let d = tempfile::tempdir().unwrap();
    let f = d.path().join("env");
    std::fs::write(
        &f,
        "# relay\nORCH_RELAY_ADMIN_LISTEN=0.0.0.0:9999\nexport ORCH_RELAY_ADMIN_TOKEN=\"from-the-file-0123456789\"\nOTHER=x\n",
    )
    .unwrap();
    let m = cli::read_env_file(&f).unwrap();
    assert_eq!(
        m.get("ORCH_RELAY_ADMIN_TOKEN").unwrap(),
        "from-the-file-0123456789"
    );
    assert!(!m.contains_key("OTHER"));
}
