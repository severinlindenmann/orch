pub mod admin;
pub mod api;
pub mod auth;
pub mod crypto;
pub mod error;
pub mod groups;
pub mod onboarding;
pub mod phone;
pub mod push;
pub mod rules;
pub mod shared;
pub mod speech;
pub mod state;
pub mod store;
pub mod subs;
pub mod subs_push;
pub mod transcribe;
pub mod util;
pub mod webhooks;

use std::time::Duration;

/// Delete messages and blobs older than 90 days, now and then.
pub fn spawn_purge(app: state::AppState) {
    tokio::spawn(async move {
        loop {
            {
                let c = app.db.lock().unwrap();
                match store::purge(&c, &app.cfg.data_dir, util::now()) {
                    Ok((m, b)) if m + b > 0 => tracing::info!("purged {m} messages, {b} blobs"),
                    Err(e) => tracing::warn!("purge failed: {e}"),
                    _ => {}
                }
                let _ = subs::purge(&c, util::now());
            }
            speech::purge(&app.cfg.data_dir, util::now(), store::RETENTION_SECS);
            tokio::time::sleep(Duration::from_secs(3600)).await;
        }
    });
}
