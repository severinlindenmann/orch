mod common;
use common::*;
use serde_json::{json, Value};

async fn put_cred(t: &T, name: &str) {
    let (s, v) = t
        .admin_json(
            "PUT",
            &format!("/admin/api/shared/credentials/{name}"),
            Some(json!({"value": format!("v-{name}")})),
        )
        .await;
    assert_eq!(s, 200, "{v}");
}

async fn put_mcp(t: &T, name: &str) {
    let (s, v) = t
        .admin_json(
            "PUT",
            &format!("/admin/api/shared/mcp/{name}"),
            Some(json!({"config": {"command": "npx"}})),
        )
        .await;
    assert_eq!(s, 200, "{v}");
}

async fn group(t: &T, body: Value) -> Value {
    let (s, v) = t.admin_json("POST", "/admin/api/groups", Some(body)).await;
    assert_eq!(s, 201, "{v}");
    v
}

async fn add_in(t: &T, name: &str, body: Value) -> (Ws, Value) {
    let mut b = json!({"name": name, "description": "", "tags": []});
    for (k, v) in body.as_object().unwrap() {
        b[k] = v.clone();
    }
    let (s, v) = t.admin_json("POST", "/admin/api/workspaces", Some(b)).await;
    assert_eq!(s, 201, "{v}");
    (
        Ws {
            id: v["id"].as_str().unwrap().into(),
            token: v["token"].as_str().unwrap().into(),
        },
        v,
    )
}

async fn snap(t: &T, w: &Ws) -> Value {
    t.call(w, "GET", "/v1/refresh", None).await.1
}

fn creds(s: &Value) -> Vec<String> {
    let mut v: Vec<String> = s["credentials"]
        .as_object()
        .unwrap()
        .keys()
        .cloned()
        .collect();
    v.sort();
    v
}

