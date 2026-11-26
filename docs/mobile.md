# orch-mobile

## What it does
iPhone app that talks only to orch-relay. Get a push when a workspace asks a question, answer with one tap,
send text or voice to a workspace inbox. Set up by opening the pairing link or QR code from the relay portal.

## Tech stack
Swift 6, SwiftUI, iOS 17+. Apple frameworks only: `Speech` (on-device speech to text), `AVFoundation` (mic),
`UserNotifications` + APNs, `Security` (Keychain for the token), `URLSession`. UI reuses the orch core mobile screens and the orch colours.

## Folder layout
```
mobile/
  OrchMobile.xcodeproj
  OrchMobile/{App.swift, RelayClient.swift, Pairing.swift, Push.swift, Voice.swift, Views/…, Theme.swift}
  OrchMobileTests/       unit tests (client, pairing link parsing, models)
  OrchMobileUITests/     XCUITest click-through
```

## Screens and endpoints
| Screen | Endpoint (`contracts/relay-api.md`) |
|---|---|
| Pairing (open `orch://pair?…` or scan QR) → workspaces → allow notifications | `POST /v1/phone/pair`, `POST /v1/phone/push` |
| Home: workspaces (name, description, tags behind a tap) with open-question badges | `GET /v1/phone/workspaces` |
| Questions: cards with options, recommended marked, one tap | `GET /v1/phone/questions`, `POST /v1/phone/answer` |
| Send: pick workspace, type or hold the mic, send | `POST /v1/phone/send` |
| Settings: relay, workspaces, sign out (deletes the token) | – |

Push tap opens the question. Pull to refresh; no background polling.

## Voice input (app side, later)
Hold the mic: record m4a, `POST /v1/phone/transcribe` (`Content-Type: audio/m4a`, max 2 min), show the returned `text` in the field so the person can edit it before sending.
On `503 transcription_off`, `502`, `429` or no network, fall back to on-device speech recognition. The Deepgram key never reaches the phone.

## Data storage
Token and phone id in the Keychain. Nothing else is stored; lists come from the relay.
The Keychain item is this device only (no backup, no iCloud Keychain) and is updated in place. The token goes only to an
`https` relay (plain `http` just to this device's own loopback, for the Simulator e2e), and a redirect that leaves the relay
is not followed. An invitation link taken from the clipboard is removed from it (the code works once).
Only a Keychain answer of "no such item" counts as signed out (queue and last rows are cleared). Any other failed read
(e.g. the phone is still locked after a restart) keeps the queue and the last rows, shows "orch can't read this phone's
sign-in right now", and reads again on the next refresh or return to the app. Pairing finishes only after the token is
saved; a failed save stops setup and asks for a new invitation.

## Tests
- T0: `xcodebuild test -scheme OrchMobile -only-testing:OrchMobileTests/RelayClientTests -destination 'platform=iOS Simulator,name=iPhone 16'`.
- Unit tests decode every `contracts/examples/message/*` example. UI tests run against a local relay binary (`relay/`, temp dir);
  push is simulated with `xcrun simctl push`.
- CI: `mobile/**`, `contracts/**` on a macOS runner.

## Install
Prototype: Xcode build to the Simulator and the owner's iPhone. TestFlight later. The APNs key stays on the VPS.

## Not included
Android, iPad layout, reading full tickets, files, delegate/start from the phone, offline queue, several relays.
