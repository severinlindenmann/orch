#!/bin/bash
# Signed-push proof (ORCH-1296): real pushes through the notification extension in the Simulator. Pushes a payload
# whose relay text changed but whose signature is intact, one whose signed text changed, and an unsigned one; the
# UI test expects the signed words, then twice only "New message from Pilatus Workspace". Screenshots: <dir>/*.png.
# `simctl push` never starts a notification service extension, so the pushes go through Apple's SANDBOX APNs to the
# Simulator's own token: set APNS_KEY_FILE to the orch APNs key (.p8, from the Agents vault; APNS_KEY_ID and
# APNS_TEAM default to the relay's). Without it the script falls back to simctl push and the test fails on purpose.
# usage: signed-push-check.sh <udid> [derivedDataPath]   (run `xcodegen generate` first)
set -u
UDID=$1; DD=${2:-$(mktemp -d ~/orch-dev/.signed-push-dd-XXXX)}
cd "${MOBILE_DIR:-$(dirname "$0")/..}"
D=$(mktemp -d ~/orch-dev/.signed-push-XXXX)
swiftc -parse-as-library OrchMobile/MessageSignature.swift scripts/signed-push-gen.swift -o "$D/gen" || exit 1
"$D/gen" "$D" > /dev/null || exit 1
( for name in signed changed unsigned; do
    while [ ! -f "$D/$name.ready" ]; do sleep 0.5; done; sleep 1
    if [ -n "${APNS_KEY_FILE:-}" ]; then
      TOKEN=$(xcrun simctl spawn "$UDID" defaults read io.severin.orch debugPushToken 2>/dev/null)
      python3 scripts/apns-sandbox-send.py "$APNS_KEY_FILE" "${APNS_KEY_ID:-TD27F9Z9V7}" "${APNS_TEAM:-77D4THRYUN}" "$TOKEN" "$D/$name.json"
    else
      xcrun simctl push "$UDID" io.severin.orch "$D/$name.json"
    fi
  done ) &
PUSHER=$!
TEST_RUNNER_ORCH_SIGNED_PUSH_DIR="$D" xcodebuild ${XCB_ACTION:-test} -scheme OrchMobile -destination "id=$UDID" -derivedDataPath "$DD" \
  -only-testing:OrchMobileUITests/SignedPushUITests > "$D/xcodebuild.log" 2>&1
grep -E "Test Case.*(passed|failed)|error:" "$D/xcodebuild.log"
kill $PUSHER 2>/dev/null
echo "screenshots and log: $D"
