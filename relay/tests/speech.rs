mod common;
use common::*;
use orch_relay::speech::{self, Aura, FakeSpeaker, Settings, Speaker};
use orch_relay::{store, util};
use serde_json::{json, Value};
use std::sync::{Arc, Mutex};

fn vectors() -> Value {
    let p = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../contracts/vectors/phone-v3-v1.json"
    );
    serde_json::from_str(&std::fs::read_to_string(p).unwrap()).unwrap()
}

#[test]
fn spoken_text_matches_the_contract_vectors() {
    let v = vectors();
    assert_eq!(v["speech_max_chars"], 900);
    for c in v["speech_text"].as_array().unwrap() {
        assert_eq!(
            speech::spoken_text(&c["body"]),
            c["spoken"].as_str().unwrap(),
            "case {}",
            c["name"]
        );
    }
}

struct Rig {
    t: T,
    ws: Ws,
    phone: (String, String),
    sp: Arc<FakeSpeaker>,
}

async fn rig() -> Rig {
    let t = start().await;
    let ws = t.add_ws("Alpha").await;
    let phone = t.pair_phone(&[&ws]).await;
    Rig {
        t,
        ws,
        phone,
        sp: Arc::new(FakeSpeaker::default()),
    }
}

impl Rig {
    fn text(&self, to: &str, from: &str, body: Value) -> String {
        let id = mid();
        let m = json!({"schema": "orch.msg/1", "id": id, "from": from, "to": to, "type": "text",
            "created_at": "2026-11-04T10:00:00Z", "body": body});
        let c = self.t.app.db.lock().unwrap();
        store::insert_message(&c, &self.t.app.key, &m, "d").unwrap();
        id
    }
    fn speak_text(&self, body: Value) -> String {
        self.text(&self.phone.0, &self.ws.id, body)
    }
    async fn get(
        &self,
        id: &str,
        lang: Option<&str>,
        cap: f64,
        speak: &str,
    ) -> Result<Vec<u8>, (u16, String)> {
        let s = Settings {
            speak: speak.into(),
            tts_cap_usd: cap,
        };
        speech::generate(
            &self.t.app.db,
            &self.t.app.key,
            &self.t.app.cfg.data_dir,
            &*self.sp,
            &self.phone.0,
            &[self.ws.id.clone()],
            &s,
            id,
            lang,
            util::now(),
        )
        .await
        .map_err(|e| (e.status.as_u16(), e.code.to_string()))
    }
    fn key(&self) {
        let c = self.t.app.db.lock().unwrap();
        orch_relay::transcribe::set_key(&c, &self.t.app.key, "dg_secret_key_ABCD1234").unwrap();
    }
    fn used(&self) -> f64 {
        speech::used_usd_month(&self.t.app.db.lock().unwrap(), &self.phone.0, util::now())
    }
}

#[tokio::test]
async fn off_without_key_then_makes_audio_caches_and_counts() {
    let r = rig().await;
    let id = r.speak_text(json!({"text": "Hallo Welt.", "speak": {"lang": "de"}}));
    assert_eq!(
        r.get(&id, None, 10.0, "auto").await.unwrap_err(),
        (503, "tts_off".into())
    );
    r.key();
    let mp3 = r.get(&id, None, 10.0, "auto").await.unwrap();
    assert_eq!(mp3, b"ID3fake-mp3");
    {
        let calls = r.sp.calls.lock().unwrap();
        assert_eq!(calls.len(), 1);
        assert_eq!(
            calls[0],
            (
                "dg_secret_key_ABCD1234".into(),
                "Hallo Welt.".into(),
                "aura-2-julius-de".into()
            )
        );
    }
    let want = 11.0 * 0.030 / 1000.0;
    assert!((r.used() - want).abs() < 1e-9, "{}", r.used());
    // second call: cache, no Deepgram call, no cost, even over the cap and with the key gone
    r.t.app
        .db
        .lock()
        .unwrap()
        .execute("DELETE FROM settings WHERE k='deepgram'", [])
        .unwrap();
    assert_eq!(r.get(&id, None, 0.0, "auto").await.unwrap(), b"ID3fake-mp3");
    assert_eq!(r.sp.calls.lock().unwrap().len(), 1);
    assert!((r.used() - want).abs() < 1e-9);
    // the cache on disk is sealed
    let f = std::fs::read_dir(r.t.app.cfg.data_dir.join("tts"))
        .unwrap()
        .next()
        .unwrap()
        .unwrap();
    assert!(!String::from_utf8_lossy(&std::fs::read(f.path()).unwrap()).contains("ID3fake"));
}

