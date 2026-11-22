#!/usr/bin/env bash
# The Linux test world of the browser add-on's network wall (ORCH-1492, wall note ORCH-1156 section 5).
#
#   sudo -E bash wall/linux-world.sh            (from workspace-addons/browse, after `uv sync` and
#                                               `uv run python -m playwright install chromium-headless-shell`)
#
# Builds a closed, hostile world WITHOUT the filter's test-only name map, runs tests/test_wall_linux.py twice and
# tears everything down again (also on Ctrl-C or a failure):
#
#   obw-host  a network namespace that is "this computer": the test, the broker, its filter and the browser run
#             here. Canaries (servers/py canary) listen on 127.0.0.1, ::1, 10.0.0.5, 192.168.1.5,
#             169.254.169.254 and fd00::5 (TCP 80/443, UDP 3478). A veth 198.51.100.1/30 leads to obw-inet.
#   obw-inet  the "internet": site.test on 203.0.113.10:80 and the attacker evil.test on 203.0.113.66:80, routed
#             (their /24 is not a network obw-host sits on). Nothing else, no way out of the world.
#   names     a hosts file bind-mounted over /etc/hosts for the test only (the real /etc/hosts is never written):
#             site.test, evil.test, local.test, meta.test, lan.test, both.test (two answers), mapped6.test.
#             DNS goes to 198.51.100.2, where nothing answers.
#   record    tcpdump on every interface of obw-host: the independent record of what left.
#   cgroup    /sys/fs/cgroup/obwall/browser: the browser's processes (a wrapper puts them there; the broker
#             starts it through the test-only ORCH_BROWSE_TEST_BROWSER, read only with ORCH_HOME_STRICT=1).
#
# Run 1, the leak run: the browser has a route to every canary and the attacker; only its proxy setting holds it
# back. An nftables table only WATCHES what the browser sends anywhere but the filter (counted, let through).
# Run 2, the hard run: the same table DROPS everything the browser's processes send except TCP to 127.0.0.1 in
# the port range the filter listens in (the test checks the filter is the only listener there), UDP included.
#
# Pass: both pytest runs green (zero canary and attacker hits, zero non-GET hits on the site, the fail-closed
# checks), tcpdump shows no packet to a canary or the attacker and no UDP but DNS. Results and logs: $WALL_OUT
# (default: a new folder under /tmp), summary.txt there. Exit 0 = green.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADDON="$(dirname "$HERE")"
NS_HOST=obw-host
NS_INET=obw-inet
CG=/sys/fs/cgroup/obwall

die() { echo "linux-world: $*" >&2; exit 2; }

[ "$(id -u)" = 0 ] || die "needs root: sudo -E bash wall/linux-world.sh"
RUN_USER="${SUDO_USER:-}"
[ -n "$RUN_USER" ] && [ "$RUN_USER" != root ] || die "start it with sudo from a normal user (the browser never runs as root)"
RUN_UID="$(id -u "$RUN_USER")"
RUN_GID="$(id -g "$RUN_USER")"
RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
PY="$ADDON/.venv/bin/python"
[ -x "$PY" ] || die "no $PY: run uv sync in $ADDON first"
for tool in ip nft tcpdump nsenter unshare setpriv; do
  command -v "$tool" > /dev/null || die "missing $tool (Debian/Ubuntu: apt-get install iproute2 nftables tcpdump util-linux)"
done
[ "$(stat -fc %T /sys/fs/cgroup)" = cgroup2fs ] || die "needs cgroup v2 at /sys/fs/cgroup"
for ns in "$NS_HOST" "$NS_INET"; do
  [ ! -e "/run/netns/$ns" ] || die "namespace $ns exists already (an earlier run?): ip netns del $ns"
done
[ ! -e "$CG" ] || die "$CG exists already (an earlier run?)"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$RUN_HOME/.cache/ms-playwright}"

OUT="${WALL_OUT:-}"
if [ -z "$OUT" ]; then
  OUT="$(mktemp -d /tmp/orch-wall.XXXXXX)"
