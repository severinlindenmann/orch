#!/usr/bin/env bash
# One Windows run in a fresh winvm clone (ORCH-1127): make a clone of golden, set it up, run the workspace tests,
# the CLI smoke with the junction check and the standard-user install, pull the results, and remove the clone - also when a step fails or the run is stopped.
#   e2e/winvm/run.sh <commit> [out-dir]          env: WINVM_CLONE (o1127), WINVM_CPUS (4), WINVM_MEM (8G), WINVM_PART (1/1)
#   WINVM_REPO: the git clone that holds <commit> (default: the one this script is in).
# At most one clone at a time from this lane: a lock folder; a second run waits for it (or exits 75 with --no-wait).
set -euo pipefail
COMMIT="${1:?commit}"; OUT="${2:-$PWD/winvm-out}"
NAME="${WINVM_CLONE:-o1127}"; CPUS="${WINVM_CPUS:-4}"; MEM="${WINVM_MEM:-8G}"; PART="${WINVM_PART:-1/1}"
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="${WINVM_REPO:-$(git -C "$HERE" rev-parse --show-toplevel)}"
LOCK="${WINVM_LOCK:-$HOME/.orch-test/winvm-$NAME.lock}"
export PATH="$HOME/.local/bin:$PATH"
mkdir -p "$OUT" "$(dirname "$LOCK")"

# Lock: mkdir is atomic; a lock left by a dead run (its pid gone) is taken over.
while ! mkdir "$LOCK" 2>/dev/null; do
  pid="$(cat "$LOCK/pid" 2>/dev/null || true)"
  if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then echo "stale lock of pid $pid, taking it over"; rm -f "$LOCK/pid"; rmdir "$LOCK" 2>/dev/null || true; continue; fi
  [ "${WINVM_NO_WAIT:-}" = 1 ] && { echo "clone $NAME busy (pid $pid)"; exit 75; }
  sleep 30
done
echo $$ > "$LOCK/pid"

cleanup() {
  rc=$?
  winvm stop "$NAME" >/dev/null 2>&1 || winvm stop "$NAME" --force >/dev/null 2>&1 || true
  if winvm rm "$NAME" >/dev/null 2>&1 || ! winvm ls 2>/dev/null | grep -q "^$NAME "; then echo "clone $NAME removed"
  else echo "WARNING: clone $NAME could not be removed"; rc=1; fi
  rm -f "$LOCK/pid"; rmdir "$LOCK" 2>/dev/null || true
  exit $rc
}
trap cleanup EXIT
trap 'exit 130' INT TERM

t0=$SECONDS
stamp() { echo "STEP $1 $((SECONDS - $2))s" | tee -a "$OUT/timings.txt"; }
: > "$OUT/timings.txt"

# A clone left behind by a crashed run of this lane is removed first (it is ours: same name).
winvm ls | grep -q "^$NAME " && { winvm stop "$NAME" >/dev/null 2>&1 || true; winvm rm "$NAME"; }
t=$SECONDS; winvm create "$NAME" "$CPUS" "$MEM"; winvm start "$NAME"; stamp clone-up $t

t=$SECONDS
git -C "$REPO" archive --format=zip -o "$OUT/src.zip" "$COMMIT"
winvm ssh "$NAME" 'New-Item -ItemType Directory -Force C:\ci | Out-Null'
winvm push "$NAME" "$OUT/src.zip" C:/ci/src.zip
winvm run "$NAME" "$HERE/setup.ps1" | tee "$OUT/setup.log"
stamp setup $t

t=$SECONDS; set +e
# winvm passes arguments as quoted strings ('-Part' never binds as a name): positional arguments only.
job="$(winvm run "$NAME" --detach "$HERE/tests.ps1" "$PART" "$CPUS" | sed -n 's/.*job \([0-9A-Za-z_-]*\) started.*/\1/p' | tail -1)"
[ -n "$job" ] || { echo "no job id from winvm run --detach"; exit 1; }
# A hung job must not hold the only clone: the tests get WINVM_TEST_MAX seconds (default 3 h), then count as failed.
max="${WINVM_TEST_MAX:-10800}"
while :; do
  winvm wait "$NAME" "$job" 540 > "$OUT/tests.log" 2>&1; trc=$?
  [ $trc -eq 124 ] || break
  [ $((SECONDS - t)) -lt "$max" ] || { echo "tests still running after ${max}s: stopped" >> "$OUT/tests.log"; trc=124; break; }
done
set -e; stamp tests $t
winvm pull "$NAME" C:/ci/junit.xml "$OUT/junit.xml" || true

t=$SECONDS; set +e
winvm run "$NAME" "$HERE/smoke.ps1" > "$OUT/smoke.log" 2>&1; src=$?
set -e; stamp smoke $t

t=$SECONDS; set +e
winvm run "$NAME" "$HERE/standard-user.ps1" "$COMMIT" > "$OUT/standard-user.log" 2>&1; urc=$?
set -e; stamp standard-user $t
stamp total $t0
echo "tests rc=$trc smoke rc=$src standard-user rc=$urc" | tee -a "$OUT/timings.txt"
[ $trc -eq 0 ] && [ $src -eq 0 ] && [ $urc -eq 0 ]
