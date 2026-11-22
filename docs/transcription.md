# Transcription: our own speech to text

A small server (ours) that turns speech into text with a Whisper model running on our own machine, instead of
sending voice to Deepgram. The relay uses it for phone and workspace voice when the admin sets it up; workspaces can
also send long recordings (meetings) as encrypted jobs. API: `contracts/transcription-api.md`.

## What it runs

- **whisper.cpp** (through the `whisper-rs` binding) with a speech model file and a voice detection model file.
- **The model we use: "Flix Swiss German"**, Whisper large-v3 retrained on Swiss German (Apache-2.0), quantized
  to q5_0 (1.1 GB, about 2 GB of memory while it runs). One model for English, German and Swiss German; it finds
  the language by itself; Swiss German comes out as written Standard German. Why this one, with the measurements:
  ticket ORCH-1258, `model-choice.md`.
- **Voice detection** (Silero, 1 MB) runs first: silence, noise and broken audio give an empty transcript instead of
  made-up text such as "Vielen Dank".
- Any multilingual Whisper ggml file works (`ORCH_TRANSCRIPTION_MODEL`); plain `large-v3-turbo` is the fallback
  choice when Swiss German does not matter.

## Set it up

1. Build: `cargo build --release` in `transcription/` (needs cmake and a C++ compiler: whisper.cpp and libopus are
   built from source). On a Mac with Apple silicon: `cargo build --release --features metal` (the graphics chip;
   several times faster).
2. Models into `<data>/models/` (default data folder `/var/lib/orch-transcription`):
   - `model.bin`: the speech model. Flix Swiss German: convert `Flix-AI/flix-swissgerman-full` with whisper.cpp's
     `models/convert-h5-to-ggml.py` (load the weights as float32), then `whisper-quantize ... q5_0`. Or download a
     ready Whisper file, e.g. `ggml-large-v3-turbo.bin` from `huggingface.co/ggerganov/whisper.cpp`.
   - `vad.bin`: `ggml-silero-v5.1.2.bin` from `huggingface.co/ggml-org/whisper-vad`.
3. Start: `orch-transcription` (settings: `orch-transcription --help`). It listens on `127.0.0.1:8104`; put it on the
   private network address (`ORCH_TRANSCRIPTION_LISTEN`) or behind a TLS reverse proxy. Never on a public address.
4. A token per caller: `orch-transcription token add relay --per-minute 300` (shown once), and
   `orch-transcription token add ws_<id>` for a workspace that sends recordings itself. `token list`,
   `token remove <name>` (refused from the next request on; its jobs are deleted within a minute).
5. Tell the relay: `PUT /admin/api/voice/service` with `{"url": "http://<private-network name>:8104", "token": "ort_…"}`
   (relay admin token). From then on the relay sends voice to our service and never to Deepgram. `DELETE` the same
   address to go back to Deepgram.

Hosting it on our machine (sleep, start at boot, private network only, encrypted disk and swap) is its own ticket
(ORCH-1194).

## How it keeps voice private

- Short voice (`/v1/transcribe`, max 2 minutes): audio and text exist only in memory for the length of the call.
- Recordings (`/v1/jobs`, max 2 hours): sent encrypted in the publish file format with a key only the workspace
  keeps; the key travels with the request and stays in memory only. On disk: the encrypted recording until the job
  ends, then the transcript encrypted with a key derived from the job key, for at most 7 days. After a restart a
  waiting job asks for its key again (`needs_key`).
- A job belongs to the token that made it; other tokens get "not found".
- Logs carry ids, sizes and timings only: never audio, text, keys or tokens.
- What is not protected: while a job runs its audio and text are in the service's memory, and the system may move
  memory to swap. That is why the machine needs encrypted disk and swap.

## Limits

One transcription at a time (the model uses all its threads); 4 more may wait, then `busy`. Long recordings run in
pieces of about 5 minutes cut at a quiet moment, and a short voice memo goes between two pieces. Per token: a
per-minute limit (default 30) and at most 4 open jobs. All stored recordings together: 2 GB.

## Tests

`cargo test` in `transcription/`: the API, sign-in and jobs with a fake engine; the real engine with the tiny Whisper
model when `ORCH_TRANSCRIPTION_TEST_MODEL` and `ORCH_TRANSCRIPTION_TEST_VAD` point at the files (CI downloads them).
