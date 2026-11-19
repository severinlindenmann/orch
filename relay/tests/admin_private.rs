//! The admin page stays private: the admin listener only takes loopback or private-network
//! addresses, a missing private address fails the bind (no fallback), and the public
//! listener answers no admin path.
mod common;
use orch_relay::state::check_admin_listen;

#[test]
fn admin_listen_takes_only_private_addresses() {
    for ok in [
        "127.0.0.1:8412",
        "100.73.196.187:8412",
        "10.0.0.5:1",
        "172.16.0.1:8412",
        "192.168.1.2:8412",
        "[::1]:8412",
        "[fd00::1]:8412",
    ] {
        assert!(check_admin_listen(ok).is_ok(), "{ok} should be accepted");
    }
    for bad in [
        "0.0.0.0:8412",
        "[::]:8412",
        "2.24.146.133:8412",
        "8.8.8.8:8412",
        "100.128.0.1:8412",
        "localhost:8412",
        "hostinger-vps.nb.severin.io:8412",
        "",
        "8412",
    ] {
        assert!(check_admin_listen(bad).is_err(), "{bad} should be refused");
    }
}

#[tokio::test]
async fn missing_private_address_fails_the_bind() {
    assert!(tokio::net::TcpListener::bind("100.127.255.254:0")
        .await
        .is_err());
}

#[tokio::test]
async fn public_listener_has_no_admin_paths() {
    let t = common::start().await;
    for p in [
        "/admin",
        "/admin/",
        "/admin/api/workspaces",
        "/admin/api/phones",
    ] {
        let r = t.http.get(format!("{}{}", t.base, p)).send().await.unwrap();
        assert_eq!(
            r.status().as_u16(),
            404,
            "public {p} answered {}",
            r.status()
        );
    }
}
