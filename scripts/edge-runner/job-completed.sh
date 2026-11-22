#!/bin/bash -p
# Runner hook after every job on the orch edge test server's CI runner (ACTIONS_RUNNER_HOOK_JOB_COMPLETED, set by
# setup.sh; ORCH-1126). Leaves nothing for the next job: stops and removes the throwaway user services a job made
# (the Services add-on's real Linux run), stops every process of the runner user except the runner itself and its
# user service manager, and empties this user's files in /tmp and /dev/shm. The job's throwaway home lives in the
# runner user's own home, which runner-loop.sh makes fresh. Before the next job runner-loop.sh (root) stops everything of
# orch-ci again and makes a fresh runner folder and home. Never fails the job.
# A job sets its own environment, and bash loads shell functions from it: a function (find, ps, kill) would replace
# that command here, whatever PATH says. So the hook first starts itself again as privileged bash (-p never loads
# functions from the environment) with only the values it needs. Only paths with a slash run before that line.
# Limit: bash reads BASH_ENV before any line of this file, so a job whose settings reach the hook can still run code
# first. The hook is the second lock; the first is the route job and GitHub holding outside contributors' runs (docs/ci-checks.md).
if [[ ${1-} != --orch-clean ]]; then   # the runner starts hooks without arguments; a job cannot add one
  pass=(PATH=/usr/bin:/bin:/usr/sbin:/sbin)
  for v in GITHUB_RUN_ID; do
    if [[ -n ${!v+x} ]]; then pass+=("$v=${!v}"); fi
  done
  /usr/bin/env -i "${pass[@]}" /bin/bash -p "$0" --orch-clean
else
set -u
set +e   # the runner runs hooks with bash -e; nothing here may stop the clean-up half way
# it stops every other process of its user: only ever as the runner's own user, never as a person
# one user per runner (setup.sh): orch-ci uses the runner folder job, orch-ci-K the folder job-K
case $(id -un) in
  (orch-ci) JOB=job;;
  (orch-ci-[2-9]) JOB=job-$(id -un | cut -d- -f3);;
  (*) echo "job-completed.sh: runs only as a runner user (orch-ci, orch-ci-2 ...); did nothing" >&2; exit 0;;
esac
HERE=$(cd "$(dirname "$0")" && pwd)
[ -f "$HERE/repo" ] && { PATH=/usr/bin:/bin:/usr/sbin:/sbin; export PATH; unset BASH_ENV ENV CDPATH; }
ME=$(id -u)
REAL_HOME=$(getent passwd "$ME" | cut -d: -f6)
export XDG_RUNTIME_DIR="/run/user/$ME"
# User services, timers, sockets, overrides and the manager's environment: the job could have changed any of them.
# In this order, so nothing of the job can write again while the next step runs:
#   1. RESTART the user service manager from the system side (the one command setup.sh allows this user with sudo):
#      every user unit and its processes end.
#   2. Stop every other leftover process of the user (below).
#   3. Remove the unit, environment and settings folders (also before step 1), restart the manager once more, check.
USER_DIRS="$REAL_HOME/.config/systemd $REAL_HOME/.config/environment.d $REAL_HOME/.local/share/systemd"
rm_user_dirs() { local d; for d in $USER_DIRS; do { [ -e "$d" ] || [ -L "$d" ]; } && rm -rf "$d"; done; }
restarted=0
rm_user_dirs   # before EVERY restart: a restarted manager must not start the job's units again
if sudo -n /usr/bin/systemctl restart "user@$ME.service" 2>/dev/null; then restarted=1; else
  # not set up for it (an older setup.sh): stop what the user manager runs, as well as it can from inside
  echo "edge runner: could not restart the user service manager; stopping its units one by one" >&2
  rm -rf "$XDG_RUNTIME_DIR/systemd/user.control" "$XDG_RUNTIME_DIR/systemd/user" 2>/dev/null
  systemctl --user daemon-reload >/dev/null 2>&1
  systemctl --user list-units --type=timer,path,socket,service,scope --state=active,activating,reloading,listening,waiting --plain --no-legend 2>/dev/null \
    | awk '{print $1}' | while read -r u; do
      case $u in (init.scope|"") continue;; esac
      systemctl --user stop "$u" >/dev/null 2>&1
    done
  systemctl --user reset-failed >/dev/null 2>&1
