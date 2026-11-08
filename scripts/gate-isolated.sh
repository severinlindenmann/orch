#!/bin/bash
# (GATE_CMD overrides the gate command, for tests.)
# scripts/gate-isolated.sh [gate args...] : run scripts/local-gate.sh in a throwaway HOME (so nothing touches the real
#   ~/.orch-tool) while sharing the real uv/npm caches (a fresh home otherwise re-downloads ~4.8 GB per run).
#   PASS: the temp home is deleted (exact path). FAIL: it is kept for debugging; the previously kept failing home is
#   deleted first (path in ~/.orch-test/.last-failed-gate), so at most one failing home exists.
set -u
REAL_HOME=$HOME
ROOT=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$REAL_HOME/.orch-test"
TMP=$(mktemp -d "$REAL_HOME/.orch-test/gate-XXXX") || exit 2
case "$TMP" in "$REAL_HOME"/.orch-test/gate-????*) ;; *) echo "gate-isolated: unexpected temp path $TMP" >&2; exit 2;; esac
STATE="${GATE_STATE:-$REAL_HOME/.orch-test/.last-failed-gate}"
rc=1
cleanup() {
  if [ "$rc" = 0 ]; then
    rm -rf "$TMP"
  else
    if [ -f "$STATE" ]; then
      old=$(cat "$STATE")
      case "$old" in "$REAL_HOME"/.orch-test/gate-????*) [ "$old" != "$TMP" ] && [ -d "$old" ] && rm -rf "$old";; esac
    fi
    printf '%s\n' "$TMP" > "$STATE"
    echo "gate-isolated: FAILED, temp home kept for debugging: $TMP" >&2
  fi
}
trap cleanup EXIT
cd "$ROOT" || exit 2
env -i HOME="$TMP" PATH="$PATH" ORCH_HOME="$TMP/.orch-tool" ORCH_HOME_STRICT=1 \
  UV_CACHE_DIR="$REAL_HOME/.cache/uv" npm_config_cache="$REAL_HOME/.npm" XDG_CACHE_HOME="$TMP/.cache" \
  LANG="${LANG:-en_US.UTF-8}" REAL_HOME="$REAL_HOME" RUSTUP_HOME="${RUSTUP_HOME:-$REAL_HOME/.rustup}" CARGO_HOME="${CARGO_HOME:-$REAL_HOME/.cargo}" ${LANE:+LANE="$LANE"} ${BASE:+BASE="$BASE"} \
  "${GATE_CMD:-$ROOT/scripts/local-gate.sh}" "$@"
rc=$?
exit $rc
