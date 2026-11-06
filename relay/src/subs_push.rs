//! Push for subscribers (relay-api.md "Subscribers", Push): the relay POSTs each event to the subscriber's https URL,
//! signed with HMAC-SHA256, retried with backoff, and stopped ("failing") after the last retry. The URL may never
//! reach a private, loopback or otherwise non-public address: checked before every request, and the request goes to
//! exactly the checked address, without following redirects.
use crate::error::*;
use crate::state::AppState;
use crate::subs::{self, event_label, read_events};
use crate::util::*;
use rusqlite::{params, OptionalExtension};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr};
use std::time::{Duration, Instant};

/// Wait before retry 1..5 after a failed delivery; a failure after the last one stops push ("failing").
pub const BACKOFF: [i64; 5] = [60, 300, 1800, 7200, 6 * 3600];
/// Events delivered in one round for one subscriber.
const ROUND: usize = 20;
const CONNECT_TIMEOUT: Duration = Duration::from_secs(5);
const TIMEOUT: Duration = Duration::from_secs(10);

/// What one delivery attempt gave: the HTTP status (None = no answer) and a short plain line.
#[derive(Clone, Debug)]
pub struct Outcome {
    pub status: Option<u16>,
    pub detail: String,
}

impl Outcome {
    pub fn ok(&self) -> bool {
        self.status.is_some_and(|s| (200..300).contains(&s))
    }
    fn refused(why: impl Into<String>) -> Outcome {
        Outcome {
            status: None,
            detail: format!("refused: {}", why.into()),
        }
    }
}

