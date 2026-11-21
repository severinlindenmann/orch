//! The speech engine: 16 kHz mono samples in, text out. Behind a trait so tests run without a model.
//! Calls block (seconds of CPU or graphics chip work); the API runs them on the blocking pool.
use std::sync::Mutex;

#[derive(Debug, Clone, PartialEq)]
pub struct Transcript {
    pub text: String,
    /// The language the engine heard or was told (`en`, `de`, ...).
    pub language: Option<String>,
}

pub trait Engine: Send + Sync {
    /// Transcribe `samples` (16 kHz mono). `language` is a Whisper code such as `de`; None = detect.
    fn transcribe(&self, samples: &[f32], language: Option<&str>) -> Result<Transcript, String>;
    /// Whether the engine knows this language code.
    fn knows_language(&self, code: &str) -> bool;
    /// A short name for the health answer (the model file name, never a path).
    fn name(&self) -> String;
}

/// Test double: records each call (number of samples, language), answers with a fixed result.
pub struct FakeEngine {
    pub calls: Mutex<Vec<(usize, Option<String>)>>,
    pub result: Mutex<Result<Transcript, String>>,
}

impl Default for FakeEngine {
    fn default() -> Self {
        FakeEngine {
            calls: Mutex::new(vec![]),
            result: Mutex::new(Ok(Transcript {
                text: "hello world".into(),
                language: Some("en".into()),
            })),
        }
    }
}

impl Engine for FakeEngine {
    fn transcribe(&self, samples: &[f32], language: Option<&str>) -> Result<Transcript, String> {
        self.calls
            .lock()
            .unwrap()
            .push((samples.len(), language.map(String::from)));
        self.result.lock().unwrap().clone()
    }
    fn knows_language(&self, code: &str) -> bool {
        matches!(code, "en" | "de" | "fr" | "it")
    }
    fn name(&self) -> String {
        "fake".into()
    }
}

#[cfg(feature = "whisper")]
pub use whisper::WhisperEngine;

#[cfg(feature = "whisper")]
mod whisper {
    use super::{Engine, Transcript};
    use std::path::{Path, PathBuf};
    use whisper_rs::{FullParams, SamplingStrategy, WhisperContext, WhisperContextParameters};

    /// A segment the model itself rates as probably not speech is dropped (made-up text on noise).
    const NO_SPEECH_MAX: f32 = 0.6;

    pub struct WhisperEngine {
        ctx: WhisperContext,
        vad: Option<String>,
        threads: i32,
        name: String,
    }

    impl WhisperEngine {
        /// Load the model (seconds, a GB or more of memory). `vad` is the voice detection model, when present.
        pub fn load(model: &Path, vad: Option<PathBuf>, threads: i32) -> Result<Self, String> {
            // whisper.cpp logs go nowhere: no transcript text and no file paths in the service log.
            whisper_rs::install_logging_hooks();
            let ctx = WhisperContext::new_with_params(model, WhisperContextParameters::default())
                .map_err(|e| format!("cannot load the model {}: {e}", model.display()))?;
            if !ctx.is_multilingual() {
                return Err(format!(
                    "the model {} knows English only; use a multilingual model",
                    model.display()
                ));
            }
            Ok(WhisperEngine {
                ctx,
                vad: vad.map(|p| p.to_string_lossy().into_owned()),
                threads,
                name: model
                    .file_name()
                    .map(|n| n.to_string_lossy().into_owned())
                    .unwrap_or_default(),
            })
        }
    }

    impl Engine for WhisperEngine {
        fn transcribe(
            &self,
            samples: &[f32],
            language: Option<&str>,
        ) -> Result<Transcript, String> {
            let mut st = self.ctx.create_state().map_err(|e| e.to_string())?;
            let mut p = FullParams::new(SamplingStrategy::BeamSearch {
                beam_size: 5,
                patience: -1.0,
            });
            p.set_n_threads(self.threads);
            p.set_language(Some(language.unwrap_or("auto")));
            p.set_translate(false);
            p.set_no_context(true);
            p.set_suppress_blank(true);
            p.set_suppress_nst(true);
            p.set_print_special(false);
            p.set_print_progress(false);
            p.set_print_realtime(false);
            p.set_print_timestamps(false);
            if let Some(v) = &self.vad {
                p.set_vad_model_path(Some(v));
                p.enable_vad(true);
            }
            st.full(p, samples).map_err(|e| e.to_string())?;
            let mut text = String::new();
            for i in 0..st.full_n_segments() {
                let Some(seg) = st.get_segment(i) else {
                    continue;
                };
                if seg.no_speech_probability() > NO_SPEECH_MAX {
                    continue;
                }
                if let Ok(s) = seg.to_str_lossy() {
                    let s = s.trim();
                    if !s.is_empty() {
                        if !text.is_empty() {
                            text.push(' ');
                        }
                        text.push_str(s);
                    }
                }
            }
            let heard = whisper_rs::get_lang_str(st.full_lang_id_from_state()).map(String::from);
            Ok(Transcript {
                text,
                language: language.map(String::from).or(heard),
            })
        }
        fn knows_language(&self, code: &str) -> bool {
            whisper_rs::get_lang_id(code).is_some()
        }
        fn name(&self) -> String {
            self.name.clone()
        }
    }
}
