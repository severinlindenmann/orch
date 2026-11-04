#!/bin/sh
# orch e2e: e2e/run.sh <id|all> [--mode local|live] [--fast]
# Everything runs in a temp folder under a clean environment (env -i): no ORCH_*/XDG_* from the dev shell.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
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
TMP=$(mktemp -d "$REAL_HOME/orch-dev/.tf-e2e-XXXX")
trap 'rm -rf "$TMP"' EXIT INT TERM
mkdir -p "$TMP/home"

BINS='{}'
if [ "$MODE" = local ]; then
  case "$WHAT" in
    all|P*|R*|M*|F*|A3)
      export PATH="/opt/homebrew/opt/rustup/bin:$PATH"
      ( cd "$REPO/publish" && cargo build --release -j 4 -q )
      ( cd "$REPO/relay" && cargo build --release -j 4 -q )
      BINS="{\"publish\": \"$REPO/publish/target/release/orch-publish\", \"relay\": \"$REPO/relay/target/release/orch-relay\"}" ;;
  esac
fi

# minimal PATH: uv, node, git, claude, codex live in these folders
EXTRA_PATH=""
for c in uv node git claude codex python3; do
  p=$(command -v "$c" 2>/dev/null || true)
  [ -n "$p" ] && EXTRA_PATH="$EXTRA_PATH:$(dirname "$p")"
done
EXTRA_PATH=${EXTRA_PATH#:}

env -i HOME="$TMP/home" PATH="$(dirname "$(command -v uv)"):/usr/bin:/bin" USER=e2e LANG=en_US.UTF-8 TERM=dumb \
  E2E_PATH_EXTRA="$EXTRA_PATH" E2E_REAL_HOME="$REAL_HOME" UV_CACHE_DIR="${UV_CACHE_DIR:-$REAL_HOME/.cache/uv}" \
  uv run --no-project --quiet --with cryptography python "$HERE/main.py" "$WHAT" --mode "$MODE" \
  --tmp "$TMP" --repo "$REPO" --bins "$BINS" $EXTRA
