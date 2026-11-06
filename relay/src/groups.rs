//! Workspace groups (relay-api.md "Groups"): one group per workspace. A group gives its members the shared tools
//! of the kinds in its defaults (through the normal `assign` rows) and, with `talk`, lets members send each other
//! messages and files both ways. Leaving a group keeps the tools a workspace already has.
use crate::error::*;
use crate::shared;
use crate::store;
use crate::util::*;
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};

pub const COLOURS: [&str; 5] = ["teal", "violet", "amber", "blue", "pink"];

pub fn init(c: &Connection) -> rusqlite::Result<()> {
    c.execute_batch(
        "CREATE TABLE IF NOT EXISTS groups(id TEXT PRIMARY KEY, name TEXT NOT NULL, colour TEXT NOT NULL,
            skills INTEGER NOT NULL, mcp INTEGER NOT NULL, credentials INTEGER NOT NULL, talk INTEGER NOT NULL,
            created_at INTEGER NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS groups_name ON groups(name COLLATE NOCASE);
        CREATE TABLE IF NOT EXISTS ws_group(ws TEXT PRIMARY KEY, grp TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS ws_group_grp ON ws_group(grp);",
    )
}

/// SQL: the other members of `?1`'s group when that group has `talk` on.
pub const TALK_PEERS_SQL: &str =
    "SELECT b.ws FROM ws_group a JOIN ws_group b ON a.grp=b.grp AND b.ws<>a.ws
    JOIN groups g ON g.id=a.grp AND g.talk=1 WHERE a.ws=?1";

pub fn group_of(c: &Connection, ws: &str) -> Option<String> {
    c.query_row("SELECT grp FROM ws_group WHERE ws=?1", [ws], |r| r.get(0))
        .optional()
        .ok()
        .flatten()
}

pub fn exists(c: &Connection, id: &str) -> bool {
    c.query_row("SELECT 1 FROM groups WHERE id=?1", [id], |_| Ok(()))
        .optional()
        .ok()
        .flatten()
        .is_some()
}

/// True when `a` and `b` are different members of one group with `talk` on.
pub fn may_talk(c: &Connection, a: &str, b: &str) -> bool {
    a != b && talk_peers(c, a).iter().any(|w| w == b)
}

pub fn talk_peers(c: &Connection, ws: &str) -> Vec<String> {
    c.prepare(TALK_PEERS_SQL)
        .and_then(|mut s| s.query_map([ws], |r| r.get(0))?.collect())
        .unwrap_or_default()
}

pub fn members(c: &Connection, grp: &str) -> rusqlite::Result<Vec<String>> {
    c.prepare(
        "SELECT g.ws FROM ws_group g JOIN workspaces w ON w.id=g.ws WHERE g.grp=?1 ORDER BY w.name",
    )?
    .query_map([grp], |r| r.get(0))?
    .collect()
}

/// The kinds a group gives its members (`shared::KINDS` order).
fn default_kinds(c: &Connection, grp: &str) -> rusqlite::Result<Vec<&'static str>> {
    let f: [bool; 3] = c.query_row(
        "SELECT skills,mcp,credentials FROM groups WHERE id=?1",
        [grp],
        |r| Ok([r.get(0)?, r.get(1)?, r.get(2)?]),
    )?;
    Ok(shared::KINDS
        .iter()
        .zip(f)
        .filter(|(_, on)| *on)
        .map(|(k, _)| *k)
        .collect())
}

/// Give `ws` every shared item of the `kinds` (adds `assign` rows, removes nothing).
fn grant(c: &Connection, ws: &str, kinds: &[&str]) -> rusqlite::Result<()> {
    for kind in kinds {
        c.execute(
            &format!(
                "INSERT OR IGNORE INTO assign(ws,kind,name) SELECT ?1,?2,name FROM {}",
                shared::table(kind)
            ),
            params![ws, kind],
        )?;
    }
    Ok(())
}

