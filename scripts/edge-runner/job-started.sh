#!/bin/bash
# Runner hook before every job on the orch edge test server's CI runner (ACTIONS_RUNNER_HOOK_JOB_STARTED, set by
# setup.sh; ORCH-1126). Refuses a job that must never run here: anything but a push to develop, the nightly run, a
# manual run or a release pull request (into main, from a branch of this repository). ci.yml's route job already
# sends nothing else here; this is the second lock on the door (the repository is public: never a fork's pull request).
# A refused job is STOPPED, not only failed: the runner treats a failed hook as a failed step and would still run
# later steps marked `if: always()`, so the hook ends the job's Runner.Worker before any step of the job runs.
set -u
# a job can set its own environment variables: the hook uses a fixed PATH and nothing a job could have set
PATH=/usr/bin:/bin:/usr/sbin:/sbin; export PATH; unset BASH_ENV ENV CDPATH
HERE=$(cd "$(dirname "$0")" && pwd)
# the job's lifetime = the Runner.Worker that runs it (this hook's ancestor)
worker=""; p=$PPID
for _ in 1 2 3 4 5 6 7 8; do
  c=$(ps -p "$p" -o args= 2>/dev/null) || break
  case $c in (*Runner.Worker*) worker=$p; break;; esac
  p=$(ps -p "$p" -o ppid= 2>/dev/null | tr -d ' '); [ -n "$p" ] && [ "$p" -gt 1 ] || break
done
refuse() {
  echo "edge runner: refused this job ($1).${2- Only pushes to develop, the nightly run, manual runs and release pull requests run on orch edge.}" >&2
  [ -n "$worker" ] && kill -9 "$worker" 2>/dev/null
  exit 1
}
# The repository comes from the root-owned file setup.sh writes next to the hooks. A job can set its own environment
# variables, so the environment is read only where that file does not exist (the tests run the hook from the repo).
if [ -f "$HERE/repo" ]; then REPO=$(cat "$HERE/repo"); else REPO=${ORCH_RUNNER_REPO:-}; fi
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
# Fail closed: user services, timers or their folders left from an earlier job mean the clean-up did not hold. The job
# is refused (red) until a person looks, rather than run next to whatever is still there. Only vendor sockets
# (gpg-agent, ssh-agent) are active on a clean runner.
ME=$(id -u); REAL_HOME=$(getent passwd "$ME" | cut -d: -f6)
if [ "$(id -un)" = orch-ci ]; then
  for d in "$REAL_HOME/.config/systemd" "$REAL_HOME/.config/environment.d" "$REAL_HOME/.local/share/systemd"; do
    { [ -e "$d" ] || [ -L "$d" ]; } && refuse "$d is left from an earlier job (the clean-up did not hold)" " A person must look at orch edge first."
  done
  units=$(XDG_RUNTIME_DIR=/run/user/$ME systemctl --user list-units --type=service,timer,path --state=active,activating --plain --no-legend 2>/dev/null) \
    || refuse "the user service manager does not answer, so nobody can see what an earlier job left" " A person must look at orch edge first."
  left=$(printf '%s\n' "$units" | awk '{print $1}' | tr '\n' ' ')
  [ -z "${left// /}" ] || refuse "user services left from an earlier job: $left" " A person must look at orch edge first."
fi
echo "edge runner: job ${GITHUB_JOB:-?} of run ${GITHUB_RUN_ID:-?} (${GITHUB_EVENT_NAME:-?}) starts with a throwaway home"
