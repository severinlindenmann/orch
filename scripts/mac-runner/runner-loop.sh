#!/bin/bash -p
# scripts/mac-runner/runner-loop.sh : one clean runner per job on this Mac (ORCH-1125, security review ORCH-1233 M2).
# setup.sh installs it as /usr/local/orch-mac-runner/runner-loop.sh and starts it at boot as root
# (io.orch.mac-runner-loop). Round after round, before each job:
#   1. closes the private and the local network to the runner user (pf rule pf-orch-ci.conf); if that fails, no runner
#   2. stops every process of the runner user orch-ci (the user exists only for the runner)
#   3. makes a fresh runner folder from the root-owned copy (template/) plus the runner's sign-up (creds/), so nothing
#      a job changed in the runner (run.sh, bin/, hooks settings) reaches the next job
#   4. lets orch-ci empty its registered home (only the Simulators stay), makes the job's HOME anew, and empties
#      its temp and cache folders
#   5. starts the runner (io.orch.mac-runner, as orch-ci) for ONE job (`run.sh --once`) and waits until it ends
# The runner user owns nothing that survives a round; the loop, the copy, the sign-up and the hooks belong to root.
set -u
PATH=/usr/bin:/bin:/usr/sbin:/sbin; export PATH
B=/usr/local/orch-mac-runner; J=$B/job; U=orch-ci
# Two homes. H is the user's registered home: macOS guards it even against root (a rename of it, and its
# Library/Caches, were refused live on 22 Nov), so root never touches it; the runner user itself empties it before
# each job (its own files, its own rights: nothing outside them can change). R is the HOME the runner and the job
# get: not a registered home, so root makes it anew each round. Both live in a folder of root's (setup.sh), so the
# runner user cannot put a link in place of either.
HB=/private/var/orch-ci; H=$HB/home; R=$HB/run
SVC=system/io.orch.mac-runner
# the runner's own output: launchd opens it as the runner user (a root-owned log made every start fail, 22 Nov), so
# the loop makes it new for each round, owned by the runner user, and keeps the last round's next to it (.1)
RL=/var/log/orch-mac-runner-job.log
MAX=$((4 * 3600))   # longest job of a round, counted from the job's start: the longest Mac job is far shorter
IDLE_MAX=$((24 * 3600))   # a runner that waits this long for a job gets a fresh start anyway
STEP_MAX=600   # longest clean-up step: a step that hangs (a root chmod waited over an hour, 23 Nov) is stopped
[ "$(id -u)" = 0 ] || { echo "runner-loop.sh: runs as root only (setup.sh starts it); did nothing" >&2; exit 1; }
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') runner-loop: $*"; }
# every step as the runner user has a time limit (limit below); a program of the user that outlives it is stopped
# by the next round (pkill -U)
as_user() { limit "$STEP_MAX" sudo -u "$U" -H env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin "$@"; }
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

limit() { # limit <seconds> <command...>: runs it in its own process group and stops the whole group (children
  # too) when it takes longer; exit 124 then, without waiting for them to end (a program stuck in the kernel may
  # take long to go). A clean-up step that hangs never stops the runner for good.
  /usr/bin/perl -e '$t = shift; my $pid = fork; die "fork" unless defined $pid;
    if (!$pid) { setpgrp(0, 0); exec @ARGV; exit 127 }
    $SIG{ALRM} = sub { kill "KILL", -$pid; kill "KILL", $pid; exit 124 };
    alarm $t; waitpid($pid, 0); exit($? & 127 ? 128 + ($? & 127) : $? >> 8)' "$@"
}

# a job has started: the runner logs 'Running job:' when it takes one, before any step of the job runs, and runs it
# in a Runner.Worker; either one starts the job limit (a job cannot hide both before its first step). The 24-hour
# limit of an idle round stays the outer bound
job_started() { grep -q 'Running job:' "$RL" 2>/dev/null || pgrep -U "$U" -f 'Runner\.Worker' >/dev/null 2>&1; }

round_over() { # round_over <round start> <job start or 0> <now>: prints why the round must end, nothing while it may
  # go on. The job limit counts from the job's start: a runner that waited idle for hours lost its job after 58
  # minutes (23 Nov), because the limit counted from the runner's start
  if [ "$2" -gt 0 ]; then
    [ $(( $3 - $2 )) -gt "$MAX" ] && echo "job longer than ${MAX}s; stopping it"
  else
    [ $(( $3 - $1 )) -gt "$IDLE_MAX" ] && echo "no job for ${IDLE_MAX}s; a fresh start"
  fi
  return 0
}

