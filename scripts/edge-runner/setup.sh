#!/bin/bash
# scripts/edge-runner/setup.sh : make the orch edge test server (Debian, ARM64) a GitHub runner for orch's Linux jobs
# (ORCH-1126). Never on a production server. Two steps, both as root:
#     sudo bash setup.sh            install everything (safe to run again; registers nothing, needs no token)
#     sudo bash setup.sh register   register the runner once: reads the runner registration token from stdin
# The registration token comes from GitHub (the repository > Settings > Actions > Runners > New self-hosted runner,
# or `gh api -X POST repos/<repo>/actions/runners/registration-token --jq .token` with an admin login; valid one hour).
# It is used once and never stored; the runner keeps only its own credentials, which can take jobs and nothing else.
#
# What it sets up:
# - packages the Linux jobs need that a job cannot install itself without sudo: faketime (clock tests), a C
#   toolchain for cargo, tmux, Node (only to install Chromium's system libraries for Playwright)
# - a user `orch-ci` with its own group and a closed home; lingering on, so the Services add-on's real Linux run
#   has a user service manager
# - Rust (rustup, stable, rustfmt, clippy) in orch-ci's download cache, which every job reuses
#   (.github/actions/edge-job-home)
# - the GitHub runner 2.338.2 (checksum checked) in /home/orch-ci/actions-runner, label orch-edge, started at boot
#   by systemd under that user at lower priority than the test services, memory capped at 5 GB (its user services at 1.5 GB)
# - job hooks in /usr/local/orch-edge-runner (owned by root, the runner cannot change them): before each job they
#   refuse anything but develop pushes, the nightly run, manual runs and release pull requests; after each job they
#   stop leftovers, remove throwaway user services and clean up. Each job gets a throwaway home in its temp folder.
# Undo everything: sudo bash uninstall.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run it as root: sudo bash $0" >&2; exit 1; }
[ "$(uname -s)" = Linux ] && [ "$(uname -m)" = aarch64 ] && [ -f /etc/debian_version ] || { echo "This is for the orch edge test server (Debian, ARM64)." >&2; exit 1; }

