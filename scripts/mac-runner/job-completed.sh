#!/bin/bash
# Runner hook after every job on this Mac's CI runner (ACTIONS_RUNNER_HOOK_JOB_COMPLETED, set by setup.sh; ORCH-1125).
# Leaves nothing for the next job: stops the Simulators, stops every process of the runner user except the runner
# itself (dashboards, Chromium, Python, node the job left running), empties this user's temp folder and releases
# the shared locks. The job's throwaway home lives in the job's temp folder, which the runner wipes itself.
# Never fails the job.
# A job sets its own environment, and bash loads shell functions from it: a function (find, ps, kill) would replace
# that command here, whatever PATH says. So the hook first starts itself again as privileged bash (-p never loads
# functions from the environment) with only the values it needs. Only paths with a slash run before that line.
# Limit: bash reads BASH_ENV before any line of this file, so a job whose settings reach the hook can still run code
# first. The hook is the second lock; the first: GitHub holds every outside contributor's run until the owner clicks (docs/ci-checks.md).
if [[ ${1-} != --orch-clean ]]; then   # the runner starts hooks without arguments; a job cannot add one
  pass=(PATH=/usr/bin:/bin:/usr/sbin:/sbin)
  for v in GITHUB_RUN_ID ORCH_LOCK_DIR; do
    if [[ -n ${!v+x} ]]; then pass+=("$v=${!v}"); fi
  done
  /usr/bin/env -i "${pass[@]}" /bin/bash -p "$0" --orch-clean
else
set -u
set +e   # the runner runs hooks with bash -e; nothing here may stop the clean-up half way
# it stops every other process of its user: only ever as the runner's own user, never as a person
[ "$(id -un)" = orch-ci ] || { echo "job-completed.sh: runs only as the user orch-ci; did nothing" >&2; exit 0; }
HERE=$(cd "$(dirname "$0")" && pwd)
# installed: fixed PATH and lock settings, whatever the job set
[ -f "$HERE/repo" ] && unset ORCH_LOCK_DIR
trap 'bash "$HERE/lock.sh" release xcode "ci-${GITHUB_RUN_ID:-}"; bash "$HERE/lock.sh" release heavy mac-runner; exit 0' EXIT
ME=$(id -u)
xcrun simctl shutdown all >/dev/null 2>&1
# Every other process of this user is a leftover of the job (the user exists only for the runner): only the runner
# itself and this hook's own ancestors stay.
keep=" $$ "; p=$PPID
while [ -n "$p" ] && [ "$p" -gt 1 ]; do keep="$keep$p "; p=$(ps -p "$p" -o ppid= 2>/dev/null | tr -d ' '); done
# The runner is recognised by the program it runs (its own bin folder), never by words in a command line a job
# could copy. The pipeline below (ps, the loop's subshell) is a child of this hook and ends before the kill.
RBIN=$(cd ~orch-ci/actions-runner/bin 2>/dev/null && pwd -P)   # the account's home, not $HOME
leftovers() {
  local pid comm
  ps -U "$ME" -o pid=,comm= | while read -r pid comm; do
    case "$keep" in (*" $pid "*) continue;; esac
    case $comm in ("$RBIN"/Runner.Listener|"$RBIN"/Runner.Worker) [ -n "$RBIN" ] && continue;; esac
    [ "$(ps -p "$pid" -o ppid= 2>/dev/null | tr -d ' ')" = "$$" ] && continue   # this hook's own helpers
    echo "$pid"
  done
}
stray=$(leftovers)
if [ -n "$stray" ]; then
  echo "mac runner: stopping $(echo "$stray" | wc -l | tr -d ' ') leftover process(es) of the job"
  kill $stray 2>/dev/null; sleep 3
  stray=$(leftovers); [ -n "$stray" ] && kill -9 $stray 2>/dev/null
fi
# this user's temp folder as macOS knows it, never a folder the job named (not the .NET runtime's own sockets)
T=$(getconf DARWIN_USER_TEMP_DIR 2>/dev/null)
if [ -n "$T" ] && [ -d "$T" ]; then
  find "$T" -mindepth 1 -maxdepth 1 ! -name 'dotnet-diagnostic-*' ! -name 'clr-debug-pipe-*' -exec rm -rf {} + 2>/dev/null
fi
exit 0
fi
