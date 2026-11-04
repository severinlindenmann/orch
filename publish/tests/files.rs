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
