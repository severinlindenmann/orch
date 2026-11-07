//! Workspace look (contracts/look.md): icon and colour from fixed allowlists, nothing else.
use crate::error::{conflict, invalid, Res};
use rusqlite::{params, Connection};
use serde_json::{json, Value};
use std::collections::HashSet;
use std::sync::OnceLock;

const LOOK_JSON: &str = include_str!("../../contracts/look.json");

struct Lists {
    icons: HashSet<String>,
    colors: HashSet<String>,
}

fn lists() -> &'static Lists {
    static L: OnceLock<Lists> = OnceLock::new();
    L.get_or_init(|| {
        let v: Value = serde_json::from_str(LOOK_JSON).expect("look.json");
        let ids = |k: &str| -> HashSet<String> {
            v[k].as_array()
                .unwrap()
                .iter()
                .map(|i| i["id"].as_str().unwrap().to_string())
                .collect()
        };
        Lists {
            icons: ids("icons"),
            colors: ids("colors"),
        }
    })
}

/// A checked look change: `None` = left out (unchanged), `Some(None)` = back to the default.
#[derive(Debug, Default)]
pub struct Patch {
    pub icon: Option<Option<String>>,
    pub color: Option<Option<String>>,
}

impl Patch {
    pub fn is_empty(&self) -> bool {
        self.icon.is_none() && self.color.is_none()
    }
}

fn field(v: &Value, key: &str, ok: impl Fn(&str) -> bool) -> Res<Option<Option<String>>> {
    match v.get(key) {
        None => Ok(None),
        Some(Value::Null) => Ok(Some(None)),
        Some(Value::String(s)) if ok(s) => Ok(Some(Some(s.clone()))),
        Some(_) => Err(invalid(format!(
            "`{key}` is not one of the allowed values."
        ))),
    }
}

/// Check `icon` and `color` of a body. Both are checked before anything is stored.
pub fn parse(v: &Value) -> Res<Patch> {
    Ok(Patch {
        icon: field(v, "icon", |s| lists().icons.contains(s))?,
        color: field(v, "color", |s| lists().colors.contains(s))?,
    })
}

/// True when the body carries a look field.
pub fn is_look_body(v: &Value) -> bool {
    v.get("icon").is_some() || v.get("color").is_some()
}

/// `PATCH /v1/me` with look fields: only icon and color, nothing else in the body. Returns the checked patch.
pub fn parse_me(v: &Value) -> Res<Patch> {
    let o = v
        .as_object()
        .ok_or_else(|| invalid("Send a JSON object."))?;
    if o.keys().any(|k| k != "icon" && k != "color") {
        return Err(invalid(
            "Send the icon and colour on their own, not with other fields.",
        ));
    }
    parse(v)
}

/// Apply a checked patch. `by` = `workspace` or `admin`.
pub fn apply(c: &Connection, table: &str, id: &str, p: &Patch, by: &str) -> rusqlite::Result<()> {
    if let Some(i) = &p.icon {
        c.execute(
            &format!("UPDATE {table} SET icon=?2 WHERE id=?1"),
            params![id, i],
        )?;
    }
    if let Some(col) = &p.color {
        c.execute(
            &format!("UPDATE {table} SET color=?2 WHERE id=?1"),
            params![id, col],
        )?;
    }
    if !p.is_empty() {
        c.execute(
            &format!("UPDATE {table} SET look_by=?2 WHERE id=?1"),
            params![id, by],
        )?;
    }
    Ok(())
}

/// On create: `look_by = admin` only when an actual icon or colour is given (null = no look).
pub fn apply_new(c: &Connection, id: &str, p: &Patch) -> rusqlite::Result<()> {
    let set = matches!(p.icon, Some(Some(_))) || matches!(p.color, Some(Some(_)));
    apply(c, "workspaces", id, p, if set { "admin" } else { "" })?;
    if !set {
        c.execute("UPDATE workspaces SET look_by=NULL WHERE id=?1", [id])?;
    }
    Ok(())
}

/// The admin may only change the look while the workspace has not chosen its own.
pub fn admin_allowed(c: &Connection, id: &str) -> Res<()> {
    let by: Option<String> = c
        .query_row("SELECT look_by FROM workspaces WHERE id=?1", [id], |r| {
            r.get(0)
        })
        .unwrap_or(None);
    if by.as_deref() == Some("workspace") {
        return Err(conflict("This workspace chooses its own icon."));
    }
    Ok(())
}

/// Add `icon`, `color` (and `look_by` when asked) of workspace `id` to a card.
pub fn add_to(c: &Connection, card: &mut Value, with_by: bool) {
    let id = card["id"].as_str().unwrap_or("").to_string();
    let (i, col, by): (Option<String>, Option<String>, Option<String>) = c
        .query_row(
            "SELECT icon,color,look_by FROM workspaces WHERE id=?1",
            [&id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .unwrap_or((None, None, None));
    card["icon"] = json!(i);
    card["color"] = json!(col);
    if with_by {
        card["look_by"] = json!(by);
    }
}
