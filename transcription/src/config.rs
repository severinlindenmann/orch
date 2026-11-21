//! Settings from the environment (`ORCH_TRANSCRIPTION_<NAME>`). Defaults cover a normal install (R4.4).
use std::path::PathBuf;

#[derive(Clone, Debug)]
pub struct Config {
    pub listen: String,
    pub data_dir: PathBuf,
    /// The speech model (ggml file). Default `<data>/models/model.bin`.
    pub model: PathBuf,
    /// The voice detection model (Silero, ggml file). Default `<data>/models/vad.bin`.
    pub vad_model: PathBuf,
    pub threads: i32,
}

pub fn var(k: &str) -> Option<String> {
    std::env::var(format!("ORCH_TRANSCRIPTION_{k}"))
        .ok()
        .filter(|v| !v.is_empty())
}

impl Config {
    pub fn from_env() -> Config {
        let data_dir =
            PathBuf::from(var("DATA_DIR").unwrap_or_else(|| "/var/lib/orch-transcription".into()));
        let threads = var("THREADS")
            .and_then(|v| v.parse().ok())
            .unwrap_or_else(|| {
                std::thread::available_parallelism()
                    .map(|n| n.get().min(8) as i32)
                    .unwrap_or(4)
            });
        Config {
            listen: var("LISTEN").unwrap_or_else(|| "127.0.0.1:8104".into()),
            model: var("MODEL")
                .map(PathBuf::from)
                .unwrap_or_else(|| data_dir.join("models/model.bin")),
            vad_model: var("VAD_MODEL")
                .map(PathBuf::from)
                .unwrap_or_else(|| data_dir.join("models/vad.bin")),
            data_dir,
            threads,
        }
    }

    /// Both model files must be there; the message says where to get them.
    pub fn validate(&self) -> Result<(), String> {
        if !self.model.is_file() {
            return Err(format!(
                "no speech model at {}. Put a Whisper ggml model there (see docs/transcription.md) or set ORCH_TRANSCRIPTION_MODEL.",
                self.model.display()
            ));
        }
        if !self.vad_model.is_file() {
            return Err(format!(
                "no voice detection model at {}. Put the Silero ggml model there (see docs/transcription.md) or set ORCH_TRANSCRIPTION_VAD_MODEL.",
                self.vad_model.display()
            ));
        }
        if self.threads < 1 {
            return Err("ORCH_TRANSCRIPTION_THREADS must be 1 or more.".into());
        }
        Ok(())
    }
}
