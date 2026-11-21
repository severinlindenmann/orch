#!/bin/bash -p
# scripts/mac-runner/runner-loop.sh : one clean runner per job on this Mac (ORCH-1125, security review ORCH-1233 M2).
# setup.sh installs it as /usr/local/orch-mac-runner/runner-loop.sh and starts it at boot as root
# (io.orch.mac-runner-loop). Round after round, before each job:
#   1. closes the private and the local network to the runner user (pf rule pf-orch-ci.conf); if that fails, no runner
#   2. stops every process of the runner user orch-ci (the user exists only for the runner)
#   3. makes a fresh runner folder from the root-owned copy (template/) plus the runner's sign-up (creds/), so nothing
#      a job changed in the runner (run.sh, bin/, hooks settings) reaches the next job
#   4. empties orch-ci's home (only the Simulators stay) and its temp and cache folders
#   5. starts the runner (io.orch.mac-runner, as orch-ci) for ONE job (`run.sh --once`) and waits until it ends
# The runner user owns nothing that survives a round; the loop, the copy, the sign-up and the hooks belong to root.
set -u
PATH=/usr/bin:/bin:/usr/sbin:/sbin; export PATH
B=/usr/local/orch-mac-runner; J=$B/job; U=orch-ci; H=/Users/orch-ci
SVC=system/io.orch.mac-runner
MAX=$((4 * 3600))   # longest round: the longest Mac job (timeout-minutes) is far shorter
[ "$(id -u)" = 0 ] || { echo "runner-loop.sh: runs as root only (setup.sh starts it); did nothing" >&2; exit 1; }
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') runner-loop: $*"; }
running() { launchctl print "$SVC" 2>/dev/null | grep -q 'state = running'; }

network_closed() { # pf: orch-ci never reaches the private network or the local network (rule in pf-orch-ci.conf)
  id "$U" >/dev/null 2>&1 || return 1
  pfctl -s info 2>/dev/null | grep -q 'Status: Enabled' || pfctl -E >/dev/null 2>&1
  # the anchor below is only read when the main rules name com.apple/* (macOS's own /etc/pf.conf does)
  pfctl -s rules 2>/dev/null | grep -q 'anchor "com.apple/\*"' || pfctl -f /etc/pf.conf >/dev/null 2>&1
  pfctl -a com.apple/orch-ci -f "$B/pf-orch-ci.conf" >/dev/null 2>&1 || return 1
  pfctl -s info 2>/dev/null | grep -q 'Status: Enabled' &&
    pfctl -s rules 2>/dev/null | grep -q 'anchor "com.apple/\*"' &&
    [ -n "$(pfctl -a com.apple/orch-ci -s rules 2>/dev/null)" ]
}

gone() { # gone <path>: remove a whole tree as root and make sure it is gone. rm walks the tree itself and never
  # follows a link inside it; the flags a user may set (uchg, uappnd) are cleared first so nothing survives
  [ -e "$1" ] || [ -L "$1" ] || return 0
  if [ -L "$1" ]; then rm -f "$1"; else chflags -R nouchg,nouappnd "$1" 2>/dev/null; fi   # -R: links stay unfollowed
  rm -rf "$1" 2>/dev/null
  [ ! -e "$1" ] && [ ! -L "$1" ] || { log "could not remove $1"; return 1; }
}

realdir() { # realdir <parent> <a/b/c>: true when every step below <parent> is a real folder, not a link
  local p=$1 part; local IFS=/
  for part in $2; do p=$p/$part; [ -d "$p" ] && [ ! -L "$p" ] || return 1; done
}

