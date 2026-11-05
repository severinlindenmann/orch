mod common;
use common::*;

#[tokio::test]
async fn files_upload_list_blob_delete() {
    let t = setup();
    let ws = t.workspace("A", basic_rights()).await;
    let blob = vector_blob();
    let r = t.api(&ws, "POST", "/v1/files?days=7", blob.clone()).await;
    assert_eq!(r.status, 201, "{}", r.text());
    let j = r.json();
    let id = j["id"].as_str().unwrap().to_string();
    assert!(id.starts_with("f_") && id.len() == 18);
    assert_eq!(j["url"], format!("https://publish.test/f/{id}"));
    assert_eq!(j["size"], blob.len());
    assert!(j["expires_at"].as_str().unwrap().ends_with('Z'));

    let l = t.api(&ws, "GET", "/v1/files", vec![]).await.json();
    assert_eq!(l["items"][0]["id"], id.as_str());
    assert!(l["next"].is_null());

    // public blob is the exact ciphertext
    let b = call(&t.public, "GET", &format!("/f/{id}/blob"), &[], vec![]).await;
    assert_eq!(b.status, 200);
    assert_eq!(b.body, blob);
    assert_eq!(b.headers["content-type"], "application/octet-stream");
    assert_eq!(b.headers["content-length"], blob.len().to_string().as_str());
    assert_eq!(b.headers["x-content-type-options"], "nosniff");
    assert_eq!(
        b.headers["x-orch-expires-at"],
        j["expires_at"].as_str().unwrap()
    );

    let d = t
        .api(&ws, "DELETE", &format!("/v1/files/{id}"), vec![])
        .await;
    assert_eq!(d.status, 204);
    assert_eq!(
        call(&t.public, "GET", &format!("/f/{id}/blob"), &[], vec![])
            .await
            .status,
        404
    );
    assert!(!t.dir.path().join("files").join(&id).exists());
}

#[tokio::test]
async fn files_page_has_security_headers() {
    let t = setup();
    let ws = t.workspace("A", basic_rights()).await;
    let id = t.api(&ws, "POST", "/v1/files", vector_blob()).await.json()["id"]
        .as_str()
        .unwrap()
        .to_string();
    let p = call(&t.public, "GET", &format!("/f/{id}"), &[], vec![]).await;
    assert_eq!(p.status, 200);
    assert_eq!(p.headers["x-frame-options"], "DENY");
    assert_eq!(p.headers["referrer-policy"], "no-referrer");
    let csp = p.headers["content-security-policy"].to_str().unwrap();
    assert!(
        csp.contains("default-src 'none'")
            && csp.contains("frame-ancestors 'none'")
            && csp.contains("script-src 'self'")
    );
    assert!(p.text().contains("/_/file.js"));
    assert_eq!(
        call(&t.public, "GET", "/_/file.js", &[], vec![])
            .await
            .status,
        200
    );
    assert_eq!(
        call(&t.public, "GET", "/_/style.css", &[], vec![])
            .await
            .status,
        200
    );
}

#[tokio::test]
async fn files_permanent_needs_right() {
    let t = setup();
    let ws = t.workspace("A", basic_rights()).await;
    let r = t
        .api(&ws, "POST", "/v1/files?permanent=1", vector_blob())
        .await;
    assert_eq!(r.status, 403);
    assert_eq!(r.json()["error"], "forbidden");
    let ws2 = t.workspace("B", all_rights()).await;
    let r = t
        .api(&ws2, "POST", "/v1/files?permanent=1", vector_blob())
        .await;
    assert_eq!(r.status, 201);
    assert!(r.json()["expires_at"].is_null());
}

#[tokio::test]
async fn files_days_and_blob_checks() {
    let t = setup();
    let ws = t.workspace("A", basic_rights()).await;
    assert_eq!(
        t.api(&ws, "POST", "/v1/files?days=91", vector_blob())
            .await
            .status,
        422
    );
    assert_eq!(
        t.api(&ws, "POST", "/v1/files?days=0", vector_blob())
            .await
            .status,
        422
    );
    assert_eq!(
        t.api(&ws, "POST", "/v1/files?days=90", vector_blob())
            .await
            .status,
        201
    );
    let r = t
        .api(
            &ws,
            "POST",
            "/v1/files",
            b"not a blob at all, but long enough to pass 32".to_vec(),
        )
        .await;
    assert_eq!(r.status, 422);
    assert_eq!(r.json()["error"], "invalid");
}

