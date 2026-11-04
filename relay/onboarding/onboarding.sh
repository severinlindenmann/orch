#!/bin/sh
# orch relay onboarding (macOS/Linux): installs orch if it is missing, then connects this folder to the relay.
# Usage: curl -fsSL __RELAY_URL__/onboarding.sh | sh -s -- --workspace ws_xxxxxxxxxx --token orn_...
set -eu
RELAY_URL="__RELAY_URL__"
WORKSPACE=""
TOKEN=""
while [ $# -gt 0 ]; do
  case "$1" in
    --workspace) WORKSPACE="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$WORKSPACE" ] || [ -z "$TOKEN" ]; then
  echo "Need --workspace and --token (from the relay admin)." >&2
  exit 2
fi
if ! command -v orch >/dev/null 2>&1; then
  echo "orch is not installed yet. Installing it..."
  curl -fsSL https://raw.githubusercontent.com/severinlindenmann/orch/__INSTALL_REF__/install.sh | ORCH_REF=__INSTALL_REF__ sh
  PATH="$HOME/.local/bin:$PATH"
  export PATH
fi
orch relay connect "$RELAY_URL" --workspace "$WORKSPACE" --token "$TOKEN"
