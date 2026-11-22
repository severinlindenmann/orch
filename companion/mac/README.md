# orch Companion (Mac)
The app in the Mac menu bar that "records your calls for Meetings" (ORCH-1195). One app for the computer; add-ons
that are turned on ask it for jobs. Windows comes later (`companion/windows/`).

Step 2 job: notice a call. It reads which processes use the microphone (Core Audio process objects, macOS 14.2+, no
permission needed) and counts a call when Teams (`com.microsoft.teams2`, `com.microsoft.teams`) holds the
microphone for 3 s; the call ends 8 s after Teams last held it (mute in Teams keeps the microphone running).

It talks to orch only through files in its own folder `~/Library/Application Support/orch Companion/` (0700):
- `now.json` (0600): `{"v":1,"state":"inactive|idle|call","app","observed_since","updated","instance","pid"}`,
  written on each change and every 15 s. A reader treats `updated` older than 45 s as "not running".
- `wanted/<id>.json`: a workspace that wants calls renews its file on each look (Personal's orch Companion way
  in). With no file younger than 2 min Companion does nothing ("inactive"); files older than a day are removed.

Step 3 job: everyone agrees. When a call starts it asks "Record this call in Teams?" (a small window at the top
right, and the same two answers in its menu). Only "Yes, everyone agreed" opens the gate (`mayRecord`); "Don't
record", closing the window or no answer records nothing, and the answer ends with the call. `now.json` carries
`consent` (asked, agreed, declined), `consent_at` and `may_record`.

Step 4 job: record. While the gate is open it records my microphone (track "me", AVAudioEngine) and the call
app's sound (track "others", a Core Audio process tap on the call app only) as 16 kHz mono into
`recordings/<id>/me.ocr` and `others.ocr`, written only encrypted (AES-256-GCM, a new key per recording kept in
the Keychain; format at the top of `record.swift`). The menu offers "Stop recording"; the icon is a red dot while
it records. Audio callbacks only copy samples; a slow disk or a write error stops the recording visibly.
`--read-recording <folder>` checks and reads a recording back (complete, cut off or broken).

Build (ad-hoc signed; signed and notarized comes in step 5): `companion/mac/build.sh [out-dir]`.
Checks: `orch-companion --selftest` (call state machine), `--diagnose [secs]` (every audio process with its bundle
id and microphone state: use it on a Mac with Teams to see which process holds the microphone in a call),
`--fake-audio` (two sine tones instead of microphone and tap), `--render-ask out.png` (the question as a picture, never shown), `--headless --fake-input FILE` with lines
`<seconds> <bundle-id> on|off` or `<seconds> answer yes|no` (tests; `ORCH_COMPANION_HOME` moves the
folder). The test is `workspace-addons/personal/tests/test_meetings_live.py`.
