//! At-rest encryption (contracts/crypto.md section 2): AES-256-GCM, random 12-byte nonce,
//! stored as `nonce | ciphertext+tag`, AAD = the item id.
use aes_gcm::aead::{Aead, KeyInit, Payload};
use aes_gcm::{Aes256Gcm, Nonce};
use rand::RngCore;
use std::path::Path;

pub type Key = [u8; 32];

pub fn seal(key: &Key, aad: &str, plain: &[u8]) -> Vec<u8> {
    let c = Aes256Gcm::new(key.into());
    let mut nonce = [0u8; 12];
    rand::rngs::OsRng.fill_bytes(&mut nonce);
    let ct = c
        .encrypt(
            Nonce::from_slice(&nonce),
            Payload {
                msg: plain,
                aad: aad.as_bytes(),
            },
        )
        .expect("aes-gcm encrypt");
    let mut out = nonce.to_vec();
    out.extend(ct);
    out
}

pub fn open(key: &Key, aad: &str, blob: &[u8]) -> Option<Vec<u8>> {
    if blob.len() < 12 + 16 {
        return None;
    }
    let c = Aes256Gcm::new(key.into());
    c.decrypt(
        Nonce::from_slice(&blob[..12]),
        Payload {
            msg: &blob[12..],
            aad: aad.as_bytes(),
        },
    )
    .ok()
}

/// The master key file holds 32 raw bytes (or 64 hex characters).
pub fn load_master_key(path: &Path) -> Result<Key, String> {
    let raw = std::fs::read(path).map_err(|e| format!("master key {}: {e}", path.display()))?;
    if raw.len() == 32 {
        return Ok(raw.try_into().unwrap());
    }
    let txt = String::from_utf8_lossy(&raw);
    if let Ok(b) = hex::decode(txt.trim()) {
        if b.len() == 32 {
            return Ok(b.try_into().unwrap());
        }
    }
    Err(format!(
        "master key {} must be 32 random bytes",
        path.display()
    ))
}
