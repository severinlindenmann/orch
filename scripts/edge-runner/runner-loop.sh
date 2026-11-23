#!/bin/bash -p
# scripts/edge-runner/runner-loop.sh : one clean runner per job on the orch edge test server (ORCH-1126; the Mac's
# security review ORCH-1233 M2, same fix). setup.sh installs it as /usr/local/orch-edge-runner/runner-loop.sh and
# starts it at boot as root (orch-edge-runner-loop.service). Round after round, before each job:
#   1. closes the private and the local network to the runner user (nft-orch-ci.nft); if that fails, no runner
#   2. stops every process of the runner user orch-ci (the user exists only for the runner) and its user services
#   3. makes a fresh runner folder from the root-owned copy (template/) plus the runner's sign-up (creds/), so nothing
#      a job changed in the runner (run.sh, bin/, the work folder with its checkout) reaches the next job
#   4. empties orch-ci's home and its files in /tmp, /var/tmp and /dev/shm, starts a fresh user service manager
#   5. starts the runner (orch-edge-runner.service, as orch-ci) for ONE job (`run.sh --once`) and waits until it ends
# The runner user owns nothing that survives a round; the loop, the copy, the sign-up and the hooks belong to root.
# orch edge runs several runners side by side (setup.sh, ORCH_RUNNER_COUNT; manager 22 Nov: one runner made a develop
# run take 40+ minutes). Each one is an instance K with its own loop, user, home, runner folder, sign-up and unit:
#   K=1: user orch-ci, $B/job, $B/creds, orch-edge-runner.service      K>=2: orch-ci-K, $B/job-K, $B/creds-K, orch-edge-runner-K.service
#     runner-loop.sh [K]           the loop of instance K (default 1)
#     runner-loop.sh --check [K]   steps 1 to 4 once, then exit (setup.sh uses it; starts no runner)
set -u
PATH=/usr/bin:/bin:/usr/sbin:/sbin; export PATH
CHECK=""; [ "${1-}" = --check ] && { CHECK=1; shift; }
K=${1:-1}
case $K in ([1-9]) ;; (*) echo "runner-loop.sh: instance must be 1 to 9, not '$K'; did nothing" >&2; exit 2;; esac
if [ "$K" = 1 ]; then SFX=""; U=orch-ci; else SFX="-$K"; U=orch-ci-$K; fi
B=/usr/local/orch-edge-runner; J=$B/job$SFX; C=$B/creds$SFX; H=/home/$U
SVC=orch-edge-runner$SFX.service
MAX=$((4 * 3600))      # longest round, idle wait included
JOB_MAX=$((60 * 60))   # longest job once its worker runs: the longest Linux job (timeout-minutes) is 20 min
[ "$(id -u)" = 0 ] || { echo "runner-loop.sh: runs as root only (setup.sh starts it); did nothing" >&2; exit 1; }
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') runner-loop $K: $*"; }
# one loop or check per instance at a time: two root clean-ups at once could race each other over its runner folder
exec 9>"/run/orch-edge-runner-loop$SFX.lock"
flock -n 9 || { log "another runner-loop.sh (or setup.sh) is running; did nothing"; exit 1; }
running() { systemctl is-active --quiet "$SVC"; }

network_closed() { # nft: orch-ci never reaches the private network or the local network (rule in nft-orch-ci.nft)
  id "$U" >/dev/null 2>&1 || return 1
  nft -f "$B/nft-orch-ci.nft" >/dev/null 2>&1 || return 1
  # both rules (IPv4 and IPv6) name this instance's user (nft lists users by number)
  [ "$(nft list table inet orch_ci_runner 2>/dev/null | grep 'skuid' | grep -cw "$(id -u "$U")")" -ge 2 ]
}

gone() { # gone <path>: remove a whole tree as root and make sure it is gone (rm never follows a link inside it)
  [ -e "$1" ] || [ -L "$1" ] || return 0
  rm -rf --one-file-system "$1" 2>/dev/null
  [ ! -e "$1" ] && [ ! -L "$1" ] || { log "could not remove $1"; return 1; }
}

orch_ci_files() { # NUL-separated: the topmost file or folder of orch-ci on each writable filesystem
  local m
  for m in $(findmnt -rn -t ext4,xfs,btrfs,tmpfs -o TARGET | grep -vE '^/(proc|sys)(/|$)' | sort -u); do
    find "$m" -xdev \( -path "$H" -o -path "$J" \) -prune -o -user "$U" -prune -print0 2>/dev/null
  done
}

