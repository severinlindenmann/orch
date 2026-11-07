use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use rusqlite::{params, Connection, OptionalExtension, Row};
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Clone, Debug, Default, PartialEq)]
pub struct Rights {
    #[serde(default)]
    pub files: bool,
    #[serde(default)]
    pub apps: bool,
    #[serde(default)]
    pub permanent: bool,
    #[serde(default)]
    pub public: bool,
}

#[derive(Clone, Debug)]
pub struct Workspace {
    pub id: String,
    pub name: String,
    pub description: String,
    pub tags: Vec<String>,
    pub rights: Rights,
    pub token_hash: String,
    /// Who wrote the live description / tags: "admin" or "workspace" (owner-approved).
    pub description_by: String,
    pub tags_by: String,
    /// The change the workspace proposed for itself, waiting for the owner.
    pub pending: Option<Pending>,
    /// Workspace look (contracts/look.md): `None` = letter / Automatic colour; `look_by` = admin | workspace | None.
    pub icon: Option<String>,
    pub color: Option<String>,
    pub look_by: Option<String>,
    /// Shared file pages show the workspace name and icon (default on).
    pub show_on_shared_pages: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Pending {
    pub description: Option<String>,
    pub tags: Option<Vec<String>>,
    pub at: String,
    pub rev: String,
}

impl Pending {
    pub fn json(p: &Option<Pending>) -> serde_json::Value {
        match p {
            Some(p) => {
                serde_json::json!({"description": p.description, "tags": p.tags, "at": p.at, "rev": p.rev})
            }
            None => serde_json::Value::Null,
        }
    }
}

#[derive(Clone, Debug)]
pub struct FileRow {
    pub id: String,
    pub workspace: String,
    pub size: i64,
    pub created_at: String,
    pub expires_at: Option<String>,
}

#[derive(Clone, Debug)]
pub struct AppRow {
    pub name: String,
    pub workspace: String,
    pub about: String,
    pub stack: String,
    pub store: String,
    pub public: bool,
    pub health: String,
    pub status: String, // running | stopped
    pub port: u16,
    pub code_dir: String,
    pub view_token_hash: Option<String>,
    pub expires_at: Option<String>,
    pub updated_at: String,
}

pub fn open(path: &std::path::Path) -> rusqlite::Result<Connection> {
    let c = Connection::open(path)?;
    c.execute_batch(
        "PRAGMA journal_mode=WAL;
         CREATE TABLE IF NOT EXISTS workspaces(
            id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '[]', rights TEXT NOT NULL, token_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            description_by TEXT NOT NULL DEFAULT 'workspace', tags_by TEXT NOT NULL DEFAULT 'workspace',
            pending_description TEXT, pending_tags TEXT, pending_at TEXT, pending_rev TEXT);
         CREATE TABLE IF NOT EXISTS files(
            id TEXT PRIMARY KEY, workspace TEXT NOT NULL, size INTEGER NOT NULL,
            created_at TEXT NOT NULL, expires_at TEXT);
         CREATE TABLE IF NOT EXISTS apps(
            name TEXT PRIMARY KEY, workspace TEXT NOT NULL, about TEXT NOT NULL DEFAULT '',
            stack TEXT NOT NULL, store TEXT NOT NULL, public INTEGER NOT NULL,
            health TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, port INTEGER NOT NULL DEFAULT 0,
            code_dir TEXT NOT NULL, view_token_hash TEXT, expires_at TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);",
    )?;
    // Older databases: add the profile columns (ignore "duplicate column"). Existing rows count as written by the workspace.
    for col in [
        "description_by TEXT NOT NULL DEFAULT 'workspace'",
        "tags_by TEXT NOT NULL DEFAULT 'workspace'",
        "pending_description TEXT",
        "pending_tags TEXT",
        "pending_at TEXT",
        "pending_rev TEXT",
        "icon TEXT",
        "color TEXT",
        "look_by TEXT",
        "show_on_shared_pages INTEGER NOT NULL DEFAULT 1",
    ] {
        let _ = c.execute(&format!("ALTER TABLE workspaces ADD COLUMN {col}"), []);
    }
    Ok(c)
}

fn ws_from(r: &Row) -> rusqlite::Result<Workspace> {
    let tags: String = r.get(3)?;
    let rights: String = r.get(4)?;
    Ok(Workspace {
        id: r.get(0)?,
        name: r.get(1)?,
        description: r.get(2)?,
        tags: serde_json::from_str(&tags).unwrap_or_default(),
        rights: serde_json::from_str(&rights).unwrap_or_default(),
        token_hash: r.get(5)?,
        description_by: r.get(6)?,
        tags_by: r.get(7)?,
        pending: match r.get::<_, Option<String>>(10)? {
            Some(at) => Some(Pending {
                description: r.get(8)?,
                tags: r
                    .get::<_, Option<String>>(9)?
                    .map(|t| serde_json::from_str(&t).unwrap_or_default()),
                at,
                rev: r.get::<_, Option<String>>(11)?.unwrap_or_default(),
            }),
            None => None,
        },
        icon: r.get(12)?,
        color: r.get(13)?,
        look_by: r.get(14)?,
        show_on_shared_pages: r.get::<_, i64>(15)? != 0,
    })
}
const WS_COLS: &str = "id,name,description,tags,rights,token_hash,description_by,tags_by,pending_description,pending_tags,pending_at,pending_rev,icon,color,look_by,show_on_shared_pages";

pub fn get_workspace(c: &Connection, id: &str) -> rusqlite::Result<Option<Workspace>> {
    c.query_row(
        &format!("SELECT {WS_COLS} FROM workspaces WHERE id=?1"),
        [id],
        ws_from,
    )
    .optional()
}

pub fn insert_workspace(c: &Connection, w: &Workspace, now: &str) -> rusqlite::Result<()> {
    c.execute(
        "INSERT INTO workspaces(id,name,description,tags,rights,token_hash,created_at,description_by,tags_by,icon,color,look_by) VALUES(?1,?2,?3,?4,?5,?6,?7,'admin','admin',?8,?9,?10)",
        params![
            w.id,
            w.name,
            w.description,
            serde_json::to_string(&w.tags).unwrap(),
            serde_json::to_string(&w.rights).unwrap(),
            w.token_hash,
            now,
            w.icon,
            w.color,
            w.look_by
        ],
    )?;
    Ok(())
}

/// Rotating the token also drops a pending proposal.
pub fn clear_pending(c: &Connection, id: &str) -> rusqlite::Result<()> {
    c.execute(
        "UPDATE workspaces SET pending_description=NULL,pending_tags=NULL,pending_at=NULL,pending_rev=NULL WHERE id=?1",
        [id],
    )?;
    Ok(())
}

pub fn update_workspace(c: &Connection, w: &Workspace) -> rusqlite::Result<()> {
    c.execute(
        "UPDATE workspaces SET name=?2,description=?3,tags=?4,rights=?5,token_hash=?6,description_by=?7,tags_by=?8 WHERE id=?1",
        params![
            w.id,
            w.name,
            w.description,
            serde_json::to_string(&w.tags).unwrap(),
            serde_json::to_string(&w.rights).unwrap(),
            w.token_hash,
            w.description_by,
            w.tags_by
        ],
    )?;
    Ok(())
}

/// Store a proposed description/tags (replacing an earlier proposal), only while the token is still the one
/// that authenticated. Returns rows changed. Nothing live changes until the owner approves.
pub fn set_pending(
    c: &Connection,
    id: &str,
    token_hash: &str,
    description: Option<&str>,
    tags: Option<&[String]>,
    at: &str,
    rev: &str,
) -> rusqlite::Result<usize> {
    c.execute(
        "UPDATE workspaces SET pending_description=?3,pending_tags=?4,pending_at=?5,pending_rev=?6 WHERE id=?1 AND token_hash=?2",
        params![
            id,
            token_hash,
            description,
            tags.map(|t| serde_json::to_string(t).unwrap()),
            at,
            rev
        ],
    )
}

/// Pending becomes live (marked "workspace"). Returns rows changed (0 = nothing pending).
pub fn approve_pending(c: &Connection, id: &str, rev: &str) -> rusqlite::Result<usize> {
    c.execute(
        "UPDATE workspaces SET
           description_by=CASE WHEN pending_description IS NULL THEN description_by ELSE 'workspace' END,
           tags_by=CASE WHEN pending_tags IS NULL THEN tags_by ELSE 'workspace' END,
           description=COALESCE(pending_description,description), tags=COALESCE(pending_tags,tags),
           pending_description=NULL, pending_tags=NULL, pending_at=NULL, pending_rev=NULL
         WHERE id=?1 AND pending_rev=?2",
        [id, rev],
    )
}

pub fn reject_pending(c: &Connection, id: &str, rev: &str) -> rusqlite::Result<usize> {
    c.execute(
        "UPDATE workspaces SET pending_description=NULL,pending_tags=NULL,pending_at=NULL,pending_rev=NULL WHERE id=?1 AND pending_rev=?2",
        [id, rev],
    )
}

pub fn delete_workspace(c: &Connection, id: &str) -> rusqlite::Result<()> {
    c.execute("DELETE FROM workspaces WHERE id=?1", [id])?;
    Ok(())
}

/// (workspace, file count, app count) rows plus the next cursor
pub type WsRows = (Vec<(Workspace, i64, i64)>, Option<String>);

pub fn list_workspaces(
    c: &Connection,
    limit: usize,
    after: Option<i64>,
) -> rusqlite::Result<WsRows> {
    let mut st = c.prepare(&format!(
        "SELECT {WS_COLS},rowid,
           (SELECT COUNT(*) FROM files f WHERE f.workspace=workspaces.id),
           (SELECT COUNT(*) FROM apps a WHERE a.workspace=workspaces.id)
         FROM workspaces WHERE rowid<?1 ORDER BY rowid DESC LIMIT ?2"
    ))?;
    let rows = st
        .query_map(params![after.unwrap_or(i64::MAX), limit + 1], |r| {
            Ok((
                ws_from(r)?,
                r.get::<_, i64>(16)?,
                r.get::<_, i64>(17)?,
                r.get::<_, i64>(18)?,
            ))
        })?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(page(rows, limit, |t| t.1).map_items(|t| (t.0, t.2, t.3)))
}

pub fn workspace_by_token_hash_exists(c: &Connection, h: &str) -> rusqlite::Result<bool> {
    c.query_row("SELECT 1 FROM workspaces WHERE token_hash=?1", [h], |_| {
        Ok(())
    })
    .optional()
    .map(|o| o.is_some())
}

// ---- files

fn file_from(r: &Row) -> rusqlite::Result<FileRow> {
    Ok(FileRow {
        id: r.get(0)?,
        workspace: r.get(1)?,
        size: r.get(2)?,
        created_at: r.get(3)?,
        expires_at: r.get(4)?,
    })
}

pub fn insert_file(c: &Connection, f: &FileRow) -> rusqlite::Result<()> {
    c.execute(
        "INSERT INTO files(id,workspace,size,created_at,expires_at) VALUES(?1,?2,?3,?4,?5)",
        params![f.id, f.workspace, f.size, f.created_at, f.expires_at],
    )?;
    Ok(())
}

pub fn get_file(c: &Connection, id: &str) -> rusqlite::Result<Option<FileRow>> {
    c.query_row(
        "SELECT id,workspace,size,created_at,expires_at FROM files WHERE id=?1",
        [id],
        file_from,
    )
    .optional()
}

pub fn update_file_expiry(c: &Connection, id: &str, expires_at: &str) -> rusqlite::Result<()> {
    c.execute(
        "UPDATE files SET expires_at=?2 WHERE id=?1",
        params![id, expires_at],
    )?;
    Ok(())
}

pub fn update_file_size(c: &Connection, id: &str, size: i64) -> rusqlite::Result<()> {
    c.execute("UPDATE files SET size=?2 WHERE id=?1", params![id, size])?;
    Ok(())
}

pub fn delete_file(c: &Connection, id: &str) -> rusqlite::Result<()> {
    c.execute("DELETE FROM files WHERE id=?1", [id])?;
    Ok(())
}

pub fn list_files(
    c: &Connection,
    workspace: Option<&str>,
    limit: usize,
    after: Option<i64>,
) -> rusqlite::Result<(Vec<FileRow>, Option<String>)> {
    let mut st = c.prepare(
        "SELECT id,workspace,size,created_at,expires_at,rowid FROM files
         WHERE rowid<?1 AND (?2 IS NULL OR workspace=?2) ORDER BY rowid DESC LIMIT ?3",
    )?;
    let rows = st
        .query_map(
            params![after.unwrap_or(i64::MAX), workspace, limit + 1],
            |r| Ok((file_from(r)?, r.get::<_, i64>(5)?)),
        )?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(page(rows, limit, |t| t.1).map_items(|t| t.0))
}

pub fn expired_files(c: &Connection, now: &str) -> rusqlite::Result<Vec<String>> {
    let mut st =
        c.prepare("SELECT id FROM files WHERE expires_at IS NOT NULL AND expires_at<=?1")?;
    let v = st
        .query_map([now], |r| r.get(0))?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(v)
}

pub fn file_ids_of(c: &Connection, ws: &str) -> rusqlite::Result<Vec<String>> {
    let mut st = c.prepare("SELECT id FROM files WHERE workspace=?1")?;
    let v = st
        .query_map([ws], |r| r.get(0))?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(v)
}

// ---- apps

const APP_COLS: &str = "name,workspace,about,stack,store,public,health,status,port,code_dir,view_token_hash,expires_at,updated_at";

fn app_from(r: &Row) -> rusqlite::Result<AppRow> {
    Ok(AppRow {
        name: r.get(0)?,
        workspace: r.get(1)?,
        about: r.get(2)?,
        stack: r.get(3)?,
        store: r.get(4)?,
        public: r.get::<_, i64>(5)? != 0,
        health: r.get(6)?,
        status: r.get(7)?,
        port: r.get::<_, i64>(8)? as u16,
        code_dir: r.get(9)?,
        view_token_hash: r.get(10)?,
        expires_at: r.get(11)?,
        updated_at: r.get(12)?,
    })
}

pub fn get_app(c: &Connection, name: &str) -> rusqlite::Result<Option<AppRow>> {
    c.query_row(
        &format!("SELECT {APP_COLS} FROM apps WHERE name=?1"),
        [name],
        app_from,
    )
    .optional()
}

/// insert or replace (keeps nothing of the old row: callers pass the full new row)
pub fn put_app(c: &Connection, a: &AppRow, now: &str) -> rusqlite::Result<()> {
    c.execute(
        &format!(
            "INSERT INTO apps({APP_COLS},created_at) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14)
             ON CONFLICT(name) DO UPDATE SET workspace=?2,about=?3,stack=?4,store=?5,public=?6,health=?7,
               status=?8,port=?9,code_dir=?10,view_token_hash=?11,expires_at=?12,updated_at=?13"
        ),
        params![
            a.name,
            a.workspace,
            a.about,
            a.stack,
            a.store,
            a.public as i64,
            a.health,
            a.status,
            a.port as i64,
            a.code_dir,
            a.view_token_hash,
            a.expires_at,
            a.updated_at,
            now
        ],
    )?;
    Ok(())
}

pub fn delete_app(c: &Connection, name: &str) -> rusqlite::Result<()> {
    c.execute("DELETE FROM apps WHERE name=?1", [name])?;
    Ok(())
}

pub fn list_apps(
    c: &Connection,
    workspace: Option<&str>,
    limit: usize,
    after: Option<i64>,
) -> rusqlite::Result<(Vec<AppRow>, Option<String>)> {
    let mut st = c.prepare(&format!(
        "SELECT {APP_COLS},rowid FROM apps
         WHERE rowid<?1 AND (?2 IS NULL OR workspace=?2) ORDER BY rowid DESC LIMIT ?3"
    ))?;
    let rows = st
        .query_map(
            params![after.unwrap_or(i64::MAX), workspace, limit + 1],
            |r| Ok((app_from(r)?, r.get::<_, i64>(13)?)),
        )?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(page(rows, limit, |t| t.1).map_items(|t| t.0))
}

pub fn all_apps(c: &Connection) -> rusqlite::Result<Vec<AppRow>> {
    Ok(list_apps(c, None, 100_000, None)?.0)
}

// ---- paging

pub struct Paged<T>(pub Vec<T>, pub Option<String>);
impl<T> Paged<T> {
    pub fn map_items<U>(self, f: impl FnMut(T) -> U) -> (Vec<U>, Option<String>) {
        (self.0.into_iter().map(f).collect(), self.1)
    }
}

/// `rows` holds up to limit+1 entries; the cursor is the rowid of the last returned one.
fn page<T>(mut rows: Vec<T>, limit: usize, rowid: impl Fn(&T) -> i64) -> Paged<T> {
    let next = if rows.len() > limit {
        rows.truncate(limit);
        rows.last()
            .map(|t| URL_SAFE_NO_PAD.encode(rowid(t).to_string()))
    } else {
        None
    };
    Paged(rows, next)
}

#[allow(clippy::result_unit_err)]
pub fn decode_cursor(after: Option<&str>) -> Result<Option<i64>, ()> {
    match after {
        None => Ok(None),
        Some(a) => URL_SAFE_NO_PAD
            .decode(a)
            .ok()
            .and_then(|b| String::from_utf8(b).ok())
            .and_then(|s| s.parse().ok())
            .map(Some)
            .ok_or(()),
    }
}
