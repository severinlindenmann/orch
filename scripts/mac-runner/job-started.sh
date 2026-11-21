#!/bin/bash
# Runner hook before every job on this Mac's CI runner (ACTIONS_RUNNER_HOOK_JOB_STARTED, set by setup.sh; ORCH-1125).
# 1. Refuses a job that must never run here: anything but a push to develop, the nightly run, a manual run or a
#    release pull request (into main, from a branch of this repository). ci.yml's route job already sends nothing
#    else here; this is the second lock on the door (the repository is public: never a pull request from a fork).
# 2. Takes the shared `heavy` lock for the job's lifetime (the helpers count it as one busy heavy slot).
# A refused job is STOPPED, not only failed: the runner treats a failed hook as a failed step and would still run
# later steps marked `if: always()`, so the hook ends the job's Runner.Worker before any step of the job runs.
# A job sets its own environment, and bash loads shell functions from it: a function (find, ps, kill) would replace
# that command here, whatever PATH says. So the hook first starts itself again as privileged bash (-p never loads
# functions from the environment) with only the values it needs. Only paths with a slash run before that line.
# Limit: bash reads BASH_ENV before any line of this file, so a job whose settings reach the hook can still run code
# first. The hook is the second lock; the first: GitHub holds every outside contributor's run until the owner clicks (docs/ci-checks.md).
if [[ ${1-} != --orch-clean ]]; then   # the runner starts hooks without arguments; a job cannot add one
  pass=(PATH=/usr/bin:/bin:/usr/sbin:/sbin)
  for v in GITHUB_REPOSITORY GITHUB_EVENT_NAME GITHUB_REF GITHUB_EVENT_PATH GITHUB_JOB GITHUB_RUN_ID ORCH_RUNNER_REPO \
           ORCH_LOCK_DIR ORCH_LOCK_TTL_MIN ORCH_LOCK_WAIT_SECS ORCH_LOCK_POLL_SECS; do
    if [[ -n ${!v+x} ]]; then pass+=("$v=${!v}"); fi
  done
  /usr/bin/env -i "${pass[@]}" /bin/bash -p "$0" --orch-clean
else
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
# the job's lifetime = the Runner.Worker that runs it (an ancestor; the parent is this hook's first start)
worker=""; p=$PPID
for _ in 1 2 3 4 5 6 7 8; do
  c=$(ps -p "$p" -o command= 2>/dev/null) || break
  case $c in (*Runner.Worker*) worker=$p; break;; esac
  p=$(ps -p "$p" -o ppid= 2>/dev/null | tr -d ' '); [ -n "$p" ] && [ "$p" -gt 1 ] || break
done
refuse() {
  echo "mac runner: refused this job ($1). Only pushes to develop, the nightly run, manual runs and release pull requests run on this Mac." >&2
  # Only the copy setup.sh installed stops the job: its repo file is owned by root, which no job can fake. Run from
  # the repository (the tests on GitHub's machines run inside a real Runner.Worker) it only fails.
  if [ -n "$worker" ] && [ -n "$(find "$HERE/repo" -maxdepth 0 -user 0 2>/dev/null)" ]; then kill -9 "$worker" 2>/dev/null; fi
  exit 1
}
# The repository comes from the root-owned file setup.sh writes next to the hooks. A job can set its own environment
# variables, so the environment is read only where that file does not exist (the tests run the hook from the repo).
if [ -f "$HERE/repo" ]; then REPO=$(cat "$HERE/repo"); unset ORCH_LOCK_DIR ORCH_LOCK_TTL_MIN ORCH_LOCK_WAIT_SECS ORCH_LOCK_POLL_SECS
else REPO=${ORCH_RUNNER_REPO:-}; fi
[ -n "$REPO" ] || refuse "no repository is set for the runner"
verdict=$(/usr/bin/python3 -I - "$REPO" <<'PY'
import json, os, sys
repo = sys.argv[1]
event = os.environ.get("GITHUB_EVENT_NAME", "")
ref = os.environ.get("GITHUB_REF", "")
if os.environ.get("GITHUB_REPOSITORY", "") != repo:
    print("no: job of another repository"); sys.exit()
if event == "push":
    print("ok" if ref == "refs/heads/develop" else "no: push to " + ref); sys.exit()
if event in ("schedule", "workflow_dispatch"):
    print("ok"); sys.exit()
if event == "pull_request":
    try:
        pr = json.load(open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8"))["pull_request"]
    except Exception as e:  # noqa: BLE001
        print("no: event file unreadable (" + type(e).__name__ + ")"); sys.exit()
    head = ((pr.get("head") or {}).get("repo") or {}).get("full_name")
    base = (pr.get("base") or {}).get("ref")
    if head != repo:
        print("no: pull request from a fork"); sys.exit()
    print("ok" if base == "main" else "no: pull request into " + str(base)); sys.exit()
print("no: event " + event)
PY
)
case $verdict in
  ok) ;;
  *) refuse "${verdict#no: }" ;;
esac
[ -n "$worker" ] || worker=$(ps -p "$PPID" -o ppid= 2>/dev/null | tr -d ' ')   # who started the hook
echo "mac runner: waiting for the shared heavy lock ($(bash "$HERE/lock.sh" status | head -1))"
bash "$HERE/lock.sh" acquire heavy mac-runner "$worker" || { echo "mac runner: no heavy lock" >&2; exit 1; }
echo "mac runner: job ${GITHUB_JOB:-?} of run ${GITHUB_RUN_ID:-?} (${GITHUB_EVENT_NAME:-?}) starts with a throwaway home"
fi
