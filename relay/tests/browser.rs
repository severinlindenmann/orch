// Browser sign-in (ORCH-1197): a browser is a device like a phone, made on the relay admin page with kind "browser".
mod common;
use common::*;
use serde_json::{json, Value};

async fn add_device(t: &T, ws: &Ws, body: Value) -> (u16, Value) {
    let mut b = body;
    b["workspaces"] = json!([ws.id]);
    t.admin_json("POST", "/admin/api/phones", Some(b)).await
}

fn code_of(link: &str) -> String {
    link.rsplit("code=").next().unwrap().to_string()
}

async fn pair_with(t: &T, code: &str, origin: Option<&str>) -> reqwest::Response {
    let mut r = t
        .http
        .post(format!("{}/v1/phone/pair", t.base))
        .json(&json!({"code": code, "name": "Firefox"}));
    if let Some(o) = origin {
        r = r.header("Origin", o);
    }
    r.send().await.unwrap()
}

async fn sign_in_browser(t: &T, ws: &Ws) -> (String, String) {
    let (s, v) = add_device(t, ws, json!({"name": "Max laptop", "kind": "browser"})).await;
    assert_eq!(s, 201, "{v}");
    let r = pair_with(
        t,
        &code_of(v["link"].as_str().unwrap()),
        Some("https://relay.test"),
    )
    .await;
    assert_eq!(r.status(), 201);
    let pv: Value = r.json().await.unwrap();
    (
        pv["phone_id"].as_str().unwrap().to_string(),
        pv["token"].as_str().unwrap().to_string(),
    )
}

#[tokio::test]
async fn browser_invitation_links_to_the_relay_page_with_the_code_after_the_hash() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let (s, v) = add_device(&t, &a, json!({"name": "Max laptop", "kind": "browser"})).await;
    assert_eq!(s, 201, "{v}");
    let link = v["link"].as_str().unwrap();
    // The code sits after `#`: browsers never send it to a server, so it stays out of every request log.
    assert!(
        link.starts_with("https://relay.test/app#code=pc_"),
        "{link}"
    );
    assert!(v["phone_id"].as_str().unwrap().starts_with("ph_"));
    assert_eq!(v["kind"], "browser");
    // A phone keeps the app link.
    let (_, p) = add_device(&t, &a, json!({"name": "P"})).await;
    assert!(p["link"].as_str().unwrap().starts_with("orch://pair?"));
    assert_eq!(p["kind"], "phone");
    // Unknown kinds are refused plainly.
    let (s, e) = add_device(&t, &a, json!({"name": "X", "kind": "tablet"})).await;
    assert_eq!(s, 422, "{e}");
}

#[tokio::test]
async fn browser_signs_in_once_and_is_listed_with_its_kind() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let (s, v) = add_device(&t, &a, json!({"name": "Max laptop", "kind": "browser"})).await;
    assert_eq!(s, 201);
    let code = code_of(v["link"].as_str().unwrap());
    assert_eq!(
        pair_with(&t, &code, Some("https://relay.test"))
            .await
            .status(),
        201
    );
    assert_eq!(
        pair_with(&t, &code, Some("https://relay.test"))
            .await
            .status(),
        410,
        "one use only"
    );
    // The admin list and the workspace snapshot say it is a browser; the name stays the admin's.
    let (_, l) = t.admin_json("GET", "/admin/api/phones", None).await;
    assert_eq!(l["items"][0]["kind"], "browser");
    assert_eq!(l["items"][0]["paired"], true);
    let (_, snap) = t.call(&a, "GET", "/v1/refresh", None).await;
    let devs = snap["workspaces"]["phones"].as_array().unwrap();
    assert_eq!(devs.len(), 1, "{snap}");
    assert_eq!(devs[0]["kind"], "browser");
    assert_eq!(devs[0]["name"], "Max laptop");
}

#[tokio::test]
async fn phone_snapshot_says_phone() {
    let t = start().await;
    let a = t.add_ws("A").await;
    t.pair_phone(&[&a]).await;
    let (_, snap) = t.call(&a, "GET", "/v1/refresh", None).await;
    assert_eq!(snap["workspaces"]["phones"][0]["kind"], "phone");
}

#[tokio::test]
async fn browser_uses_the_device_api_and_its_text_comes_from_its_own_id() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let b = sign_in_browser(&t, &a).await;
    let (s, w) = t.phone(&b, "GET", "/v1/phone/workspaces", None).await;
    assert_eq!(s, 200, "{w}");
    assert_eq!(w["items"][0]["id"], json!(a.id));
    let (s, v) = t
        .phone(
            &b,
            "POST",
            "/v1/phone/send",
            Some(json!({"to": a.id, "text": "hello from the browser"})),
        )
        .await;
    assert_eq!(s, 201, "{v}");
    let got = t.inbox(&a).await;
    let m = got
        .iter()
        .find(|m| m["type"] == "text")
        .expect("text arrived");
    assert_eq!(
        m["from"],
        json!(b.0),
        "from is set by the relay from the device token"
    );
}

