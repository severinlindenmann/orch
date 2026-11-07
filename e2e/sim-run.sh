#!/bin/bash
# Usage: dir=$(e2e/sim-run.sh start)
# SIM_RUN_DIR=$dir ORCH_E2E_UDID=<udid> e2e/sim-run.sh build|test <test names...>|stop
# Build/test print shell commands for the lead to run through heavy.sh.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
action=${1:-}; [ "$#" -eq 0 ] || shift
case "$action" in
  start)
    dir=$(mktemp -d "$HOME/orch-dev/.tf-m3w7-XXXX")
    E2E_SIM_CTL="$dir/ctl" nohup "$repo/e2e/run.sh" V3-SIM >"$dir/harness.log" 2>&1 < /dev/null &
    pid=$!
    echo "$pid" > "$dir/pid"
    # run.sh uses env -i, dropping E2E_SIM_CTL. Expose its actual ctl via a symlink.
    while :; do
      tmp=$(sed -n 's/^e2e local: .* scenarios, tmp //p' "$dir/harness.log" | head -n 1)
      if [ -n "$tmp" ]; then
        mkdir -p "$tmp/ctl"
        ln -s "$tmp/ctl" "$dir/ctl"
        break
      fi
      if ! kill -0 "$pid" 2>/dev/null; then
        echo "Harness exited; see $dir/harness.log" >&2
        exit 1
      fi
      sleep 1
    done
    echo "$dir" # wait for ctl/info.json before testing
    ;;
  stop)
    touch "${SIM_RUN_DIR:?Set SIM_RUN_DIR to the directory printed by start}/ctl/stop"
    ;;
  build|test)
    dir=${SIM_RUN_DIR:?Set SIM_RUN_DIR to the directory printed by start}
    udid=${ORCH_E2E_UDID:?Set ORCH_E2E_UDID to the simulator UUID}
    printf 'cd %q && ' "$repo/mobile"
    if [ "$action" = build ]; then
      printf 'xcodegen generate && '
      xaction=build-for-testing
    else
      xaction=test-without-building
    fi
    cmd=(env "TEST_RUNNER_ORCH_E2E_CTL=$dir/ctl" "TEST_RUNNER_ORCH_E2E_UDID=$udid"
      "TEST_RUNNER_ORCH_SHOTS=$dir/shots" xcodebuild "$xaction"
      -project OrchMobile.xcodeproj -scheme OrchMobile -destination "id=$udid"
      -derivedDataPath "$dir/DerivedData" -parallel-testing-enabled NO)
    if [ "$action" = test ]; then
      if [ "$#" -eq 0 ]; then
        cmd+=(-only-testing:OrchMobileUITests/RealRelayE2ETests)
      else
        for name in "$@"; do cmd+=("-only-testing:OrchMobileUITests/RealRelayE2ETests/$name"); done
      fi
    fi
    printf '%q ' "${cmd[@]}"
    printf '\n'
    ;;
  *) echo 'Usage: sim-run.sh start|build|test <names...>|stop' >&2; exit 2 ;;
esac
