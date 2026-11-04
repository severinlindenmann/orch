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

## Data storage
Token and phone id in the Keychain. Nothing else is stored; lists come from the relay.

## Tests
- T0: `xcodebuild test -scheme OrchMobile -only-testing:OrchMobileTests/RelayClientTests -destination 'platform=iOS Simulator,name=iPhone 16'`.
- Unit tests decode every `contracts/examples/message/*` example. UI tests run against a local relay binary (`relay/`, temp dir);
  push is simulated with `xcrun simctl push`.
- CI: `mobile/**`, `contracts/**` on a macOS runner.

## Install
Prototype: Xcode build to the Simulator and the owner's iPhone. TestFlight later. The APNs key stays on the VPS.

## Not included
Android, iPad layout, reading full tickets, files, delegate/start from the phone, offline queue, several relays.