fi
mkdir -p "$OUT"
chown "$RUN_UID:$RUN_GID" "$OUT"
HOSTS_SUM="$(sha256sum /etc/hosts | cut -d' ' -f1)"
PIDS=()

as_user() { setpriv --reuid "$RUN_UID" --regid "$RUN_GID" --init-groups -- "$@"; }
in_ns() { local ns="$1"; shift; nsenter --net="/run/netns/$ns" -- "$@"; }

cleanup() {
  local rc=$?
  set +e
  for pid in "${PIDS[@]}"; do kill "$pid" 2> /dev/null; done
  sleep 0.5
  for pid in "${PIDS[@]}"; do kill -9 "$pid" 2> /dev/null; done
  for g in "$CG/browser" "$CG/test" "$CG"; do
    if [ -d "$g" ]; then
      # only processes this run started live here (its test, broker and browser)
      while read -r p; do [ -n "$p" ] && kill -9 "$p" 2> /dev/null; done < "$g/cgroup.procs"
    fi
  done
  sleep 0.5
  for g in "$CG/browser" "$CG/test" "$CG"; do [ -d "$g" ] && rmdir "$g"; done
  ip netns del "$NS_HOST" 2> /dev/null
  ip netns del "$NS_INET" 2> /dev/null
  chown -R "$RUN_UID:$RUN_GID" "$OUT" 2> /dev/null
  if [ "$(sha256sum /etc/hosts | cut -d' ' -f1)" != "$HOSTS_SUM" ]; then
    echo "linux-world: /etc/hosts changed during the run (not by this script)" >&2
    rc=1
  fi
  [ -e "/run/netns/$NS_HOST" ] || [ -e "/run/netns/$NS_INET" ] || [ -d "$CG" ] && {
    echo "linux-world: tear-down left something behind" >&2
    rc=1
  }
  echo "linux-world: torn down; results in $OUT"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# ---------------------------------------------------------------------------------------------- the world
ip netns add "$NS_HOST"
ip netns add "$NS_INET"
ip link add obw0 type veth peer name obw1
ip link set obw0 netns "$NS_HOST"
ip link set obw1 netns "$NS_INET"

in_ns "$NS_HOST" sh -ec '
  ip link set lo up
  ip addr add 198.51.100.1/30 dev obw0
  ip link set obw0 up
  ip route add 203.0.113.0/24 via 198.51.100.2
  ip link add obwcan type dummy
  ip link set obwcan up
  for a in 10.0.0.5/32 192.168.1.5/32 169.254.169.254/32; do ip addr add "$a" dev obwcan; done
  sysctl -qw net.ipv6.conf.all.disable_ipv6=0 net.ipv6.conf.obwcan.disable_ipv6=0 net.ipv6.conf.lo.disable_ipv6=0
  ip -6 addr add fd00::5/128 dev obwcan nodad
'
in_ns "$NS_INET" sh -ec '
  ip link set lo up
  ip addr add 198.51.100.2/30 dev obw1
  ip link set obw1 up
  ip addr add 203.0.113.10/32 dev lo
  ip addr add 203.0.113.66/32 dev lo
  ip route add default via 198.51.100.1
'

cat > "$OUT/hosts" << 'EOF'
127.0.0.1 localhost
::1 localhost
203.0.113.10 site.test
203.0.113.66 evil.test
127.0.0.1 local.test
169.254.169.254 meta.test
192.168.1.5 lan.test
203.0.113.10 both.test
127.0.0.1 both.test
::ffff:127.0.0.1 mapped6.test
EOF
echo "nameserver 198.51.100.2" > "$OUT/resolv.conf"
if [ -f /etc/nsswitch.conf ]; then
  sed 's/^hosts:.*/hosts: files dns/' /etc/nsswitch.conf > "$OUT/nsswitch.conf"
else
  echo "hosts: files dns" > "$OUT/nsswitch.conf"
fi
chmod 644 "$OUT/hosts" "$OUT/resolv.conf" "$OUT/nsswitch.conf"

# A command in obw-host with the world's names (a private mount namespace; the real files stay as they are).
in_world() {
  in_ns "$NS_HOST" unshare --mount --propagation slave -- sh -ec '
    out="$1"; shift
    mount --bind "$out/hosts" /etc/hosts
    mount --bind "$out/resolv.conf" /etc/resolv.conf
    mount --bind "$out/nsswitch.conf" /etc/nsswitch.conf
    exec "$@"' sh "$OUT" "$@"
}

: > "$OUT/hits.jsonl"
chmod 644 "$OUT/hits.jsonl"
in_ns "$NS_INET" python3 "$HERE/servers.py" inet "$OUT/hits.jsonl" > "$OUT/inet.log" 2>&1 &
PIDS+=($!)
in_ns "$NS_HOST" python3 "$HERE/servers.py" canary "$OUT/hits.jsonl" > "$OUT/canary.log" 2>&1 &
PIDS+=($!)
for _ in $(seq 1 50); do
  [ "$(grep -c ready "$OUT/inet.log" "$OUT/canary.log" | awk -F: '{s+=$2} END {print s}')" = 2 ] && break
  sleep 0.1
done

# Self-check: from this computer every canary and the attacker answer directly (so the leak run has a full
# route), and the names resolve as planned (both.test gives both answers).
for url in http://127.0.0.1/ "http://[::1]/" http://10.0.0.5/ http://192.168.1.5/ http://169.254.169.254/ \
  "http://[fd00::5]/" http://site.test/ http://evil.test/ http://both.test/; do
  in_world python3 -c '
import sys, urllib.error, urllib.request
try:
    urllib.request.urlopen(sys.argv[1] + "selfcheck", timeout=5).read()
except urllib.error.HTTPError:
    pass  # an answer is an answer' "$url" \
    || die "self-check: $url does not answer"
done
in_world python3 - << 'EOF' || die "self-check: names do not resolve as planned"
import socket
got = {a[4][0] for a in socket.getaddrinfo("both.test", 80, type=socket.SOCK_STREAM)}
assert {"203.0.113.10", "127.0.0.1"} <= got, got
assert socket.getaddrinfo("site.test", 80, type=socket.SOCK_STREAM)[0][4][0] == "203.0.113.10"
print("names ok:", sorted(got))
EOF
SELF="$(wc -l < "$OUT/hits.jsonl")"
# copy and empty in place: the servers keep the file open (append mode)
cp "$OUT/hits.jsonl" "$OUT/selfcheck-hits.jsonl"
: > "$OUT/hits.jsonl"
echo "self-check: $SELF direct hits (expected), the world is wired"

# ---------------------------------------------------------------------------------------------- the browser's cgroup
mkdir "$CG" "$CG/test" "$CG/browser"
# The test (as the normal user) moves the browser from obwall/test to obwall/browser: it needs write access to
# both cgroup.procs files of the common parent and the target (cgroup v2 delegation rules).
chown "$RUN_UID:$RUN_GID" "$CG/cgroup.procs" "$CG/browser/cgroup.procs"

REAL="$(as_user env PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" HOME="$OUT" "$PY" - << 'EOF'
import os, pathlib
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    full = pathlib.Path(p.chromium.executable_path)
rev = next(part for part in full.parts if part.startswith("chromium-")).split("-", 1)[1]
base = pathlib.Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]) / f"chromium_headless_shell-{rev}"
print(next(x for x in base.rglob("*") if x.name in ("chrome-headless-shell", "headless_shell") and x.is_file()))
EOF
)" || die "the pinned headless browser is not downloaded in $PLAYWRIGHT_BROWSERS_PATH"
WRAP="$OUT/browser-wrapper.sh"
cat > "$WRAP" << EOF
#!/bin/sh
# Test world only: put the browser's processes into the walled cgroup, then start the real headless browser.
echo \$\$ > "$CG/browser/cgroup.procs" || exit 97
exec "$REAL" "\$@"
EOF
chmod 755 "$WRAP"
echo "browser: $REAL"

