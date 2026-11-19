//! Removing what belongs only to one workspace (its messages, their files, problem reports, subscriber log lines),
//! and clearing the same history of workspaces that no longer exist (a one-time clean-up after older deletes).
//!
//! Both run in one transaction. Files on disk (blobs, cached speech) go only after the commit, so a failed
//! transaction never leaves rows that point at missing files.

use rusqlite::{params, Connection};
use serde_json::{json, Value};
use std::collections::HashSet;
use std::path::{Path, PathBuf};

/// What a removal takes away (or would, in a dry run).
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct Counts {
    pub messages: usize,
    pub files: usize,
    pub problems: usize,
    pub sub_log: usize,
    pub subscribers: usize,
}

impl Counts {
    pub fn json(&self) -> Value {
        json!({
            "messages": self.messages,
            "files": self.files,
            "problems": self.problems,
            "sub_log": self.sub_log,
            "subscribers": self.subscribers,
        })
    }
    pub fn is_empty(&self) -> bool {
        *self == Counts::default()
    }
}

/// Which history a pass looks at.
#[derive(Clone, Copy)]
pub enum Scope<'a> {
    /// Everything from or to this workspace (it is being deleted).
    Workspace(&'a str),
    /// Everything from or to a workspace id (`ws_…`) that is no longer in `workspaces`.
    Orphans,
}

const GONE: &str = "LIKE 'ws\\_%' ESCAPE '\\' AND {c} NOT IN (SELECT id FROM workspaces)";

fn gone(col: &str) -> String {
    format!("{col} {}", GONE.replace("{c}", col))
}

/// Fill the temp tables `wipe_msgs` and `wipe_blobs` (candidates) for `scope`.
fn collect(c: &Connection, scope: Scope) -> rusqlite::Result<()> {
    c.execute_batch(
        "CREATE TEMP TABLE IF NOT EXISTS wipe_msgs(id TEXT PRIMARY KEY);
         CREATE TEMP TABLE IF NOT EXISTS wipe_probs(id TEXT PRIMARY KEY);
         CREATE TEMP TABLE IF NOT EXISTS wipe_blobs(id TEXT PRIMARY KEY);
         DELETE FROM wipe_msgs; DELETE FROM wipe_probs; DELETE FROM wipe_blobs;",
    )?;
    let ws = match scope {
        Scope::Workspace(id) => id,
        Scope::Orphans => "",
    };
    let (msg_where, prob_where, up_where) = match scope {
        Scope::Workspace(_) => (
            "from_addr=?1 OR to_addr=?1".to_string(),
            "from_ws=?1".to_string(),
            "uploader=?1".to_string(),
        ),
        Scope::Orphans => (
            format!("(?1='' AND ({} OR {}))", gone("from_addr"), gone("to_addr")),
            format!("(?1='' AND {})", gone("from_ws")),
            format!("(?1='' AND {})", gone("uploader")),
        ),
    };
    c.execute(
        &format!("INSERT OR IGNORE INTO wipe_msgs(id) SELECT id FROM messages WHERE {msg_where}"),
        [ws],
    )?;
    c.execute(
        &format!("INSERT OR IGNORE INTO wipe_probs(id) SELECT id FROM problems WHERE {prob_where}"),
        [ws],
    )?;
    for sql in [
        "INSERT OR IGNORE INTO wipe_blobs(id) SELECT blob_id FROM messages
           WHERE blob_id IS NOT NULL AND id IN (SELECT id FROM wipe_msgs)",
        "INSERT OR IGNORE INTO wipe_blobs(id) SELECT blob_id FROM view_blobs WHERE msg_id IN (SELECT id FROM wipe_msgs)",
        "INSERT OR IGNORE INTO wipe_blobs(id) SELECT blob_id FROM phone_blobs WHERE msg_id IN (SELECT id FROM wipe_msgs)",
        "INSERT OR IGNORE INTO wipe_blobs(id) SELECT blob_id FROM problems WHERE id IN (SELECT id FROM wipe_probs)",
    ] {
        c.execute(sql, [])?;
    }
    c.execute(
        &format!("INSERT OR IGNORE INTO wipe_blobs(id) SELECT id FROM blobs WHERE {up_where}"),
        [ws],
    )?;
    Ok(())
}

/// Candidate blobs nothing outside the removed rows still names.
const FREE_BLOBS: &str = "SELECT w.id FROM wipe_blobs w WHERE
       NOT EXISTS(SELECT 1 FROM messages m WHERE m.blob_id=w.id AND m.id NOT IN (SELECT id FROM wipe_msgs))
   AND NOT EXISTS(SELECT 1 FROM view_blobs v WHERE v.blob_id=w.id AND v.msg_id NOT IN (SELECT id FROM wipe_msgs))
   AND NOT EXISTS(SELECT 1 FROM phone_blobs p WHERE p.blob_id=w.id AND p.msg_id NOT IN (SELECT id FROM wipe_msgs))
   AND NOT EXISTS(SELECT 1 FROM problems q WHERE q.blob_id=w.id AND q.id NOT IN (SELECT id FROM wipe_probs))";

fn ids(c: &Connection, sql: &str, p: &[&dyn rusqlite::ToSql]) -> rusqlite::Result<Vec<String>> {
    c.prepare(sql)?
        .query_map(p, |r| r.get(0))?
        .collect::<Result<_, _>>()
}

