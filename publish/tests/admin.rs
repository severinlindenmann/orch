mod common;
use common::*;
use serde_json::{json, Value};

#[tokio::test]
async fn admin_needs_token() {
    let t = setup();
    assert_eq!(
        call(&t.admin, "GET", "/admin/api/workspaces", &[], vec![])
            .await
            .status,
        401
    );
    assert_eq!(
        call(
            &t.admin,
            "GET",
            "/admin/api/workspaces",
            &[("x-orch-admin", "wrong")],
            vec![]
        )
        .await
        .status,
        401
    );
    // header only: the cookie is not accepted
    assert_eq!(
        call(
            &t.admin,
            "GET",
            "/admin/api/workspaces",
            &[("cookie", "orch_admin=admin-test-token")],
            vec![]
        )
        .await
        .status,
        401
    );
    // the portal shell itself loads without a token (it asks for one)
    let p = call(&t.admin, "GET", "/admin", &[], vec![]).await;
    assert_eq!(p.status, 200);
    assert_eq!(p.headers["x-frame-options"], "DENY");
    assert_eq!(
        call(&t.admin, "GET", "/admin/portal.js", &[], vec![])
            .await
            .status,
        200
    );
    assert_eq!(
        call(&t.admin, "GET", "/admin/style.css", &[], vec![])
            .await
            .status,
        200
    );
    // admin routes do not exist on the public listener
    assert_eq!(
        call(
            &t.public,
            "GET",
            "/admin/api/workspaces",
            &[("x-orch-admin", ADMIN)],
            vec![]
        )
        .await
        .status,
        404
    );
}

#[tokio::test]
async fn admin_create_shows_prompt_and_edit() {
    let t = setup();
    let r = t.adm("POST", "/admin/api/workspaces", json!({"name": "Pilatus", "description": "Jobs", "tags": ["data", " work "], "rights": {"files": true, "apps": true, "permanent": false, "public": false}})).await;
    assert_eq!(r.status, 201);
    let j = r.json();
    let (id, tok, prompt) = (
        j["id"].as_str().unwrap(),
        j["token"].as_str().unwrap(),
        j["prompt"].as_str().unwrap(),
    );
    assert!(id.starts_with("ws_") && id.len() == 13);
    assert!(prompt.contains("orch addon add publish --yes\n  orch publish connect"));
    assert!(prompt.contains(&format!(
        "orch publish connect https://publish.test --workspace {id} --token {tok}"
    )));
    assert!(prompt.contains("onboarding.sh") && prompt.contains("onboarding.ps1"));

    let l = t
        .adm("GET", "/admin/api/workspaces", Value::Null)
        .await
        .json();
    assert_eq!(l["items"][0]["tags"], json!(["data", "work"]));
    assert_eq!(l["items"][0]["files"], 0);
    assert!(l["items"][0].get("token").is_none());

    let p = t.adm("PATCH", &format!("/admin/api/workspaces/{id}"), json!({"name": "Pilatus 2", "rights": {"files": true, "apps": false, "permanent": true, "public": false}})).await;
    assert_eq!(p.status, 200);
    assert_eq!(p.json()["name"], "Pilatus 2");
    assert_eq!(p.json()["description"], "Jobs");
    let who = t
        .api(&(id.into(), tok.into()), "GET", "/v1/whoami", vec![])
        .await
        .json();
    assert_eq!(who["rights"]["permanent"], true);
    assert_eq!(
        t.adm("PATCH", "/admin/api/workspaces/ws_nope", json!({}))
            .await
            .status,
        404
    );
    assert_eq!(
        t.adm("POST", "/admin/api/workspaces", json!({"name": ""}))
            .await
            .status,
        422
    );
}

#[tokio::test]
async fn admin_new_token_replaces_old() {
    let t = setup();
    let ws = t.workspace("A", basic_rights()).await;
    let r = t
        .adm(
            "POST",
            &format!("/admin/api/workspaces/{}/token", ws.0),
            Value::Null,
        )
        .await;
    assert_eq!(r.status, 200);
    let new = r.json()["token"].as_str().unwrap().to_string();
    assert_eq!(t.api(&ws, "GET", "/v1/whoami", vec![]).await.status, 401);
    assert_eq!(
        t.api(&(ws.0.clone(), new), "GET", "/v1/whoami", vec![])
            .await
            .status,
        200
    );
}