#[tokio::test]
async fn language_voice_and_summary() {
    let r = rig().await;
    r.key();
    let id = r.speak_text(
        json!({"text": "A long text", "speak": {"lang": "en", "summary": "Short one."}}),
    );
    r.get(&id, None, 10.0, "auto").await.unwrap();
    // other language = new paid generation
    r.get(&id, Some("de"), 10.0, "auto").await.unwrap();
    let calls = r.sp.calls.lock().unwrap().clone();
    assert_eq!(calls[0].1, "Short one.");
    assert_eq!(
        (calls[0].2.as_str(), calls[1].2.as_str()),
        ("aura-2-thalia-en", "aura-2-julius-de")
    );
    drop(calls);
    assert!((r.used() - 2.0 * 10.0 * 0.030 / 1000.0).abs() < 1e-9);
    assert_eq!(
        r.get(&id, Some("fr"), 10.0, "auto").await.unwrap_err().0,
        422
    );
    // no speak.lang and no ?lang = en
    let id2 = r.speak_text(json!({"text": "Hi.", "speak": {}}));
    r.get(&id2, None, 10.0, "auto").await.unwrap();
    assert_eq!(
        r.sp.calls.lock().unwrap().last().unwrap().2,
        "aura-2-thalia-en"
    );
}

#[tokio::test]
async fn cap_stops_new_audio() {
    let r = rig().await;
    r.key();
    let id = r.speak_text(json!({"text": "x".repeat(500), "speak": {"lang": "en"}})); // 0.015 USD
    assert_eq!(
        r.get(&id, None, 0.0, "auto").await.unwrap_err(),
        (402, "tts_cap_reached".into())
    );
    assert_eq!(r.get(&id, None, 0.014, "auto").await.unwrap_err().0, 402);
    r.get(&id, None, 0.015, "auto").await.unwrap(); // exactly the cap is fine
    let id2 = r.speak_text(json!({"text": "y".repeat(500), "speak": {"lang": "en"}}));
    assert_eq!(r.get(&id2, None, 0.029, "auto").await.unwrap_err().0, 402);
    assert_eq!(r.sp.calls.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn access_rules() {
    let r = rig().await;
    r.key();
    let plain = r.speak_text(json!({"text": "No speak mark."}));
    assert_eq!(r.get(&plain, None, 10.0, "auto").await.unwrap_err().0, 404);
    r.get(&plain, None, 10.0, "always").await.unwrap();
    let marked = r.speak_text(json!({"text": "Marked.", "speak": {"lang": "en"}}));
    assert_eq!(
        r.get(&marked, None, 10.0, "never").await.unwrap_err().0,
        404
    );
    // empty after cleaning
    let empty = r.speak_text(json!({"text": "** ``` #", "speak": {"lang": "en"}}));
    assert_eq!(r.get(&empty, None, 10.0, "auto").await.unwrap_err().0, 404);
    // a workspace not on the list, an unknown id, a non-text message
    let other = r.t.add_ws("Beta").await;
    let foreign = r.text(
        &r.phone.0,
        &other.id,
        json!({"text": "Hi.", "speak": {"lang": "en"}}),
    );
    assert_eq!(
        r.get(&foreign, None, 10.0, "auto").await.unwrap_err().0,
        404
    );
    assert_eq!(
        r.get("m_nope", None, 10.0, "auto").await.unwrap_err().0,
        404
    );
    // a text to another phone
    let other_phone = r.text(
        "p_someoneelse",
        &r.ws.id,
        json!({"text": "Hi.", "speak": {"lang": "en"}}),
    );
    assert_eq!(
        r.get(&other_phone, None, 10.0, "auto").await.unwrap_err().0,
        404
    );
    // broadcast to phones works
    let bc = r.text(
        "phones",
        &r.ws.id,
        json!({"text": "All.", "speak": {"lang": "en"}}),
    );
    r.get(&bc, None, 10.0, "auto").await.unwrap();
}

#[tokio::test]
async fn admin_switch_and_deepgram_failure() {
    let r = rig().await;
    r.key();
    let id = r.speak_text(json!({"text": "Hi.", "speak": {"lang": "en"}}));
    speech::set_enabled(&r.t.app.db.lock().unwrap(), false).unwrap();
    assert_eq!(
        r.get(&id, None, 10.0, "auto").await.unwrap_err(),
        (503, "tts_off".into())
    );
    speech::set_enabled(&r.t.app.db.lock().unwrap(), true).unwrap();
    *r.sp.result.lock().unwrap() = Err("boom".into());
    assert_eq!(
        r.get(&id, None, 10.0, "auto").await.unwrap_err(),
        (502, "tts_failed".into())
    );
    assert_eq!(r.used(), 0.0, "a failed generation costs nothing");
}

#[test]
fn month_is_utc_calendar_month() {
    assert_eq!(speech::month_of(1_793_404_800), "2026-10"); // 2026-10-31 00:00:00 UTC
    assert_eq!(speech::month_of(1_793_404_800 + 86_400), "2026-11");
}

/// The real Aura client against a local stand-in for api.deepgram.com.
#[tokio::test]
async fn aura_client_sends_model_encoding_and_key() {
    use axum::{extract::Query, http::HeaderMap, routing::post, Router};
    use std::collections::HashMap;
    let seen: Arc<Mutex<Vec<(HashMap<String, String>, String, String)>>> = Arc::default();
    let s2 = seen.clone();
    let app = Router::new().route(
        "/v1/speak",
        post(
            move |Query(q): Query<HashMap<String, String>>, h: HeaderMap, body: String| {
                let s2 = s2.clone();
                async move {
                    s2.lock()
                        .unwrap()
                        .push((q, h["authorization"].to_str().unwrap().into(), body));
                    b"MP3DATA".to_vec()
                }
            },
        ),
    );
    let l = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", l.local_addr().unwrap());
    tokio::spawn(std::future::IntoFuture::into_future(axum::serve(l, app)));
    let out = Aura::new(&base)
        .speak("KEY1", "Guten Tag.", "aura-2-julius-de")
        .await
        .unwrap();
    assert_eq!(out, b"MP3DATA");
    let s = seen.lock().unwrap();
    assert_eq!(s[0].0["model"], "aura-2-julius-de");
    assert_eq!(s[0].0["encoding"], "mp3");
    assert_eq!(s[0].1, "Token KEY1");
    assert_eq!(
        serde_json::from_str::<Value>(&s[0].2).unwrap(),
        json!({"text": "Guten Tag."})
    );
    drop(s);
    // unreachable service
    assert!(Aura::new("http://127.0.0.1:1")
        .speak("K", "x", "v")
        .await
        .is_err());
}

/// Manual check against the real Deepgram API: `ORCH_DG_KEY=... ORCH_DG_OUT=<dir> cargo test --test speech -- --ignored`.
#[tokio::test]
#[ignore]
async fn real_deepgram_makes_german_and_english_mp3() {
    let key = std::env::var("ORCH_DG_KEY").expect("ORCH_DG_KEY");
    let out = std::env::var("ORCH_DG_OUT").expect("ORCH_DG_OUT");
    for (lang, text) in [
        ("de", "Der Bericht ist fertig. Alle Tests sind grün."),
        ("en", "The report is ready. All tests are green."),
    ] {
        let mp3 = Aura::default()
            .speak(&key, text, speech::voice(lang))
            .await
            .unwrap();
        assert!(mp3.len() > 1000);
        std::fs::write(format!("{out}/speech-{lang}.mp3"), mp3).unwrap();
    }
}

#[tokio::test]
async fn concurrent_requests_never_pass_the_cap_and_one_generation_per_message() {
    let r = Arc::new(rig().await);
    r.key();
    *r.sp.delay_ms.lock().unwrap() = 100;
    // 8 different messages of 500 chars (0.015 USD each), cap 0.045: at most 3 may be made
    let ids: Vec<String> = (0..8)
        .map(|i| {
            r.speak_text(
                json!({"text": format!("{i}{}", "x".repeat(499)), "speak": {"lang": "en"}}),
            )
        })
        .collect();
    let mut hs = vec![];
    for id in ids {
        let r = r.clone();
        hs.push(tokio::spawn(async move {
            r.get(&id, None, 0.045, "auto").await
        }));
    }
    let mut ok = 0;
    for h in hs {
        match h.await.unwrap() {
            Ok(_) => ok += 1,
            Err(e) => assert_eq!(e, (402, "tts_cap_reached".into())),
        }
    }
    assert_eq!(ok, 3);
    assert!(r.used() <= 0.045 + 1e-9, "{}", r.used());
    assert_eq!(r.sp.calls.lock().unwrap().len(), 3);

    // the same message asked 5 times at once: one paid generation, the rest get the cache
    let before = r.used();
    let id = r.speak_text(json!({"text": "Hallo.", "speak": {"lang": "de"}}));
    let mut hs = vec![];
    for _ in 0..5 {
        let r = r.clone();
        let id = id.clone();
        hs.push(tokio::spawn(
            async move { r.get(&id, None, 10.0, "auto").await },
        ));
    }
    for h in hs {
        assert_eq!(h.await.unwrap().unwrap(), b"ID3fake-mp3");
    }
    assert_eq!(r.sp.calls.lock().unwrap().len(), 4);
    assert!((r.used() - before - 6.0 * 0.030 / 1000.0).abs() < 1e-9);
}

#[tokio::test]
async fn route_serves_the_mp3_end_to_end() {
    let t = start().await;
    let ws = t.add_ws("Alpha").await;
    let p = t.pair_phone(&[&ws]).await;
    let sp = Arc::new(FakeSpeaker::default());
    *t.app.speaker.lock().unwrap() = sp.clone();
    let get = |path: String| {
        let (t, p) = (&t, &p);
        async move {
            let r = t
                .http
                .get(format!("{}{}", t.base, path))
                .header("X-Orch-Phone", &p.0)
                .header("Authorization", format!("Bearer {}", p.1))
                .send()
                .await
                .unwrap();
            let ct = r
                .headers()
                .get("content-type")
                .map(|v| v.to_str().unwrap().to_string());
            (r.status().as_u16(), ct, r.bytes().await.unwrap().to_vec())
        }
    };
    let id = mid();
    let m = json!({"schema": "orch.msg/1", "id": id, "from": ws.id, "to": p.0, "type": "text",
        "created_at": "2026-11-04T10:00:00Z", "body": {"text": "Hallo Welt.", "speak": {"lang": "de"}}});
    store::insert_message(&t.app.db.lock().unwrap(), &t.app.key, &m, "d").unwrap();
    // no Deepgram key yet
    assert_eq!(get(format!("/v1/phone/speech/{id}")).await.0, 503);
    orch_relay::transcribe::set_key(
        &t.app.db.lock().unwrap(),
        &t.app.key,
        "dg_secret_key_ABCD1234",
    )
    .unwrap();
    let (s, ct, body) = get(format!("/v1/phone/speech/{id}")).await;
    assert_eq!(
        (s, ct.as_deref(), body.as_slice()),
        (200, Some("audio/mpeg"), &b"ID3fake-mp3"[..])
    );
    assert_eq!(get(format!("/v1/phone/speech/{id}?lang=fr")).await.0, 422);
    assert_eq!(get("/v1/phone/speech/m_unknown".into()).await.0, 404);
    // usage shows in the settings
    let (_, v) = t.phone(&p, "GET", "/v1/phone/settings", None).await;
    assert!(
        (v["tts_used_usd_month"].as_f64().unwrap() - 11.0 * 0.03 / 1000.0).abs() < 1e-9,
        "{v}"
    );
    // cap 0: cached audio still served, a new language is refused
    t.phone(
        &p,
        "PATCH",
        "/v1/phone/settings",
        Some(json!({"tts_cap_usd": 0})),
    )
    .await;
    assert_eq!(get(format!("/v1/phone/speech/{id}")).await.0, 200);
    assert_eq!(get(format!("/v1/phone/speech/{id}?lang=en")).await.0, 402);
    assert_eq!(sp.calls.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn swiss_german_setting_sends_de_ch_to_transcription() {
    let t = start().await;
    let ws = t.add_ws("Alpha").await;
    let p = t.pair_phone(&[&ws]).await;
    orch_relay::transcribe::set_key(
        &t.app.db.lock().unwrap(),
        &t.app.key,
        "dg_secret_key_ABCD1234",
    )
    .unwrap();
    let post = |q: &'static str| {
        let (t, p) = (&t, &p);
        async move {
            t.http
                .post(format!("{}/v1/phone/transcribe{q}", t.base))
                .header("X-Orch-Phone", &p.0)
                .header("Authorization", format!("Bearer {}", p.1))
                .header("Content-Type", "audio/m4a")
                .body(vec![1u8; 50])
                .send()
                .await
                .unwrap()
                .status()
                .as_u16()
        }
    };
    t.phone(
        &p,
        "PATCH",
        "/v1/phone/settings",
        Some(json!({"swiss_german": true})),
    )
    .await;
    assert_eq!(post("").await, 200);
    assert_eq!(post("?language=en").await, 200);
    let calls = t.dg.calls.lock().unwrap();
    assert_eq!(calls[0].3.as_deref(), Some("de-CH"));
    assert_eq!(calls[1].3.as_deref(), Some("en"));
}

#[tokio::test]
async fn refund_never_touches_another_month() {
    let t = start().await;
    let ws = t.add_ws("Alpha").await;
    let p = t.pair_phone(&[&ws]).await;
    let c = t.app.db.lock().unwrap();
    let (a, b) = (1_793_404_800, 1_793_404_800 + 86_400); // 31 Oct and 1 Nov 2026 (UTC)
    speech::add_usage(&c, &p.0, a, 0.5).unwrap(); // reserve in month A
    speech::add_usage(&c, &p.0, b, 0.2).unwrap(); // month rolls to B (a reservation there)
    speech::refund_usage(&c, &p.0, &speech::month_of(a), 0.5).unwrap(); // the late refund for A
    assert!(
        (speech::used_usd_month(&c, &p.0, b) - 0.2).abs() < 1e-9,
        "B unchanged"
    );
    speech::refund_usage(&c, &p.0, &speech::month_of(b), 0.2).unwrap();
    assert_eq!(speech::used_usd_month(&c, &p.0, b), 0.0);
}

#[tokio::test]
async fn stale_request_time_cannot_reset_the_current_month() {
    let r = rig().await;
    r.key();
    {
        let c = r.t.app.db.lock().unwrap();
        speech::add_usage(&c, &r.phone.0, util::now(), 0.5).unwrap();
    }
    let id = r.speak_text(json!({"text": "Hallo.", "speak": {"lang": "de"}}));
    let s = Settings {
        speak: "auto".into(),
        tts_cap_usd: 10.0,
    };
    // a request that carries a time from an old month still books into the current month
    speech::generate(
        &r.t.app.db,
        &r.t.app.key,
        &r.t.app.cfg.data_dir,
        &*r.sp,
        &r.phone.0,
        &[r.ws.id.clone()],
        &s,
        &id,
        None,
        1_793_404_800 - 86_400 * 40,
    )
    .await
    .unwrap();
    assert!(
        (r.used() - 0.5 - 6.0 * 0.030 / 1000.0).abs() < 1e-9,
        "{}",
        r.used()
    );
}

#[tokio::test]
async fn client_disconnect_during_deepgram_gives_the_reservation_back() {
    let r = Arc::new(rig().await);
    r.key();
    *r.sp.delay_ms.lock().unwrap() = 600;
    let id = r.speak_text(json!({"text": "Hallo Welt.", "speak": {"lang": "de"}}));
    let r2 = r.clone();
    let h = tokio::spawn(async move { r2.get(&id, None, 10.0, "auto").await });
    tokio::time::sleep(std::time::Duration::from_millis(200)).await;
    assert!(r.used() > 0.0, "reserved while Deepgram works");
    h.abort(); // the phone hung up
    let _ = h.await;
    assert_eq!(r.used(), 0.0, "the reservation is back");
}

#[test]
fn purge_removes_only_old_cached_audio() {
    let d = tempfile::tempdir().unwrap();
    std::fs::create_dir_all(d.path().join("tts")).unwrap();
    let f = d.path().join("tts").join("m_x.en.mp3");
    std::fs::write(&f, b"x").unwrap();
    let now = util::now();
    assert_eq!(speech::purge(d.path(), now, 500), 0);
    assert!(f.exists(), "fresh audio stays");
    assert_eq!(speech::purge(d.path(), now + 1000, 500), 1);
    assert!(!f.exists(), "old audio is gone");
    assert_eq!(
        speech::purge(d.path(), now + 1000, 500),
        0,
        "nothing left, no error"
    );
}