fresh() {
  # 2. nothing of the last job keeps running (the runner itself included), nothing of it is set to start again
  local uid d old=/home/.$U-old
  uid=$(id -u "$U") || return 1
  systemctl kill -s KILL "$SVC" >/dev/null 2>&1; systemctl stop "$SVC" >/dev/null 2>&1
  systemctl stop "user@$uid.service" >/dev/null 2>&1
  systemctl stop "user-runtime-dir@$uid.service" >/dev/null 2>&1   # empties /run/user/<uid>
  crontab -r -u "$U" >/dev/null 2>&1   # setup.sh also puts it in cron.deny and at.deny
  pkill -KILL -u "$U" 2>/dev/null; sleep 1
  pkill -KILL -u "$U" 2>/dev/null; sleep 1
  if pgrep -u "$U" >/dev/null 2>&1; then log "processes of $U are still there"; return 1; fi
  # 3. a fresh runner folder; its parent belongs to root, so a job can never put a link in its place
  gone "$J" || return 1
  cp -a "$B/template" "$J" || return 1
  for f in .runner .credentials .credentials_rsaparams; do
    if [ -f "$C/$f" ]; then cp "$C/$f" "$J/$f" || return 1; fi
  done
  [ -f "$J/.runner" ] || { log "no runner sign-up in $C (setup.sh register)"; return 1; }
  # only the fresh copy just made: never a recursive chown over what a job left (a hard link to a root file)
  chown -R "$U:$U" "$J" && chmod 700 "$J" || return 1
  # 4. a fresh home: the old one is moved aside whole (a rename never follows a link) and removed
  gone "$old" || return 1
  [ -L "$H" ] && { log "$H is a link"; return 1; }
  if [ -e "$H" ]; then mv "$H" "$old" || return 1; fi
  install -d -o "$U" -g "$U" -m 0700 "$H" || return 1
  gone "$old" || return 1
  # every file of orch-ci on every writable filesystem (/tmp, /var/tmp, /dev/shm, /run/lock and any other place the
  # world may write): a job must not leave a library or a program that a later job loads before its hook refuses it
  # (outside review: LD_PRELOAD of a planted library). No depth limit; NUL-separated, so a name with a line break
  # never turns into another path; the home and the runner folder were made fresh above and are left out.
  orch_ci_files | while IFS= read -r -d '' f; do [ "$(stat -c %u "$f" 2>/dev/null)" = "$uid" ] && gone "$f"; done
  left=$(orch_ci_files | tr '\0' '\n' | head -3)
  [ -z "$left" ] || { log "files of $U are still there: $left"; return 1; }
  # a fresh user service manager (the Services add-on's real Linux run needs one); its folders are in the empty home
  systemctl start "user@$uid.service" >/dev/null 2>&1 || { log "could not start the user service manager of $U"; return 1; }
  return 0
}

if [ -n "$CHECK" ]; then
  network_closed || { log "could not close the private network to $U"; exit 1; }
  fresh || exit 1
  log "check ok: network closed, $U stopped and emptied, fresh runner folder"
  exit 0
fi

fails=0
log "started"
while :; do
  if ! network_closed; then log "could not close the private network to $U; the runner stays off"; sleep 60; continue; fi
  if ! fresh; then log "could not make a fresh runner folder; trying again in a minute"; sleep 60; continue; fi
  t0=$(date +%s)
  if ! systemctl start "$SVC" >/dev/null 2>&1; then log "could not start $SVC"; sleep 60; continue; fi
  sleep 5
  # A job's own code could keep the runner alive to take more jobs here, so a round ends JOB_MAX after its job started
  # (its Runner.Worker appeared) and MAX after the round started, whatever the runner says.
  job0=""
  while running; do
    now=$(date +%s)
    [ -z "$job0" ] && pgrep -u "$U" -f 'bin/Runner.Worker' >/dev/null 2>&1 && job0=$now
    if [ -n "$job0" ] && [ $((now - job0)) -gt "$JOB_MAX" ]; then log "job longer than ${JOB_MAX}s; stopping it"; break; fi
    if [ $((now - t0)) -gt "$MAX" ]; then log "round longer than ${MAX}s; stopping it"; break; fi
    sleep 2
  done
  # a runner that ends at once, again and again (no network, sign-up removed on GitHub): wait longer each time
  if [ $(( $(date +%s) - t0 )) -lt 60 ]; then fails=$((fails + 1)); else fails=0; fi
  if [ "$fails" -gt 0 ]; then
    w=$((fails * 30)); [ "$w" -gt 600 ] && w=600
    log "the runner ended within a minute ($fails time(s) in a row); next start in ${w}s"; sleep "$w"
  fi
done