#[tokio::test]
async fn admin_files_apps_and_delete_workspace() {
    let t = setup();
    let ws = t.workspace("A", basic_rights()).await;
    let id = t.api(&ws, "POST", "/v1/files", vector_blob()).await.json()["id"]
        .as_str()
        .unwrap()
        .to_string();
    t.api(
        &ws,
        "PUT",
        "/v1/apps/site",
        bundle(&[("app.toml", "name = \"site\"\nstack = \"static\"\n")]),
    )
    .await;

    let f = t.adm("GET", "/admin/api/files", Value::Null).await.json();
    assert_eq!(f["items"][0]["id"], id.as_str());
    assert_eq!(f["items"][0]["workspace"], ws.0.as_str());
    assert!(f["items"][0].get("name").is_none());
    assert!(f["items"][0]["created_at"].as_str().unwrap().ends_with('Z'));
    let a = t.adm("GET", "/admin/api/apps", Value::Null).await.json();
    assert_eq!(a["items"][0]["workspace"], ws.0.as_str());
    let l = t
        .adm("GET", "/admin/api/workspaces", Value::Null)
        .await
        .json();
    assert_eq!(
        (
            l["items"][0]["files"].as_i64(),
            l["items"][0]["apps"].as_i64()
        ),
        (Some(1), Some(1))
    );

    assert_eq!(
        t.adm("POST", "/admin/api/apps/site/stop", Value::Null)
            .await
            .json()["status"],
        "stopped"
    );
    assert_eq!(
        t.adm("POST", "/admin/api/apps/site/restart", Value::Null)
            .await
            .json()["status"],
        "running"
    );

    assert_eq!(
        t.adm(
            "DELETE",
            &format!("/admin/api/workspaces/{}", ws.0),
            Value::Null
        )
        .await
        .status,
        204
    );
    assert_eq!(
        call(&t.public, "GET", &format!("/f/{id}/blob"), &[], vec![])
            .await
            .status,
        404
    );
    assert_eq!(
        t.adm("GET", "/admin/api/apps", Value::Null).await.json()["items"]
            .as_array()
            .unwrap()
            .len(),
        0
    );
    assert_eq!(t.api(&ws, "GET", "/v1/whoami", vec![]).await.status, 401);

    let ws2 = t.workspace("B", basic_rights()).await;
    let id2 = t.api(&ws2, "POST", "/v1/files", vector_blob()).await.json()["id"]
        .as_str()
        .unwrap()
        .to_string();
    assert_eq!(
        t.adm("DELETE", &format!("/admin/api/files/{id2}"), Value::Null)
            .await
            .status,
        204
    );
    t.api(
        &ws2,
        "PUT",
        "/v1/apps/other",
        bundle(&[("app.toml", "name = \"other\"\nstack = \"static\"\n")]),
    )
    .await;
    assert_eq!(
        t.adm("DELETE", "/admin/api/apps/other", Value::Null)
            .await
            .status,
        204
    );
}

#[tokio::test]
async fn admin_onboarding_scripts() {
    let t = setup();
    let sh = call(&t.public, "GET", "/onboarding.sh", &[], vec![]).await;
    assert_eq!(sh.status, 200);
    assert!(
        sh.text().starts_with("#!/bin/sh")
            && sh.text().contains("https://publish.test")
            && sh
                .text()
                .contains("orch addon add publish --yes\nexec orch publish connect")
    );
    assert!(!sh.text().contains("__PUBLISH_URL__"));
    // test config uses the default ref
    assert!(sh.text().contains("orch/main/install.sh") && sh.text().contains("ORCH_REF=\"main\""));
    let ps = call(&t.public, "GET", "/onboarding.ps1", &[], vec![]).await;
    assert!(
        ps.text().contains("param(")
            && ps.text().contains("orch publish connect")
            && !ps.text().contains("__INSTALL_URL__")
    );
    assert_eq!(
        call(&t.public, "GET", "/health", &[], vec![]).await.text(),
        "ok"
    );
}