PORTS="$(in_ns "$NS_HOST" cat /proc/sys/net/ipv4/ip_local_port_range | awk '{print $1 "-" $2}')"

wall_table() {
  local verdict="$1"
  in_ns "$NS_HOST" nft -f - << EOF
table inet obwall {
  counter direct {}
  counter to_filter {}
  set tried4 { type ipv4_addr . inet_proto . inet_service; flags dynamic; size 4096; }
  set tried6 { type ipv6_addr . inet_proto . inet_service; flags dynamic; size 4096; }
  chain out {
    type filter hook output priority 0; policy accept;
    socket cgroupv2 level 2 "obwall/browser" ip daddr 127.0.0.1 tcp dport $PORTS counter name to_filter accept
    socket cgroupv2 level 2 "obwall/browser" meta l4proto { tcp, udp } meta nfproto ipv4 add @tried4 { ip daddr . meta l4proto . th dport }
    socket cgroupv2 level 2 "obwall/browser" meta l4proto { tcp, udp } meta nfproto ipv6 add @tried6 { ip6 daddr . meta l4proto . th dport }
    socket cgroupv2 level 2 "obwall/browser" counter name direct $verdict
  }
}
EOF
}

CANARY_FILTER='dst host 10.0.0.5 or dst host 192.168.1.5 or dst host 169.254.169.254 or dst host fd00::5
  or dst host 203.0.113.66 or ((dst host 127.0.0.1 or dst host ::1) and (dst port 80 or dst port 443 or dst port 3478))'

