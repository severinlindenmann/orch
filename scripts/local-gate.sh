#!/bin/bash
# scripts/local-gate.sh : run the checks CI would run for the areas this branch touches (vs origin/develop). Run before every push.
#   Areas come from `git diff --name-only origin/develop...HEAD` (same path filters as .github/workflows/ci.yml).
#   Only cargo goes through the v2 global heavy lock; pytest runs under the light `t1` lease (3 slots, -n 4), ruff,
#   the contracts check and node --test run directly (7 Nov: every step behind the heavy lock made a 30 s check wait
#   8-15 min behind other lanes' cargo and Simulator runs). Last line: "local-gate: PASS (...)" or "local-gate: FAIL (...)".
# Env: HEAVY (default the v2 build heavy.sh), LANE (tag for the lock, default local-gate), BASE (default origin/develop).
set -u
export ORCH_HOME_STRICT=1   # an untrusted ORCH_HOME is an error, never a silent fallback to the real ~/.orch-tool
ROOT=$(git rev-parse --show-toplevel) || exit 2; cd "$ROOT" || exit 2
HEAVY=${HEAVY:-$HOME/orch-dev/state/v2-plan-2026-11-05/build/heavy.sh}; LANE=${LANE:-local-gate}; BASE=${BASE:-origin/develop}
export PATH="/opt/homebrew/opt/rustup/bin:$HOME/.rustup/toolchains/stable-aarch64-apple-darwin/bin:$PATH"  # cargo on this Mac
export CARGO_TARGET_DIR=${CARGO_TARGET_DIR:-$HOME/orch-dev/.cargo-target-v2}
files=$(git diff --name-only "$BASE"...HEAD; git diff --name-only HEAD)   # committed + uncommitted
[ -n "$files" ] || { echo "local-gate: PASS (nothing changed vs $BASE)"; exit 0; }
has() { printf '%s\n' "$files" | grep -Eq "$1"; }
ran=(); failed=(); skipped=()
LEASE=$HOME/orch-dev/scripts/lease.sh
heavy() { if [ -x "$HEAVY" ]; then "$HEAVY" "$LANE" -- "$@"; else "$@"; fi; }   # cargo: one at a time machine-wide
light() { if [ -x "$LEASE" ]; then "$LEASE" run t1 "$LANE" -- "$@"; else "$@"; fi; }  # pytest: a few at a time
direct() { "$@"; }
step() { # step <heavy|light|direct> <label> <dir> <cmd...>
  local how=$1 label=$2 dir=$3; shift 3
  echo "== $label"; if (cd "$dir" && "$how" "$@"); then ran+=("$label"); else failed+=("$label"); fi
}

contracts=0; workspace=0; addons=0
has '^contracts/' && contracts=1
{ has '^workspace/' || [ $contracts = 1 ]; } && workspace=1
{ has '^workspace-addons/' || [ $workspace = 1 ]; } && addons=1

[ $contracts = 1 ] && step direct contracts . uv run --with jsonschema --with rfc3339-validator --with cryptography python contracts/validate.py
if [ $workspace = 1 ]; then
  step light workspace workspace sh -c 'uv sync -q && uv run ruff check . && uv run ruff format --check . && uv run pytest -q -n 4 -m "not slow"'
fi
if [ $addons = 1 ]; then
  for d in workspace-addons/*/; do
    n=$(basename "$d")
    # a touched add-on, or any add-on when workspace/contracts changed (CI filter), runs its checks
    if has "^workspace-addons/$n/" || [ $workspace = 1 ]; then
      extra=""; [ "$n" = dashboard ] && extra='&& node --check src/orch_dashboard/web/app.js && for f in src/orch_dashboard/web/pages/*.js; do node --check $f || exit 1; done && node --check src/orch_dashboard/web/blocks.js'
      step light "addon:$n" "$d" sh -c "uv sync -q && uv run ruff check . $extra && uv run pytest -q -n 4 -m 'not slow'"
    fi
  done
  step direct tool-name-scan workspace sh -c 'uv sync -q && uv run pytest -q tests/test_adapters.py::test_no_tool_names_outside_the_adapter'
fi
for c in relay publish; do
  if has "^$c/" || has '^contracts/'; then
    [ -d "$c" ] || continue
    f=$(ls "$c"/src/*.rs 2>/dev/null | head -1); [ -n "$f" ] && touch "$f"   # force clippy to re-lint
    step heavy "$c" "$c" sh -c 'cargo fmt --check && cargo clippy -j 4 --all-targets -- -D warnings && cargo test -j 4'
  fi
done
# web JS tests next to touched .js files (node --test), e.g. publish/web/file.test.js
tests=$(for j in $(printf '%s\n' "$files" | grep -E '\.(js|mjs)$'); do
  d=$(dirname "$j"); [ -d "$d" ] && ls "$d"/*.test.js 2>/dev/null; done | sort -u)
[ -n "$tests" ] && step direct "node-test" . node --test $tests
has '^mobile/' && skipped+=("mobile (needs Xcode, runs in CI only)")

for s in "${skipped[@]:-}"; do [ -n "$s" ] && echo "note: skipped $s"; done
if [ ${#failed[@]} -gt 0 ]; then echo "local-gate: FAIL (${failed[*]}) ran: ${ran[*]:-none}"; exit 1; fi
echo "local-gate: PASS (${ran[*]:-nothing to run for these paths})"
