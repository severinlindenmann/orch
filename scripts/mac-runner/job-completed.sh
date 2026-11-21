#!/bin/bash
# Runner hook after every job on this Mac's CI runner (ACTIONS_RUNNER_HOOK_JOB_COMPLETED, set by setup.sh; ORCH-1125).
# Leaves nothing for the next job: stops the Simulators, stops every process of the runner user except the runner
# itself (dashboards, Chromium, Python, node the job left running), empties this user's temp folder and releases
# the shared locks. The job's throwaway home lives in the job's temp folder, which the runner wipes itself.
# Never fails the job.
set -u
set +e   # the runner runs hooks with bash -e; nothing here may stop the clean-up half way
HERE=$(cd "$(dirname "$0")" && pwd)
trap 'bash "$HERE/lock.sh" release xcode "ci-${GITHUB_RUN_ID:-}"; bash "$HERE/lock.sh" release heavy mac-runner; exit 0' EXIT
ME=$(id -u)
xcrun simctl shutdown all >/dev/null 2>&1
# Every other process of this user is a leftover of the job (the user exists only for the runner): only the runner
# itself and this hook's own ancestors stay.
keep=" $$ "; p=$PPID
while [ -n "$p" ] && [ "$p" -gt 1 ]; do keep="$keep$p "; p=$(ps -p "$p" -o ppid= 2>/dev/null | tr -d ' '); done
leftovers() {
  local pid cmd
  ps -U "$ME" -o pid=,command= | while read -r pid cmd; do
    case "$keep" in (*" $pid "*) continue;; esac
    case $cmd in (*Runner.Listener*|*Runner.Worker*|*/run.sh*|*/run-helper.sh*|*job-completed.sh*|*"ps -U"*) continue;; esac
    echo "$pid"
  done
}
stray=$(leftovers)
if [ -n "$stray" ]; then
  echo "mac runner: stopping $(echo "$stray" | wc -l | tr -d ' ') leftover process(es) of the job"
  kill $stray 2>/dev/null; sleep 3
  stray=$(leftovers); [ -n "$stray" ] && kill -9 $stray 2>/dev/null
fi
# this user's temp folder (not the .NET runtime's own sockets)
if [ -n "${TMPDIR:-}" ] && [ -d "$TMPDIR" ]; then
  find "$TMPDIR" -mindepth 1 -maxdepth 1 ! -name 'dotnet-diagnostic-*' ! -name 'clr-debug-pipe-*' -exec rm -rf {} + 2>/dev/null
fi
exit 0
