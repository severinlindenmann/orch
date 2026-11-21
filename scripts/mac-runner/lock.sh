#!/bin/bash
# scripts/mac-runner/lock.sh : one-at-a-time locks shared by this Mac's CI runner user and the helpers (ORCH-1125).
#   lock.sh run <name> <tag> -- <cmd...>     wait for the lock, run cmd, release; exit code of cmd
#   lock.sh acquire <name> <tag> <pid>       wait, then hold the lock as long as process <pid> lives (runner hooks)
#   lock.sh release <name> <tag>             release, only if <tag> holds it
#   lock.sh status                           who holds what
# Names: heavy (the runner's current job; helpers count it as one busy heavy slot), xcode (one xcodebuild at a time).
# Lock = mkdir in ORCH_LOCK_DIR (default /Users/Shared/orch-locks: setup.sh makes it 2770, group orch-locks = the
# owner and the runner user, so either can take over the other's stale lock and nobody else can touch it).
# Works across users: a holder is alive while `ps -p <pid>` finds it (kill -0 fails for another user's process), and
# a lock older than ORCH_LOCK_TTL_MIN (default 150) is stale whatever its pid says. Taking over a stale lock is
# serialized by a second lock (<name>.reap), so two waiters never both remove it.
set -u
D=${ORCH_LOCK_DIR:-/Users/Shared/orch-locks}
num() { case $1 in (''|*[!0-9.]*) echo "$2";; (*) echo "$1";; esac; }   # plain numbers only: never bash arithmetic on text
TTL=$(( $(num "${ORCH_LOCK_TTL_MIN:-}" 150 | cut -d. -f1) * 60 )); WAIT=$(num "${ORCH_LOCK_WAIT_SECS:-}" 7200 | cut -d. -f1)
POLL=$(num "${ORCH_LOCK_POLL_SECS:-}" 5)
CALLER_UMASK=$(umask); umask 007   # lock dirs and holder files: owner and group only
set -C                             # `>` never overwrites or follows an existing file (or a planted symlink)
valid() { case $1 in heavy|xcode) ;; *) echo "lock.sh: unknown lock $1 (heavy, xcode)" >&2; exit 2;; esac; }
alive() { [ -n "$1" ] && ps -p "$1" >/dev/null 2>&1; }
mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || date +%s; }
holder() { [ -L "$1/holder" ] && return 0; cat "$1/holder" 2>/dev/null; }
stale() { # stale <lockdir>: holder gone, unreadable for a while, or too old
  local l=$1 h pid age; h=$(holder "$l"); pid=$(printf '%s' "$h" | sed -n 's/.*pid=\([0-9]*\).*/\1/p')
  age=$(( $(date +%s) - $(mtime "$l") ))
  [ "$age" -gt "$TTL" ] && return 0
  [ -z "$h" ] && { [ "$age" -gt 30 ]; return; }   # a holder file is written right after mkdir
  ! alive "$pid"
}
drop() { rm -f "$1/holder"; rmdir "$1" 2>/dev/null; }
reap() { # reap <lockdir> <tag>: remove it if stale, one reaper at a time
  local l=$1 g="$1.reap"
  if ! mkdir "$g" 2>/dev/null; then
    [ $(( $(date +%s) - $(mtime "$g") )) -gt 60 ] && rmdir "$g" 2>/dev/null   # a reaper that died half way
    return 0
  fi
  if [ -d "$l" ] && [ ! -L "$l" ] && stale "$l"; then
    echo "lock.sh: ${l##*/} held by '$(holder "$l")' is stale, taken over by $2" >&2
    drop "$l"
  fi
  rmdir "$g" 2>/dev/null; return 0
}
take() { # take <name> <tag> <pid>
  local n=$1 t=$2 p=$3 l="$D/$1" start; start=$(date +%s)
  [ -d "$D" ] || mkdir -p "$D" 2>/dev/null
  [ -L "$D" ] || [ -L "$l" ] && { echo "lock.sh: $l or its folder is a symlink; refusing" >&2; return 2; }
  # a helper shell started before setup.sh added its user to the group cannot write here: run unlocked, never hang
  [ -w "$D" ] || { echo "lock.sh: cannot write $D (log in again after the runner setup); going on without the $n lock" >&2; return 0; }
  while :; do
    if mkdir "$l" 2>/dev/null; then
      if echo "tag=$t pid=$p user=$(id -un) since=$(date '+%Y-%m-%d %H:%M:%S')" > "$l/holder"; then return 0; fi
      rmdir "$l" 2>/dev/null   # someone planted a file in it: give it up and try again
    fi
    if stale "$l"; then reap "$l" "$t"; sleep 0.2; continue; fi
    if [ $(( $(date +%s) - start )) -gt "$WAIT" ]; then
      echo "lock.sh: gave up waiting ${WAIT}s for $n (held by '$(holder "$l")')" >&2; return 75
    fi
    sleep "$POLL"
  done
}
release() { # release <name> <tag>
  local l="$D/$1"; [ -L "$l" ] && return 0
  holder "$l" | grep -q "^tag=$2 " || return 0
  drop "$l"; return 0
}
case ${1:-} in
  run)
    [ $# -ge 4 ] || { echo "usage: lock.sh run <name> <tag> -- <cmd...>" >&2; exit 2; }
    n=$2; t=$3; valid "$n"; shift 3; [ "${1:-}" = "--" ] && shift
    take "$n" "$t" $$ || exit $?
    trap 'release "$n" "$t"' EXIT INT TERM
    ( umask "$CALLER_UMASK"; set +C; exec "$@" ); exit $? ;;
  acquire)
    [ $# -eq 4 ] || { echo "usage: lock.sh acquire <name> <tag> <pid>" >&2; exit 2; }
    valid "$2"; take "$2" "$3" "$4"; exit $? ;;
  release)
    [ $# -eq 3 ] || { echo "usage: lock.sh release <name> <tag>" >&2; exit 2; }
    valid "$2"; release "$2" "$3" ;;
  status)
    for n in heavy xcode; do h=$(holder "$D/$n"); printf '%s: %s\n' "$n" "${h:-free}"; done ;;
  *) echo "usage: lock.sh run|acquire|release|status ..." >&2; exit 2 ;;
esac
