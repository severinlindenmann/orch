//! Workspace look (contracts/look.md): icon and colour from fixed allowlists, plus the shared-pages switch.
use crate::err::{ApiError, ApiResult};
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

/// A checked change: `None` = left out (unchanged), `Some(None)` = back to the default.
#[derive(Debug, Default)]
pub struct Patch {
    pub icon: Option<Option<String>>,
    pub color: Option<Option<String>>,
    pub shared: Option<bool>,
}

impl Patch {
    pub fn has_look(&self) -> bool {
        self.icon.is_some() || self.color.is_some()
    }
    pub fn is_empty(&self) -> bool {
        !self.has_look() && self.shared.is_none()
    }
}

fn field(v: &Value, key: &str, ok: impl Fn(&str) -> bool) -> ApiResult<Option<Option<String>>> {
    match v.get(key) {
        None => Ok(None),
        Some(Value::Null) => Ok(Some(None)),
        Some(Value::String(s)) if ok(s) => Ok(Some(Some(s.clone()))),
        Some(_) => Err(ApiError::invalid(format!(
            "`{key}` is not one of the allowed values."
        ))),
    }
}

/// `icon` and `color` of a body (admin create / patch).
pub fn parse(v: &Value) -> ApiResult<Patch> {
    Ok(Patch {
        icon: field(v, "icon", |s| lists().icons.contains(s))?,
        color: field(v, "color", |s| lists().colors.contains(s))?,
        shared: None,
    })
}

/// True when the body carries a look field or the shared-pages switch.
pub fn is_look_body(v: &Value) -> bool {
    ["icon", "color", "show_on_shared_pages"]
        .iter()
        .any(|k| v.get(*k).is_some())
}

/// `PATCH /v1/me` look body: only these three fields, nothing else.
pub fn parse_me(v: &Value) -> ApiResult<Patch> {
    let o = v
        .as_object()
        .ok_or_else(|| ApiError::invalid("Send a JSON object."))?;
    if o
        .keys()
        .any(|k| !matches!(k.as_str(), "icon" | "color" | "show_on_shared_pages"))
    {
        return Err(ApiError::invalid(
            "Send the icon, colour and shared-pages switch on their own, not with other fields.",
        ));
    }
    let mut p = parse(v)?;
    p.shared = match v.get("show_on_shared_pages") {
        None => None,
        Some(Value::Bool(b)) => Some(*b),
        Some(_) => {
            return Err(ApiError::invalid(
                "`show_on_shared_pages` must be true or false.",
            ))
        }
    };
    Ok(p)
}

/// Apply a checked patch. `by` = `workspace` or `admin` (only used when icon/color change).
pub fn apply(c: &Connection, id: &str, p: &Patch, by: &str) -> rusqlite::Result<()> {
    if let Some(i) = &p.icon {
        c.execute("UPDATE workspaces SET icon=?2 WHERE id=?1", params![id, i])?;
    }
    if let Some(col) = &p.color {
        c.execute(
            "UPDATE workspaces SET color=?2 WHERE id=?1",
            params![id, col],
        )?;
    }
    if p.has_look() {
        c.execute(
            "UPDATE workspaces SET look_by=?2 WHERE id=?1",
            params![id, by],
        )?;
    }
    if let Some(s) = p.shared {
        c.execute(
            "UPDATE workspaces SET show_on_shared_pages=?2 WHERE id=?1",
            params![id, s as i64],
        )?;
    }
    Ok(())
}

/// The admin may only change icon/colour while the workspace has not chosen its own.
pub fn admin_allowed(look_by: &Option<String>) -> ApiResult<()> {
    if look_by.as_deref() == Some("workspace") {
        return Err(ApiError::conflict("This workspace chooses its own icon."));
    }
    Ok(())
}

/// Look fields of a workspace for whoami and the admin lists.
pub fn json(w: &crate::db::Workspace) -> Value {
    json!({"icon": w.icon, "color": w.color, "look_by": w.look_by, "show_on_shared_pages": w.show_on_shared_pages})
}
