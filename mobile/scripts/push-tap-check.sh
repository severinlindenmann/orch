#!/bin/bash
# Push-tap proof: runs PushTapUITests (background + terminated) and pushes a relay-shaped payload when the test is ready.
# usage: push-tap-check.sh <udid> [derivedDataPath]   (run `xcodegen generate` first; N runs via REPEAT=5)
set -u
UDID=$1; DD=${2:-$(mktemp -d ~/orch-dev/.tf-push-XXXX)}
cd "${MOBILE_DIR:-$(dirname "$0")/..}"
PAY=$(mktemp ~/orch-dev/.tf-pushpay-XXXXXX)
cat > "$PAY" <<J
{"aps":{"alert":{"title":"Pilatus Workspace","body":"Which date format should I use?"},"sound":"default"},"message_id":"m_q1date0ts0000001","workspace":"ws_pilatus"}
J
for test in ${TESTS:-testTapFromBackground testTapFromTerminated}; do
  for i in $(seq 1 ${REPEAT:-1}); do
    rm -f /tmp/orch-push-ready
    ( while [ ! -f /tmp/orch-push-ready ]; do sleep 0.5; done; sleep 2; xcrun simctl push "$UDID" io.severin.orch "$PAY" ) &
    PUSHER=$!
    TEST_RUNNER_ORCH_PUSH_TAP=1 xcodebuild ${XCB_ACTION:-test} -scheme OrchMobile -destination "id=$UDID" -derivedDataPath "$DD" \
      -only-testing:OrchMobileUITests/PushTapUITests/$test CODE_SIGN_IDENTITY=- CODE_SIGNING_REQUIRED=NO DEVELOPMENT_TEAM= CODE_SIGN_STYLE=Manual > "$DD/last.log" 2>&1; grep -E "Test Case.*(passed|failed)|error:" "$DD/last.log"
    kill $PUSHER 2>/dev/null
    echo "run $i $test done; crash reports: $(ls ~/Library/Logs/DiagnosticReports 2>/dev/null | grep -c OrchMobile)"
  done
done
rm -f "$PAY"
