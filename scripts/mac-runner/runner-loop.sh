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

clean_dir() { # clean_dir <dir> <name to keep>: remove everything else in <dir>; never follows a link
  [ -d "$1" ] && [ ! -L "$1" ] || return 0
  find "$1" -mindepth 1 -maxdepth 1 ! -name "$2" -exec rm -rf {} + 2>/dev/null
  return 0
}

fresh() {
  # 2. nothing of the last job keeps running (the runner itself included)
  running && launchctl kill SIGKILL "$SVC" >/dev/null 2>&1
  pkill -KILL -U "$U" 2>/dev/null; sleep 1
  pkill -KILL -U "$U" 2>/dev/null
  # 3. a fresh runner folder; its parent belongs to root, so a job can never put a link in its place
  rm -rf "$J"
  cp -Rc "$B/template" "$J" 2>/dev/null || { rm -rf "$J"; cp -R "$B/template" "$J"; } || return 1
  for f in .runner .credentials .credentials_rsaparams; do
    if [ -f "$B/creds/$f" ]; then cp "$B/creds/$f" "$J/$f" || return 1; fi
  done
  [ -f "$J/.runner" ] || { log "no runner sign-up in $B/creds (run setup.sh again)"; return 1; }
  chown -R "$U:$U" "$J" && chmod 700 "$J" || return 1
  # 4. a fresh home: only the Simulators stay (they take minutes to make); the temp and cache folders macOS gives it
  clean_dir "$H" Library
  clean_dir "$H/Library" Developer
  clean_dir "$H/Library/Developer" CoreSimulator
  local k d
  for k in DARWIN_USER_TEMP_DIR DARWIN_USER_CACHE_DIR; do
    d=$(sudo -u "$U" /usr/bin/getconf "$k" 2>/dev/null); d=${d%/}
    case $d in (/var/folders/?*|/private/var/folders/?*) clean_dir "$d" "-" ;; esac
  done
  pkill -KILL -U "$U" 2>/dev/null   # the getconf calls above
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
  while running; do sleep 5; done
  # a runner that ends at once, again and again (no network, sign-up removed on GitHub): wait longer each time
  if [ $(( $(date +%s) - t0 )) -lt 60 ]; then fails=$((fails + 1)); else fails=0; fi
  if [ "$fails" -gt 0 ]; then
    w=$((fails * 30)); [ "$w" -gt 600 ] && w=600
    log "the runner ended within a minute ($fails time(s) in a row); next start in ${w}s"; sleep "$w"
  fi
done
