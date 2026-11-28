# The end of an e2e run (sourced by run.sh; ORCH-2397). Run 46073797159 passed all 112 scenarios and then went red:
# a writer of the run was still alive, `rm -rf` of the temporary workspace said "Directory not empty", and under
# `set -e` that became the run's exit code. So the EXIT trap now ends what the run started and is still alive (at
# most E2E_END_ROUNDS rounds, the last with KILL), removes the folders with a short retry, and always leaves with the
# exit code the run had: a folder that still cannot be removed is one line on stderr, never a red run.
# Needs TMP and OHOME (the run's own temporary folders, made by mktemp).

e2e_alive() {
  # pids this run started that still live: the command line names one of its folders, or the working folder is in one
  {
    pgrep -f -- "$TMP|$OHOME"
    if [ -d /proc/self ]; then
      for d in /proc/[0-9]*; do
        c=$(readlink "$d/cwd" 2>/dev/null) || continue
        case "$c" in "$TMP"|"$TMP"/*|"$OHOME"|"$OHOME"/*) echo "${d#/proc/}" ;; esac
      done
    else
      "$(command -v lsof || echo /usr/sbin/lsof)" -a -d cwd -Fpn 2>/dev/null | awk -v a="$TMP" -v b="$OHOME" \
        '/^p/ { p = substr($0, 2) } /^n/ { n = substr($0, 2); if (index(n, a) == 1 || index(n, b) == 1) print p }'
    fi
  } 2>/dev/null | sort -u | grep -vx "$$"
}

e2e_cleanup() {
  rc=$?
  trap - EXIT INT TERM
  set +e
  rounds=${E2E_END_ROUNDS:-3}; n=1
  while [ "$n" -le "$rounds" ]; do
    pids=$(e2e_alive)
    [ -z "$pids" ] && break
    if [ "$n" -lt "$rounds" ]; then kill $pids 2>/dev/null; else kill -9 $pids 2>/dev/null; fi
    sleep 1; n=$((n + 1))
  done
  n=0
  until rm -rf "$TMP" "$OHOME" 2>/dev/null; do
    n=$((n + 1)); [ "$n" -ge 5 ] && break
    sleep 1
  done
  if [ -e "$TMP" ] || [ -e "$OHOME" ]; then
    echo "e2e: could not remove $TMP $OHOME (something still writes there); the result of the run stands." >&2
  fi
  exit "$rc"
}