/// How many shared items of each kind the group gives: `{skills, mcp, credentials}` (0 for kinds it does not give).
pub fn gives(c: &Connection, grp: &str) -> rusqlite::Result<Value> {
    let kinds = default_kinds(c, grp)?;
    let mut out = json!({});
    for kind in shared::KINDS {
        let n: i64 = if kinds.contains(&kind) {
            c.query_row(
                &format!("SELECT COUNT(*) FROM {}", shared::table(kind)),
                [],
                |r| r.get(0),
            )?
        } else {
            0
        };
        out[kind] = n.into();
    }
    Ok(out)
}

/// Put `ws` into `grp` (replacing its old group) and give it the group's tools.
/// Returns the workspaces whose view changed (ws, old and new talk peers).
pub fn join(c: &Connection, ws: &str, grp: &str) -> rusqlite::Result<Vec<String>> {
    let mut affected = talk_peers(c, ws);
    c.execute(
        "INSERT INTO ws_group(ws,grp) VALUES(?1,?2) ON CONFLICT(ws) DO UPDATE SET grp=?2",
        params![ws, grp],
    )?;
    grant(c, ws, &default_kinds(c, grp)?)?;
    affected.extend(talk_peers(c, ws));
    affected.push(ws.to_string());
    Ok(affected)
}

/// A new shared item: give it to every member of a group whose defaults include `kind`. Returns those members.
pub fn grant_new_item(c: &Connection, kind: &str, name: &str) -> rusqlite::Result<Vec<String>> {
    let col = match kind {
        "skills" => "skills",
        "mcp" => "mcp",
        _ => "credentials",
    };
    let ws: Vec<String> = c
        .prepare(&format!(
            "SELECT g.ws FROM ws_group g JOIN groups gr ON gr.id=g.grp WHERE gr.{col}=1"
        ))?
        .query_map([], |r| r.get(0))?
        .collect::<Result<_, _>>()?;
    for w in &ws {
        c.execute(
            "INSERT OR IGNORE INTO assign(ws,kind,name) VALUES(?1,?2,?3)",
            params![w, kind, name],
        )?;
    }
    Ok(ws)
}

fn card(c: &Connection, id: &str) -> rusqlite::Result<Value> {
    let mut v = c.query_row(
        "SELECT id,name,colour,skills,mcp,credentials,talk FROM groups WHERE id=?1",
        [id],
        |r| {
            Ok(json!({"id": r.get::<_, String>(0)?, "name": r.get::<_, String>(1)?, "colour": r.get::<_, String>(2)?,
                "defaults": {"skills": r.get::<_, bool>(3)?, "mcp": r.get::<_, bool>(4)?, "credentials": r.get::<_, bool>(5)?},
                "talk": r.get::<_, bool>(6)?}))
        },
    )?;
    v["members"] = json!(members(c, id)?);
    v["gives"] = gives(c, id)?;
    Ok(v)
}

pub fn list(c: &Connection) -> rusqlite::Result<Value> {
    let ids: Vec<String> = c
        .prepare("SELECT id FROM groups ORDER BY name COLLATE NOCASE")?
        .query_map([], |r| r.get(0))?
        .collect::<Result<_, _>>()?;
    let items: Vec<Value> = ids.iter().map(|i| card(c, i)).collect::<Result<_, _>>()?;
    Ok(json!({"items": items}))
}

fn valid_name(c: &Connection, v: &Value, except: Option<&str>) -> Res<String> {
    let n = store::valid_description(v.as_str().unwrap_or("")).map_err(invalid)?;
    if n.is_empty() || n.chars().count() > 40 {
        return Err(invalid("Give the group a name (up to 40 characters)."));
    }
    let clash: Option<String> = c
        .query_row(
            "SELECT id FROM groups WHERE name=?1 COLLATE NOCASE",
            [&n],
            |r| r.get(0),
        )
        .optional()?;
    if clash.is_some_and(|id| Some(id.as_str()) != except) {
        return Err(conflict("A group with this name already exists."));
    }
    Ok(n)
}

fn valid_colour(v: &Value) -> Res<String> {
    match v.as_str() {
        Some(s) if COLOURS.contains(&s) => Ok(s.to_string()),
        _ => Err(invalid(format!(
            "`colour` is one of {}.",
            COLOURS.join(", ")
        ))),
    }
}

