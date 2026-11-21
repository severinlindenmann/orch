//! Audio in memory -> 16 kHz mono f32 samples, the input Whisper wants.
//! Nothing touches the disk. The decoded length is capped while decoding, so a small compressed file cannot
//! expand into gigabytes of samples.
use std::io::Cursor;
use std::sync::OnceLock;

use symphonia::core::codecs::audio::AudioDecoderOptions;
use symphonia::core::codecs::registry::CodecRegistry;
use symphonia::core::errors::Error as SymError;
use symphonia::core::formats::probe::Hint;
use symphonia::core::formats::{FormatOptions, TrackType};
use symphonia::core::io::MediaSourceStream;
use symphonia::core::meta::MetadataOptions;

pub const RATE: u32 = 16_000;
const MIN_RATE: u32 = 8_000;
const MAX_RATE: u32 = 96_000;

#[derive(Debug, PartialEq)]
pub enum AudioError {
    /// Not a format or codec we read, or broken data.
    Unreadable,
    /// Longer than the allowed length.
    TooLong,
}

fn codecs() -> &'static CodecRegistry {
    static R: OnceLock<CodecRegistry> = OnceLock::new();
    R.get_or_init(|| {
        let mut r = CodecRegistry::new();
        symphonia::default::register_enabled_codecs(&mut r);
        r.register_audio_decoder::<symphonia_adapter_libopus::OpusDecoder>();
        r
    })
}

/// The container hint for a Content-Type (the probe also sniffs the bytes, so a wrong hint is not fatal).
pub fn hint_for(content_type: &str) -> Option<&'static str> {
    Some(match content_type {
        "audio/m4a" | "audio/x-m4a" | "audio/mp4" | "audio/aac" => "m4a",
        "audio/wav" | "audio/x-wav" | "audio/wave" => "wav",
        "audio/webm" => "webm",
        "audio/ogg" | "audio/opus" => "ogg",
        "audio/mpeg" | "audio/mp3" => "mp3",
        "audio/flac" | "audio/x-flac" => "flac",
        _ => return None,
    })
}

/// Decode `data` to 16 kHz mono. `max_seconds` caps the decoded length.
pub fn decode(data: Vec<u8>, ext: &str, max_seconds: f64) -> Result<Vec<f32>, AudioError> {
    let mss = MediaSourceStream::new(Box::new(Cursor::new(data)), Default::default());
    let mut hint = Hint::new();
    hint.with_extension(ext);
    let mut format = symphonia::default::get_probe()
        .probe(
            &hint,
            mss,
            FormatOptions::default(),
            MetadataOptions::default(),
        )
        .map_err(|_| AudioError::Unreadable)?;
    let track = format
        .default_track(TrackType::Audio)
        .ok_or(AudioError::Unreadable)?;
    let track_id = track.id;
    let params = track
        .codec_params
        .as_ref()
        .and_then(|p| p.audio())
        .ok_or(AudioError::Unreadable)?
        .clone();
    let mut decoder = codecs()
        .make_audio_decoder(&params, &AudioDecoderOptions::default())
        .map_err(|_| AudioError::Unreadable)?;

    // Mono at the source rate, turned into 16 kHz every 10 s: a 2-hour recording never needs a
    // full-rate copy in memory (48 kHz x 2 h = 1.4 GB of samples).
    let mut mono: Vec<f32> = Vec::new();
    let mut out: Vec<f32> = Vec::new();
    let mut frames: u64 = 0;
    let mut rate: u32 = 0;
    let mut buf: Vec<f32> = Vec::new();
    loop {
        let packet = match format.next_packet() {
            Ok(Some(p)) => p,
            Ok(None) => break,
            // A truncated tail ends the stream; what was decoded so far still counts.
            Err(SymError::IoError(_)) => break,
            Err(_) if frames > 0 => break,
            Err(_) => return Err(AudioError::Unreadable),
        };
        if packet.track_id != track_id {
            continue;
        }
        let ab = match decoder.decode(&packet) {
            Ok(ab) => ab,
            Err(SymError::DecodeError(_)) => continue,
            Err(_) => return Err(AudioError::Unreadable),
        };
        let spec = ab.spec();
        let ch = spec.channels().count().max(1);
        if rate == 0 {
            rate = spec.rate();
            // A made-up rate would get past the length cap (it counts samples): only real audio rates.
            if !(MIN_RATE..=MAX_RATE).contains(&rate) {
                return Err(AudioError::Unreadable);
            }
        } else if spec.rate() != rate {
            return Err(AudioError::Unreadable);
        }
        buf.resize(ab.samples_interleaved(), 0.0);
        ab.copy_to_slice_interleaved(&mut buf);
        for frame in buf.chunks(ch) {
            mono.push(frame.iter().sum::<f32>() / ch as f32);
        }
        frames += (buf.len() / ch) as u64;
        if frames as f64 > max_seconds * rate as f64 {
            return Err(AudioError::TooLong);
        }
        // 10 s of source = exactly 160 000 samples at 16 kHz, so the pieces join without a gap
        let piece = rate as usize * 10;
        while mono.len() >= piece {
            out.extend(resample(&mono[..piece], rate, RATE));
            mono.drain(..piece);
        }
    }
    if rate == 0 {
        return Err(AudioError::Unreadable);
    }
    out.extend(resample(&mono, rate, RATE));
    Ok(out)
}

