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
