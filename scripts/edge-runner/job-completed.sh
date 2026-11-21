#!/bin/bash
# Runner hook after every job on the orch edge test server's CI runner (ACTIONS_RUNNER_HOOK_JOB_COMPLETED, set by
# setup.sh; ORCH-1126). Leaves nothing for the next job: stops and removes the throwaway user services a job made
# (the Services add-on's real Linux run), stops every process of the runner user except the runner itself and its
# user service manager, and empties this user's files in /tmp and /dev/shm. The job's throwaway home lives in the
# job's temp folder, which the runner wipes itself. Never fails the job.
set -u
set +e   # the runner runs hooks with bash -e; nothing here may stop the clean-up half way
# it stops every other process of its user: only ever as the runner's own user, never as a person
[ "$(id -un)" = orch-ci ] || { echo "job-completed.sh: runs only as the user orch-ci; did nothing" >&2; exit 0; }
HERE=$(cd "$(dirname "$0")" && pwd)
[ -f "$HERE/repo" ] && { PATH=/usr/bin:/bin:/usr/sbin:/sbin; export PATH; unset BASH_ENV ENV CDPATH; }
ME=$(id -u)
REAL_HOME=$(getent passwd "$ME" | cut -d: -f6)
# user services: every unit file in the runner user's own unit folder is a job's leftover (setup.sh puts none there)
export XDG_RUNTIME_DIR="/run/user/$ME"
if [ -d "$REAL_HOME/.config/systemd/user" ] && [ ! -L "$REAL_HOME/.config/systemd/user" ]; then
  for f in "$REAL_HOME/.config/systemd/user"/*; do
    [ -e "$f" ] || continue
    u=$(basename "$f")
    systemctl --user disable --now "$u" >/dev/null 2>&1
  done
  rm -rf "$REAL_HOME/.config/systemd/user"
  systemctl --user daemon-reload >/dev/null 2>&1
fi
# transient units too (systemd-run --user ..., Restart=always would bring a killed process back) and timers, paths
# and sockets that would start something later: every active user unit except the session bus
rm -rf "$REAL_HOME/.local/share/systemd/user" 2>/dev/null
systemctl --user list-units --type=timer,path,socket,service,scope --state=active,activating,reloading,listening,waiting --plain --no-legend 2>/dev/null \
  | awk '{print $1}' | while read -r u; do
    case $u in (dbus.service|dbus.socket|init.scope|"") continue;; esac
    systemctl --user stop "$u" >/dev/null 2>&1
  done
systemctl --user reset-failed >/dev/null 2>&1
# Every other process of this user is a leftover of the job (the user exists only for the runner): only the runner,
# its user service manager and this hook's own ancestors stay.
keep=" $$ "; p=$PPID
while [ -n "$p" ] && [ "$p" -gt 1 ]; do keep="$keep$p "; p=$(ps -p "$p" -o ppid= 2>/dev/null | tr -d ' '); done
# The runner is recognised by the program it runs (its own bin folder), never by words in a command line a job
# could copy.
RBIN=$(cd "$REAL_HOME/actions-runner/bin" 2>/dev/null && pwd -P)
# The manager's PID comes from the system manager (a job cannot change it). (sd-pam) is the one child the manager
# starts in its first second (a job's own units are its children too, but start later). The bus counts only when its
# program is the system's dbus binary (a job could replace dbus.service with a runtime override).
start() { awk '{print $22}' "/proc/$1/stat" 2>/dev/null; }
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
bus=$(systemctl --user show dbus.service -p MainPID --value 2>/dev/null)
if [ "${bus:-0}" -gt 0 ] 2>/dev/null; then
  case $(readlink "/proc/$bus/exe" 2>/dev/null) in
    (/usr/bin/dbus-daemon|/usr/bin/dbus-broker|/usr/bin/dbus-broker-launch) SYSTEM_PIDS="$SYSTEM_PIDS $bus";;
  esac
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
exit 0
