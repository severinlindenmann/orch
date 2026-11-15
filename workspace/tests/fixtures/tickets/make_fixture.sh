#!/bin/sh
# usage: make_fixture.sh <oldwt> <home> ; makes a workspace in <home>/ws with sample tickets
HERE=$(cd "$(dirname "$0")" && pwd); WT=$1; HM=$2; WS=$HM/ws
mkdir -p "$WS"; cd "$WS"
O() { "$HERE/orch_old.sh" "$WT" "$HM" "$WS" "$@"; }
mkdir -p src; echo "# exporter" > src/export.py
O init --yes --code FIX || exit 1
A=$(O ticket new "Export invoices as CSV" --json --by human:tester --owner tester --due 2026-12-01 --done-when "CSV export works and is documented" --note "fixture ticket" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
echo "A=$A"
O check add $A "Write the exporter" --by human:tester
O check add $A "Add a test" --by human:tester
O check add $A "Document it" --by human:tester
O check add $A "Ask about the date format" --by human:tester
O check done $A c1 --by agent:fixture --commit abc1234 --file src/export.py --url https://example.com/pr/1 --pr "#12" --note "exporter written" --summary "exporter done"
O check done $A c2 --by agent:fixture --command "pytest tests/test_export.py" --note "passes"
O ticket summary $A "Exporter done, tests pass, docs open." --by agent:fixture
O ticket outcome $A --changed "Added a CSV exporter." --why "Finance needs it." --by agent:fixture
O ask $A "Which date format?" --option "ISO 8601" --option "dd.mm.yyyy" --recommend "ISO 8601" --by agent:fixture --check c4
O ticket status $A active --by agent:fixture
B=$(O ticket new "Fix the login page" --json --by human:tester | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
echo "B=$B"
O check add $B "Reproduce the bug" --by human:tester
O check done $B c1 --by agent:fixture --note "reproduced" --url https://example.com/issue/9
O ticket wait $B --until 2026-11-30 --by agent:fixture
C=$(O ticket new "Sub task of export" --json --by human:tester --parent $A | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
echo "C=$C"
D=$(O ticket new "Review me" --json --by human:tester --ext 'dashboard={"pinned":true}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
O check add $D "Only step" --by human:tester
O check done $D c1 --by agent:fixture --note ok
O ticket status $D review --by agent:fixture
O ticket wait $B --on external:vendor-reply --by agent:fixture
ls -R "$WS/.orch" | head -40
