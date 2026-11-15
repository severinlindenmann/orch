use std::path::PathBuf;

#[derive(Clone, Debug)]
pub struct Config {
    pub data_dir: PathBuf,
    pub apps_dir: PathBuf,
    pub public_url: String,
    /// Optional private-network listener (address to bind) and its URL; both or neither.
    pub private_listen: Option<String>,
    pub private_url: Option<String>,
    pub max_file_mb: u64,
    pub default_days: i64,
    pub max_days: i64,
    pub admin_token: String,
    pub port_lo: u16,
    pub port_hi: u16,
    pub health_secs: u64,
    /// Seconds without a request before a non-static app sleeps (0 = never). Default 900 in container mode.
    pub idle_secs: u64,
    /// How often the sleep sweeper looks for idle apps.
    pub sleep_sweep_secs: u64,
    pub build_secs: u64,
    pub test_secs: u64,
    pub install_url: String,
    pub install_ref: String,
}

/// ORCH_PUBLISH_<k> first, then PUBLISH_<k>.
pub(crate) fn var(k: &str) -> Option<String> {
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
            private_listen: None,
            private_url: None,
            max_file_mb: 100,
            default_days: 7,
            max_days: 90,
            admin_token,
            port_lo: 9100,
            port_hi: 9199,
            health_secs: 20,
            idle_secs: 0,
            sleep_sweep_secs: 30,
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
        c.private_listen = var("PRIVATE_LISTEN").filter(|v| !v.trim().is_empty());
        c.private_url = var("PRIVATE_URL")
            .map(|v| v.trim().trim_end_matches('/').to_string())
            .filter(|v| !v.is_empty());
        c.max_file_mb = env_or("MAX_FILE_MB", c.max_file_mb);
        c.default_days = env_or("DEFAULT_DAYS", c.default_days);
        c.max_days = env_or("MAX_DAYS", c.max_days);
        c.health_secs = env_or("HEALTH_SECS", c.health_secs);
        // scale to zero: only in container mode (default 15 min), 0 = never
        c.idle_secs = if crate::runner::container_mode() {
            env_or("IDLE_SECS", 900)
        } else {
            0
        };
        c.sleep_sweep_secs = env_or("SLEEP_SWEEP_SECS", c.sleep_sweep_secs).max(1);
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

    /// Startup check: the private-network listener and its URL are set together or not at all.
    pub fn validate(&self) -> Result<(), String> {
        if self.private_listen.is_some() != self.private_url.is_some() {
            return Err("ORCH_PUBLISH_PRIVATE_LISTEN and ORCH_PUBLISH_PRIVATE_URL must be set together or not at all.".into());
        }
        if let (Some(l), Some(u)) = (&self.private_listen, &self.private_url) {
            let ok = l
                .parse::<std::net::SocketAddr>()
                .is_ok_and(|a| private_ip(a.ip()));
            if !ok {
                return Err("ORCH_PUBLISH_PRIVATE_LISTEN must be an IP address and port on the private network (not 0.0.0.0, not a public address).".into());
            }
            if u.trim_end_matches('/') == self.public_url.trim_end_matches('/') {
                return Err("ORCH_PUBLISH_PRIVATE_URL must differ from the public URL.".into());
            }
        }
        Ok(())
    }
    /// Host[:port] that requests on the private listener must carry (default port from the scheme).
    pub fn private_authority(&self) -> Option<(String, u16)> {
        let u = self.private_url.as_deref()?;
        let (scheme, rest) = u.split_once("://").unwrap_or(("http", u));
        let auth = rest.split('/').next().unwrap_or("");
        let dflt = if scheme == "https" { 443 } else { 80 };
        Some(split_authority(auth, dflt))
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

/// Lower-case host and port of an authority; a missing port becomes `dflt`.
pub fn split_authority(a: &str, dflt: u16) -> (String, u16) {
    let a = a.to_ascii_lowercase();
    if let Some(r) = a.strip_prefix('[') {
        if let Some((h, p)) = r.split_once(']') {
            let port = p
                .strip_prefix(':')
                .and_then(|p| p.parse().ok())
                .unwrap_or(dflt);
            return (format!("[{h}]"), port);
        }
    }
    match a.rsplit_once(':') {
        Some((h, p)) if p.parse::<u16>().is_ok() => (h.to_string(), p.parse().unwrap()),
        _ => (a, dflt),
    }
}

/// 100.64/10, 10/8, 172.16/12, 192.168/16, fd00::/8 or loopback (local runs). Never unspecified.
fn private_ip(ip: std::net::IpAddr) -> bool {
    use std::net::IpAddr::*;
    match ip {
        V4(a) => {
            let o = a.octets();
            !a.is_unspecified()
                && (a.is_loopback()
                    || o[0] == 10
                    || (o[0] == 100 && (64..128).contains(&o[1]))
                    || (o[0] == 172 && (16..32).contains(&o[1]))
                    || (o[0] == 192 && o[1] == 168))
        }
        V6(a) => !a.is_unspecified() && (a.is_loopback() || a.octets()[0] == 0xfd),
    }
}
