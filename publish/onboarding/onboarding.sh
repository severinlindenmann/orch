#!/bin/sh
# Connects this project to orch-publish. Installs orch first if it is missing.
# Usage: curl -fsSL __PUBLISH_URL__/onboarding.sh | sh -s -- --workspace ws_xxx --token orp_xxx
set -eu
URL="__PUBLISH_URL__"
INSTALL_URL="__INSTALL_URL__"
WS=""
TOKEN=""
while [ $# -gt 0 ]; do
  case "$1" in
    --workspace) WS="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$WS" ] || [ -z "$TOKEN" ]; then
  echo "Usage: sh -s -- --workspace <id> --token <token>" >&2
  exit 2
fi
if ! command -v orch >/dev/null 2>&1; then
  echo "Installing orch ..."
  curl -fsSL "$INSTALL_URL" | ORCH_REF="__INSTALL_REF__" sh
  PATH="$HOME/.local/bin:$PATH"
  export PATH
fi
orch addon add publish --yes
exec orch publish connect "$URL" --workspace "$WS" --token "$TOKEN"
