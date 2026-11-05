use crate::error::*;
use crate::state::App;
use crate::store;
use crate::util::*;
use axum::http::HeaderMap;
use rusqlite::{Connection, OptionalExtension};

pub fn bearer(h: &HeaderMap) -> Option<&str> {
    h.get("authorization")?
        .to_str()
        .ok()?
        .strip_prefix("Bearer ")
}

fn header<'a>(h: &'a HeaderMap, k: &str) -> Option<&'a str> {
    h.get(k)?.to_str().ok()
}

/// Workspace id of an authenticated workspace call (also marks it online).
pub fn workspace(c: &Connection, h: &HeaderMap) -> Res<String> {
    let (id, tok) = (header(h, "x-orch-workspace"), bearer(h));
    let (Some(id), Some(tok)) = (id, tok) else {
        return Err(unauthorized());
    };
    let hash: Option<String> = c
        .query_row("SELECT token_hash FROM workspaces WHERE id=?1", [id], |r| {
            r.get(0)
        })
        .optional()?;
    match hash {
        Some(hh) if ct_eq(&hh, &token_hash(tok)) => {
            c.execute(
                "UPDATE workspaces SET last_seen=?2 WHERE id=?1",
                rusqlite::params![id, now()],
            )?;
            Ok(id.to_string())
        }
        _ => Err(unauthorized()),
    }
}

/// (phone id, name, workspaces it may reach) of an authenticated phone call.
pub fn phone(c: &Connection, h: &HeaderMap) -> Res<(String, String, Vec<String>)> {
    let (Some(id), Some(tok)) = (header(h, "x-orch-phone"), bearer(h)) else {
        return Err(unauthorized());
    };
    let row: Option<(Option<String>, String, String)> = c
        .query_row(
            "SELECT token_hash,name,workspaces FROM phones WHERE id=?1",
            [id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .optional()?;
    match row {
        Some((Some(hh), name, ws)) if ct_eq(&hh, &token_hash(tok)) => {
            c.execute(
                "UPDATE phones SET last_seen=?2 WHERE id=?1",
                rusqlite::params![id, now()],
            )?;
            Ok((id.to_string(), name, store::parse_ws_list(&ws)))
        }
        _ => Err(unauthorized()),
    }
}

pub fn admin(app: &App, h: &HeaderMap) -> Res<()> {
    // Only the X-Orch-Admin header (a custom header cannot be sent cross-site, so no CSRF via cookies).
    match header(h, "x-orch-admin") {
        Some(t) if ct_eq(t, &app.cfg.admin_token) => Ok(()),
        _ => Err(unauthorized()),
    }
}