#[tokio::test]
async fn requests_from_another_web_origin_are_refused() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let (_, v) = add_device(&t, &a, json!({"name": "Max laptop", "kind": "browser"})).await;
    let code = code_of(v["link"].as_str().unwrap());
    // A page on another site cannot use up or redeem the invitation...
    assert_eq!(
        pair_with(&t, &code, Some("https://evil.example"))
            .await
            .status(),
        403
    );
    assert_eq!(pair_with(&t, &code, Some("null")).await.status(), 403);
    // ...so it still works from the relay's own page.
    let r = pair_with(&t, &code, Some("https://relay.test")).await;
    assert_eq!(r.status(), 201);
    let pv: Value = r.json().await.unwrap();
    let (id, tok) = (
        pv["phone_id"].as_str().unwrap(),
        pv["token"].as_str().unwrap(),
    );
    // ...and a signed-in device's token is refused when sent from another site.
    let r = t
        .http
        .get(format!("{}/v1/phone/workspaces", t.base))
        .header("X-Orch-Phone", id)
        .header("Authorization", format!("Bearer {tok}"))
        .header("Origin", "https://evil.example")
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 403);
    // The phone app sends no Origin and keeps working.
    let (s, _) = t
        .phone(
            &(id.to_string(), tok.to_string()),
            "GET",
            "/v1/phone/workspaces",
            None,
        )
        .await;
    assert_eq!(s, 200);
}

#[tokio::test]
async fn device_api_sends_no_cross_site_permission() {
    let t = start().await;
    let r = t
        .http
        .request(
            reqwest::Method::OPTIONS,
            format!("{}/v1/phone/workspaces", t.base),
        )
        .header("Origin", "https://evil.example")
        .header("Access-Control-Request-Method", "GET")
        .send()
        .await
        .unwrap();
    assert!(r.headers().get("access-control-allow-origin").is_none());
}

#[tokio::test]
async fn a_browser_invitation_cannot_be_merged_into_a_phone_and_back() {
    let t = start().await;
    let (a, b) = (t.add_ws("A").await, t.add_ws("B").await);
    let phone = t.pair_phone(&[&a]).await;
    let (_, v) = add_device(&t, &b, json!({"name": "Max laptop", "kind": "browser"})).await;
    let code = code_of(v["link"].as_str().unwrap());
    let (s, e) = t
        .phone(
            &phone,
            "POST",
            "/v1/phone/invitations/redeem",
            Some(json!({"code": code})),
        )
        .await;
    assert_eq!(s, 410, "a phone does not take a browser's invitation: {e}");
    let (_, w) = t.phone(&phone, "GET", "/v1/phone/workspaces", None).await;
    assert_eq!(
        w["items"].as_array().unwrap().len(),
        1,
        "the phone gained nothing"
    );
    // The refused invitation still works for a browser that is already signed in (browser to browser).
    let br0 = sign_in_browser(&t, &a).await;
    let (s, r) = t
        .phone(
            &br0,
            "POST",
            "/v1/phone/invitations/redeem",
            Some(json!({"code": code})),
        )
        .await;
    assert_eq!(s, 200, "{r}");
    assert_eq!(r["workspaces"], json!([{"id": b.id, "name": "B"}]));
    // A browser does not take a phone's invitation either.
    let br = sign_in_browser(&t, &a).await;
    let (_, p) = add_device(&t, &b, json!({"name": "P2"})).await;
    let pcode = code_of(p["link"].as_str().unwrap());
    let (s, _) = t
        .phone(
            &br,
            "POST",
            "/v1/phone/invitations/redeem",
            Some(json!({"code": pcode})),
        )
        .await;
    assert_eq!(s, 410);
}

#[tokio::test]
async fn cut_browser_is_refused_from_its_next_request() {
    let t = start().await;
    let a = t.add_ws("A").await;
    let b = sign_in_browser(&t, &a).await;
    let (s, _) = t
        .admin_json("DELETE", &format!("/admin/api/phones/{}", b.0), None)
        .await;
    assert_eq!(s, 204);
    let (s, _) = t.phone(&b, "GET", "/v1/phone/workspaces", None).await;
    assert_eq!(s, 401);
    let (_, snap) = t.call(&a, "GET", "/v1/refresh", None).await;
    assert_eq!(snap["workspaces"]["phones"], json!([]));
}

#[test]
fn a_database_from_before_browsers_gets_kind_phone_and_keeps_working() {
    let dir = tempfile::tempdir().unwrap();
    let c = rusqlite::Connection::open(dir.path().join("relay.db")).unwrap();
    // The phones table exactly as it was before this change, with a paired phone and an open invitation.
    c.execute_batch(
        "CREATE TABLE phones(id TEXT PRIMARY KEY, name TEXT NOT NULL, workspaces TEXT NOT NULL,
            token_hash TEXT, apns_token TEXT, sandbox INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL,
            last_seen INTEGER, paired_at INTEGER);
         INSERT INTO phones(id,name,workspaces,token_hash,created_at) VALUES('ph_aaaaaaaaaa','Old','[]','h',1);
         INSERT INTO phones(id,name,workspaces,created_at) VALUES('ph_bbbbbbbbbb','Invited','[]',2);",
    )
    .unwrap();
    for _ in 0..2 {
        orch_relay::store::init(&c).unwrap();
    }
    let kinds: Vec<(String, String, Option<String>)> = c
        .prepare("SELECT id,kind,token_hash FROM phones ORDER BY id")
        .unwrap()
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap();
    assert_eq!(
        kinds,
        vec![
            ("ph_aaaaaaaaaa".into(), "phone".into(), Some("h".into())),
            ("ph_bbbbbbbbbb".into(), "phone".into(), None),
        ]
    );
}