fi
# Every other process of this user is a leftover of the job (the user exists only for the runner): only the runner,
# its user service manager and this hook's own ancestors stay.
keep=" $$ "; p=$PPID
while [ -n "$p" ] && [ "$p" -gt 1 ]; do keep="$keep$p "; p=$(ps -p "$p" -o ppid= 2>/dev/null | tr -d ' '); done
# The runner is recognised by the program it runs (its own bin folder), never by words in a command line a job
# could copy.
RBIN=$(cd "$HERE/$JOB/bin" 2>/dev/null && pwd -P)   # the fresh runner folder runner-loop.sh makes per job
# The manager's PID comes from the system manager (a job cannot change it). (sd-pam) is the one child the manager
# starts in its first second (a job's own units are its children too, but start later). The session bus is NOT kept:
# a job could start it with its own settings; it is stopped like the rest and starts again when it is next needed.
# start time = field 22 of /proc/PID/stat, counted after the LAST ')' (the name in brackets may hold spaces)
start() { local st; st=$(cat "/proc/$1/stat" 2>/dev/null) || return; st=${st##*) }; set -- $st; echo "${20}"; }
SYSTEM_PIDS=""
mgr=$(systemctl show "user@$ME.service" -p MainPID --value 2>/dev/null)
if [ "${mgr:-0}" -gt 0 ] 2>/dev/null; then
  SYSTEM_PIDS=" $mgr"
  m0=$(start "$mgr"); hz=$(getconf CLK_TCK)
  for c in $(ps -o pid= --ppid "$mgr" 2>/dev/null); do
    c0=$(start "$c")
    [ -n "$c0" ] && [ -n "$m0" ] && [ $((c0 - m0)) -le "$hz" ] && { SYSTEM_PIDS="$SYSTEM_PIDS $c"; break; }
  done
fi
leftovers() {
  local pid exe
  ps -u "$ME" -o pid= | while read -r pid; do
    case "$keep" in (*" $pid "*) continue;; esac
    exe=$(readlink "/proc/$pid/exe" 2>/dev/null)
    case $exe in ("$RBIN"/Runner.Listener|"$RBIN"/Runner.Worker) [ -n "$RBIN" ] && continue;; esac
    # the user service manager, its (sd-pam) helper and its session bus: by the main PIDs systemd reports, never by a
    # control group (the user owns its own cgroup tree, so a job could move a process into init.scope)
    case " $SYSTEM_PIDS " in (*" $pid "*) continue;; esac
    [ "$(ps -p "$pid" -o ppid= 2>/dev/null | tr -d ' ')" = "$$" ] && continue   # this hook's own helpers
    echo "$pid"
  done
}
stray=$(leftovers)
if [ -n "$stray" ]; then
  echo "edge runner: stopping $(echo "$stray" | wc -l | tr -d ' ') leftover process(es) of the job"
  kill $stray 2>/dev/null; sleep 3
  stray=$(leftovers); [ -n "$stray" ] && kill -9 $stray 2>/dev/null
fi
find /tmp /var/tmp /dev/shm -mindepth 1 -maxdepth 1 -user "$ME" ! -name 'dotnet-diagnostic-*' ! -name 'clr-debug-pipe-*' -exec rm -rf {} + 2>/dev/null
rm_user_dirs
[ "$restarted" = 1 ] && sudo -n /usr/bin/systemctl restart "user@$ME.service" 2>/dev/null
rm_user_dirs
# Anything still there now is refused by the next job's start hook (job-started.sh): the runner then stays red
# until a person looks, rather than run the next job next to it.
for d in $USER_DIRS; do { [ -e "$d" ] || [ -L "$d" ]; } && echo "edge runner: $d came back after the clean-up; the next job will be refused" >&2; done
exit 0
fi
