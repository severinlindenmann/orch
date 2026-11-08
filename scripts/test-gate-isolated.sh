#!/bin/bash
# Test for gate-isolated.sh: PASS removes the temp home, FAIL keeps exactly one (the newest). Run: scripts/test-gate-isolated.sh
set -u
D=$(cd "$(dirname "$0")" && pwd); G="$D/gate-isolated.sh"; T=$HOME/.orch-test; mkdir -p "$T"
S=$(mktemp -d "$T/gtest-XXXX"); trap 'rm -rf "$S"' EXIT
printf '#!/bin/sh\necho "$HOME" > "%s/home"; touch "$HOME/marker"; [ "$ORCH_HOME_STRICT" = 1 ] && [ "$HOME" != "%s" ] || exit 9; exit 0\n' "$S" "$HOME" > "$S/ok.sh"
printf '#!/bin/sh\ntouch "$HOME/marker"; exit 1\n' > "$S/bad.sh"; chmod +x "$S"/*.sh
export GATE_STATE="$S/state"; fail() { echo "FAIL: $*"; exit 1; }
GATE_CMD="$S/ok.sh" "$G" || fail "pass run exited non-zero"
[ -s "$S/home" ] && [ ! -e "$(cat "$S/home")" ] || fail "temp home left after PASS"
GATE_CMD="$S/bad.sh" "$G" 2>/dev/null && fail "failing gate returned 0"
k1=$(cat "$S/state"); [ -f "$k1/marker" ] || fail "failed home not kept"
GATE_CMD="$S/bad.sh" "$G" 2>/dev/null
k2=$(cat "$S/state"); [ "$k1" != "$k2" ] && [ ! -e "$k1" ] && [ -d "$k2" ] || fail "previous failing home not replaced"
rm -rf "$k2"
echo "test-gate-isolated: PASS"
