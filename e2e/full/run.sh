#!/bin/sh
# orch full e2e (plan B): e2e/full/run.sh [--quick|--full] [--sha <commit>] [--lanes S,A,B] [--no-windows] [--phone]
#                                         [--real-agents] [--no-review] [--no-build] [--keep-root]
# One command. Holds the global heavy lock (v2 build) when it exists. Everything runs under one root
# ~/.tf-fe2e-XXXX with `env -i`; the real ~/.orch-tool and ~/.config/orch are never touched. Report: ~/orch-dev/state/e2e-full/reports/
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
REAL_HOME=$HOME
HEAVY="$REAL_HOME/orch-dev/state/v2-plan-2026-11-05/build/heavy.sh"
if [ -z "${E2E_FULL_LOCKED:-}" ] && [ -x "$HEAVY" ]; then
  E2E_FULL_LOCKED=1 exec "$HEAVY" e2e-full -- "$HERE/run.sh" "$@"
fi
MODE=quick; REAL_AGENTS=0; KEEP=0
# keep every argument as ONE word (a value may contain spaces, e.g. --build-label "TF 1"): rebuild "$@" without --quick/--full
n=$#
while [ "$n" -gt 0 ]; do
  a=$1; shift; n=$((n - 1))
  case "$a" in
    --quick) MODE=quick ;;
    --full) MODE=full ;;
    --real-agents) REAL_AGENTS=1; set -- "$@" "$a" ;;
    --keep-root) KEEP=1; set -- "$@" "$a" ;;
    *) set -- "$@" "$a" ;;
  esac
done
if [ -n "${E2E_FULL_ARGS_ONLY:-}" ]; then printf 'mode=%s\n' "$MODE"; for a in "$@"; do printf 'arg=%s\n' "$a"; done; exit 0; fi
df -k "$REAL_HOME" | awk 'NR==2 && $4 < 5000000 { print "under 5 GB free: stop"; exit 1 }'
[ -d "$HERE/web/node_modules" ] || (cd "$HERE/web" && npm_config_cache="$REAL_HOME/.npm" npm i --no-audit --no-fund --silent)
ROOT=$(mktemp -d "$REAL_HOME/.tf-fe2e-XXXX")
OHOME=$(mktemp -d "$REAL_HOME/.orch-e2e-XXXX")   # ORCH_HOME is only trusted under the real home outside any git repo
trap '[ "$KEEP" = 1 ] || rm -rf "$ROOT" "$OHOME"' EXIT
trap 'exit 130' INT TERM
mkdir -p "$ROOT/home" "$ROOT/tools"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$REAL_HOME/orch-dev/.cargo-target-v2}"

# Claude login: only for --real-agents (about 25 short runs), from Proton Pass, written nowhere
if [ "$REAL_AGENTS" = 1 ] && [ -x "$REAL_HOME/orch-dev/scripts/pass-login.sh" ]; then
  . /dev/stdin <<PASS || true
$("$REAL_HOME/orch-dev/scripts/pass-login.sh" 2>/dev/null)
PASS
  export PROTON_PASS_AGENT_REASON="orch full e2e real agents"
  LIST=$(pass-cli item list --vault-name Agents 2>/dev/null || true)
  ID=$(printf '%s\n' "$LIST" | grep -F "Claude setup-token lindenmann@severin.io" | grep -F "(state=Active)" | sed 's/^- \[\(.*\)\]:.*/\1/' | head -1)
  [ -n "$ID" ] && export E2E_CLAUDE_TOKEN="$(pass-cli item view --vault-name Agents --item-id "$ID" --field password 2>/dev/null || true)"
fi
CLAUDE_BIN=""; for c in "$REAL_HOME/.local/bin/claude" /opt/homebrew/bin/claude /usr/local/bin/claude; do [ -x "$c" ] && CLAUDE_BIN=$c && break; done
[ -n "$CLAUDE_BIN" ] && ln -s "$CLAUDE_BIN" "$ROOT/tools/claude"
EXTRA_PATH="$ROOT/tools"
for c in uv node git python3 tmux; do p=$(command -v "$c" 2>/dev/null || true); [ -n "$p" ] && EXTRA_PATH="$EXTRA_PATH:$(dirname "$p")"; done

env -i HOME="$ROOT/home" PATH="$(dirname "$(command -v uv)"):$(dirname "$(command -v node)"):/usr/bin:/bin" USER=e2e LANG=en_US.UTF-8 TERM=dumb ORCH_HOME_STRICT=1 \
  E2E_CLAUDE_TOKEN="${E2E_CLAUDE_TOKEN:-}" E2E_PATH_EXTRA="$EXTRA_PATH" E2E_ORCH_HOME="$OHOME" E2E_REAL_HOME="$REAL_HOME" \
  UV_CACHE_DIR="${UV_CACHE_DIR:-$REAL_HOME/.cache/uv}" CARGO_TARGET_DIR="$CARGO_TARGET_DIR" \
  uv run --no-project --quiet --with cryptography --with jsonschema --with rfc3339-validator \
  python "$HERE/harness/main.py" --mode "$MODE" --repo "$REPO" --root "$ROOT" "$@"
