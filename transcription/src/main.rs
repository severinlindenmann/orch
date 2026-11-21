use orch_transcription::config::Config;

const HELP: &str = "orch-transcription: speech to text with a self-hosted Whisper model.

Usage:
  orch-transcription [serve]   start the service (settings: ORCH_TRANSCRIPTION_* variables)
  orch-transcription --version
  orch-transcription --help

Settings (all optional):
  ORCH_TRANSCRIPTION_LISTEN      address to listen on (default 127.0.0.1:8103)
  ORCH_TRANSCRIPTION_DATA_DIR    data folder (default /var/lib/orch-transcription)
  ORCH_TRANSCRIPTION_MODEL       speech model file (default <data>/models/model.bin)
  ORCH_TRANSCRIPTION_VAD_MODEL   voice detection model file (default <data>/models/vad.bin)
  ORCH_TRANSCRIPTION_THREADS     threads for one transcription (default: cores, at most 8)

Guide: docs/transcription.md
";

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        None | Some("serve") => {}
        Some("--help") | Some("-h") | Some("help") => {
            print!("{HELP}");
            return;
        }
        Some("--version") | Some("-V") => {
            println!("orch-transcription {}", env!("CARGO_PKG_VERSION"));
            return;
        }
        Some(other) => {
            eprintln!(
                "orch-transcription: unknown command `{other}`. Run orch-transcription --help."
            );
            std::process::exit(2);
        }
    }
    // Our own lines at info; libraries (audio decoding) only when something is wrong.
    use tracing_subscriber::prelude::*;
    let only = tracing_subscriber::filter::Targets::new()
        .with_default(tracing::Level::ERROR)
        .with_target("orch_transcription", tracing::Level::INFO);
    tracing_subscriber::registry()
        .with(tracing_subscriber::fmt::layer().with_target(false))
        .with(only)
        .init();
    let rt = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .expect("tokio runtime");
    if let Err(e) = rt.block_on(serve()) {
        eprintln!("orch-transcription: {e}");
        std::process::exit(1);
    }
}

#[cfg(feature = "whisper")]
fn load_engine(
    cfg: &Config,
) -> Result<std::sync::Arc<dyn orch_transcription::engine::Engine>, String> {
    let e = orch_transcription::engine::WhisperEngine::load(
        &cfg.model,
        Some(cfg.vad_model.clone()),
        cfg.threads,
    )?;
    Ok(std::sync::Arc::new(e))
}

#[cfg(not(feature = "whisper"))]
fn load_engine(
    _cfg: &Config,
) -> Result<std::sync::Arc<dyn orch_transcription::engine::Engine>, String> {
    Err("this build has no speech engine; build with the `whisper` feature".into())
}

async fn serve() -> Result<(), String> {
    let cfg = Config::from_env();
    let listener = tokio::net::TcpListener::bind(&cfg.listen)
        .await
        .map_err(|e| {
            format!(
                "cannot listen on {}: {e} (is another orch-transcription running?)",
                cfg.listen
            )
        })?;
    cfg.validate()?;
    tracing::info!("loading the speech model");
    let engine = tokio::task::spawn_blocking({
        let cfg = cfg.clone();
        move || load_engine(&cfg)
    })
    .await
    .map_err(|e| e.to_string())??;
    let app = orch_transcription::App::new(engine);
    tracing::info!("listening on {}", cfg.listen);
    axum::serve(listener, orch_transcription::router(app))
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await
        .map_err(|e| e.to_string())
}