#[async_trait::async_trait]
pub trait Deliver: Send + Sync {
    async fn post(&self, url: &str, headers: Vec<(&'static str, String)>, body: Vec<u8>)
        -> Outcome;
}

// ---------- signing ----------

/// HMAC-SHA256 (RFC 2104).
pub fn hmac_sha256(key: &[u8], msg: &[u8]) -> [u8; 32] {
    let mut k = [0u8; 64];
    if key.len() > 64 {
        k[..32].copy_from_slice(&Sha256::digest(key));
    } else {
        k[..key.len()].copy_from_slice(key);
    }
    let (mut ipad, mut opad) = ([0x36u8; 64], [0x5cu8; 64]);
    for i in 0..64 {
        ipad[i] ^= k[i];
        opad[i] ^= k[i];
    }
    let inner = Sha256::new()
        .chain_update(ipad)
        .chain_update(msg)
        .finalize();
    Sha256::new()
        .chain_update(opad)
        .chain_update(inner)
        .finalize()
        .into()
}

/// `X-Orch-Signature`: `v1=` + hex HMAC-SHA256(secret, timestamp + "." + body).
pub fn sign(secret: &str, ts: i64, body: &[u8]) -> String {
    let mut msg = format!("{ts}.").into_bytes();
    msg.extend_from_slice(body);
    format!("v1={}", hex::encode(hmac_sha256(secret.as_bytes(), &msg)))
}

// ---------- address checks ----------

/// True only for globally reachable unicast addresses.
pub fn public_ip(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(a) => public_v4(a),
        IpAddr::V6(a) => public_v6(a),
    }
}

fn public_v4(a: Ipv4Addr) -> bool {
    let o = a.octets();
    !(o[0] == 0                                   // "this network"
        || o[0] == 10                             // private
        || (o[0] == 100 && (o[1] & 0xc0) == 64)   // shared / carrier-grade NAT (private networks use it)
        || o[0] == 127                            // loopback
        || (o[0] == 169 && o[1] == 254)           // link-local (cloud metadata)
        || (o[0] == 172 && (o[1] & 0xf0) == 16)   // private
        || (o[0] == 192 && o[1] == 0 && o[2] == 0) // IETF protocol assignments
        || (o[0] == 192 && o[1] == 0 && o[2] == 2) // documentation
        || (o[0] == 192 && o[1] == 88 && o[2] == 99) // 6to4 relay
        || (o[0] == 192 && o[1] == 168)           // private
        || (o[0] == 198 && (o[1] & 0xfe) == 18)   // benchmarking
        || (o[0] == 198 && o[1] == 51 && o[2] == 100) // documentation
        || (o[0] == 203 && o[1] == 0 && o[2] == 113) // documentation
        || o[0] >= 224) // multicast, reserved, broadcast
}

fn public_v6(a: Ipv6Addr) -> bool {
    if let Some(v4) = a.to_ipv4_mapped() {
        return public_v4(v4);
    }
    let s = a.segments();
    // NAT64 (64:ff9b::/96 and 64:ff9b:1::/48): judge the IPv4 address inside.
    if s[0] == 0x64 && s[1] == 0xff9b {
        let v4 = Ipv4Addr::new((s[6] >> 8) as u8, s[6] as u8, (s[7] >> 8) as u8, s[7] as u8);
        return s[2] == 0 && public_v4(v4);
    }
    !(a.is_unspecified()
        || a.is_loopback()
        || s[0..6] == [0, 0, 0, 0, 0, 0]        // IPv4-compatible (deprecated)
        || (s[0] & 0xfe00) == 0xfc00            // unique local
        || (s[0] & 0xffc0) == 0xfe80            // link-local
        || (s[0] & 0xffc0) == 0xfec0            // site-local (deprecated)
        || (s[0] & 0xff00) == 0xff00            // multicast
        || (s[0] == 0x2001 && s[1] == 0x0db8)   // documentation
        || (s[0] == 0x2001 && s[1] < 0x0200)    // IETF protocol assignments, Teredo, benchmarking, ORCHID
        || s[0] == 0x2002                       // 6to4
        || (s[0] == 0x0100 && s[1..4] == [0, 0, 0]) // discard-only
        || s[0] == 0x3fff) // documentation (2024)
}

/// The syntax check (also at save time): https, a host, no user name or password, no fragment; an IP literal must be
/// public. Host names are looked up on every delivery (`resolve_public`).
pub fn check_url(raw: &str) -> Result<reqwest::Url, String> {
    let u = reqwest::Url::parse(raw)
        .map_err(|_| "The push address must be a full https:// address.".to_string())?;
    if u.scheme() != "https" {
        return Err("The push address must start with https://.".into());
    }
    if !u.username().is_empty() || u.password().is_some() {
        return Err("The push address must not contain a user name or password.".into());
    }
    if raw.len() > 2000 {
        return Err("The push address is too long.".into());
    }
    match u.host() {
        None => return Err("The push address needs a host name.".into()),
        Some(url::Host::Ipv4(a)) if !public_v4(a) => {
            return Err(
                "The push address must be a public address, not a private or local one.".into(),
            )
        }
        Some(url::Host::Ipv6(a)) if !public_v6(a) => {
            return Err(
                "The push address must be a public address, not a private or local one.".into(),
            )
        }
        _ => {}
    }
    Ok(u)
}

/// Look `host` up (5 s at most) and return its addresses, only when every one of them is public.
pub async fn resolve_public(host: &str, port: u16) -> Result<Vec<SocketAddr>, String> {
    let addrs: Vec<SocketAddr> =
        match tokio::time::timeout(CONNECT_TIMEOUT, tokio::net::lookup_host((host, port))).await {
            Ok(Ok(a)) => a.collect(),
            Ok(Err(_)) | Err(_) => return Err("the address could not be found".into()),
        };
    if addrs.is_empty() {
        return Err("the address could not be found".into());
    }
    if addrs.iter().any(|a| !public_ip(a.ip())) {
        return Err("private address".into());
    }
    Ok(addrs)
}

/// The real transport: checks the address on every request and connects only to the checked addresses.
pub struct Https;

#[async_trait::async_trait]
impl Deliver for Https {
    async fn post(
        &self,
        url: &str,
        headers: Vec<(&'static str, String)>,
        body: Vec<u8>,
    ) -> Outcome {
        let u = match check_url(url) {
            Ok(u) => u,
            Err(_) => return Outcome::refused("not a public https address"),
        };
        let port = u.port_or_known_default().unwrap_or(443);
        let mut b = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .no_proxy()
            .https_only(true)
            .connect_timeout(CONNECT_TIMEOUT)
            .timeout(TIMEOUT);
        if let Some(url::Host::Domain(host)) = u.host() {
            match resolve_public(host, port).await {
                Ok(addrs) => b = b.resolve_to_addrs(host, &addrs),
                Err(e) => return Outcome::refused(e),
            }
        }
        let client = match b.build() {
            Ok(c) => c,
            Err(_) => return Outcome::refused("could not start the request"),
        };
        let mut req = client
            .post(u)
            .header("content-type", "application/json")
            .header("user-agent", "orch-relay");
        for (k, v) in headers {
            req = req.header(k, v);
        }
        // The response body is never read.
        match req.body(body).send().await {
            Ok(r) => Outcome {
                status: Some(r.status().as_u16()),
                detail: String::new(),
            },
            Err(e) if e.is_timeout() => Outcome {
                status: None,
                detail: "no answer within 10 s".into(),
            },
            Err(_) => Outcome {
                status: None,
                detail: "could not connect".into(),
            },
        }
    }
}

// ---------- the worker ----------

struct PushRow {
    url: String,
    secret: String,
    cursor: i64,
    fails: i64,
}

/// push_url, push_secret (sealed), push_state, push_cursor, push_fails, push_next_at
type PushCols = (
    Option<String>,
    Option<Vec<u8>>,
    Option<String>,
    Option<i64>,
    i64,
    Option<i64>,
);

fn push_row(app: &AppState, c: &rusqlite::Connection, id: &str, due_only: bool) -> Option<PushRow> {
    let row: Option<PushCols> = c
        .query_row(
            "SELECT push_url,push_secret,push_state,push_cursor,push_fails,push_next_at FROM subscribers WHERE id=?1",
            [id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?, r.get(5)?)),
        )
        .optional()
        .ok()
        .flatten();
    let (Some(url), Some(sealed), state, cursor, fails, next_at) = row? else {
        return None;
    };
    if due_only && (state.as_deref() == Some("failing") || next_at.is_some_and(|t| t > now())) {
        return None;
    }
    let secret = String::from_utf8(crate::crypto::open(&app.key, id, &sealed)?).ok()?;
    Some(PushRow {
        url,
        secret,
        cursor: cursor.unwrap_or(0),
        fails,
    })
}

fn headers(id: &str, ts: i64, sig: String) -> Vec<(&'static str, String)> {
    vec![
        ("x-orch-event-id", id.to_string()),
        ("x-orch-timestamp", ts.to_string()),
        ("x-orch-signature", sig),
    ]
}

fn result_line(o: &Outcome, ms: u128) -> String {
    match o.status {
        Some(s) if o.ok() => format!("{s} in {ms} ms"),
        Some(s) => s.to_string(),
        None => o.detail.clone(),
    }
}

/// Deliver up to `ROUND` due events of one subscriber, oldest first; stop at the first failure.
pub async fn round(app: &AppState, id: &str) {
    if !app.subs.pushing.lock().unwrap().insert(id.to_string()) {
        return;
    }
    struct Done<'a>(&'a AppState, &'a str);
    impl Drop for Done<'_> {
        fn drop(&mut self) {
            self.0.subs.pushing.lock().unwrap().remove(self.1);
        }
    }
    let _done = Done(app, id);
    for _ in 0..ROUND {
        let (p, seq, event) = {
            let c = app.db.lock().unwrap();
            let Some(p) = push_row(app, &c, id, true) else {
                return;
            };
            let Ok(Some(s)) = subs::load(&c, id) else {
                return;
            };
            let Ok(page) = read_events(&c, &app.key, &s, p.cursor, 1) else {
                return;
            };
            match page.items.into_iter().next() {
                Some((seq, e)) => (p, seq, e),
                None => {
                    // Nothing to send: skip what was looked at, so the next round starts there.
                    if page.last_seq > p.cursor {
                        let _ = c.execute(
                            "UPDATE subscribers SET push_cursor=?2 WHERE id=?1 AND push_url=?3",
                            params![id, page.last_seq, p.url],
                        );
                    }
                    if page.more {
                        continue;
                    }
                    return;
                }
            }
        };
        let body = serde_json::to_vec(&event).unwrap_or_default();
        let ts = now();
        let t0 = Instant::now();
        let out = app
            .subs
            .deliver()
            .post(
                &p.url,
                headers(
                    event["id"].as_str().unwrap_or(""),
                    ts,
                    sign(&p.secret, ts, &body),
                ),
                body,
            )
            .await;
        let ms = t0.elapsed().as_millis();
        let c = app.db.lock().unwrap();
        // Removed, push turned off or the address changed meanwhile: forget this attempt.
        match push_row(app, &c, id, false) {
            Some(cur) if cur.url == p.url && cur.cursor == p.cursor => {}
            _ => return,
        }
        let label = event_label(&event);
        if out.ok() {
            let _ = c.execute(
                "UPDATE subscribers SET push_cursor=?2, push_state='ok', push_fails=0, push_next_at=NULL, push_last_ok=?3 WHERE id=?1",
                params![id, seq, now()],
            );
            subs::log(&c, id, "push", Some(&label), &result_line(&out, ms), true);
            continue;
        }
        let fails = p.fails + 1;
        let line = result_line(&out, ms);
        if fails as usize > BACKOFF.len() {
            let _ = c.execute(
                "UPDATE subscribers SET push_state='failing', push_fails=?2, push_next_at=NULL WHERE id=?1",
                params![id, fails],
            );
            subs::log(
                &c,
                id,
                "push",
                Some(&label),
                &format!("{line} · stopped"),
                false,
            );
        } else {
            let wait = BACKOFF[fails as usize - 1];
            let _ = c.execute(
                "UPDATE subscribers SET push_state='retrying', push_fails=?2, push_next_at=?3 WHERE id=?1",
                params![id, fails, now() + wait],
            );
            let next = fmt_time(now() + wait);
            subs::log(
                &c,
                id,
                "push",
                Some(&label),
                &format!("{line} · next try {} UTC", &next[11..16]),
                false,
            );
        }
        return;
    }
}

