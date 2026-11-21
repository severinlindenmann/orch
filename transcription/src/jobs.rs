//! Encrypted jobs (transcription-api.md "Long audio"). On disk only ciphertext: `<id>.in` (the OPF1 recording,
//! as sent) and `<id>.out` (the OPF1 transcript under the result key), plus `<id>.json` (status, times, sizes:
//! no content). Job keys live in memory only; after a restart a job that has not run says `needs_key`.
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tokio::sync::Notify;

use crate::api::App;
use crate::audio::{self, AudioError};
use crate::engine::Segment;
use crate::opf1;
use crate::tokens::now;

pub const MAX_BLOB: usize = 200 * 1024 * 1024;
pub const MAX_SECONDS: f64 = 2.0 * 3600.0;
pub const MAX_OPEN_PER_CALLER: usize = 4;
/// All stored recordings together.
pub const MAX_STORED: u64 = 2 * 1024 * 1024 * 1024;
pub const KEEP_SECS: i64 = 7 * 24 * 3600;
/// Job uploads read at the same time (each holds up to 200 MB, and opening it once more).
pub const MAX_UPLOADS: usize = 2;
/// A job runs in pieces of about this length, so short calls get a turn in between.
pub const PIECE_SECS: usize = 300;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Waiting,
    Running,
    Done,
    Failed,
    NeedsKey,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Meta {
    pub id: String,
    pub owner: String,
    pub status: Status,
    pub created_at: i64,
    pub expires_at: i64,
    /// The audio container (from the OPF1 header type), e.g. `m4a`.
    pub ext: String,
    pub language: Option<String>,
    pub size: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub duration: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

impl Meta {
    /// What a caller sees.
    pub fn public(&self) -> serde_json::Value {
        let mut v = serde_json::json!({
            "id": self.id, "status": self.status,
            "created_at": self.created_at, "expires_at": self.expires_at,
        });
        if let Some(d) = self.duration {
            v["duration"] = d.into();
        }
        if let Some(e) = &self.error {
            v["error"] = e.clone().into();
        }
        v
    }
    fn open(&self) -> bool {
        matches!(
            self.status,
            Status::Waiting | Status::Running | Status::NeedsKey
        )
    }
}

#[derive(Debug, PartialEq)]
pub enum JobError {
    NotFound,
    BadKey,
    BadBlob,
    TooLarge,
    Busy,
    Conflict,
    Io,
}

pub struct Jobs {
    dir: PathBuf,
    keys: Mutex<HashMap<String, [u8; 32]>>,
    /// Serialises changes to the files (create, status, delete).
    lock: Mutex<()>,
    pub wake: Notify,
}

pub fn valid_id(id: &str) -> bool {
    id.len() == 18
        && id.starts_with("j_")
        && id[2..]
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit())
}

fn new_id() -> String {
    const A: &[u8] = b"abcdefghijklmnopqrstuvwxyz0123456789";
    let mut b = [0u8; 16];
    rand::RngCore::fill_bytes(&mut rand::rngs::OsRng, &mut b);
    format!(
        "j_{}",
        b.iter()
            .map(|x| A[*x as usize % A.len()] as char)
            .collect::<String>()
    )
}

fn write_atomic(path: &Path, data: &[u8]) -> std::io::Result<()> {
    let tmp = path.with_extension("tmp");
    std::fs::write(&tmp, data)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&tmp, std::fs::Permissions::from_mode(0o600))?;
    }
    std::fs::rename(&tmp, path)
}