unguard() { # unguard <path>: clear the locks (uchg, uappnd) and access rules (ACL) the runner user put in a tree, so
  # root's mv and rm work. macOS puts "everyone deny delete" on each home folder; a job can lock or guard its files.
  # find never follows a link and -h changes a link itself, not its target (macOS `chmod -R -N` follows links even
  # with -P). Only what orch-ci owns: a hard link the job made to someone else's file is the same file, so root
  # never changes it (rm only takes the name away). No process of the user runs while the loop does this.
  [ -e "$1" ] || [ -L "$1" ] || return 0
  limit "$STEP_MAX" find -P "$1" -user "$U" -exec chflags -h nouchg,nouappnd {} + -exec chmod -h -N {} + 2>/dev/null
  [ $? = 124 ] && log "unlocking $1 took longer than ${STEP_MAX}s; stopped it"
  return 0
}

gone() { # gone <path>: remove a whole tree as root and make sure it is gone. rm walks the tree itself and never
  # follows a link inside it; the locks and access rules of the runner user are cleared first so nothing survives
  [ -e "$1" ] || [ -L "$1" ] || return 0
  if [ -L "$1" ]; then chflags -h nouchg,nouappnd "$1" 2>/dev/null; rm -f "$1"
  else
    # remove first; only what is left (locked or guarded by the job) is unlocked, then removed again. The unlock walks
    # every file, so a big job home (a phone build) is only walked when something stays
    limit "$STEP_MAX" rm -rf "$1" 2>/dev/null
    if [ -e "$1" ]; then unguard "$1"; limit "$STEP_MAX" rm -rf "$1" 2>/dev/null; fi
  fi
  [ ! -e "$1" ] && [ ! -L "$1" ] || { log "could not remove $1"; return 1; }
}

realdir() { # realdir <parent> <a/b/c>: true when every step below <parent> is a real folder, not a link
  local p=$1 part; local IFS=/
  for part in $2; do p=$p/$part; [ -d "$p" ] && [ ! -L "$p" ] || return 1; done
}

# runs as the runner user (sudo -u, empty environment, bash -p): empties its registered home $1, keeping only
# Library/Developer/CoreSimulator (its Simulators); a link anywhere on that way is removed, never followed
CLEAN_AS_USER='set -u; H=$1
chflags nouchg,nouappnd "$H" 2>/dev/null; chmod -N "$H" 2>/dev/null; chmod u+rwx "$H"; cd "$H" || exit 1
# a link or a file on the way to the Simulators goes first (unlocked, removed, and stop when that fails): nothing
# below is touched through a link
for p in "$H/Library" "$H/Library/Developer" "$H/Library/Developer/CoreSimulator"; do
  if [ -L "$p" ] || { [ -e "$p" ] && [ ! -d "$p" ]; }; then
    chflags -h nouchg,nouappnd "$p" 2>/dev/null; rm -f "$p" || exit 1
  fi
  [ -L "$p" ] && exit 1
  [ -d "$p" ] || break
done
find -P "$H" -mindepth 1 -exec chflags -h nouchg,nouappnd {} + -exec chmod -h -N {} + 2>/dev/null
find -P "$H" -mindepth 1 -type d -exec chmod u+rwx {} + 2>/dev/null
find -P "$H" -mindepth 1 -maxdepth 1 ! -name Library -exec rm -rf {} +
if [ -d "$H/Library" ] && [ ! -L "$H/Library" ]; then
  find -P "$H/Library" -mindepth 1 -maxdepth 1 ! -name Developer -exec rm -rf {} + 2>/dev/null
  # macOS keeps these two folders of a home even from their own user (seen live 22 Nov): empty them instead
  for k in Caches Preferences; do
    if [ -d "$H/Library/$k" ] && [ ! -L "$H/Library/$k" ]; then
      find -P "$H/Library/$k" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
    fi
  done
  if [ -d "$H/Library/Developer" ] && [ ! -L "$H/Library/Developer" ]; then
    find -P "$H/Library/Developer" -mindepth 1 -maxdepth 1 ! -name CoreSimulator -exec rm -rf {} +
  fi
