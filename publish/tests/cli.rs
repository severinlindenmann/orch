//! The orch-publish program: help never starts a server or writes to the data folder, start checks, admin commands.
mod common;
use common::*;
use orch_publish::cli::{self, Admin, AdminWhat};
use std::future::IntoFuture;
use std::process::{Command, Output};

const BIN: &str = env!("CARGO_BIN_EXE_orch-publish");

fn run(dir: &std::path::Path, args: &[&str], extra: &[(&str, &str)]) -> Output {
    let mut c = Command::new(BIN);
    c.args(args)
        .env_clear()
        .env("HOME", dir)
        .env("ORCH_PUBLISH_DATA_DIR", dir.join("data"))
        .env("ORCH_PUBLISH_ADMIN_TOKEN_FILE", dir.join("no-such-token"));
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
fn help_and_version_print_and_never_touch_the_data_folder() {
    let d = tempfile::tempdir().unwrap();
    for a in ["--help", "-h"] {
        let o = run(d.path(), &[a], &[]);
        assert_eq!(o.status.code(), Some(0), "{}", text(&o));
        let out = String::from_utf8_lossy(&o.stdout);
        assert!(
            out.contains("Usage:") && out.contains("workspaces remove"),
            "{out}"
        );
    }
    let o = run(d.path(), &["--version"], &[]);
    assert_eq!(o.status.code(), Some(0));
    assert!(String::from_utf8_lossy(&o.stdout).starts_with("orch-publish "));
    // No admin-token file, no apps folder, nothing (the 19 Nov incident).
    assert!(!d.path().join("data").exists());
}

#[test]
fn unknown_arguments_are_refused_without_starting() {
    let d = tempfile::tempdir().unwrap();
    for a in [&["--hepl"][..], &["start"], &["admin", "groups", "list"]] {
        let o = run(d.path(), a, &[]);
        assert_eq!(o.status.code(), Some(2), "{a:?} {}", text(&o));
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
            ("ORCH_PUBLISH_LISTEN", &format!("127.0.0.1:{}", free_port())),
            ("ORCH_PUBLISH_ADMIN_LISTEN", &addr),
        ],
    );
    assert_eq!(o.status.code(), Some(1), "{}", text(&o));
    assert!(text(&o).contains("cannot listen on"), "{}", text(&o));
    assert!(!d.path().join("data").exists());
}

#[test]
fn a_data_folder_in_use_stops_the_start_before_any_token_is_written() {
    let d = tempfile::tempdir().unwrap();
    let _held = cli::lock_data_dir(&d.path().join("data"), "orch-publish").unwrap();
    let o = run(
        d.path(),
        &["--allow-root"],
        &[
            ("ORCH_PUBLISH_LISTEN", &format!("127.0.0.1:{}", free_port())),
            (
                "ORCH_PUBLISH_ADMIN_LISTEN",
                &format!("127.0.0.1:{}", free_port()),
            ),
        ],
    );
    assert_eq!(o.status.code(), Some(1), "{}", text(&o));
    assert!(
        text(&o).contains("in use by another orch-publish"),
        "{}",
        text(&o)
    );
    assert!(!d.path().join("data").join("admin-token").exists());
    assert!(!d.path().join("data").join("apps").exists());
}

#[test]
fn root_is_refused_unless_allowed() {
    assert!(cli::check_root(false, true)
        .unwrap_err()
        .contains("--allow-root"));
}

#[tokio::test]
async fn admin_commands_list_and_remove_with_a_dry_run() {
    let t = setup();
    let l = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", l.local_addr().unwrap());
    tokio::spawn(axum::serve(l, t.admin.clone()).into_future());
    let a = t.workspace("Alpha", basic_rights()).await;
    let b = t.workspace("Beta", basic_rights()).await;
    t.api(&a, "POST", "/v1/files", vector_blob()).await;
    let go = |what, dry_run| {
        cli::run_admin_at(
            Admin {
                what,
                dry_run,
                ..Default::default()
            },
            &url,
            ADMIN,
        )
    };
    let out = go(AdminWhat::WorkspacesList, false).await.unwrap();
    assert!(out.starts_with("2 workspaces"), "{out}");
    assert!(
        out.contains(&format!("{}  Alpha  1 file  0 apps", a.0)),
        "{out}"
    );

    let out = go(AdminWhat::WorkspacesRemove(a.0.clone()), true)
        .await
        .unwrap();
    assert_eq!(
        out,
        format!(
            "Dry run: removing {} (Alpha) would delete 1 file, 0 apps.\n",
            a.0
        )
    );
    assert!(go(AdminWhat::WorkspacesList, false)
        .await
        .unwrap()
        .contains(&a.0));
    let out = go(AdminWhat::WorkspacesRemove(a.0.clone()), false)
        .await
        .unwrap();
    assert!(
        out.starts_with(&format!("Removed {} (Alpha)", a.0)),
        "{out}"
    );
    let out = go(AdminWhat::WorkspacesList, false).await.unwrap();
    assert!(!out.contains(&a.0) && out.contains(&b.0), "{out}");
    assert!(go(AdminWhat::WorkspacesRemove(a.0.clone()), false)
        .await
        .is_err());

    let e = cli::run_admin_at(
        Admin {
            what: AdminWhat::WorkspacesList,
            ..Default::default()
        },
        &url,
        "wrong",
    )
    .await
    .unwrap_err();
    assert!(e.contains("401"), "{e}");
}
