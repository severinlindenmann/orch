#!/usr/bin/env bash
# The relay browser page's click-through (ORCH-1197, #2495): a relay built from this checkout on loopback with a
# temp data folder, one browser signed in through /app with Playwright, 29 checks (clickthrough.mjs).
#
#   relay/tests/browser-page/run.sh [path/to/orch-relay]     default: relay/target/debug/orch-relay
#
# Needs node and Playwright with Chromium (PW_DIR = the folder that holds the playwright package, default
# `npm root -g`). Pictures and the relay log go to OUT (default: a temp folder). Exit 0 = every check passed.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
bin="${1:-$here/../../target/debug/orch-relay}"
[ -x "$bin" ] || { echo "no relay binary at $bin: run 'cargo build' in relay/ first" >&2; exit 2; }
tmp="$(mktemp -d)"
export OUT="${OUT:-$tmp/out}"
mkdir -p "$OUT" "$tmp/data"
export PW_DIR="${PW_DIR:-$(npm root -g)}"
port() { python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'; }
rp="$(port)"; ra="$(port)"
head -c 32 /dev/urandom > "$tmp/master.key"
export ADMIN_TOKEN="ct-$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
export PUB="http://127.0.0.1:$rp" ADM="http://127.0.0.1:$ra"
ORCH_RELAY_DATA_DIR="$tmp/data" ORCH_RELAY_MASTER_KEY_FILE="$tmp/master.key" \
  ORCH_RELAY_LISTEN="127.0.0.1:$rp" ORCH_RELAY_ADMIN_LISTEN="127.0.0.1:$ra" \
  ORCH_RELAY_ADMIN_TOKEN="$ADMIN_TOKEN" ORCH_RELAY_PUBLIC_ORIGIN="$PUB" \
  "$bin" > "$OUT/relay.log" 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; rm -rf "$tmp/data" "$tmp/master.key"' EXIT
for _ in $(seq 1 50); do
  curl -fs "$PUB/health" > /dev/null 2>&1 && break
  kill -0 "$pid" 2>/dev/null || { echo "the relay stopped at start; its log:" >&2; cat "$OUT/relay.log" >&2; exit 1; }
  sleep 0.2
done
curl -fs "$PUB/health" > /dev/null || { echo "the relay did not answer on $PUB/health; log in $OUT/relay.log" >&2; exit 1; }
node "$here/clickthrough.mjs"