impl Jobs {
    /// Open the job folder. Jobs that were waiting or running lost their key with the old process: `needs_key`.
    pub fn open(data_dir: &Path) -> Jobs {
        let j = Jobs {
            dir: data_dir.join("jobs"),
            keys: Mutex::new(HashMap::new()),
            lock: Mutex::new(()),
            wake: Notify::new(),
        };
        let _ = std::fs::create_dir_all(&j.dir);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = std::fs::set_permissions(&j.dir, std::fs::Permissions::from_mode(0o700));
        }
        for mut m in j.all() {
            if matches!(m.status, Status::Waiting | Status::Running) {
                m.status = Status::NeedsKey;
                let _ = j.save(&m);
            }
        }
        j
    }

    fn path(&self, id: &str, ext: &str) -> PathBuf {
        self.dir.join(format!("{id}.{ext}"))
    }

    fn save(&self, m: &Meta) -> std::io::Result<()> {
        write_atomic(&self.path(&m.id, "json"), &serde_json::to_vec(m).unwrap())
    }

    fn load(&self, id: &str) -> Option<Meta> {
        if !valid_id(id) {
            return None;
        }
        serde_json::from_slice(&std::fs::read(self.path(id, "json")).ok()?).ok()
    }

    pub fn all(&self) -> Vec<Meta> {
        let Ok(rd) = std::fs::read_dir(&self.dir) else {
            return vec![];
        };
        let mut v: Vec<Meta> = rd
            .flatten()
            .filter_map(|e| {
                let n = e.file_name().into_string().ok()?;
                self.load(n.strip_suffix(".json")?)
            })
            .collect();
        v.sort_by_key(|m| m.created_at);
        v
    }

    /// The job if it belongs to `owner` (others get NotFound, as for an id that does not exist).
    pub fn get(&self, owner: &str, id: &str) -> Result<Meta, JobError> {
        self.load(id)
            .filter(|m| m.owner == owner)
            .ok_or(JobError::NotFound)
    }

    fn remove_files(&self, id: &str) {
        for ext in ["in", "out", "json", "tmp"] {
            let _ = std::fs::remove_file(self.path(id, ext));
        }
        self.keys.lock().unwrap().remove(id);
    }

    /// Before reading an upload: Busy when the caller has its 4 open jobs or the store is full.
    pub fn room_for(&self, owner: &str) -> Result<(), JobError> {
        let all = self.all();
        if all.iter().filter(|m| m.owner == owner && m.open()).count() >= MAX_OPEN_PER_CALLER {
            return Err(JobError::Busy);
        }
        let stored: u64 = all.iter().filter(|m| m.open()).map(|m| m.size).sum();
        if stored + MAX_BLOB as u64 > MAX_STORED {
            return Err(JobError::Busy);
        }
        Ok(())
    }

    /// Check the blob with its key, store it encrypted as sent, keep the key in memory.
    pub fn create(
        &self,
        owner: &str,
        key: Option<&str>,
        blob: &[u8],
        language: Option<String>,
    ) -> Result<Meta, JobError> {
        let key = key.and_then(opf1::key_from_b64).ok_or(JobError::BadKey)?;
        if blob.len() > MAX_BLOB {
            return Err(JobError::TooLarge);
        }
        let (header, _) = opf1::open(&key, blob).ok_or(JobError::BadBlob)?;
        let ext = audio::hint_for(header.kind.split(';').next().unwrap_or("").trim())
            .ok_or(JobError::BadBlob)?;
        let _g = self.lock.lock().unwrap();
        let all = self.all();
        if all.iter().filter(|m| m.owner == owner && m.open()).count() >= MAX_OPEN_PER_CALLER {
            return Err(JobError::Busy);
        }
        let stored: u64 = all.iter().filter(|m| m.open()).map(|m| m.size).sum();
        if stored + blob.len() as u64 > MAX_STORED {
            return Err(JobError::Busy);
        }
        let t = now();
        let m = Meta {
            id: new_id(),
            owner: owner.into(),
            status: Status::Waiting,
            created_at: t,
            expires_at: t + KEEP_SECS,
            ext: ext.into(),
            language,
            size: blob.len() as u64,
            duration: None,
            error: None,
        };
        write_atomic(&self.path(&m.id, "in"), blob).map_err(|_| JobError::Io)?;
        self.save(&m).map_err(|_| JobError::Io)?;
        self.keys.lock().unwrap().insert(m.id.clone(), key);
        drop(_g);
        self.wake.notify_one();
        Ok(m)
    }

    /// Send the key again after a restart (`needs_key` only).
    pub fn resupply(&self, owner: &str, id: &str, key: Option<&str>) -> Result<Meta, JobError> {
        let key = key.and_then(opf1::key_from_b64).ok_or(JobError::BadKey)?;
        let _g = self.lock.lock().unwrap();
        let mut m = self.get(owner, id)?;
        if m.status != Status::NeedsKey {
            return Err(JobError::Conflict);
        }
        let blob = std::fs::read(self.path(id, "in")).map_err(|_| JobError::Io)?;
        opf1::open(&key, &blob).ok_or(JobError::BadKey)?;
        m.status = Status::Waiting;
        self.save(&m).map_err(|_| JobError::Io)?;
        self.keys.lock().unwrap().insert(m.id.clone(), key);
        drop(_g);
        self.wake.notify_one();
        Ok(m)
    }

    pub fn result(&self, owner: &str, id: &str) -> Result<Vec<u8>, JobError> {
        let m = self.get(owner, id)?;
        if m.status != Status::Done {
            return Err(JobError::Conflict);
        }
        std::fs::read(self.path(id, "out")).map_err(|_| JobError::Io)
    }

    pub fn delete(&self, owner: &str, id: &str) -> Result<(), JobError> {
        let _g = self.lock.lock().unwrap();
        self.get(owner, id)?;
        self.remove_files(id);
        Ok(())
    }

    /// Delete expired jobs and the jobs of removed tokens; also stray files without a status file.
    pub fn sweep(&self, owners: &[String], at: i64) -> usize {
        let _g = self.lock.lock().unwrap();
        let mut n = 0;
        for m in self.all() {
            if m.expires_at <= at || !owners.contains(&m.owner) {
                self.remove_files(&m.id);
                n += 1;
            }
        }
        if let Ok(rd) = std::fs::read_dir(&self.dir) {
            for e in rd.flatten() {
                let name = e.file_name().to_string_lossy().into_owned();
                let id = name.split('.').next().unwrap_or("");
                if !valid_id(id) || !self.path(id, "json").exists() {
                    let _ = std::fs::remove_file(e.path());
                }
            }
        }
        n
    }

    /// The oldest waiting job whose key we hold, now marked running, with its key.
    fn next(&self) -> Option<(Meta, [u8; 32])> {
        let _g = self.lock.lock().unwrap();
        let keys = self.keys.lock().unwrap();
        let mut m = self
            .all()
            .into_iter()
            .find(|m| m.status == Status::Waiting && keys.contains_key(&m.id))?;
        let key = keys[&m.id];
        drop(keys);
        m.status = Status::Running;
        self.save(&m).ok()?;
        Some((m, key))
    }

    /// End a job: write the result (or the error), delete the recording, forget the key.
    fn finish(&self, mut m: Meta, out: Result<(Vec<u8>, f64), &'static str>) {
        let _g = self.lock.lock().unwrap();
        // deleted (or its token removed) while it ran: nothing to keep
        if self.load(&m.id).is_none() {
            self.remove_files(&m.id);
            return;
        }
        match out {
            Ok((blob, duration)) => {
                if write_atomic(&self.path(&m.id, "out"), &blob).is_ok() {
                    m.status = Status::Done;
                    m.duration = Some(duration);
                } else {
                    m.status = Status::Failed;
                    m.error = Some("transcription_failed".into());
                }
            }
            Err(code) => {
                m.status = Status::Failed;
                m.error = Some(code.into());
            }
        }
        let _ = std::fs::remove_file(self.path(&m.id, "in"));
        self.keys.lock().unwrap().remove(&m.id);
        let _ = self.save(&m);
    }
}

