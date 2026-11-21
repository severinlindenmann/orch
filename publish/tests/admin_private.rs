//! The admin page stays private: the admin listener only takes loopback or private-network
//! addresses, a missing private address fails the bind (no fallback), and the public
//! listener answers no admin path.
mod common;
use common::{call, setup};
use orch_publish::check_admin_listen;

#[test]
fn admin_listen_takes_only_private_addresses() {
    for ok in [
        "127.0.0.1:8411",
        "100.73.196.187:8411",
        "10.0.0.5:1",
        "172.16.0.1:8411",
        "192.168.1.2:8411",
        "[::1]:8411",
        "[fd00::1]:8411",
    ] {
        assert!(check_admin_listen(ok).is_ok(), "{ok} should be accepted");
    }
    for bad in [
        "0.0.0.0:8411",
        "[::]:8411",
        "2.24.146.133:8411",
        "8.8.8.8:8411",
        "100.128.0.1:8411",
        "localhost:8411",
        "hostinger-vps.nb.severin.io:8411",
        "",
        "8411",
    ] {
        assert!(check_admin_listen(bad).is_err(), "{bad} should be refused");
    }
}

#[tokio::test]
async fn missing_private_address_fails_the_bind() {
    // An address of the private range this machine does not have: the bind must fail,
    // so the service stops instead of listening anywhere else.
    assert!(tokio::net::TcpListener::bind("100.127.255.254:0")
        .await
        .is_err());
}

#[tokio::test]
async fn public_listener_has_no_admin_paths() {
    let t = setup();
    for p in [
        "/admin",
        "/admin/",
        "/admin/portal.js",
        "/admin/api/workspaces",
        "/admin/api/status",
    ] {
        let r = call(&t.public, "GET", p, &[], vec![]).await;
        assert_eq!(r.status.as_u16(), 404, "public {p} answered {}", r.status);
    }
}

#[test]
fn interface_form_takes_the_private_address_at_start() {
    use orch_publish::listen::resolve_with;
    use std::net::Ipv4Addr;
    let wt0 = |n: &str| match n {
        "wt0" => vec![Ipv4Addr::new(100, 73, 196, 187)],
        "eth0" => vec![Ipv4Addr::new(2, 24, 146, 133)],
        _ => vec![],
    };
    assert_eq!(
        resolve_with("V", "wt0:8411", wt0).unwrap(),
        "100.73.196.187:8411"
    );
    assert!(resolve_with("V", "eth0:8411", wt0).is_err());
    assert!(resolve_with("V", "wt1:8411", wt0).is_err());
    assert!(orch_publish::listen::valid_form("wt0:8410"));
    assert!(!orch_publish::listen::valid_form("0.0.0.0:8410"));
}

#[cfg(unix)]
#[test]
fn interface_form_reads_the_real_loopback() {
    let lo = ["lo", "lo0"]
        .into_iter()
        .find(|n| !orch_publish::listen::interface_ipv4(n).is_empty())
        .expect("a loopback interface");
    assert_eq!(
        orch_publish::resolve_admin_listen(&format!("{lo}:8411")).unwrap(),
        "127.0.0.1:8411"
    );
    assert!(check_admin_listen("no-such-if9:8411").is_err());
}

#[test]
fn admin_command_never_sends_the_token_to_a_host_name() {
    use orch_publish::listen::client_addr_with;
    use std::net::Ipv4Addr;
    let wt0 = |n: &str| match n {
        "wt0" => vec![Ipv4Addr::new(100, 73, 196, 187)],
        _ => vec![],
    };
    assert_eq!(
        client_addr_with("V", "wt0:8411", wt0).unwrap(),
        "100.73.196.187:8411"
    );
    assert_eq!(
        client_addr_with("V", "0.0.0.0:8411", wt0).unwrap(),
        "127.0.0.1:8411"
    );
    assert_eq!(
        client_addr_with("V", "[::]:8411", wt0).unwrap(),
        "[::1]:8411"
    );
    // private network down, or a host name: refuse instead of a name lookup
    assert!(client_addr_with("V", "wt1:8411", wt0).is_err());
    assert!(client_addr_with("V", "relay.severin.io:8411", wt0).is_err());
}

#[cfg(unix)]
#[test]
fn admin_command_resolves_the_interface_form_from_its_env_file() {
    use orch_publish::cli::{admin_target, Admin};
    let lo = ["lo", "lo0"]
        .into_iter()
        .find(|n| !orch_publish::listen::interface_ipv4(n).is_empty())
        .expect("a loopback interface");
    let dir = tempfile::tempdir().unwrap();
    let env = dir.path().join("env");
    let target = |listen: &str| {
        std::fs::write(
            &env,
            format!("ORCH_PUBLISH_ADMIN_LISTEN={listen}\nORCH_PUBLISH_ADMIN_TOKEN=t0k\n"),
        )
        .unwrap();
        admin_target(&Admin {
            env_file: Some(env.clone()),
            ..Default::default()
        })
    };
    let (url, _) = target(&format!("{lo}:8411")).unwrap();
    assert_eq!(url, "http://127.0.0.1:8411");
    let e = target("no-such-if9:8411").unwrap_err();
    assert!(e.contains("no private IPv4 address"), "{e}");
}