/// Subscribers with push on that are due now.
fn due(app: &AppState) -> Vec<String> {
    let c = app.db.lock().unwrap();
    c.prepare(
        "SELECT id FROM subscribers WHERE push_url IS NOT NULL AND COALESCE(push_state,'ok')<>'failing'
           AND (push_next_at IS NULL OR push_next_at<=?1)",
    )
    .and_then(|mut st| st.query_map([now()], |r| r.get(0))?.collect())
    .unwrap_or_default()
}

/// One pass over every due subscriber, waiting for all of them (tests call this directly).
pub async fn tick(app: &AppState) {
    let ids = due(app);
    futures_util::future::join_all(ids.iter().map(|id| round(app, id))).await;
}

/// The background worker: a pass on every new message and at least every 5 s; each subscriber's round runs on its own,
/// so a slow receiver does not hold up the others.
pub fn spawn(app: AppState) {
    tokio::spawn(async move {
        loop {
            let notified = app.notify.notified();
            tokio::pin!(notified);
            notified.as_mut().enable();
            for id in due(&app) {
                let a = app.clone();
                tokio::spawn(async move { round(&a, &id).await });
            }
            tokio::select! {
                _ = &mut notified => {}
                _ = tokio::time::sleep(Duration::from_secs(5)) => {}
            }
        }
    });
}