#[tokio::test]
async fn group_crud_colours_and_names() {
    let t = start().await;
    let a = group(&t, json!({"name": "Work"})).await;
    assert_eq!(a["colour"], "teal");
    assert_eq!(
        a["defaults"],
        json!({"skills": true, "mcp": true, "credentials": true})
    );
    assert_eq!(a["talk"], true);
    assert_eq!(a["members"], json!([]));
    assert!(a["id"].as_str().unwrap().starts_with("grp_"));
    let b = group(
        &t,
        json!({"name": "Private", "talk": false, "defaults": {"credentials": false}}),
    )
    .await;
    assert_eq!(b["colour"], "violet");
    assert_eq!(b["talk"], false);
    assert_eq!(b["defaults"]["credentials"], false);
    // names are unique without regard to case; bad colour and empty name are refused
    let (s, _) = t
        .admin_json("POST", "/admin/api/groups", Some(json!({"name": "work"})))
        .await;
    assert_eq!(s, 409);
    let (s, _) = t
        .admin_json(
            "POST",
            "/admin/api/groups",
            Some(json!({"name": "X", "colour": "red"})),
        )
        .await;
    assert_eq!(s, 422);
    let (s, _) = t
        .admin_json("POST", "/admin/api/groups", Some(json!({"name": "  "})))
        .await;
    assert_eq!(s, 422);
    let id = a["id"].as_str().unwrap();
    let (s, v) = t
        .admin_json(
            "PATCH",
            &format!("/admin/api/groups/{id}"),
            Some(json!({"name": "Work team", "colour": "amber"})),
        )
        .await;
    assert_eq!(s, 200, "{v}");
    assert_eq!(
        (v["name"].as_str(), v["colour"].as_str()),
        (Some("Work team"), Some("amber"))
    );
    let (s, _) = t
        .admin_json(
            "PATCH",
            &format!("/admin/api/groups/{id}"),
            Some(json!({"name": "private"})),
        )
        .await;
    assert_eq!(s, 409);
    let (_, l) = t.admin_json("GET", "/admin/api/groups", None).await;
    let names: Vec<&str> = l["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|g| g["name"].as_str().unwrap())
        .collect();
    assert_eq!(names, ["Private", "Work team"]);
    let (s, _) = t
        .admin_json("DELETE", "/admin/api/groups/grp_nope000000", None)
        .await;
    assert_eq!(s, 404);
}

#[tokio::test]
async fn new_workspace_gets_the_group_tools_now_and_later() {
    let t = start().await;
    put_cred(&t, "BANK").await;
    put_mcp(&t, "files").await;
    let work = group(
        &t,
        json!({"name": "Work", "defaults": {"credentials": false}}),
    )
    .await;
    let wid = work["id"].as_str().unwrap();
    let (a, v) = add_in(&t, "Finance", json!({"group": wid})).await;
    assert_eq!(v["group"], wid);
    assert_eq!(
        v["shared"],
        json!({"skills": 0, "mcp": 1, "credentials": 0})
    );
    let s = snap(&t, &a).await;
    assert_eq!(s["mcp"]["files"]["command"], "npx");
    assert!(creds(&s).is_empty(), "Work does not give secrets");

    // "New group…" in the same call: all kinds on, so the secret comes too
    let (b, v) = add_in(&t, "Home", json!({"new_group": "Private"})).await;
    let pid = v["group"].as_str().unwrap().to_string();
    assert_eq!(
        v["shared"],
        json!({"skills": 0, "mcp": 1, "credentials": 1})
    );
    assert_eq!(creds(&snap(&t, &b).await), ["BANK"]);

    // a tool added later goes to the members whose group gives that kind
    t.inbox(&a).await;
    t.inbox(&b).await;
    put_cred(&t, "ROUTER").await;
    assert_eq!(creds(&snap(&t, &b).await), ["BANK", "ROUTER"]);
    assert!(creds(&snap(&t, &a).await).is_empty());
    assert!(t
        .inbox(&b)
        .await
        .iter()
        .any(|m| m["type"] == "refresh-hint"));

    // updating an existing tool does not give it back to someone the admin took it from
    let (s, _) = t
        .admin_json(
            "PUT",
            &format!("/admin/api/shared/assign/{}", b.id),
            Some(json!({"mcp": ["files"], "credentials": ["BANK"]})),
        )
        .await;
    assert_eq!(s, 200);
    put_cred(&t, "ROUTER").await;
    assert_eq!(creds(&snap(&t, &b).await), ["BANK"]);

    // the list shows the group, the group lists its members
    let (_, l) = t.admin_json("GET", "/admin/api/workspaces", None).await;
    let g: Vec<(&str, &str)> = l["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|w| (w["name"].as_str().unwrap(), w["group"].as_str().unwrap()))
        .collect();
    assert_eq!(g, [("Finance", wid), ("Home", pid.as_str())]);
    let (_, gl) = t.admin_json("GET", "/admin/api/groups", None).await;
    let priv_g = gl["items"]
        .as_array()
        .unwrap()
        .iter()
        .find(|x| x["id"] == pid.as_str())
        .unwrap()
        .clone();
    assert_eq!(priv_g["members"], json!([b.id]));
    assert_eq!(
        priv_g["gives"],
        json!({"skills": 0, "mcp": 1, "credentials": 2})
    );
}

#[tokio::test]
async fn bad_group_creates_nothing_and_no_group_still_works() {
    let t = start().await;
    let g = group(&t, json!({"name": "Work"})).await;
    for body in [
        json!({"name": "A", "group": "grp_nope000000"}),
        json!({"name": "A", "group": g["id"], "new_group": "Other"}),
        json!({"name": "A", "new_group": "work"}),
    ] {
        let (s, v) = t
            .admin_json("POST", "/admin/api/workspaces", Some(body))
            .await;
        assert!(s == 422 || s == 409, "{s} {v}");
    }
    let (_, l) = t.admin_json("GET", "/admin/api/workspaces", None).await;
    assert_eq!(l["items"], json!([]));
    let (_, gl) = t.admin_json("GET", "/admin/api/groups", None).await;
    assert_eq!(gl["items"].as_array().unwrap().len(), 1);
    // scripts and older callers send no group: the workspace is in no group and gets nothing
    put_cred(&t, "BANK").await;
    let (w, v) = add_in(&t, "Loose", json!({})).await;
    assert_eq!(v["group"], Value::Null);
    assert!(creds(&snap(&t, &w).await).is_empty());
}

#[tokio::test]
async fn group_members_may_message_each_other_when_talk_is_on() {
    let t = start().await;
    let g = group(&t, json!({"name": "Work"})).await;
    let gid = g["id"].as_str().unwrap().to_string();
    let (a, _) = add_in(&t, "Finance", json!({"group": gid})).await;
    let (b, _) = add_in(&t, "Reports", json!({"group": gid})).await;
    let (c, _) = add_in(&t, "Outside", json!({})).await;
    let (s, v) = t.send(&a, &b.id, "text", json!({"text": "hi"})).await;
    assert_eq!(s, 201, "{v}");
    let (s, v) = t.send(&b, &a.id, "text", json!({"text": "hi back"})).await;
    assert_eq!(s, 201, "{v}");
    // tasks stay per pair (Who can do what)
    let (s, _) = t
        .send(&a, &b.id, "delegate", json!({"title": "x", "text": "y"}))
        .await;
    assert_eq!(s, 403);
    // outsiders are not connected
    let (s, _) = t.send(&c, &a.id, "text", json!({"text": "x"})).await;
    assert_eq!(s, 404);
    // directory: members see each other with messages and files allowed
    let d = &snap(&t, &a).await["workspaces"]["workspaces"];
    assert_eq!(d.as_array().unwrap().len(), 1);
    assert_eq!(d[0]["id"], b.id);
    assert_eq!(
        d[0]["can_send"],
        json!({"text": true, "files": true, "delegate": false, "start": false})
    );
    // a pair rule adds to the group rule
    t.rules(json!([rule(&a, &b, [false, false, true, false])]))
        .await;
    let d = &snap(&t, &a).await["workspaces"]["workspaces"];
    assert_eq!(
        d[0]["can_send"],
        json!({"text": true, "files": true, "delegate": true, "start": false})
    );
    t.rules(json!([])).await;
    // talk off: hints go out, and they are no longer connected
    t.inbox(&a).await;
    let (s, _) = t
        .admin_json(
            "PATCH",
            &format!("/admin/api/groups/{gid}"),
            Some(json!({"talk": false})),
        )
        .await;
    assert_eq!(s, 200);
    assert!(t
        .inbox(&a)
        .await
        .iter()
        .any(|m| m["type"] == "refresh-hint"));
    let (s, _) = t.send(&a, &b.id, "text", json!({"text": "x"})).await;
    assert_eq!(s, 404);
    assert_eq!(snap(&t, &a).await["workspaces"]["workspaces"], json!([]));
}

#[tokio::test]
async fn moving_keeps_old_tools_and_defaults_on_give_to_members() {
    let t = start().await;
    put_cred(&t, "BANK").await;
    put_mcp(&t, "files").await;
    let private = group(&t, json!({"name": "Private", "defaults": {"mcp": false}})).await;
    let work = group(
        &t,
        json!({"name": "Work", "defaults": {"credentials": false, "mcp": false}, "talk": false}),
    )
    .await;
    let (a, _) = add_in(&t, "Home", json!({"group": private["id"]})).await;
    assert_eq!(creds(&snap(&t, &a).await), ["BANK"]);
    // move to Work: keeps BANK, Work gives nothing extra
    let (s, _) = t
        .admin_json(
            "PATCH",
            &format!("/admin/api/workspaces/{}", a.id),
            Some(json!({"group": work["id"]})),
        )
        .await;
    assert_eq!(s, 200);
    let s1 = snap(&t, &a).await;
    assert_eq!(creds(&s1), ["BANK"]);
    assert!(s1["mcp"].as_object().unwrap().is_empty());
    // Work turns MCP on: the current member gets it at once
    let wid = work["id"].as_str().unwrap();
    let (s, v) = t
        .admin_json(
            "PATCH",
            &format!("/admin/api/groups/{wid}"),
            Some(json!({"defaults": {"mcp": true}})),
        )
        .await;
    assert_eq!(s, 200, "{v}");
    assert_eq!(snap(&t, &a).await["mcp"]["files"]["command"], "npx");
    // turning it off takes nothing away
    t.admin_json(
        "PATCH",
        &format!("/admin/api/groups/{wid}"),
        Some(json!({"defaults": {"mcp": false}})),
    )
    .await;
    assert_eq!(snap(&t, &a).await["mcp"]["files"]["command"], "npx");
    // unknown group is refused
    let (s, _) = t
        .admin_json(
            "PATCH",
            &format!("/admin/api/workspaces/{}", a.id),
            Some(json!({"group": "grp_nope000000"})),
        )
        .await;
    assert_eq!(s, 422);
    // deleting the group: the member stays, keeps its tools, is in no group
    let (s, _) = t
        .admin_json("DELETE", &format!("/admin/api/groups/{wid}"), None)
        .await;
    assert_eq!(s, 204);
    let (_, l) = t.admin_json("GET", "/admin/api/workspaces", None).await;
    assert_eq!(l["items"][0]["group"], Value::Null);
    assert_eq!(creds(&snap(&t, &a).await), ["BANK"]);
    // deleting a workspace removes it from its group
    let (b, _) = add_in(&t, "Spare", json!({"group": private["id"]})).await;
    t.admin_json("DELETE", &format!("/admin/api/workspaces/{}", b.id), None)
        .await;
    let (_, gl) = t.admin_json("GET", "/admin/api/groups", None).await;
    assert_eq!(gl["items"][0]["members"], json!([]));
}

#[tokio::test]
async fn group_routes_need_the_admin_header() {
    let t = start().await;
    let g = group(&t, json!({"name": "Work"})).await;
    let gid = g["id"].as_str().unwrap().to_string();
    let (w, _) = add_in(&t, "Finance", json!({"group": gid})).await;
    let calls: Vec<(&str, String, Option<Value>)> = vec![
        ("GET", "/admin/api/groups".into(), None),
        (
            "POST",
            "/admin/api/groups".into(),
            Some(json!({"name": "X"})),
        ),
        (
            "PATCH",
            format!("/admin/api/groups/{gid}"),
            Some(json!({"defaults": {"credentials": true}})),
        ),
        ("DELETE", format!("/admin/api/groups/{gid}"), None),
        (
            "PATCH",
            format!("/admin/api/workspaces/{}", w.id),
            Some(json!({"group": Value::Null})),
        ),
        (
            "POST",
            "/admin/api/workspaces".into(),
            Some(json!({"name": "Y", "new_group": "Z"})),
        ),
    ];
    for (m, path, body) in calls {
        for hdr in [None, Some("wrong")] {
            let mut r = t.http.request(
                reqwest::Method::from_bytes(m.as_bytes()).unwrap(),
                format!("{}{}", t.admin, path),
            );
            if let Some(h) = hdr {
                r = r.header("X-Orch-Admin", h);
            }
            if let Some(b) = &body {
                r = r.json(b);
            }
            assert_eq!(r.send().await.unwrap().status(), 401, "{m} {path} {hdr:?}");
        }
    }
    // nothing changed
    let (_, gl) = t.admin_json("GET", "/admin/api/groups", None).await;
    assert_eq!(gl["items"].as_array().unwrap().len(), 1);
    assert_eq!(gl["items"][0]["members"], json!([w.id]));
    assert_eq!(gl["items"][0]["defaults"], g["defaults"]);
}

fn skill_tar(text: &str) -> Vec<u8> {
    let mut tar = tar::Builder::new(Vec::new());
    let mut h = tar::Header::new_gnu();
    h.set_size(text.len() as u64);
    h.set_mode(0o644);
    h.set_cksum();
    tar.append_data(&mut h, "SKILL.md", text.as_bytes())
        .unwrap();
    let raw = tar.into_inner().unwrap();
    let mut gz = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::fast());
    std::io::Write::write_all(&mut gz, &raw).unwrap();
    gz.finish().unwrap()
}

async fn put_skill(t: &T, name: &str, text: &str) -> Value {
    let r = t
        .http
        .put(format!("{}/admin/api/shared/skills/{name}", t.admin))
        .header("X-Orch-Admin", ADMIN)
        .body(skill_tar(text))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 200);
    r.json().await.unwrap()
}