#[tokio::test]
async fn portal_prompt_skips_describe_line_when_admin_described() {
    let t = setup();
    let r = t
        .adm(
            "POST",
            "/admin/api/workspaces",
            json!({"name": "A", "description": "Jobs", "tags": []}),
        )
        .await;
    let j = r.json();
    assert!(!j["prompt"]
        .as_str()
        .unwrap()
        .contains("describe this workspace"));
    let id = j["id"].as_str().unwrap().to_string();
    let r = t
        .adm("POST", "/admin/api/workspaces", json!({"name": "B"}))
        .await;
    assert!(r.json()["prompt"]
        .as_str()
        .unwrap()
        .contains("describe this workspace"));
    let r = t
        .adm(
            "POST",
            &format!("/admin/api/workspaces/{id}/token"),
            Value::Null,
        )
        .await;
    assert!(!r.json()["prompt"]
        .as_str()
        .unwrap()
        .contains("describe this workspace"));
}

#[tokio::test]
async fn admin_assets_served() {
    let t = setup();
    let css = call(&t.admin, "GET", "/admin/style.css", &[], vec![]).await;
    assert_eq!(css.status, 200);
    assert_eq!(css.headers["content-type"], "text/css; charset=utf-8");
    assert!(css.text().contains("--brand:var(--info)"));
    assert!(
        css.text().contains("--info:"),
        "master tokens are served first"
    );
    let public_css = call(&t.public, "GET", "/_/style.css", &[], vec![]).await;
    assert_eq!(public_css.status, 200);
    assert_ne!(css.text(), public_css.text());

    let kit = call(&t.admin, "GET", "/admin/kit.js", &[], vec![]).await;
    assert_eq!(kit.status, 200);
    assert_eq!(
        kit.headers["content-type"],
        "text/javascript; charset=utf-8"
    );
    assert!(kit.text().contains("window.icon"));
    assert!(kit.text().contains("window.orch"));
}

#[test]
fn portal_shows_small_sizes_in_bytes_like_the_public_page() {
    let js = include_str!("../web/portal.js");
    assert!(js.contains("value === 1 ? 'byte' : 'bytes'"));
}

