#!/usr/bin/env bash
# ORCH-371 Services end-to-end walk on a throwaway GitHub Ubuntu machine (never a real server).
# usage: e2e-linux.sh <commit sha> <mode: sealed|own-home> <out dir>
set -u
SHA="$1"; MODE="$2"; OUT="$3"; HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$OUT/shots"
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
R=$(mktemp -d "$HOME/.orch-e2e-XXXX"); W=$R/ws/svc-walk; mkdir -p "$W" "$R/home"
if [ "$MODE" = sealed ]; then H=$R/home; else H=$HOME; fi
OH=$(mktemp -d "$H/.orch-test-XXXX")/orch-tool   # orch's own folder is always sealed (must be under HOME)
UVH=$R/uv
E() {
  (cd "$W" && env -i HOME="$H" ORCH_HOME="$OH" ORCH_HOME_STRICT=1 ORCH_INSTALL_KIND=test ORCH_REF="$SHA" \
    PATH="$UVH/bin:$H/.local/bin:/usr/local/bin:/usr/bin:/bin" USER="$USER" LOGNAME="$USER" LANG=C.UTF-8 \
    XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" \
    UV_TOOL_DIR="$UVH/tools" UV_TOOL_BIN_DIR="$UVH/bin" UV_CACHE_DIR="$UVH/cache" UV_PYTHON_INSTALL_DIR="$UVH/python" "$@")
}
PASS=0; FAIL=0
o() { echo; echo "\$ orch services $*"; E orch services "$@"; local rc=$?; echo "exit $rc"; return $rc; }
ok() { if eval "$2"; then echo "PASS: $1"; PASS=$((PASS+1)); else echo "FAIL: $1"; FAIL=$((FAIL+1)); fi; }
state() { E orch services list --json | python3 -c "import json,sys;print({s['id']:s['state'] for s in json.load(sys.stdin)['services']}.get('$1','gone'))"; }
auto() { E orch services list --json | python3 -c "import json,sys;print({s['id']:s['auto'] for s in json.load(sys.stdin)['services']}.get('$1'))"; }
U() { systemctl --user "$@"; }

echo "== mode $MODE, HOME=$H, commit $SHA"
git -C "$W" init -q . && git -C "$W" -c user.name=W -c user.email=w@example.com commit -q --allow-empty -m init
E sh "$(git -C "$HERE" rev-parse --show-toplevel)/install.sh" > "$OUT/install-$MODE.log" 2>&1 || { tail -20 "$OUT/install-$MODE.log"; exit 1; }
E orch --version
E orch init --yes --recommended > "$OUT/init-$MODE.log" 2>&1; echo "init exit $?"
E orch addon add services --yes 2>&1 | tail -2
E orch ticket new "Web preview for the shop" | head -1
WSID=$(cat "$W/.orch/.local-id")
echo "== secret scan probe"
E "$UVH/tools/orch-workspace/bin/python" -I -c 'from pathlib import Path
from orch import secretscan
print(secretscan.find("Web preview\npython3", Path.cwd()))
print(secretscan.find("Web preview\npython3", Path.cwd(), strict=False))'

o add "Web preview" --id web-preview --port 18741 --ticket SW-1 -- python3 -m http.server 18741
ok "add leaves it stopped" '[ "$(state web-preview)" = stopped ]'
o start web-preview; sleep 3
ok "start runs it" '[ "$(state web-preview)" = running ]'
ok "it answers on its port" 'curl -fs -o /dev/null http://127.0.0.1:18741/'
U status "orch-svc-$WSID-web-preview.service" --no-pager 2>&1 | head -5
o restart web-preview; sleep 3
ok "restart keeps it running" '[ "$(state web-preview)" = running ] && curl -fs -o /dev/null http://127.0.0.1:18741/'
o auto web-preview on
ok "starts by itself on" '[ "$(auto web-preview)" = True ] && [ "$(U is-enabled orch-svc-$WSID-web-preview.service)" = enabled ]'
o auto web-preview off
ok "starts by itself off" '[ "$(auto web-preview)" = False ] && [ "$(U is-enabled orch-svc-$WSID-web-preview.service)" != enabled ]'
o stop web-preview; sleep 1
ok "stop stops it" '[ "$(state web-preview)" = stopped ] && ! curl -fs -o /dev/null http://127.0.0.1:18741/'
o log web-preview --lines 5

mkdir -p "$W/tools"
printf '#!/bin/sh\necho "starting talky"\necho "OPENAI_API_KEY=sk-proj-%s"\necho "all good"\nexec sleep 3600\n' "abcdefghijklmnopqrstuvwxyz0123456789ABCD" > "$W/tools/talky.sh"
o add "Talky bot" --id talky --start -- sh tools/talky.sh; sleep 2
LOG=$(E orch services log talky); echo "$LOG"
ok "log masks the key" 'echo "$LOG" | grep -q "••••••" && ! echo "$LOG" | grep -q "sk-proj-"'

# a found unit of this user, not made by orch
UD="$HOME/.config/systemd/user"; mkdir -p "$UD"
printf '[Unit]\nDescription=walk found\n[Service]\nExecStart=/bin/sleep 3600\n' > "$UD/walkfound.service"
U daemon-reload
o found
ok "found lists the unit" 'E orch services found --json | grep -q "systemd:walkfound.service"'
o adopt systemd:walkfound.service --name "Found sleeper"
o start found-sleeper; sleep 2
ok "a taken-over unit starts" '[ "$(U is-active walkfound.service)" = active ]'
o stop found-sleeper; sleep 1
ok "a taken-over unit stops" '[ "$(U is-active walkfound.service)" != active ]'

printf '#!/bin/sh\necho "crashy starting"; sleep 1; echo "crashy: cannot open database"; exit 1\n' > "$W/tools/crashy.sh"
o add "Order sync" --id order-sync --ticket SW-1 --start -- sh tools/crashy.sh
for i in 1 2 3 4 5; do sleep 12; o check --json | python3 -c "import json,sys;[print(c) for c in json.load(sys.stdin)['checked'] if c['id']=='order-sync']"; done
NQ=$(E orch ticket show SW-1 --json | python3 -c "import json,sys;print(sum(1 for q in json.load(sys.stdin).get('questions',[]) if 'keeps stopping' in q.get('text','')))")
ok "exactly one question for the failing service" '[ "$NQ" = 1 ]'
E orch ticket show SW-1 | sed -n 1,12p

# dashboard: pictures and one click each, signed in with a launch token
E orch start > /dev/null 2>&1; sleep 4
BASE=$(E orch status | sed -n 's/.*dashboard *\(http:\/\/127.0.0.1:[0-9]*\).*/\1/p' | head -1)
echo "dashboard $BASE"
tok() { E "$UVH/tools/orch-workspace/bin/python" -I -c 'from pathlib import Path
from orch import pagelaunch as m
print(m.write_launch_token(Path.cwd(),"dashboard"))'; }
if [ -n "$BASE" ]; then
  LAUNCH=$(tok) node "$HERE/walk.js" "$BASE" "$OUT/shots" after "L-$MODE-01-services" | grep -v '^shot'
  LAUNCH=$(tok) node "$HERE/walk.js" "$BASE" "$OUT/shots" clicks | grep -v '^shot'
  for f in "$OUT"/shots/[01][0-9]-click-*.png; do [ -e "$f" ] && mv "$f" "$OUT/shots/L-$MODE-$(basename "$f")"; done
  ok "dashboard Stop click left it stopped" '[ "$(state web-preview)" = stopped ]'
  LAUNCH=$(tok) node "$HERE/walk.js" "$BASE" "$OUT/shots" answer SW-1 Stop | grep -v '^shot'
  for f in "$OUT"/shots/L-question-on-ticket-1280.png "$OUT"/shots/L-answered-1280.png; do [ -e "$f" ] && mv "$f" "$OUT/shots/L-$MODE-$(basename "$f" | cut -c3-)"; done
  o check --json | python3 -c "import json,sys;[print(c) for c in json.load(sys.stdin)['checked'] if c['id']=='order-sync']"
  ok "the answer Stop stopped it" '[ "$(state order-sync)" = stopped ]'
  LAUNCH=$(tok) node "$HERE/walk.js" "$BASE" "$OUT/shots" after "L-$MODE-02-after-answer" | grep -v '^shot'
fi
for s in web-preview talky order-sync found-sleeper; do o remove "$s"; done
ok "nothing left in the user service manager" '! U list-unit-files "orch-svc-$WSID-*" --no-legend | grep -q .'
ok "logs are kept" '[ -f "$W/.orch/addons/services/logs/web-preview.log" ]'
E orch stop > /dev/null 2>&1
echo; echo "== $MODE: $PASS passed, $FAIL failed"