#[tokio::test]
async fn files_too_large_is_413() {
    let t = setup_with(|c| c.max_file_mb = 0);
    let ws = t.workspace("A", basic_rights()).await;
    let mut big = b"OPF1".to_vec();
    big.resize(64 * 1024 + 37, 1);
    let r = t.api(&ws, "POST", "/v1/files", big).await;
    assert_eq!(r.status, 413);
    assert_eq!(r.json()["error"], "too_large");
}

#[tokio::test]
async fn files_other_workspace_sees_404() {
    let t = setup();
    let a = t.workspace("A", basic_rights()).await;
    let b = t.workspace("B", basic_rights()).await;
    let id = t.api(&a, "POST", "/v1/files", vector_blob()).await.json()["id"]
        .as_str()
        .unwrap()
        .to_string();
    assert_eq!(
        t.api(&b, "DELETE", &format!("/v1/files/{id}"), vec![])
            .await
            .status,
        404
    );
    assert_eq!(
        t.api(&b, "GET", "/v1/files", vec![]).await.json()["items"]
            .as_array()
            .unwrap()
            .len(),
        0
    );
}

#[tokio::test]
async fn files_expired_is_410_and_sweep_removes() {
    let t = setup();
    let ws = t.workspace("A", basic_rights()).await;
    let id = t.api(&ws, "POST", "/v1/files", vector_blob()).await.json()["id"]
        .as_str()
        .unwrap()
        .to_string();
    t.st.db
        .lock()
        .unwrap()
        .execute("UPDATE files SET expires_at='2000-01-01T00:00:00Z'", [])
        .unwrap();
    assert_eq!(
        call(&t.public, "GET", &format!("/f/{id}"), &[], vec![])
            .await
            .status,
        410
    );
    assert_eq!(
        call(&t.public, "GET", &format!("/f/{id}/blob"), &[], vec![])
            .await
            .status,
        410
    );
    orch_publish::sweep::sweep(&t.st).await;
    assert_eq!(
        call(&t.public, "GET", &format!("/f/{id}/blob"), &[], vec![])
            .await
            .status,
        404
    );
    assert!(!t.dir.path().join("files").join(&id).exists());
}

#[tokio::test]
async fn files_list_paging() {
    let t = setup();
    let ws = t.workspace("A", basic_rights()).await;
    for _ in 0..3 {
        t.api(&ws, "POST", "/v1/files", vector_blob()).await;
    }
    let p1 = t.api(&ws, "GET", "/v1/files?limit=2", vec![]).await.json();
    assert_eq!(p1["items"].as_array().unwrap().len(), 2);
    let next = p1["next"].as_str().unwrap();
    let p2 = t
        .api(
            &ws,
            "GET",
            &format!("/v1/files?limit=2&after={next}"),
            vec![],
        )
        .await
        .json();
    assert_eq!(p2["items"].as_array().unwrap().len(), 1);
    assert!(p2["next"].is_null());
}

#[test]
fn files_vector_decrypts_with_rust_aes_gcm() {
    use aes_gcm::aead::{Aead, KeyInit, Payload};
    use aes_gcm::{Aes256Gcm, Nonce};
    use base64::Engine;
    let v: serde_json::Value = serde_json::from_str(
        &std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../contracts/vectors/publish-blob-v1.json"
        ))
        .unwrap(),
    )
    .unwrap();
    let key = base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(v["good"]["key_b64url"].as_str().unwrap())
        .unwrap();
    let blob = vector_blob();
    let c = Aes256Gcm::new_from_slice(&key).unwrap();
    let plain = c
        .decrypt(
            Nonce::from_slice(&blob[4..16]),
            Payload {
                msg: &blob[16..],
                aad: b"OPF1",
            },
        )
        .unwrap();
    let n = u32::from_be_bytes(plain[0..4].try_into().unwrap()) as usize;
    assert_eq!(
        &plain[4..4 + n],
        v["good"]["header_json"].as_str().unwrap().as_bytes()
    );
    assert_eq!(
        &plain[4 + n..],
        v["good"]["content_utf8"].as_str().unwrap().as_bytes()
    );
    let bad = Aes256Gcm::new_from_slice(&[0u8; 32]).unwrap();
    assert!(bad
        .decrypt(
            Nonce::from_slice(&blob[4..16]),
            Payload {
                msg: &blob[16..],
                aad: b"OPF1"
            }
        )
        .is_err());
}

