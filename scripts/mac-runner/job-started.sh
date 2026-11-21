#!/bin/bash
# Runner hook before every job on this Mac's CI runner (ACTIONS_RUNNER_HOOK_JOB_STARTED, set by setup.sh; ORCH-1125).
# 1. Refuses a job that must never run here: anything but a push to develop, the nightly run, a manual run or a
#    release pull request (into main, from a branch of this repository). ci.yml's route job already sends nothing
#    else here; this is the second lock on the door (the repository is public: never a pull request from a fork).
# 2. Takes the shared `heavy` lock for the job's lifetime (the helpers count it as one busy heavy slot).
# A refused job is STOPPED, not only failed: the runner treats a failed hook as a failed step and would still run
# later steps marked `if: always()`, so the hook ends the job's Runner.Worker before any step of the job runs.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
# the job's lifetime = the Runner.Worker that runs it (this hook's ancestor)
worker=""; p=$PPID
for _ in 1 2 3 4 5 6 7 8; do
  c=$(ps -p "$p" -o command= 2>/dev/null) || break
  case $c in (*Runner.Worker*) worker=$p; break;; esac
  p=$(ps -p "$p" -o ppid= 2>/dev/null | tr -d ' '); [ -n "$p" ] && [ "$p" -gt 1 ] || break
done
refuse() {
  echo "mac runner: refused this job ($1). Only pushes to develop, the nightly run, manual runs and release pull requests run on this Mac." >&2
  [ -n "$worker" ] && [ -z "${ORCH_HOOK_TEST:-}" ] && kill -9 "$worker" 2>/dev/null
  exit 1
}
REPO=${ORCH_RUNNER_REPO:-}
[ -n "$REPO" ] || refuse "ORCH_RUNNER_REPO is not set for the runner"
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
[ -n "$worker" ] || worker=$PPID
echo "mac runner: waiting for the shared heavy lock ($(bash "$HERE/lock.sh" status | head -1))"
bash "$HERE/lock.sh" acquire heavy mac-runner "$worker" || { echo "mac runner: no heavy lock" >&2; exit 1; }
echo "mac runner: job ${GITHUB_JOB:-?} of run ${GITHUB_RUN_ID:-?} (${GITHUB_EVENT_NAME:-?}) starts with a throwaway home"