/// Subscribers whose own workspace list names a workspace in scope, with the list they keep.
fn subscriber_lists(c: &Connection, scope: Scope) -> rusqlite::Result<Vec<(String, Vec<String>)>> {
    let rows: Vec<(String, String)> = c
        .prepare("SELECT id,workspaces FROM subscribers")?
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .collect::<Result<_, _>>()?;
    let mut out = vec![];
    for (id, raw) in rows {
        let list = crate::store::parse_ws_list(&raw);
        let keep: Vec<String> = list
            .iter()
            .filter(|w| match scope {
                Scope::Workspace(ws) => w.as_str() != ws,
                Scope::Orphans => crate::store::ws_exists(c, w),
            })
            .cloned()
            .collect();
        if keep.len() != list.len() {
            out.push((id, keep));
        }
    }
    Ok(out)
}

fn sub_log_where(scope: Scope) -> &'static str {
    match scope {
        // A subscriber's "file" line names the blob it fetched.
        Scope::Workspace(_) => "what='file' AND result IN (SELECT id FROM wipe_free)",
        Scope::Orphans => {
            "(what='file' AND result IN (SELECT id FROM wipe_free)) OR sub NOT IN (SELECT id FROM subscribers)"
        }
    }
}

/// Count what `remove` would take away, changing nothing.
pub fn preview(c: &mut Connection, scope: Scope) -> rusqlite::Result<Counts> {
    let tx = c.transaction()?;
    let (n, _) = run(&tx, scope)?;
    tx.rollback()?;
    Ok(n)
}

/// Remove the history in `scope` in one transaction (the caller removes the workspace's own rows in the same
/// transaction first), returning the counts and the files to delete once it is committed.
pub fn run(c: &Connection, scope: Scope) -> rusqlite::Result<(Counts, Files)> {
    collect(c, scope)?;
    c.execute_batch(
        "CREATE TEMP TABLE IF NOT EXISTS wipe_free(id TEXT PRIMARY KEY); DELETE FROM wipe_free;",
    )?;
    c.execute(&format!("INSERT INTO wipe_free(id) {FREE_BLOBS}"), [])?;
    let msgs = ids(c, "SELECT id FROM wipe_msgs", &[])?;
    let blobs = ids(c, "SELECT id FROM wipe_free", &[])?;
    let file_rows: usize = c.query_row(
        "SELECT COUNT(*) FROM blobs WHERE id IN (SELECT id FROM wipe_free)",
        [],
        |r| r.get(0),
    )?;
    let sub_log = c.execute(
        &format!("DELETE FROM sub_log WHERE {}", sub_log_where(scope)),
        [],
    )?;
    let lists = subscriber_lists(c, scope)?;
    for (id, keep) in &lists {
        c.execute(
            "UPDATE subscribers SET workspaces=?2 WHERE id=?1",
            params![id, serde_json::to_string(keep).unwrap()],
        )?;
    }
    for t in [
        "view_blobs",
        "phone_blobs",
        "phone_client_ids",
        "question_taken_back",
    ] {
        c.execute(
            &format!("DELETE FROM {t} WHERE msg_id IN (SELECT id FROM wipe_msgs)"),
            [],
        )?;
    }
    let messages = c.execute(
        "DELETE FROM messages WHERE id IN (SELECT id FROM wipe_msgs)",
        [],
    )?;
    let problems = c.execute(
        "DELETE FROM problems WHERE id IN (SELECT id FROM wipe_probs)",
        [],
    )?;
    c.execute(
        "DELETE FROM blobs WHERE id IN (SELECT id FROM wipe_free)",
        [],
    )?;
    c.execute_batch("DELETE FROM wipe_msgs; DELETE FROM wipe_probs; DELETE FROM wipe_blobs; DELETE FROM wipe_free;")?;
    Ok((
        Counts {
            messages,
            files: file_rows,
            problems,
            sub_log,
            subscribers: lists.len(),
        },
        Files { blobs, msgs },
    ))
}

/// Files to delete after the commit.
#[derive(Default)]
pub struct Files {
    blobs: Vec<String>,
    msgs: Vec<String>,
}

impl Files {
    /// Delete the blob files and the cached speech of the removed messages.
    pub fn remove(self, data_dir: &Path) {
        for b in &self.blobs {
            if safe_name(b) {
                let _ = std::fs::remove_file(data_dir.join("blobs").join(b));
            }
        }
        if self.msgs.is_empty() {
            return;
        }
        let gone: HashSet<&str> = self.msgs.iter().map(|s| s.as_str()).collect();
        let Ok(rd) = std::fs::read_dir(data_dir.join("tts")) else {
            return;
        };
        let doomed: Vec<PathBuf> = rd
            .flatten()
            .filter(|e| {
                let name = e.file_name();
                let name = name.to_string_lossy();
                name.split('.').next().is_some_and(|m| gone.contains(m))
            })
            .map(|e| e.path())
            .collect();
        for p in doomed {
            let _ = std::fs::remove_file(p);
        }
    }
}

/// A blob id is a plain token; never let one walk out of the blobs folder.
fn safe_name(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 128
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}
