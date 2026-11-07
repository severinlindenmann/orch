//! Mobile mode (contracts/relay-api.md, "Mobile mode"): the workspace's heartbeat carries the flag; the relay stores it,
//! shows it to phones and pushes `mobile_mode_unreachable`, `mobile_mode_back` and `mobile_mode_ended`.
//! The phone's "turn off" request is `POST /v1/phone/control` (phone.rs).
use crate::api::parse_body;
use crate::auth;
use crate::error::*;
use crate::state::AppState;
use crate::store;
use crate::util::now;
use axum::body::Bytes;
use axum::extract::State;
use axum::http::HeaderMap;
use axum::Json;
use rusqlite::Connection;
use serde_json::{json, Value};
use std::time::Duration;

/// The relay has not heard from a workspace in Mobile mode for this long: tell the phones once.
pub const UNREACHABLE_SECS: i64 = 300;

/// `POST /v1/heartbeat`: `{mobile_mode: {on, since, ends_at, machine, ended?}}` (phone-api.schema.json `heartbeat_request`).
pub async fn heartbeat(State(app): State<AppState>, h: HeaderMap, body: Bytes) -> Res<Json<Value>> {
    let v = parse_body(&body)?;
    crate::phone::check("heartbeat_request", &v)?;
    let m = &v["mobile_mode"];
    let on = m["on"].as_bool().unwrap_or(false);
    let machine = m["machine"].as_str();
    if let Some(name) = machine {
        // one line of plain text (the description character rule)
        match store::valid_description(name) {
            Ok(n) if n == name && !name.contains(['\n', '\r']) => {}
            _ => return Err(invalid("`machine` must be one line of plain text.")),
        }
    }
    let (stored, push) = {
        let c = app.db.lock().unwrap();
        let ws = auth::workspace(&c, &h)?;
        let (was_on, unreach, old_machine): (i64, i64, Option<String>) = c.query_row(
            "SELECT mm_on,mm_unreach,mm_machine FROM workspaces WHERE id=?1",
            [&ws],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )?;
        c.execute(
            "UPDATE workspaces SET mm_on=?2, mm_since=?3, mm_ends_at=?4, mm_machine=?5, mm_unreach=0 WHERE id=?1",
            rusqlite::params![
                ws,
                on as i64,
                if on { m["since"].as_str() } else { None },
                if on { m["ends_at"].as_str() } else { None },
                if on { machine } else { None },
            ],
        )?;
        let push = match (was_on != 0, on) {
            (true, false) => Some((
                "mobile_mode_ended",
                old_machine,
                m["ended"].as_str().map(String::from),
            )),
            (true, true) if unreach != 0 => {
                Some(("mobile_mode_back", machine.map(String::from), None))
            }
            _ => None,
        };
        (
            store::mobile_mode(&c, &ws),
            push.map(|(k, mach, ended)| (ws, k, mach, ended)),
        )
    };
    if let Some((ws, kind, machine, ended)) = push {
        notify(&app, &ws, kind, machine.as_deref(), ended.as_deref()).await;
    }
    Ok(Json(json!({"mobile_mode": stored})))
}

/// Text of a Mobile mode push (relay-api.md table; `vectors/mobile-mode-v1.json` `pushes`).
pub fn push_text(kind: &str, machine: &str, ended: Option<&str>) -> String {
    match (kind, ended) {
        ("mobile_mode_unreachable", _) => {
            format!("Can't reach {machine}. Your answers wait until it is back.")
        }
        ("mobile_mode_back", _) => format!("{machine} is back."),
        (_, Some("lease")) => "Mobile mode ended: the time ran out.".into(),
        (_, Some("restart")) => "Mobile mode ended: the computer restarted.".into(),
        _ => "Mobile mode was turned off.".into(),
    }
}

/// Push to every signed-in phone that has `ws` on its list and has not muted it.
pub async fn notify(
    app: &AppState,
    ws: &str,
    kind: &str,
    machine: Option<&str>,
    ended: Option<&str>,
) {
    let (targets, name) = {
        let c = app.db.lock().unwrap();
        (targets(&c, ws), store::ws_name(&c, ws).unwrap_or_default())
    };
    if targets.is_empty() {
        return;
    }
    let machine = machine.unwrap_or(&name);
    let payload = json!({"aps": {"alert": {"title": name, "body": push_text(kind, machine, ended)}, "sound": "default"},
        "workspace": ws, "type": "mobile_mode", "kind": kind});
    crate::phone::send_pushes(app, targets, &payload).await;
}

fn targets(c: &Connection, ws: &str) -> Vec<(bool, String)> {
    let Ok(mut st) = c.prepare(
        "SELECT sandbox,apns_token,workspaces,id FROM phones WHERE apns_token IS NOT NULL AND token_hash IS NOT NULL",
    ) else {
        return vec![];
    };
    let rows: Vec<(bool, String, String, String)> = st
        .query_map([], |r| {
            Ok((r.get::<_, i64>(0)? != 0, r.get(1)?, r.get(2)?, r.get(3)?))
        })
        .map(|r| r.flatten().collect())
        .unwrap_or_default();
    rows.into_iter()
        // only phones paired with the workspace, and not muted for it
        .filter(|(_, _, list, id)| {
            store::parse_ws_list(list).iter().any(|w| w == ws) && !store::is_muted(c, id, ws)
        })
        .map(|(s, t, ..)| (s, t))
        .collect()
}

/// Workspaces in Mobile mode that were not heard from for 5 minutes and were not announced yet: push once.
pub async fn sweep(app: &AppState, at: i64) {
    let due: Vec<(String, Option<String>)> = {
        let c = app.db.lock().unwrap();
        let Ok(mut st) = c.prepare(
            "SELECT id,mm_machine FROM workspaces WHERE mm_on=1 AND mm_unreach=0 AND COALESCE(last_seen,0)<?1",
        ) else {
            return;
        };
        let rows: Vec<(String, Option<String>)> = st
            .query_map([at - UNREACHABLE_SECS], |r| Ok((r.get(0)?, r.get(1)?)))
            .map(|r| r.flatten().collect())
            .unwrap_or_default();
        for (id, _) in &rows {
            let _ = c.execute("UPDATE workspaces SET mm_unreach=1 WHERE id=?1", [id]);
        }
        rows
    };
    for (ws, machine) in due {
        notify(
            app,
            &ws,
            "mobile_mode_unreachable",
            machine.as_deref(),
            None,
        )
        .await;
    }
}

/// Look for silent workspaces every 60 s.
pub fn spawn(app: AppState) {
    tokio::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_secs(60)).await;
            sweep(&app, now()).await;
        }
    });
}