fi
mkdir -p "$H/Library/Developer"
# the folders that stay keep no data of the job in their extended attributes
for d in "$H" "$H/Library" "$H/Library/Developer" "$H/Library/Caches" "$H/Library/Preferences"; do
  if [ -d "$d" ] && [ ! -L "$d" ]; then xattr -c "$d" 2>/dev/null; fi
done
exit 0'

# runs as the runner user: empties a folder of its own ($1) without removing the folder; nothing is followed
EMPTY_AS_USER='set -u; d=$1; cd "$d" || exit 1
find -P "$d" -mindepth 1 -user "$(id -u)" -exec chflags -h nouchg,nouappnd {} + -exec chmod -h -N {} + 2>/dev/null
find -P "$d" -mindepth 1 -type d -user "$(id -u)" -exec chmod u+rwx {} + 2>/dev/null
find -P "$d" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null
exit 0'

# What stays after the runner user's clean-up. macOS's own services (trustd, CoreSimulator, ContainerManager, xcrun)
# write into the registered home and the temp and cache folders at any moment, also right after a clean-up (seen
# live, 22 Nov), so "empty" can never hold there. The jobs get their own HOME and TMPDIR ($R) instead. This runner is
# a persistent machine trusted with merged code only, with no secrets on it (docs/ci-checks.md): the clean-up is
# best effort, and only what breaks it or could start on its own stops the round.
blocking_in_home() {
  local d
  for d in "$H/Library" "$H/Library/Developer" "$H/Library/Developer/CoreSimulator"; do
    [ -L "$d" ] && echo "link $d"
  done
  # a link at the top of the home or of its Library: the next clean-up would see it first
  find -P "$H" "$H/Library" -mindepth 1 -maxdepth 1 -type l -print 2>/dev/null | sed 's/^/link /'
  # a launch agent left behind could start by itself in a later session of the user
  [ -d "$H/Library/LaunchAgents" ] && [ -n "$(find -P "$H/Library/LaunchAgents" -mindepth 1 -print -quit 2>/dev/null)" ] &&
    echo "launch agent in $H/Library/LaunchAgents"
  return 0
}

note_left() { # note_left <where> <list>: log what macOS keeps, only when it changed since the last round
  local f; f="$B/left.$(printf '%s' "$1" | cksum | cut -d' ' -f1)"
  [ "$(cat "$f" 2>/dev/null)" = "$2" ] && return 0
  printf '%s' "$2" > "$f"; [ -n "$2" ] && log "left in $1 (macOS keeps or makes it again): $2"
  return 0
}

fresh_home() {
  [ -d "$HB" ] && [ ! -L "$HB" ] || { log "$HB is missing (run setup.sh again)"; return 1; }
  [ -d "$H" ] && [ ! -L "$H" ] || { log "$H is missing or a link (run setup.sh again)"; return 1; }
  # the registered home: emptied by the runner user itself
  as_user /bin/bash -p -c "$CLEAN_AS_USER" clean "$H"
  local stop; stop=$(blocking_in_home | head -3 | tr '\n' ' ')
  [ -z "$stop" ] || { log "the runner user's home is not safe to use: $stop"; return 1; }
  note_left "$H" "$(find -P "$H" -mindepth 1 -maxdepth 2 ! -path "$H/Library" ! -path "$H/Library/Developer" -print0 2>/dev/null | tr '\0\n' '  ' | cut -c1-300)"
  # the job's HOME: made anew by root (a rename or removal never follows a link)
  gone "$R" || return 1
  # modes first, then owner from the bottom up while the parent still is root's; -h never follows a link
  mkdir -m 700 "$R" && mkdir -m 700 "$R/tmp" && chown -h "$U:$U" "$R/tmp" && chown -h "$U:$U" "$R"
}

