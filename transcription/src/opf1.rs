//! The publish file format (crypto.md §1, `OPF1`): AES-256-GCM, random 12-byte IV, AAD "OPF1",
//! plaintext = u32 BE header length | header JSON | file bytes. Used for job recordings in and transcripts out.
use aes_gcm::aead::{Aead, Payload};
use aes_gcm::{Aes256Gcm, KeyInit, Nonce};
use base64::Engine as _;
use serde::{Deserialize, Serialize};

pub const MAGIC: &[u8; 4] = b"OPF1";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Header {
    pub name: String,
    #[serde(rename = "type")]
    pub kind: String,
    pub size: u64,
}

/// A 32-byte key from its base64url (no padding, 43 chars) form.
pub fn key_from_b64(s: &str) -> Option<[u8; 32]> {
    let s = s.trim();
    if s.len() != 43 {
        return None;
    }
    let v = base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(s)
        .ok()?;
    v.try_into().ok()
}

/// HKDF-SHA256(job key, salt empty, info "orch-transcription result v1") -> the key of the transcript blob.
pub fn result_key(job_key: &[u8; 32]) -> [u8; 32] {
    let hk = hkdf::Hkdf::<sha2::Sha256>::new(None, job_key);
    let mut out = [0u8; 32];
    hk.expand(b"orch-transcription result v1", &mut out)
        .expect("32 bytes is a valid HKDF length");
    out
}

/// Check the tag before using any byte; any failure = None ("wrong key or broken file").
pub fn open(key: &[u8; 32], blob: &[u8]) -> Option<(Header, Vec<u8>)> {
    if blob.len() < 32 || &blob[..4] != MAGIC {
        return None;
    }
    let c = Aes256Gcm::new(key.into());
    let plain = c
        .decrypt(
            Nonce::from_slice(&blob[4..16]),
            Payload {
                msg: &blob[16..],
                aad: MAGIC,
            },
        )
        .ok()?;
    if plain.len() < 4 {
        return None;
    }
    let n = u32::from_be_bytes(plain[..4].try_into().ok()?) as usize;
    if !(1..=65_536).contains(&n) || plain.len() < 4 + n {
        return None;
    }
    let header: Header = serde_json::from_slice(&plain[4..4 + n]).ok()?;
    let body = plain[4 + n..].to_vec();
    if header.size != body.len() as u64 {
        return None;
    }
    Some((header, body))
}

/// Encrypt `body` with a new random IV.
pub fn seal(key: &[u8; 32], name: &str, kind: &str, body: &[u8]) -> Vec<u8> {
    let mut iv = [0u8; 12];
    rand::RngCore::fill_bytes(&mut rand::rngs::OsRng, &mut iv);
    seal_with_iv(key, &iv, name, kind, body)
}

pub fn seal_with_iv(key: &[u8; 32], iv: &[u8; 12], name: &str, kind: &str, body: &[u8]) -> Vec<u8> {
    let header = serde_json::to_vec(&Header {
        name: name.into(),
        kind: kind.into(),
        size: body.len() as u64,
    })
    .expect("header json");
    let mut plain = Vec::with_capacity(4 + header.len() + body.len());
    plain.extend_from_slice(&(header.len() as u32).to_be_bytes());
    plain.extend_from_slice(&header);
    plain.extend_from_slice(body);
    let c = Aes256Gcm::new(key.into());
    let ct = c
        .encrypt(
            Nonce::from_slice(iv),
            Payload {
                msg: &plain,
                aad: MAGIC,
            },
        )
        .expect("AES-GCM encrypt");
    let mut out = Vec::with_capacity(16 + ct.len());
    out.extend_from_slice(MAGIC);
    out.extend_from_slice(iv);
    out.extend_from_slice(&ct);
    out
}
