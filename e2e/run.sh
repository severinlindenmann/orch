#!/bin/sh
# orch e2e: e2e/run.sh <id|all> [--mode local|live] [--fast]
# Everything runs in a temp folder under a clean environment (env -i): no ORCH_*/XDG_* from the dev shell.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
case "${1:-}" in agents|AG-*|v2real|V2-R3*|V2-R4*|V2-R5*|V2-R7*|V2-R8*|V2-R9*) exec sh "$HERE/agents/run.sh" "$@" ;; esac  # scenarios with real agents
REPO=$(cd "$HERE/.." && pwd)
WHAT=${1:-all}; [ $# -gt 0 ] && shift
MODE=local; EXTRA=""
while [ $# -gt 0 ]; do
  case "$1" in
    --mode) MODE=$2; shift 2 ;;
    --fast) EXTRA="$EXTRA --fast"; shift ;;
    *) echo "unknown option $1"; exit 2 ;;
  esac
done
REAL_HOME=$HOME
mkdir -p "$REAL_HOME/orch-dev"
TMP=$(mktemp -d "$REAL_HOME/orch-dev/.tf-e2e-XXXX")
# ORCH_HOME is only trusted under the REAL home with no .git/.orch/.agents above it: ~/orch-dev has a .git, so use a sibling folder
OHOME=$(mktemp -d "$REAL_HOME/.orch-e2e-XXXX")
trap 'rm -rf "$TMP" "$OHOME"' EXIT INT TERM
mkdir -p "$TMP/home"

BINS='{}'
if [ "$MODE" = local ]; then
  case "$WHAT" in
    all|P*|R*|M*|F*|*,P*|*,R*|V2|V2-P6*|V2-W2*|*,V2-P6*|*,V2-W2*)
      export PATH="/opt/homebrew/opt/rustup/bin:$PATH"
      ( cd "$REPO/publish" && cargo build --release -j 4 -q )
      ( cd "$REPO/relay" && cargo build --release -j 4 -q )
      BINS="{\"publish\": \"$REPO/publish/target/release/orch-publish\", \"relay\": \"$REPO/relay/target/release/orch-relay\"}" ;;
  esac
fi

# live: admin tokens from Proton Pass (never printed): "orch publish admin token", "orch relay admin token"
if [ "$MODE" = live ] && [ -z "${E2E_PUBLISH_ADMIN_TOKEN:-}" ] && [ -x "$REAL_HOME/orch-dev/scripts/pass-login.sh" ]; then
  . /dev/stdin <<PASS || true
$("$REAL_HOME/orch-dev/scripts/pass-login.sh" 2>/dev/null)
PASS
  LIST=$(pass-cli item list --vault-name Agents 2>/dev/null || true)
  for T in "publish:E2E_PUBLISH_ADMIN_TOKEN" "relay:E2E_RELAY_ADMIN_TOKEN"; do
    ID=$(printf '%s\n' "$LIST" | grep "orch ${T%%:*} admin token (state=Active)" | sed 's/^- \[\(.*\)\]:.*/\1/' | head -1)
    [ -n "$ID" ] && export "${T##*:}=$(pass-cli item view --vault-name Agents --item-id "$ID" --field password 2>/dev/null || true)"
  done
fi

# minimal PATH: uv, node, git, claude, codex live in these folders
EXTRA_PATH=""
for c in uv node git claude codex python3 tmux; do
  p=$(command -v "$c" 2>/dev/null || true)
  [ -n "$p" ] && EXTRA_PATH="$EXTRA_PATH:$(dirname "$p")"
done
EXTRA_PATH=${EXTRA_PATH#:}

env -i HOME="$TMP/home" PATH="$(dirname "$(command -v uv)"):/usr/bin:/bin" USER=e2e LANG=en_US.UTF-8 TERM=dumb \
  E2E_PUBLISH_ADMIN_TOKEN="${E2E_PUBLISH_ADMIN_TOKEN:-}" E2E_RELAY_ADMIN_TOKEN="${E2E_RELAY_ADMIN_TOKEN:-}" \
  E2E_PATH_EXTRA="$EXTRA_PATH" E2E_ORCH_HOME="$OHOME" E2E_REAL_HOME="$REAL_HOME" UV_CACHE_DIR="${UV_CACHE_DIR:-$REAL_HOME/.cache/uv}" \
  uv run --no-project --quiet --with cryptography --with jsonschema python "$HERE/main.py" "$WHAT" --mode "$MODE" \
  --tmp "$TMP" --repo "$REPO" --bins "$BINS" $EXTRA
