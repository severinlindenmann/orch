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

Build (ad-hoc signed; signed and notarized comes in step 5): `companion/mac/build.sh [out-dir]`.
Checks: `orch-companion --selftest` (call state machine), `--diagnose [secs]` (every audio process with its bundle
id and microphone state: use it on a Mac with Teams to see which process holds the microphone in a call),
`--headless --fake-input FILE` with lines `<seconds> <bundle-id> on|off` (tests; `ORCH_COMPANION_HOME` moves the
folder). The test is `workspace-addons/personal/tests/test_meetings_live.py`.
