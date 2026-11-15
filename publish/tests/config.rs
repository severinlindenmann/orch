//! Defaults of the scale-to-zero settings (own test binary: it sets process-wide env vars).
use orch_publish::Config;

#[test]
fn idle_secs_default_by_mode() {
    let d = tempfile::tempdir().unwrap();
    std::env::set_var("ORCH_PUBLISH_DATA_DIR", d.path());
    std::env::set_var("ORCH_PUBLISH_ADMIN_TOKEN", "t");
    std::env::remove_var("ORCH_PUBLISH_IDLE_SECS");
    std::env::remove_var("ORCH_PUBLISH_SANDBOX");
    assert_eq!(Config::from_env().idle_secs, 0);
    std::env::set_var("ORCH_PUBLISH_SANDBOX", "container");
    assert_eq!(Config::from_env().idle_secs, 900);
    std::env::set_var("ORCH_PUBLISH_IDLE_SECS", "60");
    assert_eq!(Config::from_env().idle_secs, 60);
    std::env::set_var("ORCH_PUBLISH_IDLE_SECS", "0");
    assert_eq!(Config::from_env().idle_secs, 0);
    // other modes never sleep, whatever the setting
    std::env::set_var("ORCH_PUBLISH_IDLE_SECS", "60");
    std::env::set_var("ORCH_PUBLISH_SANDBOX", "systemd");
    assert_eq!(Config::from_env().idle_secs, 0);
    std::env::remove_var("ORCH_PUBLISH_SANDBOX");
    assert_eq!(Config::from_env().idle_secs, 0);
}
