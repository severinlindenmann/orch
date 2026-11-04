use crate::{apps, db, files, util, State};

/// Removes expired files and apps. Runs hourly; tests call it directly.
pub async fn sweep(st: &State) {
    let now = util::now();
    let (ids, names) = {
        let c = st.db.lock().unwrap();
        let ids = db::expired_files(&c, &now).unwrap_or_default();
        let names: Vec<String> = db::all_apps(&c)
            .unwrap_or_default()
            .into_iter()
            .filter(|a| a.expires_at.as_deref().is_some_and(|e| e <= now.as_str()))
            .map(|a| a.name)
            .collect();
        (ids, names)
    };
    for id in ids {
        files::remove(st, &id);
    }
    for n in names {
        let _g = st.app_lock.lock().await;
        apps::remove(st, &n).await;
    }
}