/// The colour used least so far (first in `COLOURS` order on a tie).
fn next_colour(c: &Connection) -> rusqlite::Result<String> {
    let mut best = (i64::MAX, COLOURS[0]);
    for col in COLOURS {
        let n: i64 = c.query_row("SELECT COUNT(*) FROM groups WHERE colour=?1", [col], |r| {
            r.get(0)
        })?;
        if n < best.0 {
            best = (n, col);
        }
    }
    Ok(best.1.to_string())
}

fn flag(v: &Value, k: &str) -> Res<Option<bool>> {
    match v.get(k) {
        None => Ok(None),
        Some(Value::Bool(b)) => Ok(Some(*b)),
        _ => Err(invalid(format!("`{k}` must be true or false."))),
    }
}

/// `POST /admin/api/groups`. Defaults: every kind on, `talk` on. Returns the new group's card.
pub fn create(c: &Connection, v: &Value) -> Res<Value> {
    let name = valid_name(c, &v["name"], None)?;
    let colour = match v.get("colour") {
        Some(x) if !x.is_null() => valid_colour(x)?,
        _ => next_colour(c)?,
    };
    let d = v.get("defaults").cloned().unwrap_or(json!({}));
    let k = |kind| flag(&d, kind).map(|b| b.unwrap_or(true));
    let (s, m, cr) = (k("skills")?, k("mcp")?, k("credentials")?);
    let talk = flag(v, "talk")?.unwrap_or(true);
    let id = rand_id("grp_", 10);
    c.execute(
        "INSERT INTO groups(id,name,colour,skills,mcp,credentials,talk,created_at) VALUES(?1,?2,?3,?4,?5,?6,?7,?8)",
        params![id, name, colour, s, m, cr, talk, now()],
    )?;
    Ok(card(c, &id)?)
}

/// `PATCH /admin/api/groups/<id>`. A default kind turned on is given to the current members at once; turning one
/// off takes nothing away. Returns (card, workspaces to hint).
pub fn edit(c: &Connection, id: &str, v: &Value) -> Res<(Value, Vec<String>)> {
    if !exists(c, id) {
        return Err(not_found("No such group."));
    }
    if v.get("name").is_some() {
        let n = valid_name(c, &v["name"], Some(id))?;
        c.execute("UPDATE groups SET name=?2 WHERE id=?1", params![id, n])?;
    }
    if let Some(x) = v.get("colour") {
        c.execute(
            "UPDATE groups SET colour=?2 WHERE id=?1",
            params![id, valid_colour(x)?],
        )?;
    }
    let mut affected = vec![];
    let members = members(c, id)?;
    if let Some(d) = v.get("defaults") {
        let mut turned_on = vec![];
        let before = default_kinds(c, id)?;
        for kind in shared::KINDS {
            if let Some(on) = flag(d, kind)? {
                c.execute(
                    &format!("UPDATE groups SET {kind}=?2 WHERE id=?1"),
                    params![id, on],
                )?;
                if on && !before.contains(&kind) {
                    turned_on.push(kind);
                }
            }
        }
        if !turned_on.is_empty() {
            for w in &members {
                grant(c, w, &turned_on)?;
            }
            affected.extend(members.iter().cloned());
        }
    }
    if let Some(t) = flag(v, "talk")? {
        let old: bool = c.query_row("SELECT talk FROM groups WHERE id=?1", [id], |r| r.get(0))?;
        if old != t {
            c.execute("UPDATE groups SET talk=?2 WHERE id=?1", params![id, t])?;
            affected.extend(members.iter().cloned());
        }
    }
    Ok((card(c, id)?, affected))
}

/// `DELETE /admin/api/groups/<id>`: members stay and keep their tools; they are just in no group.
pub fn delete(c: &Connection, id: &str) -> Res<Vec<String>> {
    if !exists(c, id) {
        return Err(not_found("No such group."));
    }
    let talk: bool = c.query_row("SELECT talk FROM groups WHERE id=?1", [id], |r| r.get(0))?;
    let members = members(c, id)?;
    c.execute("DELETE FROM ws_group WHERE grp=?1", [id])?;
    c.execute("DELETE FROM groups WHERE id=?1", [id])?;
    Ok(if talk { members } else { vec![] })
}
