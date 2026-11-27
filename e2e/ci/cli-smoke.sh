#!/usr/bin/env bash
# CLI smoke for CI (R1.6, R3.4): orch is already installed (install.sh / install.ps1) and on PATH.
# Runs in a test folder (under .orch-test in the home) whose name has a space and an umlaut. bash on all three OSes (Git Bash on Windows).
#   cli-smoke.sh <addon-name>      # the add-on to add and remove again (default: focus)
set -eu
ADDON="${1:-focus}"
# Never the real ~/.orch-tool: orch's per-machine folder is a temp folder under the home, and strict mode makes any
# fallback to the real one an error. The workflow sets both (so the install is covered too); this is the local default.
if [ -z "${ORCH_HOME:-}" ]; then ORCH_HOME="$HOME/.orch-test/smoke-home-$$"; mkdir -p "$ORCH_HOME"; fi
export ORCH_HOME ORCH_HOME_STRICT=1
AGENT_PY="$(cd "$(dirname "$0")/../fixtures/generic-agent" && pwd)/agent.py"  # the generic fake agent (R3.4)
# The workspace sits beside that folder, under .orch-test: a test install works only in test folders there, and
# an evidence write is refused where orch cannot read the saved keys (ORCH-2077).
BASE="$(dirname "$ORCH_HOME")"
if command -v cygpath >/dev/null 2>&1; then BASE="$(cygpath -u "$BASE")"; fi
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
# F2 with the scripted fake agent (R3.4, R2.1-R2.6, ORCH-2069): it asks and works on while it waits; the person
# answers; its next run picks the answer up and sends the ticket to Check; the person marks it Done. The folder has a
# space and an umlaut, and so has the evidence file.
step "F2 loop with the fake agent"
PY=""; for c in python3 python; do if "$c" -c 'import sys' >/dev/null 2>&1; then PY="$c"; break; fi; done
[ -n "$PY" ] || { echo "no python for the fake agent"; exit 1; }
f2_is() {  # f2_is <python expression over the ticket t>: fails the smoke when it is false
  orch ticket show "$FID" --json | "$PY" -c 'import json, sys
t = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
ok = eval(sys.argv[1])
print("ok:" if ok else "FAILED:", sys.argv[1])
ok or print(json.dumps({k: t.get(k) for k in ("status", "waiting_on", "checklist", "questions")}, indent=1))
sys.exit(0 if ok else 1)' "$1"
}
F="$(orch ticket new "F2 Übung" --json)"
FID="$(printf '%s' "$F" | grep -m1 '"id"' | sed 's/.*"id": *"\([^"]*\)".*/\1/')"
orch check add "$FID" "draft the letter"
orch check add "$FID" "attach the report"
orch check add "$FID" "send it after the answer"
ORCH_TICKET="$FID" "$PY" "$AGENT_PY" --ask "Send it today?" "work on $FID"
f2_is 't["status"] == "waiting" and t["waiting_on"] == {"kind": "question", "ref": "q1"}'
f2_is 't["checklist"][0]["done"] and t["checklist"][0]["evidence"] and not t["checklist"][2]["done"]'
rc=0; orch check done "$FID" c2 || rc=$?
[ "$rc" = 2 ] || { echo "check done without evidence: exit $rc, expected 2"; exit 1; }
mkdir -p "Berichte Ü"; echo "Umsatz ok" > "Berichte Ü/Q4 Bericht.txt"
orch check done "$FID" c2 --file "Berichte Ü/Q4 Bericht.txt"
f2_is 't["checklist"][1]["evidence"][0]["type"] == "file" and t["checklist"][1]["evidence"][0]["ref"].endswith("Q4 Bericht.txt")'
orch answer "$FID" q1 no
f2_is 't["waiting_on"] is None and t["questions"][0]["answer"] == "no"'
ORCH_TICKET="$FID" "$PY" "$AGENT_PY" --ask "Send it today?" "work on $FID"
f2_is 't["status"] == "review" and t["checklist"][2]["evidence"][0]["ref"] == "answer was no"'
# a helper's own Done stays in Review: a person marks a ticket Done (ORCH-2108)
orch ticket status "$FID" done
f2_is 't["status"] == "review"'
# ORCH-897 (first run): init is safe to repeat, and orch uninstall keeps the tickets so init brings the folder back
step "init again"
ORCH_AGENT=claude orch init
orch ticket show "$ID" >/dev/null
step "uninstall keeps tickets, init again"
orch uninstall </dev/null
test ! -f .agents/skills/orch/SKILL.md
orch ticket show "$ID" >/dev/null 2>&1 || test -f ".orch/tickets/$ID.json"
ORCH_AGENT=claude orch init
test -f .agents/skills/orch/SKILL.md
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