/// Cut points of about `PIECE_SECS`, each moved to the quietest 0.1 s within 10 s of the target.
pub fn pieces(samples: &[f32]) -> Vec<(usize, usize)> {
    let rate = audio::RATE as usize;
    let piece = PIECE_SECS * rate;
    let win = 10 * rate;
    let frame = rate / 10;
    let mut out = vec![];
    let mut start = 0;
    while samples.len() - start > piece + win {
        let target = start + piece;
        let mut best = target;
        let mut best_e = f32::MAX;
        let mut f = target - win;
        while f + frame <= target + win {
            let e: f32 = samples[f..f + frame].iter().map(|v| v * v).sum();
            if e < best_e {
                best_e = e;
                best = f + frame / 2;
            }
            f += frame;
        }
        out.push((start, best));
        start = best;
    }
    out.push((start, samples.len()));
    out
}

#[derive(Serialize)]
struct Result_ {
    text: String,
    language: Option<String>,
    duration: f64,
    segments: Vec<Segment>,
}

/// Run one job: decrypt in memory, decode, transcribe piece by piece (taking the run slot per piece), seal.
async fn run_one(app: &Arc<App>, m: &Meta, key: [u8; 32]) -> Result<(Vec<u8>, f64), &'static str> {
    let path = app.jobs.path(&m.id, "in");
    let ext = m.ext.clone();
    let samples = tokio::task::spawn_blocking(move || {
        let blob = std::fs::read(path).map_err(|_| "transcription_failed")?;
        let (_, data) = opf1::open(&key, &blob).ok_or("transcription_failed")?;
        audio::decode(data, &ext, MAX_SECONDS).map_err(|e| match e {
            AudioError::TooLong => "too_large",
            AudioError::Unreadable => "unsupported_audio",
        })
    })
    .await
    .map_err(|_| "transcription_failed")??;
    let samples = Arc::new(samples);
    let duration = samples.len() as f64 / audio::RATE as f64;
    let mut language = m.language.clone();
    let mut text = String::new();
    let mut segments = vec![];
    for (a, b) in pieces(&samples) {
        // Fair line: a short call waiting for the slot gets it before our next piece.
        let slot = app
            .run
            .clone()
            .acquire_owned()
            .await
            .map_err(|_| "transcription_failed")?;
        let engine = app.engine.clone();
        let s = samples.clone();
        let lang = language.clone();
        let t = tokio::task::spawn_blocking(move || {
            let _slot = slot;
            let piece = &s[a..b];
            let loud =
                (piece.iter().map(|v| v * v).sum::<f32>() / piece.len().max(1) as f32).sqrt();
            if loud < 1e-4 {
                return Ok(None);
            }
            engine.transcribe(piece, lang.as_deref()).map(Some)
        })
        .await
        .map_err(|_| "transcription_failed")?
        .map_err(|_| "transcription_failed")?;
        let Some(t) = t else { continue };
        // the first piece's language holds for the rest (one recording, one language)
        if language.is_none() {
            language = t.language.clone();
        }
        let off = a as f64 / audio::RATE as f64;
        for s in t.segments {
            segments.push(Segment {
                start: ((s.start + off) * 100.0).round() / 100.0,
                end: ((s.end + off) * 100.0).round() / 100.0,
                text: s.text,
            });
        }
        if !t.text.is_empty() {
            if !text.is_empty() {
                text.push(' ');
            }
            text.push_str(&t.text);
        }
    }
    let body = serde_json::to_vec(&Result_ {
        text,
        language,
        duration: (duration * 100.0).round() / 100.0,
        segments,
    })
    .map_err(|_| "transcription_failed")?;
    let rk = opf1::result_key(&key);
    Ok((
        opf1::seal(&rk, "transcript.json", "application/json", &body),
        duration,
    ))
}

