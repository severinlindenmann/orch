use std::path::PathBuf;

#[derive(Clone, Debug)]
pub struct Config {
    pub data_dir: PathBuf,
    pub apps_dir: PathBuf,
    pub public_url: String,
    pub max_file_mb: u64,
    pub default_days: i64,
    pub max_days: i64,
    pub admin_token: String,
    pub port_lo: u16,
    pub port_hi: u16,
    pub health_secs: u64,
    pub build_secs: u64,
    pub test_secs: u64,
    pub install_url: String,
    pub install_ref: String,
}

/// ORCH_PUBLISH_<k> first, then PUBLISH_<k>.
fn var(k: &str) -> Option<String> {
    std::env::var(format!("ORCH_PUBLISH_{k}"))
        .or_else(|_| std::env::var(format!("PUBLISH_{k}")))
        .ok()
}

fn env_or<T: std::str::FromStr>(k: &str, d: T) -> T {
    var(k).and_then(|v| v.parse().ok()).unwrap_or(d)
}

impl Config {
    pub fn new(data_dir: PathBuf, admin_token: String) -> Self {
        Config {
            apps_dir: data_dir.join("apps"),
            data_dir,
            public_url: "https://publish.severin.io".into(),
            max_file_mb: 100,
            default_days: 7,
            max_days: 90,
            admin_token,
            port_lo: 9100,
            port_hi: 9199,
            health_secs: 20,
            build_secs: 300,
            test_secs: 120,
            install_url: "https://raw.githubusercontent.com/severinlindenmann/orch/main/install.sh"
                .into(),
            install_ref: "main".into(),
        }
    }

    /// Reads PUBLISH_* env. Admin token: PUBLISH_ADMIN_TOKEN, else the file PUBLISH_ADMIN_TOKEN_FILE
    /// (default /etc/orch-publish/admin-token), else a new one in `<data dir>/admin-token`.
    pub fn from_env() -> Self {
        let data_dir =
            PathBuf::from(var("DATA_DIR").unwrap_or_else(|| "/var/lib/orch-publish".into()));
        let token = admin_token(&data_dir);
        let mut c = Config::new(data_dir, token);
        if let Some(a) = var("APPS_DIR") {
            c.apps_dir = PathBuf::from(a);
        }
        c.public_url = var("PUBLIC_ORIGIN")
            .or_else(|| var("PUBLIC_URL"))
            .unwrap_or(c.public_url)
            .trim_end_matches('/')
            .to_string();
        c.max_file_mb = env_or("MAX_FILE_MB", c.max_file_mb);
        c.default_days = env_or("DEFAULT_DAYS", c.default_days);
        c.max_days = env_or("MAX_DAYS", c.max_days);
        c.health_secs = env_or("HEALTH_SECS", c.health_secs);
        // ORCH_INSTALL_REF (git ref of the orch repo the onboarding scripts install from)
        if let Ok(r) = std::env::var("ORCH_INSTALL_REF") {
            if !r.is_empty() {
                c.install_ref = r;
            }
        }
        c.install_url = format!(
            "https://raw.githubusercontent.com/severinlindenmann/orch/{}/install.sh",
            c.install_ref
        );
        c.install_url = var("INSTALL_URL").unwrap_or(c.install_url);
        if let Some(r) = var("APP_PORTS") {
            if let Some((a, b)) = r.split_once('-') {
                if let (Ok(a), Ok(b)) = (a.parse(), b.parse()) {
                    c.port_lo = a;
                    c.port_hi = b;
                }
            }
        }
        c
    }

    /// Largest accepted upload body: cap + 64 KiB header + 36 bytes overhead.
    pub fn max_blob_bytes(&self) -> usize {
        (self.max_file_mb * 1024 * 1024 + 64 * 1024 + 36) as usize
    }
    pub fn blobs_dir(&self) -> PathBuf {
        self.data_dir.join("files")
    }
    /// code of one version of an app: <apps dir>/<name>/<version>
    pub fn app_root(&self, name: &str) -> PathBuf {
        self.apps_dir.join(name)
    }
    pub fn app_data_dir(&self, name: &str) -> PathBuf {
        self.apps_dir.join(name).join("data")
    }
    pub fn log_path(&self, name: &str) -> PathBuf {
        self.data_dir.join("logs").join(format!("{name}.log"))
    }
}

fn admin_token(data_dir: &std::path::Path) -> String {
    if let Some(t) = var("ADMIN_TOKEN") {
        return t.trim().to_string();
    }
    let file = var("ADMIN_TOKEN_FILE")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/etc/orch-publish/admin-token"));
    if let Ok(t) = std::fs::read_to_string(&file) {
        return t.trim().to_string();
    }
    let own = data_dir.join("admin-token");
    if let Ok(t) = std::fs::read_to_string(&own) {
        return t.trim().to_string();
    }
    let t = crate::util::rand_token("", 32);
    let _ = std::fs::create_dir_all(data_dir);
    #[cfg(unix)]
    {
        use std::io::Write;
        use std::os::unix::fs::OpenOptionsExt;
        if let Ok(mut f) = std::fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .mode(0o600)
            .open(&own)
        {
            let _ = f.write_all(t.as_bytes());
        }
    }
    #[cfg(not(unix))]
    let _ = std::fs::write(&own, &t);
    eprintln!("orch-publish: admin token written to {}", own.display());
    t
}
