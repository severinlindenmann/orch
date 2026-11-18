#!/usr/bin/env bash
# Run a command as if the wall clock (UTC) read HH:MM:SS today, ticking on from there (ORCH-390, issues 1371/1421).
# Tests that read the real clock and expect "today", "tomorrow", a weekday or a time on the same day pass by day and
# fail late in the evening or just after midnight; this makes CI see that on every pull request instead of at night.
#
#   scripts/at-clock.sh 23:59:40 python -m pytest -q
#
# Linux only (libfaketime, `apt-get install faketime`). Only the wall clock moves: monotonic time stays real, so
# timeouts and sleeps behave. Every child process (pytest-xdist workers, node, orch subprocesses) sees the same time.
set -euo pipefail
target="${1:?usage: at-clock.sh HH:MM:SS command...}"
shift
lib="$(ls /usr/lib/*/faketime/libfaketime.so.1 /usr/lib/faketime/libfaketime.so.1 2>/dev/null | head -n 1 || true)"
[ -n "$lib" ] || { echo "at-clock: libfaketime not found; install it with: sudo apt-get install -y faketime" >&2; exit 2; }
now=$(date -u +%s)
want=$(date -u -d "$(date -u +%Y-%m-%d) $target" +%s)
offset=$((want - now))
sign="+"; [ "$offset" -lt 0 ] && sign=""
echo "at-clock: wall clock set to $(date -u -d "@$want" '+%Y-%m-%d %H:%M:%S') UTC (offset ${sign}${offset}s)" >&2
export FAKETIME="${sign}${offset}" FAKETIME_DONT_FAKE_MONOTONIC=1 FAKETIME_DONT_RESET=1 TZ=UTC
export LD_PRELOAD="$lib${LD_PRELOAD:+:$LD_PRELOAD}"
exec "$@"
