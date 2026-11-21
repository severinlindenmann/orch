//! Sign-in: `Authorization: Bearer ort_<43 chars>`. Tokens are made by the admin on the service machine
//! (`orch-transcription token add <name>`), shown once, stored as a SHA-256 hash only in `<data>/tokens.json`.
//! The running service rereads the file when it changes, so add and remove work without a restart.
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::SystemTime;

use base64::Engine as _;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

pub const PREFIX: &str = "ort_";
pub const DEFAULT_PER_MINUTE: u32 = 30;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Entry {
    pub name: String,
    /// SHA-256 of the whole token, hex.
    pub hash: String,
    pub per_minute: u32,
    pub created_at: i64,
}

#[derive(Default, Serialize, Deserialize)]
struct File {
    v: u32,
    tokens: Vec<Entry>,
}

/// When the token file last changed: modified time and size.
type Stamp = (SystemTime, u64);

pub struct Tokens {
    path: PathBuf,
    cache: Mutex<(Option<Stamp>, Vec<Entry>)>,
    rate: Mutex<HashMap<String, (i64, u32)>>,
}

pub fn now() -> i64 {
    SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

/// `YYYY-MM-DD` (UTC) for unix seconds (days-to-civil, H. Hinnant).
pub fn day(ts: i64) -> String {
    let z = ts.div_euclid(86_400) + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + i64::from(m <= 2);
    format!("{y:04}-{m:02}-{d:02}")
}

fn hash(token: &str) -> String {
    Sha256::digest(token.as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

/// A token name: 1-40 of `a-z 0-9 _ -` (`relay`, `ws_pilatus001`).
pub fn valid_name(n: &str) -> bool {
    (1..=40).contains(&n.len())
        && n.chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '-')
}

fn read(path: &Path) -> Result<Vec<Entry>, String> {
    match std::fs::read(path) {
        Ok(b) => serde_json::from_slice::<File>(&b)
            .map(|f| f.tokens)
            .map_err(|e| format!("{} is broken ({e}); fix or remove it", path.display())),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(vec![]),
        Err(e) => Err(format!("{}: {e}", path.display())),
    }
}

fn write(path: &Path, tokens: &[Entry]) -> Result<(), String> {
    if let Some(d) = path.parent() {
        std::fs::create_dir_all(d).map_err(|e| format!("{}: {e}", d.display()))?;
    }
    let body = serde_json::to_vec_pretty(&File {
        v: 1,
        tokens: tokens.to_vec(),
    })
    .map_err(|e| e.to_string())?;
    let tmp = path.with_extension("json.tmp");
    std::fs::write(&tmp, body).map_err(|e| format!("{}: {e}", tmp.display()))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(&tmp, std::fs::Permissions::from_mode(0o600));
    }
    std::fs::rename(&tmp, path).map_err(|e| format!("{}: {e}", path.display()))
}

impl Tokens {
    pub fn open(data_dir: &Path) -> Tokens {
        Tokens {
            path: data_dir.join("tokens.json"),
            cache: Mutex::new((None, vec![])),
            rate: Mutex::new(HashMap::new()),
        }
    }

    /// The current list (reread when the file changed).
    pub fn list(&self) -> Vec<Entry> {
        let mtime = std::fs::metadata(&self.path)
            .and_then(|m| Ok((m.modified()?, m.len())))
            .ok();
        let mut c = self.cache.lock().unwrap();
        if c.0 != mtime || mtime.is_none() {
            match read(&self.path) {
                Ok(t) => *c = (mtime, t),
                // A broken file refuses everyone rather than keep a removed token working.
                Err(e) => {
                    tracing::error!("{e}");
                    *c = (None, vec![]);
                }
            }
        }
        c.1.clone()
    }

    /// The entry for an `Authorization` header value, or None.
    pub fn check(&self, header: Option<&str>) -> Option<Entry> {
        let token = header?.strip_prefix("Bearer ")?.trim();
        if !token.starts_with(PREFIX) || token.len() != PREFIX.len() + 43 {
            return None;
        }
        let h = hash(token);
        self.list().into_iter().find(|e| e.hash == h)
    }

    /// Count one call for `e`; false when it is over its per-minute limit.
    pub fn take(&self, e: &Entry) -> bool {
        let t = now();
        let mut m = self.rate.lock().unwrap();
        let r = m.entry(e.name.clone()).or_insert((t, 0));
        if t - r.0 >= 60 {
            *r = (t, 0);
        }
        r.1 += 1;
        r.1 <= e.per_minute
    }

    /// Make a token; returns it (shown once).
    pub fn add(&self, name: &str, per_minute: u32) -> Result<String, String> {
        if !valid_name(name) {
            return Err(
                "a token name is 1-40 of a-z, 0-9, _ and - (for example relay or ws_pilatus001)"
                    .into(),
            );
        }
        if per_minute == 0 {
            return Err("--per-minute must be 1 or more".into());
        }
        let mut all = read(&self.path)?;
        if all.iter().any(|e| e.name == name) {
            return Err(format!(
                "a token named {name} exists; remove it first to make a new one"
            ));
        }
        let mut raw = [0u8; 32];
        rand::RngCore::fill_bytes(&mut rand::rngs::OsRng, &mut raw);
        let token = format!(
            "{PREFIX}{}",
            base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(raw)
        );
        all.push(Entry {
            name: name.into(),
            hash: hash(&token),
            per_minute,
            created_at: now(),
        });
        write(&self.path, &all)?;
        Ok(token)
    }

    /// Remove a token by name. True when it existed.
    pub fn remove(&self, name: &str) -> Result<bool, String> {
        let mut all = read(&self.path)?;
        let n = all.len();
        all.retain(|e| e.name != name);
        if all.len() == n {
            return Ok(false);
        }
        write(&self.path, &all)?;
        Ok(true)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn add_check_remove() {
        let d = tempfile::tempdir().unwrap();
        let t = Tokens::open(d.path());
        let tok = t.add("relay", 30).unwrap();
        assert!(tok.starts_with("ort_") && tok.len() == 47);
        let e = t.check(Some(&format!("Bearer {tok}"))).unwrap();
        assert_eq!(e.name, "relay");
        // only the hash is on disk
        let file = std::fs::read_to_string(d.path().join("tokens.json")).unwrap();
        assert!(!file.contains(&tok[4..]));
        assert!(t.add("relay", 30).is_err());
        assert!(t.remove("relay").unwrap());
        assert!(t.check(Some(&format!("Bearer {tok}"))).is_none());
        assert!(!t.remove("relay").unwrap());
    }

    #[test]
    fn bad_headers_and_names() {
        let d = tempfile::tempdir().unwrap();
        let t = Tokens::open(d.path());
        t.add("a", 30).unwrap();
        for h in [
            "",
            "Bearer",
            "Bearer ort_x",
            "Basic abc",
            "ort_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        ] {
            assert!(t.check(Some(h)).is_none(), "{h}");
        }
        assert!(t.check(None).is_none());
        for n in ["", "Relay", "a b", "../x", &"x".repeat(41)] {
            assert!(t.add(n, 30).is_err(), "{n}");
        }
        assert!(t.add("zero", 0).is_err());
    }

    #[test]
    fn day_formats_dates() {
        assert_eq!(day(0), "1970-01-01");
        assert_eq!(day(1_795_290_059), "2026-11-21");
        assert_eq!(day(951_782_400), "2000-02-29");
    }

    #[test]
    fn per_minute_limit() {
        let d = tempfile::tempdir().unwrap();
        let t = Tokens::open(d.path());
        t.add("w", 2).unwrap();
        let e = t.list().pop().unwrap();
        assert!(t.take(&e) && t.take(&e));
        assert!(!t.take(&e));
    }

    #[test]
    fn broken_file_refuses_everyone() {
        let d = tempfile::tempdir().unwrap();
        let t = Tokens::open(d.path());
        let tok = t.add("w", 30).unwrap();
        std::fs::write(d.path().join("tokens.json"), b"{not json").unwrap();
        assert!(t.check(Some(&format!("Bearer {tok}"))).is_none());
    }
}
