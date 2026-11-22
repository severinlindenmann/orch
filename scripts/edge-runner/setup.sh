#!/bin/bash
# scripts/edge-runner/setup.sh : make the orch edge test server (Debian, ARM64) a GitHub runner for orch's Linux jobs
# (ORCH-1126). Never on a production server. Two steps, both as root:
#     sudo bash setup.sh            install everything (safe to run again; registers nothing, needs no token)
#     sudo bash setup.sh register   register the runner once: reads the runner registration token from stdin
# The registration token comes from GitHub (the repository > Settings > Actions > Runners > New self-hosted runner,
# or `gh api -X POST repos/<repo>/actions/runners/registration-token --jq .token` with an admin login; valid one hour).
# It is used once and never stored; the runner keeps only its own credentials, which can take jobs and nothing else.
#
# What it sets up (the same safety as the Mac's runner after its security review ORCH-1233):
# - packages the Linux jobs need that a job cannot install itself without sudo: faketime (clock tests), a C
#   toolchain for cargo, tmux, Chromium's system libraries (Playwright), nftables for the network rule
# - a user `orch-ci` with its own group and a closed home; lingering on, so the Services add-on's real Linux run
#   has a user service manager
# - everything of the runner in /usr/local/orch-edge-runner, owned by root (orch-ci can change none of it): the GitHub
#   runner 2.338.2 (checksum checked) as a read-only copy, its sign-up (label orch-edge), the job hooks, a `bash`
#   that starts the hooks without the job's settings (bash), the network rule (nft-orch-ci.nft) and the loop
# - the loop (runner-loop.sh, root, started at boot): before EVERY job it closes the private and the local network to
#   orch-ci, stops everything of orch-ci, makes a fresh runner folder from the copy and empties orch-ci's home and
#   temp files, then starts the runner for one job, under orch-ci, at lower priority than the test services, memory
#   capped at 5 GB (its user services at 1.5 GB)
# - job hooks: before each job they refuse anything but develop pushes, the nightly run, manual runs and release pull
#   requests; after each job they stop leftovers. Each job gets a throwaway home with its own download caches (Rust,
#   uv, Python, browsers, npm): no job leaves a program for the next one.
# - several runners side by side (ORCH_RUNNER_COUNT, default 3; manager 22 Nov: one runner made a develop run take
#   40+ minutes), each with all of the above on its own: runner 1 is user orch-ci with /usr/local/orch-edge-runner/job,
#   creds and orch-edge-runner(-loop).service; runner K>=2 is user orch-ci-K with job-K, creds-K and
#   orch-edge-runner(-loop)-K.service. Memory is shared out so the runners together never take more than the machine
#   minus 1.5 GB for the test services; test workers and build jobs per job follow the count (edge-job-home).
#   Change the count: sudo ORCH_RUNNER_COUNT=<n> bash setup.sh, then register the new ones (below).
# Run it again to take a new runner version (VER below): the sign-up stays. The runner never updates itself (each job
# starts from the copy), so bump VER when GitHub asks for a newer runner.
# Undo everything: sudo bash uninstall.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run it as root: sudo bash $0" >&2; exit 1; }
[ "$(uname -s)" = Linux ] && [ "$(uname -m)" = aarch64 ] && [ -f /etc/debian_version ] || { echo "This is for the orch edge test server (Debian, ARM64)." >&2; exit 1; }

