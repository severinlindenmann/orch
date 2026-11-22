//! Replays the shared vectors: OPF1 (publish-blob-v1.json) and the result key (transcription-result-key-v1.json).
use orch_transcription::opf1;
use serde_json::Value;

fn vectors(name: &str) -> Value {
    let p = format!("{}/../contracts/vectors/{name}", env!("CARGO_MANIFEST_DIR"));
    serde_json::from_str(&std::fs::read_to_string(p).unwrap()).unwrap()
}

fn hex(s: &str) -> Vec<u8> {
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap())
        .collect()
}

#[test]
fn opf1_vectors() {
    let v = vectors("publish-blob-v1.json");
    for name in ["good", "good_with_note"] {
        let c = &v[name];
        let key = opf1::key_from_b64(c["key_b64url"].as_str().unwrap()).unwrap();
        let (h, body) = opf1::open(&key, &hex(c["blob_hex"].as_str().unwrap())).expect(name);
        let want: Value = serde_json::from_str(c["header_json"].as_str().unwrap()).unwrap();
        assert_eq!(h.name, want["name"]);
        assert_eq!(body, c["content_utf8"].as_str().unwrap().as_bytes());
        // our writer makes the same bytes for the same IV (no note)
        if name == "good" {
            let iv: [u8; 12] = hex(c["iv_hex"].as_str().unwrap()).try_into().unwrap();
            let again = opf1::seal_with_iv(&key, &iv, &h.name, &h.kind, &body);
            assert_eq!(again, hex(c["blob_hex"].as_str().unwrap()));
        }
    }
    for c in v["must_fail"].as_array().unwrap() {
        let key = opf1::key_from_b64(c["key_b64url"].as_str().unwrap()).unwrap();
        assert!(
            opf1::open(&key, &hex(c["blob_hex"].as_str().unwrap())).is_none(),
            "{}",
            c["name"]
        );
    }
}

#[test]
fn result_key_vectors() {
    let v = vectors("transcription-result-key-v1.json");
    for c in v["cases"].as_array().unwrap() {
        let k = opf1::key_from_b64(c["job_key_b64url"].as_str().unwrap()).unwrap();
        let want = opf1::key_from_b64(c["result_key_b64url"].as_str().unwrap()).unwrap();
        assert_eq!(opf1::result_key(&k), want, "{}", c["name"]);
    }
}