#[tokio::test]
async fn a_new_version_of_a_revoked_tool_is_not_given_back() {
    let t = start().await;
    let g = group(&t, json!({"name": "Work"})).await;
    let (a, _) = add_in(&t, "Finance", json!({"group": g["id"]})).await;
    put_skill(&t, "sql", "---\nname: sql\n---\nv1\n").await;
    put_mcp(&t, "files").await;
    put_cred(&t, "BANK").await;
    let s = snap(&t, &a).await;
    assert_eq!(s["skills"][0]["name"], "sql");
    // the admin takes all three away from this workspace
    let (st, _) = t
        .admin_json(
            "PUT",
            &format!("/admin/api/shared/assign/{}", a.id),
            Some(json!({})),
        )
        .await;
    assert_eq!(st, 200);
    // new versions of each come out: the group default does not give them back
    assert_eq!(
        put_skill(&t, "sql", "---\nname: sql\n---\nv2\n").await["version"],
        2
    );
    put_mcp(&t, "files").await;
    put_cred(&t, "BANK").await;
    let s = snap(&t, &a).await;
    assert!(s["skills"].as_array().unwrap().is_empty(), "{s}");
    assert!(s["mcp"].as_object().unwrap().is_empty(), "{s}");
    assert!(creds(&s).is_empty());
    // a brand new tool still comes through the group default
    put_cred(&t, "ROUTER").await;
    assert_eq!(creds(&snap(&t, &a).await), ["ROUTER"]);
}