#[tokio::test]
async fn files_page_csp_allows_previews_but_no_inline_or_eval() {
    let t = setup();
    let ws = t.workspace("A", basic_rights()).await;
    let id = t.api(&ws, "POST", "/v1/files", vector_blob()).await.json()["id"]
        .as_str()
        .unwrap()
        .to_string();
    let p = call(&t.public, "GET", &format!("/f/{id}"), &[], vec![]).await;
    let csp = p.headers["content-security-policy"].to_str().unwrap();
    for part in [
        "script-src 'self';",
        "img-src 'self' data: blob: https:",
        "media-src blob:",
        "frame-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
    ] {
        assert!(csp.contains(part), "{part} missing in {csp}");
    }
    assert!(!csp.contains("unsafe-inline") && !csp.contains("unsafe-eval"));
    assert!(p.text().contains("href=\"/_/favicon.svg\""));
}

#[tokio::test]
async fn preview_frame_is_sandboxed_and_has_its_own_csp() {
    let t = setup();
    let f = call(&t.public, "GET", "/_/frame.html", &[], vec![]).await;
    assert_eq!(f.status, 200);
    assert!(f.text().contains("<script src=\"/_/frame.js\">"));
    let csp = f.headers["content-security-policy"].to_str().unwrap();
    assert!(csp.starts_with("default-src 'none';"));
    assert!(csp.contains("frame-ancestors 'self'") && csp.contains("form-action 'none'"));
    // opaque origin even if someone frames or opens it without the iframe sandbox attribute
    assert!(csp.ends_with("; sandbox allow-scripts"));
    // the frame is framed by the file page only, so no X-Frame-Options: DENY here
    assert!(f.headers.get("x-frame-options").is_none());
    assert_eq!(f.headers["referrer-policy"], "no-referrer");
    let js = call(&t.public, "GET", "/_/file.js", &[], vec![])
        .await
        .text();
    // HTML previews: scripts yes, same origin / top navigation / popups never
    assert!(js.contains(r#"f.setAttribute("sandbox", "allow-scripts")"#));
    for bad in [
        "allow-same-origin",
        "allow-top-navigation",
        "allow-popups",
        "allow-forms",
    ] {
        assert!(!js.contains(bad), "{bad} in file.js");
    }
    let fj = call(&t.public, "GET", "/_/frame.js", &[], vec![]).await;
    assert_eq!(fj.status, 200);
    assert!(fj.text().contains("e.source !== window.parent"));
}

#[tokio::test]
async fn favicons_on_public_and_admin() {
    let t = setup();
    for r in [&t.public, &t.admin] {
        let s = call(r, "GET", "/_/favicon.svg", &[], vec![]).await;
        assert_eq!(s.status, 200);
        assert_eq!(s.headers["content-type"], "image/svg+xml");
        assert!(s.text().contains("#60a5fa"), "publish icon is blue");
        let p = call(r, "GET", "/_/apple-touch-icon.png", &[], vec![]).await;
        assert_eq!(p.status, 200);
        assert_eq!(&p.body[1..4], b"PNG");
    }
    let portal = call(&t.admin, "GET", "/admin", &[], vec![]).await.text();
    assert!(portal.contains("rel=\"icon\" href=\"/_/favicon.svg\""));
    let nf = call(&t.public, "GET", "/nope", &[], vec![]).await.text();
    assert!(nf.contains("rel=\"apple-touch-icon\""));
}

fn expire_all(t: &T) {
    t.st.db
        .lock()
        .unwrap()
        .execute("UPDATE files SET expires_at='2000-01-01T00:00:00Z'", [])
        .unwrap();
}

#[tokio::test]
async fn replace_keeps_id_and_expiry_and_swaps_blob() {
    let t = setup();
    let ws = t.workspace("A", basic_rights()).await;
    let j = t
        .api(&ws, "POST", "/v1/files?days=3", vector_blob())
        .await
        .json();
    let id = j["id"].as_str().unwrap().to_string();
    let mut nb = b"OPF1".to_vec();
    nb.resize(80, 7);
    let r = t
        .api(&ws, "PUT", &format!("/v1/files/{id}"), nb.clone())
        .await;
    assert_eq!(r.status, 200, "{}", r.text());
    assert_eq!(r.json()["id"], id.as_str());
    assert_eq!(r.json()["expires_at"], j["expires_at"]);
    let b = call(&t.public, "GET", &format!("/f/{id}/blob"), &[], vec![]).await;
    assert_eq!(b.body, nb);
    let l = t.api(&ws, "GET", "/v1/files", vec![]).await.json();
    assert_eq!(l["items"][0]["size"], 80);
    // same OPF1 check
    let bad = t
        .api(&ws, "PUT", &format!("/v1/files/{id}"), vec![1u8; 64])
        .await;
    assert_eq!(bad.status, 422);
    assert_eq!(
        call(&t.public, "GET", &format!("/f/{id}/blob"), &[], vec![])
            .await
            .body,
        nb
    );
}

#[tokio::test]
async fn replace_only_by_owner_and_never_revives_expired() {
    let t = setup();
    let a = t.workspace("A", basic_rights()).await;
    let b = t.workspace("B", basic_rights()).await;
    let id = t.api(&a, "POST", "/v1/files", vector_blob()).await.json()["id"]
        .as_str()
        .unwrap()
        .to_string();
    let uri = format!("/v1/files/{id}");
    assert_eq!(t.api(&b, "PUT", &uri, vector_blob()).await.status, 404);
    assert_eq!(
        t.api(&b, "PATCH", &uri, br#"{"days":5}"#.to_vec())
            .await
            .status,
        404
    );
    expire_all(&t);
    assert_eq!(t.api(&a, "PUT", &uri, vector_blob()).await.status, 410);
    assert_eq!(
        t.api(&a, "PATCH", &uri, br#"{"days":5}"#.to_vec())
            .await
            .status,
        410
    );
}

#[tokio::test]
async fn replace_too_large_is_413() {
    let t = setup_with(|c| c.max_file_mb = 0);
    let ws = t.workspace("A", basic_rights()).await;
    let id = t.api(&ws, "POST", "/v1/files", vector_blob()).await.json()["id"]
        .as_str()
        .unwrap()
        .to_string();
    let mut big = b"OPF1".to_vec();
    big.resize(64 * 1024 + 37, 1);
    let r = t.api(&ws, "PUT", &format!("/v1/files/{id}"), big).await;
    assert_eq!(r.status, 413);
}

#[tokio::test]
async fn extend_sets_new_expiry_and_checks_days() {
    let t = setup();
    let ws = t.workspace("A", basic_rights()).await;
    let j = t
        .api(&ws, "POST", "/v1/files?days=1", vector_blob())
        .await
        .json();
    let id = j["id"].as_str().unwrap();
    let uri = format!("/v1/files/{id}");
    let r = t.api(&ws, "PATCH", &uri, br#"{"days":30}"#.to_vec()).await;
    assert_eq!(r.status, 200, "{}", r.text());
    assert!(r.json()["expires_at"].as_str().unwrap() > j["expires_at"].as_str().unwrap());
    // never shortens
    let r2 = t.api(&ws, "PATCH", &uri, br#"{"days":2}"#.to_vec()).await;
    assert_eq!(r2.json()["expires_at"], r.json()["expires_at"]);
    for body in [&br#"{"days":0}"#[..], br#"{"days":91}"#, b"{}", b"nope"] {
        assert_eq!(t.api(&ws, "PATCH", &uri, body.to_vec()).await.status, 422);
    }
    let l = t.api(&ws, "GET", "/v1/files", vec![]).await.json();
    assert_eq!(l["items"][0]["expires_at"], r.json()["expires_at"]);
}

#[tokio::test]
async fn patch_needs_files_right_and_has_small_body_limit() {
    let t = setup();
    let ws = t.workspace("A", basic_rights()).await;
    let id = t.api(&ws, "POST", "/v1/files", vector_blob()).await.json()["id"]
        .as_str()
        .unwrap()
        .to_string();
    let uri = format!("/v1/files/{id}");
    // PATCH keeps axum's default 2 MB body limit
    let mut big = br#"{"days":5,"x":""#.to_vec();
    big.resize(3 * 1024 * 1024, b'a');
    big.extend_from_slice(b"\"}");
    assert_eq!(t.api(&ws, "PATCH", &uri, big).await.status, 413);
    // a workspace whose files right was removed may not extend
    t.st.db
        .lock()
        .unwrap()
        .execute(
            "UPDATE workspaces SET rights=REPLACE(rights,'\"files\":true','\"files\":false')",
            [],
        )
        .unwrap();
    let r = t.api(&ws, "PATCH", &uri, br#"{"days":5}"#.to_vec()).await;
    assert_eq!(r.status, 403, "{}", r.text());
}

#[tokio::test]
async fn replace_leaves_no_temp_files() {
    let t = setup();
    let ws = t.workspace("A", basic_rights()).await;
    let id = t.api(&ws, "POST", "/v1/files", vector_blob()).await.json()["id"]
        .as_str()
        .unwrap()
        .to_string();
    t.api(&ws, "PUT", &format!("/v1/files/{id}"), vector_blob())
        .await;
    let n = std::fs::read_dir(t.dir.path().join("files"))
        .unwrap()
        .count();
    assert_eq!(n, 1);
}
