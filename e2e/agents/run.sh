#!/bin/sh
# e2e with REAL agents (claude -p, codex exec): e2e/run.sh agents|AG-<id>[,AG-<id>] [--mode live]
# Same clean environment as e2e/run.sh (env -i, temp HOME). Secrets: admin tokens + Claude setup-token from Proton Pass
# (never printed); Codex auth.json is copied into <tmp>/codex and deleted at the end.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
WHAT=${1:-agents}; [ $# -gt 0 ] && shift
MODE=live
while [ $# -gt 0 ]; do
  case "$1" in
    --mode) MODE=$2; shift 2 ;;
    *) echo "unknown option $1"; exit 2 ;;
  esac
done
[ "$MODE" = live ] || { echo "agent scenarios run in live mode only"; exit 2; }
REAL_HOME=$HOME
TMP=$(mktemp -d "$REAL_HOME/orch-dev/.tf-agents-XXXX")
trap 'rm -rf "$TMP/codex"; rm -rf "$TMP"' EXIT INT TERM
mkdir -p "$TMP/home" "$TMP/tools"

if [ -z "${E2E_PUBLISH_ADMIN_TOKEN:-}" ] && [ -x "$REAL_HOME/orch-dev/scripts/pass-login.sh" ]; then
  . /dev/stdin <<PASS || true
$("$REAL_HOME/orch-dev/scripts/pass-login.sh" 2>/dev/null)
PASS
  export PROTON_PASS_AGENT_REASON="orch e2e agents"
  LIST=$(pass-cli item list --vault-name Agents 2>/dev/null || true)
  for T in "orch publish admin token:E2E_PUBLISH_ADMIN_TOKEN" "orch relay admin token:E2E_RELAY_ADMIN_TOKEN" \
           "Claude setup-token lindenmann@severin.io:E2E_CLAUDE_TOKEN"; do
    ID=$(printf '%s\n' "$LIST" | grep -F "${T%%:*}" | grep -F "(state=Active)" | sed 's/^- \[\(.*\)\]:.*/\1/' | head -1)
    [ -n "$ID" ] && export "${T##*:}=$(pass-cli item view --vault-name Agents --item-id "$ID" --field password 2>/dev/null || true)"
  done
fi

# agent CLIs: link the real binaries (not the cmux shims) into <tmp>/tools
CLAUDE_BIN=""; for c in "$REAL_HOME/.local/bin/claude" /opt/homebrew/bin/claude /usr/local/bin/claude; do [ -x "$c" ] && CLAUDE_BIN=$c && break; done
CODEX_BIN=""; for c in $(which -a codex 2>/dev/null); do case "$c" in *cmuxterm*) ;; *) CODEX_BIN=$c; break ;; esac; done
[ -n "$CLAUDE_BIN" ] && ln -s "$CLAUDE_BIN" "$TMP/tools/claude"
[ -n "$CODEX_BIN" ] && ln -s "$CODEX_BIN" "$TMP/tools/codex"
if [ -f "$REAL_HOME/.codex/auth.json" ]; then mkdir -p "$TMP/codex"; cp "$REAL_HOME/.codex/auth.json" "$TMP/codex/auth.json"; chmod 600 "$TMP/codex/auth.json"; fi

EXTRA_PATH="$TMP/tools"
for c in uv node git python3; do
  p=$(command -v "$c" 2>/dev/null || true)
  [ -n "$p" ] && EXTRA_PATH="$EXTRA_PATH:$(dirname "$p")"
done

env -i HOME="$TMP/home" PATH="$(dirname "$(command -v uv)"):/usr/bin:/bin" USER=e2e LANG=en_US.UTF-8 TERM=dumb \
  E2E_PUBLISH_ADMIN_TOKEN="${E2E_PUBLISH_ADMIN_TOKEN:-}" E2E_RELAY_ADMIN_TOKEN="${E2E_RELAY_ADMIN_TOKEN:-}" \
  E2E_CLAUDE_TOKEN="${E2E_CLAUDE_TOKEN:-}" E2E_AGENT_RUNS="${E2E_AGENT_RUNS:-$REAL_HOME/orch-dev/state/fresh-start-2026-11-04/agent-runs}" \
  E2E_PATH_EXTRA="$EXTRA_PATH" E2E_REAL_HOME="$REAL_HOME" UV_CACHE_DIR="${UV_CACHE_DIR:-$REAL_HOME/.cache/uv}" \
  uv run --no-project --quiet --with cryptography --with jsonschema --with rfc3339-validator \
  python "$HERE/main.py" "$WHAT" --mode "$MODE" --tmp "$TMP" --repo "$REPO"