FAIL=0
summary() { echo "$*" | tee -a "$OUT/summary.txt"; }

run_one() {
  local mode="$1" verdict="$2"
  local pcap="$OUT/$mode.pcap"
  in_ns "$NS_HOST" nft delete table inet obwall 2> /dev/null || true
  wall_table "$verdict"
  in_ns "$NS_HOST" tcpdump -i any -nn -U -s 256 -Z root -w "$pcap" > "$OUT/$mode-tcpdump.log" 2>&1 &
  local tpid=$!
  PIDS+=("$tpid")
  sleep 1.5
  local start
  start="$(wc -l < "$OUT/hits.jsonl")"
  local home
  home="$(as_user mktemp -d "$OUT/home-$mode.XXXX")"
  set +e
  # The test process joins obwall/test (root does that), then runs as the normal user in the world.
  sh -c 'echo $$ > "$1/test/cgroup.procs" && shift && exec "$@"' sh "$CG" \
    nsenter --net="/run/netns/$NS_HOST" -- unshare --mount --propagation slave -- sh -ec '
      out="$1"; shift
      mount --bind "$out/hosts" /etc/hosts
      mount --bind "$out/resolv.conf" /etc/resolv.conf
      mount --bind "$out/nsswitch.conf" /etc/nsswitch.conf
      exec "$@"' sh "$OUT" \
    setpriv --reuid "$RUN_UID" --regid "$RUN_GID" --init-groups -- \
    env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="$home" USERPROFILE="$home" ORCH_HOME="$home/orch" \
    ORCH_HOME_STRICT=1 TMPDIR="$home" PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" \
    ORCH_BROWSE_LINUX_WORLD=1 ORCH_WALL_MODE="$mode" ORCH_WALL_DIR="$OUT" ORCH_WALL_CGROUP="$CG/browser" \
    ORCH_BROWSE_TEST_BROWSER="$WRAP" PYTHONDONTWRITEBYTECODE=1 \
    sh -c 'cd "$1" && exec "$2" -m pytest -q -rs -p no:cacheprovider tests/test_wall_linux.py' sh "$ADDON" "$PY" \
    2>&1 | tee "$OUT/$mode-pytest.log"
  local prc=${PIPESTATUS[0]}
  set -e
  sleep 1
  kill "$tpid" 2> /dev/null || true
  wait "$tpid" 2> /dev/null || true
  in_ns "$NS_HOST" nft list table inet obwall > "$OUT/$mode-nft.txt" 2>&1 || true

  local canary udp leaks
  # shellcheck disable=SC2086
  canary="$(tcpdump -nn -r "$pcap" $CANARY_FILTER 2> /dev/null | tee "$OUT/$mode-canary-packets.txt" | wc -l)"
  udp="$(tcpdump -nn -r "$pcap" 'udp and not port 53' 2> /dev/null | tee "$OUT/$mode-udp-packets.txt" | wc -l)"
  leaks="$(tail -n +"$((start + 1))" "$OUT/hits.jsonl" | "$PY" -c '
import json, sys
bad = [h for h in map(json.loads, sys.stdin) if h["who"] != "site" or h["method"] not in ("GET", "HEAD")]
for h in bad:
    print(h, file=sys.stderr)
print(len(bad))')"
  local before after_probe
  before="$(grep -A1 'counter direct' "$OUT/$mode-nft.txt" | grep -o '[0-9][0-9]*' | head -1)"
  # Probe (after the record above): a program in the browser's cgroup connects straight to a canary, TCP
  # and UDP. Leak run: it gets through (the route is there). Hard run: the rule must drop it and count it.
  local probe
  probe="$(in_world sh -c 'echo $$ > "$1/cgroup.procs" && shift && exec "$@"' sh "$CG/browser" \
    setpriv --reuid "$RUN_UID" --regid "$RUN_GID" --init-groups -- python3 -c "
import socket
s = socket.socket(); s.settimeout(2)
try:
    s.connect((\"10.0.0.5\", 80)); print(\"tcp-through\", end=\" \")
except OSError:
    print(\"tcp-stopped\", end=\" \")
u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    u.sendto(b\"probe\", (\"10.0.0.5\", 3478)); print(\"udp-sent\")
except OSError:
    print(\"udp-stopped\")
" 2>&1)" || true
  in_ns "$NS_HOST" nft list table inet obwall > "$OUT/$mode-nft-after-probe.txt" 2>&1 || true
  after_probe="$(grep -A1 'counter direct' "$OUT/$mode-nft-after-probe.txt" | grep -o '[0-9][0-9]*' | head -1)"
  local direct tofilter
  direct="$(grep -A1 'counter direct' "$OUT/$mode-nft.txt" | grep -o 'packets [0-9]*' | head -1)"
  tofilter="$(grep -A1 'counter to_filter' "$OUT/$mode-nft.txt" | grep -o 'packets [0-9]*' | head -1)"
  summary "== $mode run ($([ "$verdict" = drop ] && echo 'the browser may only reach the filter' || echo 'only the proxy setting holds the browser back'))"
  summary "   pytest: exit $prc ($(tail -1 "$OUT/$mode-pytest.log"))"
  summary "   hits on canaries/attacker/site-non-GET (servers' logs): $leaks"
  summary "   tcpdump: $canary packets to a canary or the attacker, $udp UDP packets that are not DNS"
  summary "   nft: browser to the filter: ${tofilter:-?}; browser sent elsewhere ($([ "$verdict" = drop ] && echo dropped || echo let through)): ${direct:-?}"
  summary "   what the browser sent elsewhere (address . protocol . port):"
  sed -n '/set tried[46]/,/}/p' "$OUT/$mode-nft.txt" | grep -v '^\s*\(type\|size\|flags\)' | sed 's/^/      /' | tee -a "$OUT/summary.txt"
  summary "   probe from the browser's cgroup straight to 10.0.0.5 (after the record): $probe (nft direct counter $before -> $after_probe)"
  local want="tcp-through udp-sent"
  [ "$verdict" = drop ] && want="tcp-stopped udp-stopped"
  if [ "$prc" != 0 ] || [ "$leaks" != 0 ] || [ "$canary" != 0 ] || [ "$udp" != 0 ] || [ "$probe" != "$want" ] \
    || [ "${after_probe:-0}" -le "${before:-0}" ]; then
    FAIL=1
    summary "   RESULT: FAILED"
  else
    summary "   RESULT: green"
  fi
}

run_one leak accept
run_one hard drop

[ "$FAIL" = 0 ] && summary "linux-world: both runs green" || summary "linux-world: FAILED (see $OUT)"
exit "$FAIL"