/// Windowed-sinc low-pass, then linear interpolation. Good enough for speech; no extra dependency.
pub fn resample(x: &[f32], from: u32, to: u32) -> Vec<f32> {
    if from == to || x.is_empty() {
        return x.to_vec();
    }
    let filtered;
    let src: &[f32] = if from > to {
        // cut-off a little under the new Nyquist
        let fc = 0.45 * to as f64 / from as f64;
        let half = 16i64;
        let taps: Vec<f32> = (-half..=half)
            .map(|n| {
                let n = n as f64;
                let sinc = if n == 0.0 {
                    2.0 * fc
                } else {
                    (2.0 * std::f64::consts::PI * fc * n).sin() / (std::f64::consts::PI * n)
                };
                let w = 0.54 + 0.46 * (std::f64::consts::PI * n / half as f64).cos();
                (sinc * w) as f32
            })
            .collect();
        let sum: f32 = taps.iter().sum();
        let len = x.len() as i64;
        filtered = (0..len)
            .map(|i| {
                let mut acc = 0.0f32;
                for (k, t) in taps.iter().enumerate() {
                    let j = i + k as i64 - half;
                    if (0..len).contains(&j) {
                        acc += x[j as usize] * t;
                    }
                }
                acc / sum
            })
            .collect::<Vec<f32>>();
        &filtered
    } else {
        x
    };
    let ratio = from as f64 / to as f64;
    let n = ((src.len() as f64) / ratio).floor() as usize;
    (0..n)
        .map(|i| {
            let p = i as f64 * ratio;
            let j = p.floor() as usize;
            let f = (p - j as f64) as f32;
            let a = src[j];
            let b = *src.get(j + 1).unwrap_or(&a);
            a + (b - a) * f
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resample_keeps_length_ratio() {
        let x = vec![0.0f32; 48_000];
        assert_eq!(resample(&x, 48_000, 16_000).len(), 16_000);
        assert_eq!(resample(&x, 16_000, 16_000).len(), 48_000);
        assert_eq!(resample(&x[..8000], 8_000, 16_000).len(), 16_000);
    }

    #[test]
    fn resample_keeps_a_speech_tone() {
        // 440 Hz at 48 kHz -> still 440 Hz at 16 kHz (same energy, roughly)
        let x: Vec<f32> = (0..48_000)
            .map(|i| (2.0 * std::f32::consts::PI * 440.0 * i as f32 / 48_000.0).sin())
            .collect();
        let y = resample(&x, 48_000, 16_000);
        let rms = (y[1000..15000].iter().map(|v| v * v).sum::<f32>() / 14000.0).sqrt();
        assert!((rms - 0.707).abs() < 0.05, "rms {rms}");
    }

    #[test]
    fn a_made_up_sample_rate_is_refused() {
        // a WAV header claiming 1 MHz: 120 s of "audio" would be 120 million samples
        let mut v = Vec::new();
        let n: u32 = 1000;
        v.extend_from_slice(b"RIFF");
        v.extend_from_slice(&(36 + n * 2).to_le_bytes());
        v.extend_from_slice(b"WAVEfmt ");
        v.extend_from_slice(&16u32.to_le_bytes());
        v.extend_from_slice(&1u16.to_le_bytes());
        v.extend_from_slice(&1u16.to_le_bytes());
        v.extend_from_slice(&1_000_000u32.to_le_bytes());
        v.extend_from_slice(&2_000_000u32.to_le_bytes());
        v.extend_from_slice(&2u16.to_le_bytes());
        v.extend_from_slice(&16u16.to_le_bytes());
        v.extend_from_slice(b"data");
        v.extend_from_slice(&(n * 2).to_le_bytes());
        v.resize(v.len() + n as usize * 2, 1);
        assert_eq!(decode(v, "wav", 120.0), Err(AudioError::Unreadable));
    }

    #[test]
    fn hint_for_known_types() {
        assert_eq!(hint_for("audio/m4a"), Some("m4a"));
        assert_eq!(hint_for("audio/webm"), Some("webm"));
        assert_eq!(hint_for("text/plain"), None);
    }
}