// PCX-01 (owner 28 Nov): the workspace right `public` is named by what it changes (an internet app may open without
// its access link); "private" and "public" stay words for an app's network reach and are not used for this choice.
#[test]
fn portal_names_the_access_link_right_not_reach() {
    let js = include_str!("../web/portal.js");
    assert!(js.contains(r#"<label for="sharing">Internet apps without an access link</label>"#));
    assert!(js.contains(">Not allowed</option>") && js.contains(">Allowed</option>"));
    assert!(js.contains("An app's network reach is chosen separately."));
    assert!(js.contains("'Internet apps may open without an access link' : 'Internet apps require an access link'"));
    // the same field name and values as before: no policy change
    assert!(js.contains(r#"<select id="sharing" name="public""#));
    assert!(js.contains("public: data.get('public') === 'true'"));
    for old in ["Private only", "Public links allowed", "Private apps open only with their access link"] {
        assert!(!js.contains(old), "old wording: {old}");
    }
}

#[test]
fn portal_markup_respects_csp() {
    let html = include_str!("../web/portal.html");
    let js = include_str!("../web/portal.js");
    for source in [html, js] {
        let source = source.to_ascii_lowercase();
        assert!(!source.contains("style=\""));
        assert!(!source.contains("style='"));
        assert!(!source.contains("<style"));
    }
    for script in html.split("<script").skip(1) {
        let (attributes, rest) = script.split_once('>').expect("script opening tag");
        assert!(attributes.contains("src=\""), "scripts must be external");
        let (body, _) = rest.split_once("</script>").expect("script closing tag");
        assert!(body.trim().is_empty(), "no inline script body");
    }
    assert!(html.contains("src=\"/admin/kit.js\" defer"));
    assert!(html.contains("src=\"/admin/portal.js\" defer"));
}

#[tokio::test]
async fn admin_root_goes_to_the_portal() {
    let t = setup();
    let r = call(&t.admin, "GET", "/", &[], vec![]).await;
    assert!(r.status.is_redirection());
    assert_eq!(r.headers["location"], "/admin");
}

/// Every text cell of every table that contains `needle`.
fn rows_naming(c: &rusqlite::Connection, needle: &str) -> Vec<String> {
    let tables: Vec<String> = c
        .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        .unwrap()
        .query_map([], |r| r.get(0))
        .unwrap()
        .map(|r| r.unwrap())
        .collect();
    let mut hits = vec![];
    for t in tables {
        let cols: Vec<String> = c
            .prepare(&format!("SELECT name FROM pragma_table_info('{t}')"))
            .unwrap()
            .query_map([], |r| r.get(0))
            .unwrap()
            .map(|r| r.unwrap())
            .collect();
        for col in cols {
            let n: i64 = c
                .query_row(
                    &format!("SELECT COUNT(*) FROM \"{t}\" WHERE typeof(\"{col}\")='text' AND instr(\"{col}\", ?1)>0"),
                    [needle],
                    |r| r.get(0),
                )
                .unwrap();
            if n > 0 {
                hits.push(format!("{t}.{col}"));
            }
        }
    }
    hits
}

/// Every path under `dir` whose name contains one of `needles`.
fn paths_naming(dir: &std::path::Path, needles: &[&str]) -> Vec<String> {
    let mut out = vec![];
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&d) else {
            continue;
        };
        for e in rd.flatten() {
            let p = e.path();
            let name = e.file_name().to_string_lossy().to_string();
            if needles.iter().any(|n| name.contains(n)) {
                out.push(p.display().to_string());
            }
            if p.is_dir() {
                stack.push(p);
            }
        }
    }
    out
}

#[tokio::test]
async fn delete_workspace_leaves_no_row_or_file_of_it() {
    let t = setup();
    let gone = t.workspace("Gone", basic_rights()).await;
    let stays = t.workspace("Stays", basic_rights()).await;
    let mut fids = vec![];
    for _ in 0..2 {
        fids.push(
            t.api(&gone, "POST", "/v1/files", vector_blob())
                .await
                .json()["id"]
                .as_str()
                .unwrap()
                .to_string(),
        );
    }
    let keep = t
        .api(&stays, "POST", "/v1/files", vector_blob())
        .await
        .json()["id"]
        .as_str()
        .unwrap()
        .to_string();
    for (w, name) in [(&gone, "gone-site"), (&stays, "kept-site")] {
        let r = t
            .api(
                w,
                "PUT",
                &format!("/v1/apps/{name}"),
                bundle(&[
                    (
                        "app.toml",
                        &format!("name = \"{name}\"\nstack = \"static\"\n"),
                    ),
                    ("index.html", "<p>hi</p>"),
                ]),
            )
            .await;
        assert!(r.status.is_success(), "{}", r.text());
    }
    std::fs::create_dir_all(t.st.cfg.data_dir.join("logs")).unwrap();
    std::fs::write(t.st.cfg.log_path("gone-site"), b"log").unwrap();
    let dir = t.st.cfg.data_dir.clone();
    assert!(!paths_naming(&dir, &["gone-site"]).is_empty());

    let pre = t
        .adm(
            "GET",
            &format!("/admin/api/workspaces/{}/removal", gone.0),
            Value::Null,
        )
        .await;
    assert_eq!(pre.status, 200, "{}", pre.text());
    assert_eq!(pre.json()["removes"], json!({"files": 2, "apps": 1}));
    assert_eq!(pre.json()["name"], "Gone");
    assert!(
        !rows_naming(&t.st.db.lock().unwrap(), &gone.0).is_empty(),
        "dry run changed nothing"
    );

    let r = t
        .adm(
            "DELETE",
            &format!("/admin/api/workspaces/{}", gone.0),
            Value::Null,
        )
        .await;
    assert_eq!(r.status, 204);
    {
        let c = t.st.db.lock().unwrap();
        assert_eq!(rows_naming(&c, &gone.0), Vec::<String>::new());
        assert_eq!(rows_naming(&c, "gone-site"), Vec::<String>::new());
        for f in &fids {
            assert_eq!(rows_naming(&c, f), Vec::<String>::new());
        }
        assert!(!rows_naming(&c, &stays.0).is_empty());
        assert!(!rows_naming(&c, &keep).is_empty());
    }
    let mut needles: Vec<&str> = fids.iter().map(String::as_str).collect();
    needles.push("gone-site");
    assert_eq!(paths_naming(&dir, &needles), Vec::<String>::new());
    assert!(!paths_naming(&dir, &[&keep]).is_empty());
    assert!(!paths_naming(&dir, &["kept-site"]).is_empty());
}