fresh() {
  # 2. nothing of the last job keeps running (the runner itself included), nothing of it is set to start again
  running && launchctl kill SIGKILL "$SVC" >/dev/null 2>&1
  local uid k d; uid=$(id -u "$U") || return 1
  launchctl bootout "user/$uid" >/dev/null 2>&1; launchctl bootout "gui/$uid" >/dev/null 2>&1
  crontab -u "$U" -r >/dev/null 2>&1   # setup.sh also puts it in cron.deny and at.deny
  pkill -KILL -U "$U" 2>/dev/null; sleep 1
  pkill -KILL -U "$U" 2>/dev/null; sleep 1
  if pgrep -U "$U" >/dev/null 2>&1; then log "programs of $U still run after a stop"; return 1; fi
  # 3. a fresh runner folder; its parent belongs to root, so a job can never put a link in its place
  gone "$J" || return 1
  cp -Rc "$B/template" "$J" 2>/dev/null || { gone "$J" && cp -R "$B/template" "$J"; } || return 1
  for f in .runner .credentials .credentials_rsaparams; do
    if [ -f "$B/creds/$f" ]; then cp "$B/creds/$f" "$J/$f" || return 1; fi
  done
  [ -f "$J/.runner" ] || { log "no runner sign-up in $B/creds (run setup.sh again)"; return 1; }
  chown -R "$U:$U" "$J" && chmod 700 "$J" || return 1
  # 4. a fresh home
  fresh_home || return 1
  # the runner's log: the last round's moved aside (a rename never follows a link), a new one for this round
  rm -f "$RL.1"; [ -e "$RL" ] || [ -L "$RL" ] && mv -f "$RL" "$RL.1"
  install -m 0640 -o "$U" -g wheel /dev/null "$RL" || return 1
  # the temp and cache folders macOS gives the user: macOS guards these folders like the home (root's removal was
  # refused live, 22 Nov), so the runner user empties them itself; the job's TMPDIR is in its fresh HOME anyway
  for k in DARWIN_USER_TEMP_DIR DARWIN_USER_CACHE_DIR; do
    d=$(as_user /usr/bin/getconf "$k" 2>/dev/null); d=${d%/}
    case $d in
      (/var/folders/?*|/private/var/folders/?*)
        [ -L "$d" ] && { log "$d is a link"; return 1; }
        [ -d "$d" ] || continue
        as_user /bin/bash -p -c "$EMPTY_AS_USER" empty "$d"
        # best effort: macOS's services (trustd, CoreSimulator, xcrun) keep or make files here again at once
        note_left "$d" "$(find -P "$d" -mindepth 1 -maxdepth 1 -print0 2>/dev/null | tr '\0\n' '  ' | cut -c1-300)" ;;
    esac
  done
  # its files in the shared temp folders and in /Users/Shared; the apps and data in its Simulators
  for d in /private/tmp /private/var/tmp /Users/Shared; do
    # NUL-separated: a file name with a line break never turns into another path
    find "$d" -xdev -mindepth 1 -maxdepth 3 -user "$U" -prune -print0 2>/dev/null | while IFS= read -r -d '' f; do
      [ "$(stat -f %u "$f" 2>/dev/null)" = "$uid" ] && gone "$f"
    done
  done
  /usr/bin/perl -e 'alarm 300; exec @ARGV' sudo -u "$U" /usr/bin/xcrun simctl erase all >/dev/null 2>&1 ||
    log "simctl erase all did not finish; the Simulators keep the last job's apps and data this round"
  pkill -KILL -U "$U" 2>/dev/null   # the calls above
  return 0
}

fails=0
log "started"
while :; do
  if ! network_closed; then log "could not close the private network to $U; the runner stays off"; sleep 60; continue; fi
  if ! fresh; then log "could not make a fresh runner folder; trying again in a minute"; sleep 60; continue; fi
  t0=$(date +%s); tj=0
  if ! launchctl kickstart "$SVC" >/dev/null 2>&1; then log "could not start $SVC"; sleep 60; continue; fi
  sleep 5
  # the runner is the job's own process: a job could keep it alive and take more jobs without a fresh start, so
  # the loop ends every round MAX seconds after its first job started, whatever the runner says (no job here runs
  # that long)
  while running; do
    now=$(date +%s)
    [ "$tj" = 0 ] && job_started && tj=$now
    why=$(round_over "$t0" "$tj" "$now")
    if [ -n "$why" ]; then log "$why"; break; fi
    sleep 5
  done
  # a runner that ends at once, again and again (no network, sign-up removed on GitHub): wait longer each time
  if [ $(( $(date +%s) - t0 )) -lt 60 ]; then fails=$((fails + 1)); else fails=0; fi
  if [ "$fails" -gt 0 ]; then
    w=$((fails * 30)); [ "$w" -gt 600 ] && w=600
    log "the runner ended within a minute ($fails time(s) in a row); next start in ${w}s"; sleep "$w"
  fi
done
