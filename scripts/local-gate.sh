#!/bin/bash
# scripts/local-gate.sh : run the checks CI would run for the areas this branch touches (vs origin/develop). Run before every push.
#   Areas come from `git diff --name-only origin/develop...HEAD` (same path filters as .github/workflows/ci.yml).
#   Heavy parts go through the v2 global heavy lock. Last line: "local-gate: PASS (...)" or "local-gate: FAIL (...)".
# Env: HEAVY (default the v2 build heavy.sh), LANE (tag for the lock, default local-gate), BASE (default origin/develop).
set -u
ROOT=$(git rev-parse --show-toplevel) || exit 2; cd "$ROOT"
HEAVY=${HEAVY:-$HOME/orch-dev/state/v2-plan-2026-11-05/build/heavy.sh}; LANE=${LANE:-local-gate}; BASE=${BASE:-origin/develop}
export CARGO_TARGET_DIR=${CARGO_TARGET_DIR:-$HOME/orch-dev/.cargo-target-v2}
files=$(git diff --name-only "$BASE"...HEAD; git diff --name-only HEAD)   # committed + uncommitted
[ -n "$files" ] || { echo "local-gate: PASS (nothing changed vs $BASE)"; exit 0; }
has() { printf '%s\n' "$files" | grep -Eq "$1"; }
ran=(); failed=(); skipped=()
heavy() { if [ -x "$HEAVY" ]; then "$HEAVY" "$LANE" -- "$@"; else "$@"; fi; }
step() { # step <label> <dir> <cmd...>
  local label=$1 dir=$2; shift 2
  echo "== $label"; if (cd "$dir" && heavy "$@"); then ran+=("$label"); else failed+=("$label"); fi
}

contracts=0; workspace=0; addons=0
has '^contracts/' && contracts=1
{ has '^workspace/' || [ $contracts = 1 ]; } && workspace=1
{ has '^workspace-addons/' || [ $workspace = 1 ]; } && addons=1

[ $contracts = 1 ] && step contracts . uv run --with jsonschema --with rfc3339-validator --with cryptography python contracts/validate.py
if [ $workspace = 1 ]; then
  step workspace workspace sh -c 'uv sync -q && uv run ruff check . && uv run ruff format --check . && uv run pytest -q -m "not slow"'
fi
if [ $addons = 1 ]; then
  for d in workspace-addons/*/; do
    n=$(basename "$d")
    # a touched add-on, or any add-on when workspace/contracts changed (CI filter), runs its checks
    if has "^workspace-addons/$n/" || [ $workspace = 1 ]; then
      extra=""; [ "$n" = dashboard ] && extra='&& node --check src/orch_dashboard/web/app.js && node --check src/orch_dashboard/web/blocks.js'
      step "addon:$n" "$d" sh -c "uv sync -q && uv run ruff check . $extra && uv run pytest -q -m 'not slow'"
    fi
  done
  step tool-name-scan workspace sh -c 'uv sync -q && uv run pytest -q tests/test_adapters.py::test_no_tool_names_outside_the_adapter'
fi
for c in relay publish; do
  if has "^$c/" || has '^contracts/'; then
    [ -d "$c" ] || continue
    f=$(ls "$c"/src/*.rs 2>/dev/null | head -1); [ -n "$f" ] && touch "$f"   # force clippy to re-lint
    step "$c" "$c" sh -c 'cargo fmt --check && cargo clippy -j 4 --all-targets -- -D warnings && cargo test -j 4'
  fi
done
# web JS tests next to touched .js files (node --test), e.g. publish/web/file.test.js
tests=$(for j in $(printf '%s\n' "$files" | grep -E '\.(js|mjs)$'); do
  d=$(dirname "$j"); [ -d "$d" ] && ls "$d"/*.test.js 2>/dev/null; done | sort -u)
[ -n "$tests" ] && step "node-test" . node --test $tests
has '^mobile/' && skipped+=("mobile (needs Xcode, runs in CI only)")

for s in "${skipped[@]:-}"; do [ -n "$s" ] && echo "note: skipped $s"; done
if [ ${#failed[@]} -gt 0 ]; then echo "local-gate: FAIL (${failed[*]}) ran: ${ran[*]:-none}"; exit 1; fi
echo "local-gate: PASS (${ran[*]:-nothing to run for these paths})"
