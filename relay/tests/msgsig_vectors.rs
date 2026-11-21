//! Signed messages v1: the shared vectors (contracts/vectors/signing-v1.json) against the relay's gate.

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use ed25519_dalek::{Signer, SigningKey};
use orch_relay::msgsig::{self, RelayOutcome};
use serde_json::Value;

fn vectors() -> Value {
    serde_json::from_str(include_str!("../../contracts/vectors/signing-v1.json")).unwrap()
}

fn h(s: &Value) -> Vec<u8> {
    hex::decode(s.as_str().unwrap()).unwrap()
}

#[test]
fn constants_match_the_contract() {
    let v = vectors();
    let c = &v["constants"];
    assert_eq!(c["tag"], "orch-sig-v1");
    assert_eq!(c["purposes"], serde_json::json!(msgsig::PURPOSES));
    assert_eq!(c["max_signed_bytes"], msgsig::MAX_SIGNED_BYTES);
    assert_eq!(c["max_depth"], msgsig::MAX_DEPTH);
    assert_eq!(c["max_expiry_ms"], msgsig::MAX_EXPIRY_MS);
}

#[test]
fn key_ids_and_fingerprints() {
    let v = vectors();
    for (name, p) in v["parties"].as_object().unwrap() {
        let pk = h(&p["pub"]);
        let sk = SigningKey::from_bytes(&h(&p["seed"]).try_into().unwrap());
        assert_eq!(sk.verifying_key().to_bytes().to_vec(), pk, "{name}");
        assert_eq!(msgsig::key_id(&pk), p["key_id"].as_str().unwrap(), "{name}");
        assert_eq!(
            msgsig::fingerprint(&pk),
            p["fingerprint"].as_str().unwrap(),
            "{name}"
        );
        assert!(msgsig::registration_key_ok(&pk), "{name}");
    }
}

#[test]
fn public_key_rules() {
    let v = vectors();
    for c in v["keys"].as_array().unwrap() {
        let pk = h(&c["pub"]);
        let ok = c["ok"].as_bool().unwrap();
        assert_eq!(msgsig::public_key_ok(&pk), ok, "{}", c["name"]);
        if !ok {
            assert!(!msgsig::registration_key_ok(&pk), "{}", c["name"]);
        }
    }
}

#[test]
fn signatures_are_exact() {
    let v = vectors();
    for c in v["sign"].as_array().unwrap() {
        let sk = SigningKey::from_bytes(&h(&c["seed"]).try_into().unwrap());
        let signed = URL_SAFE_NO_PAD
            .decode(c["signed"].as_str().unwrap())
            .unwrap();
        let sig = sk.sign(&msgsig::signature_input(
            c["purpose"].as_str().unwrap(),
            &signed,
        ));
        assert_eq!(
            URL_SAFE_NO_PAD.encode(sig.to_bytes()),
            c["sig"].as_str().unwrap(),
            "{}",
            c["name"]
        );
    }
}

#[test]
fn strict_json() {
    let v = vectors();
    for c in v["strict_json"].as_array().unwrap() {
        let got = msgsig::read_strict_json(&h(&c["hex"]));
        assert_eq!(
            got.is_ok(),
            c["ok"].as_bool().unwrap(),
            "{} {:?}",
            c["name"],
            got.err()
        );
    }
}

#[test]
fn relay_gate() {
    let v = vectors();
    let mut n = 0;
    for c in v["messages"].as_array().unwrap() {
        let r = &c["relay"];
        if r.is_null() {
            continue;
        }
        let registered: Vec<[u8; 32]> = r["registered"]
            .as_array()
            .unwrap()
            .iter()
            .map(|k| h(k).try_into().unwrap())
            .collect();
        let seen = r["seen"].as_object().unwrap().clone();
        let got = match msgsig::relay_check(
            &c["envelope"],
            r["caller"].as_str().unwrap(),
            &registered,
            |id| seen.get(id).map(|s| s.as_str().unwrap().to_string()),
        ) {
            Ok((RelayOutcome::New, _)) => "ok",
            Ok((RelayOutcome::Duplicate, _)) => "duplicate",
            Err(e) => e.code(),
        };
        assert_eq!(
            got,
            c["expect_relay"].as_str().unwrap(),
            "{}: {}",
            c["name"],
            c["note"]
        );
        n += 1;
    }
    assert!(n >= 60, "only {n} relay cases");
}

#[test]
fn wycheproof() {
    let v = vectors();
    let mut wrong = vec![];
    for t in v["wycheproof"]["cases"].as_array().unwrap() {
        let got = msgsig::verify_raw(&h(&t["pk"]), &h(&t["msg"]), &h(&t["sig"]));
        if let Some(exp) = t["expect"].as_bool() {
            if got != exp {
                wrong.push((t["tcId"].clone(), t["flags"].clone(), exp, got));
            }
        }
        // a key with a torsion part is never registered, so a library difference on it cannot matter
        let flags = t["flags"].as_array().unwrap();
        if flags
            .iter()
            .any(|f| f == "MixedOrderPublicKey" || f == "SmallOrderPublicKey")
        {
            assert!(
                !msgsig::registration_key_ok(&h(&t["pk"])),
                "tc {}",
                t["tcId"]
            );
        }
    }
    assert!(wrong.is_empty(), "{wrong:?}");
}