REPO_URL=${ORCH_RUNNER_REPO_URL:-https://github.com/severinlindenmann/orch}
REPO=${REPO_URL#https://github.com/}
NAME=${ORCH_RUNNER_NAME:-orch-edge-$(hostname -s)}
VER=2.338.2; SHA=670adb2f268fe21dcbb58b3db0e0aa9d5b3bddfe2c651481336e561ff86de945
TAR=actions-runner-linux-arm64-$VER.tar.gz
PW_VER=1.55.0   # e2e/walkthrough/package-lock.json
PW_E2E_VER=1.64.1   # .github/workflows/e2e.yml
B=/usr/local/orch-edge-runner; HOOKS=$B
UNIT=/etc/systemd/system/orch-edge-runner.service; LOOP=/etc/systemd/system/orch-edge-runner-loop.service
SRC=$(cd "$(dirname "$0")" && pwd)
N=${ORCH_RUNNER_COUNT:-$(cat "$B/count" 2>/dev/null || echo 3)}
case $N in ([1-9]) ;; (*) echo "ORCH_RUNNER_COUNT must be 1 to 9, not '$N'." >&2; exit 2;; esac
# instance K: its user, the suffix of its folders and units ("" for 1, so the first runner keeps its old names)
user_of() { if [ "$1" = 1 ]; then echo orch-ci; else echo "orch-ci-$1"; fi; }
sfx_of() { if [ "$1" = 1 ]; then echo ""; else echo "-$1"; fi; }
stop_all() {  # every runner and loop, also of runners above the count (a lower count after a higher one)
  local k s
  for k in 1 2 3 4 5 6 7 8 9; do s=$(sfx_of "$k"); systemctl stop "orch-edge-runner-loop$s.service" "orch-edge-runner$s.service" 2>/dev/null || true; done
}

if [ "${1:-}" = register ]; then
  [ -f "$B/template/config.sh" ] || { echo "Run 'sudo bash $0' (the install) first." >&2; exit 1; }
  N=$(cat "$B/count" 2>/dev/null || echo 1)
  todo=""; for k in $(seq 1 "$N"); do [ -f "$B/creds$(sfx_of "$k")/.runner" ] || todo="$todo $k"; done
  if [ -n "$todo" ]; then
    # one token signs up every runner still without a sign-up (GitHub's token is valid for an hour, any number of runners)
    if [ -t 0 ]; then printf 'Runner registration token (from GitHub, not stored): '; IFS= read -rs TOKEN; echo
    else IFS= read -r TOKEN || true; fi
    [ -n "${TOKEN:-}" ] || { echo "No token; stopped. Run it again with the token on stdin." >&2; exit 1; }
    for k in $todo; do
      U=$(user_of "$k"); S=$(sfx_of "$k")
      systemctl stop "orch-edge-runner-loop$S.service" "orch-edge-runner$S.service" 2>/dev/null || true
      rm -rf "/usr/local/orch-edge-runner/job$S"; cp -a "$B/template" "$B/job$S"; chown -R "$U:$U" "$B/job$S"
      ( cd "$B/job$S" && sudo -u "$U" -H ./config.sh --unattended --replace --disableupdate --url "$REPO_URL" \
          --token "$TOKEN" --name "$NAME$S" --labels orch-edge --work "$B/job$S/_work" )
      rm -rf "/usr/local/orch-edge-runner/creds$S.new"; install -d -o root -g root -m 0700 "$B/creds$S.new"
      for f in .runner .credentials .credentials_rsaparams; do
        if [ -f "$B/job$S/$f" ] && [ ! -L "$B/job$S/$f" ]; then install -o root -g root -m 0600 "$B/job$S/$f" "$B/creds$S.new/$f"; fi
      done
      [ -f "$B/creds$S.new/.runner" ] || { unset TOKEN; echo "Runner $k did not sign up; stopped." >&2; exit 1; }
      rm -rf "/usr/local/orch-edge-runner/creds$S"; mv "$B/creds$S.new" "$B/creds$S"; rm -rf "/usr/local/orch-edge-runner/job$S"
    done
    unset TOKEN
  fi
  for k in $(seq 1 "$N"); do
    S=$(sfx_of "$k")
    # a runner whose loop already runs keeps running (its loop holds the lock --check would need)
    systemctl is-active --quiet "orch-edge-runner-loop$S.service" && continue
    "$B/runner-loop.sh" --check "$k"
    systemctl enable --now "orch-edge-runner-loop$S.service"
  done
  echo "Done. $N runner(s) ($NAME, $NAME-2 ...) run; GitHub shows them under Settings > Actions > Runners as Idle within a minute."
  echo "It takes the Linux jobs once the repository variable EDGE_RUNNER is orch-edge (docs/ci-checks.md)."
  exit 0
fi
[ -z "${1:-}" ] || { echo "usage: sudo bash $0 [register]" >&2; exit 2; }

# a running job is never killed by a re-install: stopping the runners would fail it in the middle (22 Nov: a re-install
# failed three jobs of the release keeper's test run). ORCH_SETUP_FORCE=1 stops them anyway. A job GitHub hands a
# runner in the seconds between this check and the stop below is still lost: re-install when no run is due.
if [ "${ORCH_SETUP_FORCE:-}" != 1 ] && pgrep -f 'Runner.Worker' >/dev/null 2>&1; then
  echo "A CI job is running on orch edge right now; run setup again when every runner is idle (or ORCH_SETUP_FORCE=1)." >&2
  exit 1
fi
# nothing of the runners runs while setup changes them (each loop also holds a lock, runner-loop.sh)
stop_all

# Memory: the machine minus 1.5 GB (relay, publish and hub test services, the system) for the runners. A job's user
# services (only the Services run starts some, one job per run) get a cap of their own, outside the runners': 1.5 GB
# for one runner, 1 GB for several, counted once. The rest is one shared pool (the slice orch-edge-runners.slice):
# the runners together never take more, but one heavy job (the relay build: one rustc takes 1.6 GB) may use most of
# it while the others run light tests. An even split (1.8 GB each with 3) killed rustc (ORCH-1126 measured run).
MEM_MB=$(awk '/^MemTotal:/ {print int($2/1024)}' /proc/meminfo)
if [ "$N" = 1 ]; then USER_MB=1536; else USER_MB=1024; fi
POOL_MB=$(( MEM_MB - 1536 - USER_MB ))
[ $(( POOL_MB / N )) -ge 1024 ] || { echo "$N runners leave each less than 1 GB of memory; use a lower ORCH_RUNNER_COUNT." >&2; exit 1; }
RUN_MAX=$POOL_MB; [ "$RUN_MAX" -gt 5120 ] && RUN_MAX=5120
RUN_MAX=${RUN_MAX}M; POOL_MAX=${POOL_MB}M; USER_MAX=${USER_MB}M

echo "== 1/6 packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq faketime build-essential pkg-config git curl tmux nodejs npm jq nftables >/dev/null

# orch edge gets an IPv6 default route from its network but no public IPv6 address: a download from a host with
# IPv6 addresses (pypi, raw.githubusercontent.com) then fails with "No route to host". Prefer IPv4 (RFC 6724 table).
grep -q '^precedence ::ffff:0:0/96' /etc/gai.conf 2>/dev/null || echo 'precedence ::ffff:0:0/96  100   # orch edge runner: prefer IPv4' >> /etc/gai.conf

echo "== 2/6 users orch-ci ... ($N runner(s))"
SUDO=/etc/sudoers.d/orch-ci-runner; : > "$SUDO.new"
for k in $(seq 1 "$N"); do
  U=$(user_of "$k"); H=/home/$U
  id "$U" >/dev/null 2>&1 || useradd --create-home --home-dir "$H" --shell /bin/bash --user-group "$U"
  chmod 700 "$H"
  loginctl enable-linger "$U"
  # no cron or at jobs for it: a job must not leave work that starts after it
  for f in /etc/cron.deny /etc/at.deny; do touch "$f"; grep -qx "$U" "$f" || echo "$U" >> "$f"; done
  crontab -r -u "$U" 2>/dev/null || true
  # after every job the clean-up hook restarts this user's own service manager: that one command, nothing else
  printf '%s ALL=(root) NOPASSWD: /usr/bin/systemctl restart user@%s.service\n' "$U" "$(id -u "$U")" >> "$SUDO.new"
  # user services a job starts (systemd --user) live outside the runner's own cap: give them one of their own
  mkdir -p "/etc/systemd/system/user-$(id -u "$U").slice.d"
  printf '[Slice]\nMemoryMax=%s\nTasksMax=2048\n' "$USER_MAX" > "/etc/systemd/system/user-$(id -u "$U").slice.d/orch-ci.conf"
done
chmod 0440 "$SUDO.new"; visudo -cqf "$SUDO.new" && mv -f "$SUDO.new" "$SUDO" || { rm -f /etc/sudoers.d/orch-ci-runner.new; echo "sudoers rule invalid; stopped." >&2; exit 1; }
for d in /home/* /root; do   # the runners should not read other people's files; say so, change nothing of theirs
  case $d in (/home/orch-ci|/home/orch-ci-[2-9]) continue;; esac
  [ -d "$d" ] || continue
  sudo -u orch-ci ls "$d" >/dev/null 2>&1 && echo "  note: the runner users can read $d (chmod o-rwx $d closes it)"
done
# an earlier install kept the runner and a shared download cache in the runner's home and its work folder in /srv:
# both were writable by every job (security review ORCH-1233 M2). The loop empties the home before each job.
systemctl disable --now orch-edge-runner.service 2>/dev/null || true
rm -rf /srv/orch-ci

echo "== 3/6 Chromium's system libraries (Playwright $PW_VER)"
npx -y "playwright@$PW_VER" install-deps chromium >/dev/null 2>&1 || echo "  note: Playwright could not install Chromium's libraries; the Services click-through may fail here"
# the full e2e run (e2e.yml, the nightly run on orch edge with EDGE_RUNNER=orch-edge-long) pins its own version
npx -y "playwright@$PW_E2E_VER" install-deps chromium >/dev/null 2>&1 || echo "  note: Playwright $PW_E2E_VER could not install Chromium's libraries; the full e2e run may fail here"

echo "== 4/6 hooks, bash, network rule and loop in $B (owned by root)"
[ -L "$B" ] && { echo "$B is a symlink; stopped." >&2; exit 1; }
install -d -o root -g root -m 0755 "$B" "$B/bin"
install -m 0755 -o root -g root "$SRC/job-started.sh" "$SRC/job-completed.sh" "$SRC/runner-loop.sh" "$B/"
# the network rule names every runner user (the file in the repository names orch-ci), also those of runners above
# the count that still exist: a leftover of theirs must never reach the private network either
users=""; for k in 1 2 3 4 5 6 7 8 9; do
  { [ "$k" -le "$N" ] || id "$(user_of "$k")" >/dev/null 2>&1; } && users="$users${users:+, }\"$(user_of "$k")\""
done
sed "s/meta skuid \"orch-ci\"/meta skuid { $users }/" "$SRC/nft-orch-ci.nft" > "$B/nft-orch-ci.nft.new"
[ "$(grep -c 'meta skuid {' "$B/nft-orch-ci.nft.new")" = 2 ] || { echo "network rule not written; stopped." >&2; exit 1; }
chown root:root "$B/nft-orch-ci.nft.new"; chmod 0644 "$B/nft-orch-ci.nft.new"; mv -f "$B/nft-orch-ci.nft.new" "$B/nft-orch-ci.nft"
printf '%s\n' "$N" > "$B/count.new"; chmod 0644 "$B/count.new"; mv -f "$B/count.new" "$B/count"   # read by edge-job-home
install -m 0755 -o root -g root "$SRC/bash" "$B/bin/bash"
printf '%s\n' "$REPO" > "$B/repo.new"; chmod 0644 "$B/repo.new"
mv -f "$B/repo.new" "$B/repo"   # the hooks trust this file, never the job's environment
# a copy of these scripts for registering and the undo (docs/ci-checks.md names this folder)
KEEP=/opt/orch-edge-runner-src; mkdir -p "$KEEP"
[ "$SRC" = "$KEEP" ] || install -m 0644 -o root -g root "$SRC/setup.sh" "$SRC/uninstall.sh" "$SRC/job-started.sh" \
  "$SRC/job-completed.sh" "$SRC/runner-loop.sh" "$SRC/nft-orch-ci.nft" "$SRC/bash" "$KEEP/"

echo "== 5/6 GitHub runner $VER (read-only copy)"
if [ "$(cat "$B/template/.orch-version" 2>/dev/null)" != "$VER" ]; then
  DL=/usr/local/orch-edge-runner/runner-download.tar.gz
  curl -fsSL -o "$DL" "https://github.com/actions/runner/releases/download/v$VER/$TAR"
  echo "$SHA  $DL" | sha256sum -c - >/dev/null || { echo "Checksum of the runner download is wrong; stopped." >&2; exit 1; }
  rm -rf /usr/local/orch-edge-runner/template.new; mkdir "$B/template.new"
  tar xzf "$DL" -C "$B/template.new" --no-same-owner
  rm -f /usr/local/orch-edge-runner/runner-download.tar.gz
  echo "$VER" > "$B/template.new/.orch-version"
  "$B/template.new/bin/installdependencies.sh" >/dev/null
  chown -R root:root "$B/template.new"; chmod -R go-w "$B/template.new"
  rm -rf /usr/local/orch-edge-runner/template.old; [ -d "$B/template" ] && mv "$B/template" "$B/template.old"
  mv "$B/template.new" "$B/template"; rm -rf /usr/local/orch-edge-runner/template.old
fi

echo "== 6/6 start at boot: per runner a loop as root and the runner under its user (one job per start)"
for k in $(seq 1 "$N"); do
U=$(user_of "$k"); H=/home/$U; S=$(sfx_of "$k")
UNIT=/etc/systemd/system/orch-edge-runner$S.service; LOOP=/etc/systemd/system/orch-edge-runner-loop$S.service
# The hooks and settings live in this root-owned unit, never in a file in the runner's own folder.
cat > "$UNIT.new" <<EOF
[Unit]
Description=orch CI runner $k of $N for the Linux jobs, one job per start (ORCH-1126, label orch-edge); never production
After=network-online.target
Wants=network-online.target

[Service]
User=$U
Group=$U
WorkingDirectory=$B/job$S
ExecStart=$B/job$S/run.sh --once
Environment=HOME=$H
Environment=ACTIONS_RUNNER_HOOK_JOB_STARTED=$HOOKS/job-started.sh
Environment=ACTIONS_RUNNER_HOOK_JOB_COMPLETED=$HOOKS/job-completed.sh
# the clean bash first: the runner starts the hooks with the first bash on this PATH (security review ORCH-1233 M1)
Environment=PATH=$B/bin:/usr/local/bin:/usr/bin:/bin
Environment=LANG=C.UTF-8
Restart=no
Nice=5
# GitHub's machines use 022; the user's own default (002) makes folders group-writable and orch's tests refuse that
UMask=0022
CPUWeight=50
Slice=orch-edge-runners.slice
MemoryMax=$RUN_MAX
KillMode=control-group
TimeoutStopSec=30
EOF
cat > "$LOOP.new" <<EOF
[Unit]
Description=orch CI runner loop $k: a fresh runner, home and closed private network before every job (ORCH-1126)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=$B/runner-loop.sh $k
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
for f in "$UNIT" "$LOOP"; do chmod 0644 "$f.new"; mv -f "$f.new" "$f"; done
done
# runners above the count (a lower count than before): off; their users and registrations stay (GitHub shows them offline)
for k in $(seq $((N + 1)) 9); do
  S=$(sfx_of "$k")
  [ -f "/etc/systemd/system/orch-edge-runner-loop$S.service" ] || continue
  systemctl disable --now "orch-edge-runner-loop$S.service" "orch-edge-runner$S.service" 2>/dev/null || true
  rm -f "/etc/systemd/system/orch-edge-runner-loop$S.service" "/etc/systemd/system/orch-edge-runner$S.service"
  # nothing of its user keeps running or starts again (it stays in the network rule above)
  U=$(user_of "$k")
  if uid=$(id -u "$U" 2>/dev/null); then
    loginctl disable-linger "$U" 2>/dev/null || true
    systemctl stop "user@$uid.service" "user-runtime-dir@$uid.service" 2>/dev/null || true
    pkill -KILL -u "$U" 2>/dev/null || true
  fi
  echo "  runner $k is off (above the count $N); remove it on GitHub under Settings > Actions > Runners"
done
# the runners' shared memory pool (see Memory above)
printf '[Unit]\nDescription=orch CI runners: one shared memory pool (ORCH-1126)\n\n[Slice]\nMemoryMax=%s\n' "$POOL_MAX" > /etc/systemd/system/orch-edge-runners.slice.new
chmod 0644 /etc/systemd/system/orch-edge-runners.slice.new; mv -f /etc/systemd/system/orch-edge-runners.slice.new /etc/systemd/system/orch-edge-runners.slice
systemctl daemon-reload
missing=""
for k in $(seq 1 "$N"); do
  S=$(sfx_of "$k")
  if [ -f "$B/creds$S/.runner" ]; then
    "$B/runner-loop.sh" --check "$k"
    systemctl enable "orch-edge-runner-loop$S.service"; systemctl restart "orch-edge-runner-loop$S.service"
  else missing="$missing $k"; fi
done
if [ -n "$missing" ]; then
  echo "Installed. Runner(s)$missing have no sign-up yet. Before registering: Settings > Actions > General > 'Fork pull"
  echo "request workflows from outside collaborators' must be the strictest choice (docs/ci-checks.md). Then:"
  echo "<token> | sudo bash $0 register   (one token signs up all of them)"
fi
