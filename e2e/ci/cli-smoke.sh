#!/usr/bin/env bash
# CLI smoke for CI (R1.6, R3.4): orch is already installed (install.sh / install.ps1) and on PATH.
# Runs in a temp folder whose name has a space and an umlaut. bash on all three OSes (Git Bash on Windows).
#   cli-smoke.sh <addon-name>      # the add-on to add and remove again (default: focus)
set -eu
ADDON="${1:-focus}"
BASE="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
D="$BASE/orch smoke Büro $$"
mkdir -p "$D"; cd "$D"
step() { printf '\n=== %s\n' "$*"; }
# Windows cannot replace orch while it runs: add-on installs and removals finish in the background once the command
# has ended (winfinish.py) and print "Log: <file>". Wait for that file's RESULT line (e2e/windows/standard-user-flow.ps1 does too).
run_wait() {
  out="$("$@" 2>&1)"; rc=$?; echo "$out"; [ $rc -eq 0 ] || return $rc
  log="$(printf '%s\n' "$out" | sed -n 's/.*Log: \(.*\)$/\1/p' | tail -1)"
  [ -n "$log" ] || return 0
  command -v cygpath >/dev/null 2>&1 && log="$(cygpath -u "$log")"
  for _ in $(seq 1 200); do
    if grep -q ' RESULT ' "$log" 2>/dev/null; then grep ' RESULT ' "$log" | tail -1; grep -q ' RESULT ok' "$log"; return $?; fi
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