fresh() {
  # 2. nothing of the last job keeps running (the runner itself included), nothing of it is set to start again
  running && launchctl kill SIGKILL "$SVC" >/dev/null 2>&1
  local uid k d; uid=$(id -u "$U") || return 1
  launchctl bootout "user/$uid" >/dev/null 2>&1; launchctl bootout "gui/$uid" >/dev/null 2>&1
  crontab -u "$U" -r >/dev/null 2>&1   # setup.sh also puts it in cron.deny and at.deny
  pkill -KILL -U "$U" 2>/dev/null; sleep 1
  pkill -KILL -U "$U" 2>/dev/null
  # 3. a fresh runner folder; its parent belongs to root, so a job can never put a link in its place
  gone "$J" || return 1
  cp -Rc "$B/template" "$J" 2>/dev/null || { gone "$J" && cp -R "$B/template" "$J"; } || return 1
  for f in .runner .credentials .credentials_rsaparams; do
    if [ -f "$B/creds/$f" ]; then cp "$B/creds/$f" "$J/$f" || return 1; fi
  done
  [ -f "$J/.runner" ] || { log "no runner sign-up in $B/creds (run setup.sh again)"; return 1; }
  chown -R "$U:$U" "$J" && chmod 700 "$J" || return 1
  # 4. a fresh home: the old one is moved aside whole (a rename never follows a link) and removed; only its
  #    Simulators move over, and only when every folder on the way is a real folder (Library could be a link to /Library)
  local old=/Users/.orch-ci-old
  gone "$old" || return 1
  [ -L "$H" ] && { log "$H is a link"; return 1; }
  if [ -e "$H" ]; then mv "$H" "$old" || return 1; fi
  mkdir -p "$H/Library/Developer" || return 1
  if realdir "$old" Library/Developer/CoreSimulator; then mv "$old/Library/Developer/CoreSimulator" "$H/Library/Developer/"; fi
  chown -R "$U:$U" "$H" && chmod 700 "$H" || return 1
  gone "$old" || return 1
  # the temp and cache folders macOS gives the user (their parent belongs to root or is not the user's to replace)
  for k in DARWIN_USER_TEMP_DIR DARWIN_USER_CACHE_DIR; do
    d=$(sudo -u "$U" /usr/bin/getconf "$k" 2>/dev/null); d=${d%/}
    case $d in (/var/folders/?*|/private/var/folders/?*) gone "$d" && mkdir "$d" && chown "$U" "$d" && chmod 700 "$d" || return 1 ;; esac
  done
  # its files in the shared temp folders and in /Users/Shared; the apps and data in its Simulators
  for d in /private/tmp /private/var/tmp /Users/Shared; do
    find "$d" -xdev -mindepth 1 -maxdepth 3 -user "$U" -prune -print 2>/dev/null | while IFS= read -r f; do gone "$f"; done
  done
  /usr/bin/perl -e 'alarm 300; exec @ARGV' sudo -u "$U" /usr/bin/xcrun simctl erase all >/dev/null 2>&1
  pkill -KILL -U "$U" 2>/dev/null   # the calls above
  return 0
}

fails=0
log "started"
while :; do
  if ! network_closed; then log "could not close the private network to $U; the runner stays off"; sleep 60; continue; fi
  if ! fresh; then log "could not make a fresh runner folder; trying again in a minute"; sleep 60; continue; fi
  t0=$(date +%s)
  if ! launchctl kickstart "$SVC" >/dev/null 2>&1; then log "could not start $SVC"; sleep 60; continue; fi
  sleep 5
  # the runner is the job's own process: a job could keep it alive and take more jobs without a fresh start, so
  # the loop ends every round after MAX seconds whatever the runner says (no job here runs that long)
  while running; do
    if [ $(( $(date +%s) - t0 )) -gt "$MAX" ]; then log "round longer than ${MAX}s; stopping it"; break; fi
    sleep 5
  done
  # a runner that ends at once, again and again (no network, sign-up removed on GitHub): wait longer each time
  if [ $(( $(date +%s) - t0 )) -lt 60 ]; then fails=$((fails + 1)); else fails=0; fi
  if [ "$fails" -gt 0 ]; then
    w=$((fails * 30)); [ "$w" -gt 600 ] && w=600
    log "the runner ended within a minute ($fails time(s) in a row); next start in ${w}s"; sleep "$w"
  fi
done