REPO_URL=${ORCH_RUNNER_REPO_URL:-https://github.com/severinlindenmann/orch}
REPO=${REPO_URL#https://github.com/}
U=orch-ci; H=/home/$U; WORK=/srv/orch-ci/work; NAME=${ORCH_RUNNER_NAME:-orch-edge-$(hostname -s)}
VER=2.338.2; SHA=670adb2f268fe21dcbb58b3db0e0aa9d5b3bddfe2c651481336e561ff86de945
TAR=actions-runner-linux-arm64-$VER.tar.gz
PW_VER=1.55.0   # e2e/walkthrough/package-lock.json
HOOKS=/usr/local/orch-edge-runner
UNIT=/etc/systemd/system/orch-edge-runner.service
SRC=$(cd "$(dirname "$0")" && pwd)
R=$H/actions-runner

if [ "${1:-}" = register ]; then
  [ -x "$R/config.sh" ] || { echo "Run 'sudo bash $0' (the install) first." >&2; exit 1; }
  if [ ! -f "$R/.runner" ]; then
    if [ -t 0 ]; then printf 'Runner registration token (from GitHub, not stored): '; IFS= read -rs TOKEN; echo
    else IFS= read -r TOKEN || true; fi
    [ -n "${TOKEN:-}" ] || { echo "No token; stopped. Run it again with the token on stdin." >&2; exit 1; }
    ( cd "$R" && sudo -u "$U" -H ./config.sh --unattended --replace --url "$REPO_URL" \
        --token "$TOKEN" --name "$NAME" --labels orch-edge --work "$WORK" )
    unset TOKEN
  fi
  systemctl enable --now orch-edge-runner.service
  echo "Done. '$NAME' runs; GitHub shows it under Settings > Actions > Runners as Idle within a minute."
  echo "It takes the Linux jobs once the repository variable EDGE_RUNNER is orch-edge (docs/ci-checks.md)."
  exit 0
fi
[ -z "${1:-}" ] || { echo "usage: sudo bash $0 [register]" >&2; exit 2; }

echo "== 1/6 packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq faketime build-essential pkg-config git curl tmux nodejs npm jq >/dev/null

# orch edge gets an IPv6 default route from its network but no public IPv6 address: a download from a host with
# IPv6 addresses (pypi, raw.githubusercontent.com) then fails with "No route to host". Prefer IPv4 (RFC 6724 table).
grep -q '^precedence ::ffff:0:0/96' /etc/gai.conf 2>/dev/null || echo 'precedence ::ffff:0:0/96  100   # orch edge runner: prefer IPv4' >> /etc/gai.conf

echo "== 2/6 user $U"
id "$U" >/dev/null 2>&1 || useradd --create-home --home-dir "$H" --shell /bin/bash --user-group "$U"
chmod 700 "$H"
# the jobs' work folder (with each job's throwaway home and temp files) lies OUTSIDE the runner user's home: orch's
# tests check that a test home is never inside the real one
install -d -o root -g root -m 0755 /srv/orch-ci; install -d -o "$U" -g "$U" -m 0750 "$WORK"
loginctl enable-linger "$U"
# no cron or at jobs for it: a job must not leave work that starts after it
for f in /etc/cron.deny /etc/at.deny; do touch "$f"; grep -qx "$U" "$f" || echo "$U" >> "$f"; done
crontab -r -u "$U" 2>/dev/null || true
# user services a job starts (systemd --user) live outside the runner's own cap: give them one of their own, so the
# runner (5 GB) and its user services (1.5 GB) together leave room for the test copies of relay, publish and hub
mkdir -p "/etc/systemd/system/user-$(id -u "$U").slice.d"
printf '[Slice]\nMemoryMax=1536M\nTasksMax=2048\n' > "/etc/systemd/system/user-$(id -u "$U").slice.d/orch-ci.conf"
for d in /home/* /root; do   # the runner should not read other people's files; say so, change nothing of theirs
  [ "$d" = "$H" ] || [ ! -d "$d" ] && continue
  sudo -u "$U" ls "$d" >/dev/null 2>&1 && echo "  note: $U can read $d (chmod o-rwx $d closes it)"
done

echo "== 3/6 Rust for the jobs (in $H/ci-cache)"
sudo -u "$U" -H mkdir -p "$H/ci-cache/cargo" "$H/ci-cache/rustup"
if [ ! -x "$H/ci-cache/cargo/bin/rustup" ]; then
  tmp=$(mktemp -d); chmod 755 "$tmp"
  curl -fsSL --proto '=https' --tlsv1.2 -o "$tmp/rustup-init.sh" https://sh.rustup.rs; chmod 644 "$tmp/rustup-init.sh"
  sudo -u "$U" -H env CARGO_HOME="$H/ci-cache/cargo" RUSTUP_HOME="$H/ci-cache/rustup" \
    sh "$tmp/rustup-init.sh" -y -q --no-modify-path --profile minimal --default-toolchain stable -c rustfmt -c clippy
  rm -f "$tmp/rustup-init.sh"; rmdir "$tmp"
fi
sudo -u "$U" -H env CARGO_HOME="$H/ci-cache/cargo" RUSTUP_HOME="$H/ci-cache/rustup" "$H/ci-cache/cargo/bin/cargo" --version

echo "== 4/6 Chromium's system libraries (Playwright $PW_VER)"
npx -y "playwright@$PW_VER" install-deps chromium >/dev/null 2>&1 || echo "  note: Playwright could not install Chromium's libraries; the Services click-through may fail here"

echo "== 5/6 GitHub runner $VER and job hooks"
if [ ! -x "$R/config.sh" ]; then
  sudo -u "$U" -H mkdir -p "$R"
  tmp=$(mktemp -d); curl -fsSL -o "$tmp/$TAR" "https://github.com/actions/runner/releases/download/v$VER/$TAR"
  echo "$SHA  $tmp/$TAR" | sha256sum -c - >/dev/null || { echo "Checksum of the runner download is wrong; stopped." >&2; exit 1; }
  sudo -u "$U" tar xzf - -C "$R" < "$tmp/$TAR"; rm -f "$tmp/$TAR"; rmdir "$tmp"
  "$R/bin/installdependencies.sh" >/dev/null
fi
mkdir -p "$HOOKS"
install -m 0755 -o root -g root "$SRC/job-started.sh" "$SRC/job-completed.sh" "$HOOKS/"
# a copy of these scripts for registering and the undo (docs/ci-checks.md names this folder)
KEEP=/opt/orch-edge-runner-src; mkdir -p "$KEEP"
[ "$SRC" = "$KEEP" ] || install -m 0644 -o root -g root "$SRC/setup.sh" "$SRC/uninstall.sh" "$SRC/job-started.sh" "$SRC/job-completed.sh" "$KEEP/"
printf '%s\n' "$REPO" > "$HOOKS/repo.new"; chmod 0644 "$HOOKS/repo.new"
mv -f "$HOOKS/repo.new" "$HOOKS/repo"   # the hooks trust this file, never the job's environment

echo "== 6/6 start at boot under $U"
# The hooks and settings live in this root-owned unit, never in a file in the runner's own folder.
cat > "$UNIT.new" <<EOF
[Unit]
Description=orch CI runner for the Linux jobs (ORCH-1126, label orch-edge); never production
After=network-online.target
Wants=network-online.target

[Service]
User=$U
Group=$U
WorkingDirectory=$R
ExecStart=$R/run.sh
Environment=HOME=$H
Environment=ACTIONS_RUNNER_HOOK_JOB_STARTED=$HOOKS/job-started.sh
Environment=ACTIONS_RUNNER_HOOK_JOB_COMPLETED=$HOOKS/job-completed.sh
Environment=PATH=/usr/local/bin:/usr/bin:/bin
Environment=LANG=C.UTF-8
Restart=always
RestartSec=10
Nice=5
# GitHub's machines use 022; the user's own default (002) makes folders group-writable and orch's tests refuse that
UMask=0022
CPUWeight=50
MemoryMax=5G
KillMode=process
KillSignal=SIGTERM
TimeoutStopSec=5min

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$UNIT.new"; mv -f "$UNIT.new" "$UNIT"
systemctl daemon-reload
if [ -f "$R/.runner" ]; then systemctl enable --now orch-edge-runner.service; systemctl restart orch-edge-runner.service
else echo "Installed. Register the runner once: <token> | sudo bash $0 register"; fi