/// `POST /admin/api/subscribers/<id>/push/test`: one signed test event, now. Does not change the push state.
pub async fn send_test(app: &AppState, id: &str) -> Res<Value> {
    let p = {
        let c = app.db.lock().unwrap();
        push_row(app, &c, id, false).ok_or_else(|| not_found("No such subscriber."))?
    };
    let ev = json!({"v": 1, "id": rand_id("test_", 10), "type": "test",
        "text": "Test event from your orch relay.", "at": fmt_time(now())});
    let body = serde_json::to_vec(&ev).unwrap_or_default();
    let ts = now();
    let t0 = Instant::now();
    let out = app
        .subs
        .deliver()
        .post(
            &p.url,
            headers(
                ev["id"].as_str().unwrap_or(""),
                ts,
                sign(&p.secret, ts, &body),
            ),
            body,
        )
        .await;
    let ms = t0.elapsed().as_millis();
    let line = result_line(&out, ms);
    let detail = if out.ok() {
        format!("Your address answered {line}.")
    } else if let Some(s) = out.status {
        format!("Your address answered {s}. It must answer 2xx.")
    } else {
        format!("Not delivered: {}.", out.detail)
    };
    {
        let c = app.db.lock().unwrap();
        subs::log(&c, id, "test", None, &line, out.ok());
    }
    Ok(json!({"ok": out.ok(), "status": out.status, "ms": ms as u64, "detail": detail}))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hmac_rfc4231_case_2() {
        let mac = hmac_sha256(b"Jefe", b"what do ya want for nothing?");
        assert_eq!(
            hex::encode(mac),
            "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"
        );
    }

    #[test]
    fn hmac_long_key_rfc4231_case_6() {
        let key = [0xaau8; 131];
        let mac = hmac_sha256(
            &key,
            b"Test Using Larger Than Block-Size Key - Hash Key First",
        );
        assert_eq!(
            hex::encode(mac),
            "60e431591ee0b67f0d8a26aacbf5b77f8e0bc6213728c5140546040f0ee37f54"
        );
    }

    #[test]
    fn private_addresses_are_not_public() {
        for a in [
            "0.0.0.0",
            "10.1.2.3",
            "100.64.0.1",
            "100.127.255.254",
            "127.0.0.1",
            "169.254.169.254",
            "172.16.0.1",
            "172.31.255.255",
            "192.0.0.8",
            "192.0.2.1",
            "192.168.1.1",
            "198.18.0.1",
            "198.51.100.7",
            "203.0.113.9",
            "224.0.0.1",
            "240.0.0.1",
            "255.255.255.255",
            "::",
            "::1",
            "::ffff:10.0.0.1",
            "::ffff:127.0.0.1",
            "64:ff9b::a00:1",
            "fc00::1",
            "fd12::1",
            "fe80::1",
            "ff02::1",
            "2001:db8::1",
            "2001::1",
            "2002:a00:1::1",
            "::127.0.0.1",
        ] {
            assert!(
                !public_ip(a.parse().unwrap()),
                "{a} must not count as public"
            );
        }
        for a in [
            "1.1.1.1",
            "8.8.8.8",
            "100.128.0.1",
            "172.32.0.1",
            "2606:4700::1111",
            "::ffff:8.8.8.8",
            "64:ff9b::808:808",
        ] {
            assert!(public_ip(a.parse().unwrap()), "{a} is public");
        }
    }

    #[test]
    fn url_rules() {
        assert!(check_url("https://hooks.example.com/orch").is_ok());
        for bad in [
            "http://hooks.example.com/x",
            "ftp://x.com",
            "https://user:pw@x.com/",
            "https://127.0.0.1/",
            "https://10.0.0.5:8443/x",
            "https://[::1]/",
            "https://[fd00::1]/",
            "https://169.254.169.254/latest/meta-data",
            "not a url",
        ] {
            assert!(check_url(bad).is_err(), "{bad}");
        }
    }

    #[tokio::test]
    async fn https_transport_refuses_local_hosts() {
        for u in [
            "https://localhost:9/x",
            "https://127.0.0.1:9/",
            "http://example.com/",
            "https://[::1]:9/",
        ] {
            let o = Https.post(u, vec![], b"{}".to_vec()).await;
            assert!(
                o.status.is_none() && o.detail.starts_with("refused"),
                "{u}: {o:?}"
            );
        }
    }
}
