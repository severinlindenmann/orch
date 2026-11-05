#!/bin/sh
# Walkthrough against the live publish + relay. Tokens come from Proton Pass (never printed).
# Needs: node, uv, the Pass helper ~/orch-dev/scripts/pass-login.sh. Output: ~/orch-dev/state/fresh-start-2026-11-04/walkthrough/
set -eu
cd "$(dirname "$0")"
[ -d node_modules ] || npm i --no-audit --no-fund --silent
eval "$("$HOME/orch-dev/scripts/pass-login.sh")"
E2E_PUBLISH_ADMIN_TOKEN=$(pass-cli item view --vault-name Agents --item-title "orch publish admin token" --field password)
E2E_RELAY_ADMIN_TOKEN=$(pass-cli item view --vault-name Agents --item-title "orch relay admin token" --field password)
export E2E_PUBLISH_ADMIN_TOKEN E2E_RELAY_ADMIN_TOKEN
WALK_TMP=$(mktemp -d "$HOME/orch-dev/.tf-walk-XXXX")
# ORCH_HOME is only trusted under the real home with no .git above it (~/orch-dev has one): sibling folder
WALK_ORCH_HOME=$(mktemp -d "$HOME/.orch-e2e-XXXX")
export WALK_TMP WALK_ORCH_HOME
node walk.mjs || true
rm -rf "$WALK_TMP" "$WALK_ORCH_HOME"   # exact paths made above