/// The job worker: runs waiting jobs one by one; sweeps expired jobs and removed tokens' jobs every minute.
pub async fn worker(app: Arc<App>) {
    let mut last_sweep = 0;
    loop {
        let t = now();
        if t - last_sweep >= 60 {
            let owners: Vec<String> = app.tokens.list().into_iter().map(|e| e.name).collect();
            let n = app.jobs.sweep(&owners, t);
            if n > 0 {
                tracing::info!("deleted {n} expired or orphaned jobs");
            }
            last_sweep = t;
        }
        match app.jobs.next() {
            Some((m, key)) => {
                let started = std::time::Instant::now();
                let out = run_one(&app, &m, key).await;
                tracing::info!(
                    "job {} {} after {:.1} s",
                    m.id,
                    if out.is_ok() { "done" } else { "failed" },
                    started.elapsed().as_secs_f64()
                );
                app.jobs.finish(m, out);
            }
            None => {
                let _ =
                    tokio::time::timeout(Duration::from_secs(60), app.jobs.wake.notified()).await;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pieces_cut_at_the_quiet_moment() {
        let rate = audio::RATE as usize;
        // 9 minutes of tone with a silent 0.2 s at 5:04
        let mut s: Vec<f32> = (0..9 * 60 * rate)
            .map(|i| ((i % 40) as f32 / 40.0) - 0.5)
            .collect();
        let q = 304 * rate;
        for v in &mut s[q..q + rate / 5] {
            *v = 0.0;
        }
        let p = pieces(&s);
        assert_eq!(p.len(), 2, "{p:?}");
        assert!((q..q + rate / 5).contains(&p[0].1), "cut at {}", p[0].1);
        assert_eq!(p[1], (p[0].1, s.len()));
        // short audio: one piece
        assert_eq!(pieces(&s[..60 * rate]), vec![(0, 60 * rate)]);
    }

    #[test]
    fn ids() {
        let id = new_id();
        assert!(valid_id(&id), "{id}");
        for bad in [
            "",
            "j_",
            "j_../../etc/passwd",
            "J_AAAAAAAAAAAAAAAA",
            "x_aaaaaaaaaaaaaaaa",
        ] {
            assert!(!valid_id(bad), "{bad}");
        }
    }
}
