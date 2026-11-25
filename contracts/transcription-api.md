# orch-transcription API (v1)

Speech to text with a self-hosted Whisper model (whisper.cpp). Runs on our own machine, reached over the private
network; the relay uses it in place of Deepgram when it is set up (relay-api.md `/v1/phone/transcribe`).
Base: `http://<private-network name>:8104`, or behind a TLS reverse proxy. JSON in, JSON out; errors as `common.md`:
`{"error": "<code>", "message"}`, and every message says what to do next.

**Auth** (every route except `/v1/health`): `Authorization: Bearer ort_<43 chars>`. Wrong or missing → `401
unauthorized`. Tokens are made by the service admin on the service machine (`orch-transcription token add <name>`),
shown once, stored as a SHA-256 hash only (crypto.md §3). Each token has a name (`relay`, `ws_pilatus001`) and a
per-minute limit (default 30; over it → `429 rate_limited`). Removing a token (`token remove <name>`) refuses it from
the next request on and deletes its jobs.

Who holds a token: the relay (one token; it signs in phones and workspaces itself and keeps its own per-phone
limits), and a workspace that sends recordings itself (its own token). Phones never get a token.

## Short audio: answer in the same call

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/v1/health` | – | `200 {ok: true, version}` (no auth, no model or token details) |
| POST | `/v1/transcribe` | body = audio bytes, `Content-Type` `audio/m4a` (`audio/x-m4a`, `audio/mp4`), `audio/aac` (raw ADTS), `audio/wav` (`audio/x-wav`), `audio/webm` (Opus), `audio/ogg`, `audio/mpeg`, `audio/flac`; parameters after `;` are ignored. Max 10 MB, 2 minutes; the upload must finish within 60 s. Optional `?language=de` (`de-CH` → `de`; any Whisper language code); left out = detected | `200 {text, language, duration}`: `duration` in seconds (2 decimals), `language` the code heard or given. Silence or noise → `text: ""` (never made-up text). `415 unsupported_audio` (type unknown or audio unreadable), `413 too_large` (over 10 MB or 2 minutes), `422 invalid` (empty, bad language), `503 busy` (one runs and 4 wait; try again later), `500 transcription_failed` |

Audio and text exist only in memory for the length of the call. Nothing about the content is logged.

## Long audio: an encrypted job (recordings, meetings)

The recording is encrypted by the sender in the publish file format (crypto.md §1, `OPF1`), with a new random key
per job. The key travels with the request (TLS or the private network) and is held **in memory only**; the
service stores only the encrypted recording and the encrypted transcript.

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/v1/jobs` | body = OPF1 blob (`application/octet-stream`) whose header `type` is one of the audio types above and whose file bytes are the recording. Header `X-Orch-Job-Key: <key, base64url, 43 chars>`. Optional `?language=de`. Max 200 MB blob, 2 hours of audio; the upload must finish within 10 minutes; at most 2 job uploads are read at a time (more → `503 busy` before the body is read) | `202 {id, status: "waiting", created_at, expires_at}`. `422 invalid` (no or bad key, not OPF1, wrong key: the blob is opened once on arrival to check it), `413 too_large`, `503 busy` (4 open jobs for this token, or the service's storage for jobs is full) |
| GET | `/v1/jobs/<id>` | – | `200 {id, status, created_at, expires_at, duration?, error?}`. `status`: `waiting`, `running`, `done`, `failed` (`error`: `unsupported_audio`, `too_large` or `transcription_failed`), `needs_key` (the service restarted before the job ran: send the key again) |
| POST | `/v1/jobs/<id>/key` | header `X-Orch-Job-Key` | `200 {id, status: "waiting"}`. Only for `needs_key`; a wrong key → `422 invalid`; another status → `409 conflict` |
| GET | `/v1/jobs/<id>/result` | – | `200` body = OPF1 blob (`application/octet-stream`), encrypted with the **result key** (below); header JSON `{"name": "transcript.json", "type": "application/json", "size"}`, file bytes = JSON `{text, language, duration, segments: [{start, end, text}]}` (times in seconds). Repeatable until deleted or expired. Not done yet → `409 conflict` |
| DELETE | `/v1/jobs/<id>` | – | `204`. Deletes the recording and the result at once |

- **Result key** = HKDF-SHA256(ikm = job key, salt = empty, info = `"orch-transcription result v1"`, 32 bytes). A
  different key from the recording's, so the two blobs never share a key; each blob has its own random IV.
- A job belongs to the token that made it (each token made has its own id; a new token under an old name does not
  see the old token's jobs): any other token gets `404` for it, as for an id that does not exist.
- Lifetimes: the encrypted recording is deleted when the job ends (`done` or `failed`); a job and its result are
  deleted 7 days after `created_at` (`expires_at`; from then on it answers `404` at once), or on `DELETE`. A cleanup
  runs every minute on its own (a long job never holds it up); a job deleted or whose token was removed while it runs
  stops after its current piece. When the token file cannot be read, the cleanup deletes only expired jobs.
- Order: one transcription runs at a time. A job runs in pieces of about 5 minutes (cut at a quiet moment), and a
  short `/v1/transcribe` call goes between two pieces, so a voice memo never waits for a whole meeting.
- The plain-text boundary (what is never protected): while a job runs, its decrypted audio and text are in the
  service's memory; the operating system may move memory to swap. The machine is ours (hosting ticket), with
  encrypted disk and swap. Logs carry ids, sizes and timings only, never content, keys or tokens.

Response bodies: `transcription-api.schema.json`. Unknown fields are allowed: an older caller ignores them.

Test vectors: `vectors/transcription-api-v1.json` (request/response pairs; the service replays them with its fake
engine, the relay replays every `/v1/transcribe` answer against a stand-in service and reads it as the vector says;
`contracts/validate.py` checks every body against the schema), `vectors/transcription-result-key-v1.json` (job key →
result key). OPF1 itself: `vectors/publish-blob-v1.json`.
