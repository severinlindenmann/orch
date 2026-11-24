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
When someone joins a running recorded call (ORCH-1501) it asks again ("Someone joined: record this call in
Teams?"; the menu item "Someone joined: ask again" says it, Core Audio cannot tell who is on a call). Until the
answer the recording is paused (`consent` asked, `paused` true, no audio kept); "Yes, everyone agreed" goes on in
the same recording, "Don't record" ends it, no answer keeps it paused to the end of the call. `info.json` lists the
`paused` spans; `--read-recording` shows each track's `gaps`.

Step 4 job: record. While the gate is open it records my microphone (track "me", AVAudioEngine) and the call
app's sound (track "others", a Core Audio process tap on the call app only) as 16 kHz mono into
`recordings/<id>/me.ocr` and `others.ocr`, written only encrypted (AES-256-GCM, a new key per recording kept in
the Keychain; format at the top of `record.swift`). The menu offers "Stop recording"; the icon is a red dot while
it records. Audio callbacks only copy samples; a slow disk or a write error stops the recording visibly.
`--read-recording <folder>` checks and reads a recording back (complete, cut off or broken).

Step 5 job: install and stay current. The first start opens a window that explains the two Mac permissions in plain
words before the Mac asks (Microphone; Screen & System Audio Recording, of which it takes only the call app's
sound) and turns on "Start orch Companion with my Mac" (SMAppService; the person can turn it off there or later
under Permissions… in the menu). Updates: every 6 hours it looks for the newest `companion-vX.Y.Z` release of
this repo with `orch-Companion-X.Y.Z.zip`, and installs it only when all of this holds (ORCH-1497): Developer ID
signature of team `77D4THRYUN` with our bundle id, notarized; newer than the running app and the same version the
release names (never older); the release list, the download and every redirect are HTTPS to GitHub. It waits while a
call runs. An unsigned build never updates itself. The helper account can publish GitHub releases, so the signature
check is the barrier; the signing key is used only in the owner-run `release.sh` (it refuses to run in CI or a test
home). `--check-update <app>` says whether an app would be accepted; `release.sh` runs it on the stapled build.

Build: `companion/mac/build.sh [out-dir]` (ad-hoc signed, for tests). Release: `companion/mac/release.sh` signs
with the Developer ID certificate (hardened runtime, `entitlements.plist`), notarizes with the App Store Connect
key, staples, and makes `orch-Companion-X.Y.Z.dmg` (what people download: open it, drag orch Companion to
Applications; layout in `dmg_settings.py`, background drawn by `dmg_background.py`, packed by `dmg.sh`) and
`orch-Companion-X.Y.Z.zip` (what the update downloads); both go on the release; the inputs come from Proton Pass and are listed at the top of the script.
Checks: `orch-companion --selftest` (call state machine), `--diagnose [secs]` (every audio process with its bundle
id and microphone state: use it on a Mac with Teams to see which process holds the microphone in a call),
`--fake-audio` (two sine tones instead of microphone and tap), `--render-ask out.png` / `--render-setup out.png` (the question / the first-run window as a picture, never shown), `--headless --fake-input FILE` with lines
`<seconds> <bundle-id> on|off` or `<seconds> answer yes|no` or `<seconds> join` (tests; `ORCH_COMPANION_HOME` moves the
folder). The test is `workspace-addons/personal/tests/test_meetings_live.py`.
