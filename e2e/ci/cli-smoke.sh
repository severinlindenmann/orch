#!/usr/bin/env bash
# CLI smoke for CI (R1.6, R3.4): orch is already installed (install.sh / install.ps1) and on PATH.
# Runs in a temp folder whose name has a space and an umlaut. bash on all three OSes (Git Bash on Windows).
#   cli-smoke.sh <addon-name>      # the add-on to add and remove again (default: focus)
set -eu
ADDON="${1:-focus}"
# Never the real ~/.orch-tool: orch's per-machine folder is a temp folder under the home, and strict mode makes any
# fallback to the real one an error. The workflow sets both (so the install is covered too); this is the local default.
if [ -z "${ORCH_HOME:-}" ]; then ORCH_HOME="$HOME/.orch-test/smoke-home-$$"; mkdir -p "$ORCH_HOME"; fi
export ORCH_HOME ORCH_HOME_STRICT=1
BASE="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
D="$BASE/orch smoke Büro $$"
mkdir -p "$D"; cd "$D"
step() { printf '\n=== %s\n' "$*"; }
# Windows cannot replace orch while it runs: add-on installs and removals finish in the background once the command
# has ended (winfinish.py) and print "Log: <file>". Wait for that file's RESULT line (e2e/windows/standard-user-flow.ps1 does too).
run_wait() {
  # the log is shared by all finishes: only a RESULT line beyond the count before this command is ours
  base="$(grep -c ' RESULT ' "$ORCH_HOME/finish.log" 2>/dev/null || true)"; base="${base:-0}"
  out="$("$@" 2>&1)"; rc=$?; echo "$out"; [ $rc -eq 0 ] || return $rc
  log="$(printf '%s\n' "$out" | sed -n 's/.*Log: \(.*\)$/\1/p' | tail -1)"
  [ -n "$log" ] || return 0
  command -v cygpath >/dev/null 2>&1 && log="$(cygpath -u "$log")"
  for _ in $(seq 1 200); do
    n="$(grep -c ' RESULT ' "$log" 2>/dev/null || true)"
    if [ "${n:-0}" -gt "$base" ]; then last="$(grep ' RESULT ' "$log" | tail -1)"; echo "$last"; case "$last" in *"RESULT ok"*) return 0 ;; *) return 1 ;; esac; fi
    sleep 3
  done
  echo "no RESULT in $log after 10 min"; return 1
}
export ORCH_AGENT=claude   # no agent on the runner: init links this one's skills folder (as workspace.yml does)

step "version";  orch --version
step "init";     orch init
test -f .agents/skills/orch/SKILL.md
unset ORCH_AGENT

step "ticket new"
T="$(orch ticket new "Smoke Übung" --json)"; echo "$T"
ID="$(printf '%s' "$T" | grep -m1 '"id"' | sed 's/.*"id": *"\([^"]*\)".*/\1/')"
step "check add + record"
C="$(orch check add "$ID" "run the thing" --json)"; echo "$C"
CID="$(printf '%s' "$C" | grep -m1 '"id"' | sed 's/.*"id": *"\([^"]*\)".*/\1/')"
orch check record "$ID" "$CID" --cmd "echo ok" --exit 0
step "ticket status + summary"
orch ticket status "$ID" active
orch ticket summary "$ID" "Smoke run on $(uname -s)"
step "ask"
orch ask "$ID" "Which colour?" --option red --option blue --recommend red
orch ticket show "$ID"
step "addon add $ADDON"
run_wait orch addon add "$ADDON" --yes
orch addon list
step "addon remove $ADDON"
run_wait orch addon remove "$ADDON"
run_wait orch addon uninstall "$ADDON"
step "uninstall orch"
uv tool uninstall orch-workspace
hash -r
if command -v orch >/dev/null 2>&1; then echo "orch is still on PATH after uninstall"; exit 1; fi
echo "SMOKE OK"
