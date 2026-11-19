//! Listen addresses that must stay off the internet (admin page, private-network listener).
//! Same file in relay/src/listen.rs and publish/src/listen.rs; keep them equal.
//!
//! Two forms:
//! - `<IP>:<port>`: the IP must be loopback or private (10/8, 100.64/10, 172.16/12, 192.168/16, fd00::/8).
//! - `<interface>:<port>`, e.g. `wt0:8412`: the private IPv4 address of that interface, taken at start, so a
//!   new private address (server move, network rebuilt) needs no config change.
//!
//! 0.0.0.0, `::`, a public address and a host name are refused. A missing interface, or one without a private
//! IPv4 address (private network down), is an error: the caller stops instead of listening anywhere else.
use std::net::{IpAddr, Ipv4Addr, SocketAddr};

pub fn private_ip(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(a) => {
            let o = a.octets();
            a.is_loopback()
                || o[0] == 10
                || (o[0] == 100 && (64..128).contains(&o[1]))
                || (o[0] == 172 && (16..32).contains(&o[1]))
                || (o[0] == 192 && o[1] == 168)
        }
        IpAddr::V6(a) => a.is_loopback() || a.octets()[0] == 0xfd,
    }
}

/// `(interface, port)` when `listen` is the interface form (a short name of letters, digits, `-`, `_`).
fn interface_form(listen: &str) -> Option<(&str, u16)> {
    let (name, port) = listen.rsplit_once(':')?;
    let ok = !name.is_empty()
        && name.len() <= 15
        && name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_');
    Some((name, port.parse().ok()?)).filter(|_| ok)
}

/// Checks the form without looking at the machine's interfaces (startup config check).
pub fn valid_form(listen: &str) -> bool {
    let s = listen.trim();
    match s.parse::<SocketAddr>() {
        Ok(a) => private_ip(a.ip()),
        Err(_) => interface_form(s).is_some(),
    }
}

/// The address to bind for `listen` (named `var` in messages), or why not.
pub fn resolve(var: &str, listen: &str) -> Result<String, String> {
    resolve_with(var, listen, interface_ipv4)
}

pub fn resolve_with(
    var: &str,
    listen: &str,
    lookup: impl Fn(&str) -> Vec<Ipv4Addr>,
) -> Result<String, String> {
    let s = listen.trim();
    let refused = || {
        format!(
            "{var}={listen} must be an IP address and port on loopback or the private network, or a \
             private-network interface and port such as wt0:8412 (not 0.0.0.0, not a public address, not a host name)."
        )
    };
    if let Ok(a) = s.parse::<SocketAddr>() {
        return if private_ip(a.ip()) {
            Ok(a.to_string())
        } else {
            Err(refused())
        };
    }
    let (name, port) = interface_form(s).ok_or_else(refused)?;
    let ip = lookup(name)
        .into_iter()
        .find(|ip| private_ip(IpAddr::V4(*ip)))
        .ok_or_else(|| {
            format!(
                "{var}={listen}: the interface {name} has no private IPv4 address (is the private network up?)."
            )
        })?;
    Ok(SocketAddr::from((ip, port)).to_string())
}

/// IPv4 addresses of one network interface.
#[cfg(unix)]
pub fn interface_ipv4(name: &str) -> Vec<Ipv4Addr> {
    let mut out = Vec::new();
    // SAFETY: getifaddrs fills a linked list we only read and then free with freeifaddrs.
    unsafe {
        let mut head: *mut libc::ifaddrs = std::ptr::null_mut();
        if libc::getifaddrs(&mut head) != 0 {
            return out;
        }
        let mut p = head;
        while !p.is_null() {
            let ifa = &*p;
            if !ifa.ifa_addr.is_null()
                && i32::from((*ifa.ifa_addr).sa_family) == libc::AF_INET
                && std::ffi::CStr::from_ptr(ifa.ifa_name).to_bytes() == name.as_bytes()
            {
                let sin = &*(ifa.ifa_addr as *const libc::sockaddr_in);
                out.push(Ipv4Addr::from(u32::from_be(sin.sin_addr.s_addr)));
            }
            p = ifa.ifa_next;
        }
        libc::freeifaddrs(head);
    }
    out
}

#[cfg(not(unix))]
pub fn interface_ipv4(_name: &str) -> Vec<Ipv4Addr> {
    Vec::new()
}
