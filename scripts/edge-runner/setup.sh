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
# Run it again to take a new runner version (VER below): the sign-up stays. The runner never updates itself (each job
# starts from the copy), so bump VER when GitHub asks for a newer runner.
# Undo everything: sudo bash uninstall.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run it as root: sudo bash $0" >&2; exit 1; }
[ "$(uname -s)" = Linux ] && [ "$(uname -m)" = aarch64 ] && [ -f /etc/debian_version ] || { echo "This is for the orch edge test server (Debian, ARM64)." >&2; exit 1; }

REPO_URL=${ORCH_RUNNER_REPO_URL:-https://github.com/severinlindenmann/orch}
REPO=${REPO_URL#https://github.com/}
U=orch-ci; H=/home/$U; NAME=${ORCH_RUNNER_NAME:-orch-edge-$(hostname -s)}
VER=2.338.2; SHA=670adb2f268fe21dcbb58b3db0e0aa9d5b3bddfe2c651481336e561ff86de945
TAR=actions-runner-linux-arm64-$VER.tar.gz
PW_VER=1.55.0   # e2e/walkthrough/package-lock.json
B=/usr/local/orch-edge-runner; HOOKS=$B
UNIT=/etc/systemd/system/orch-edge-runner.service; LOOP=/etc/systemd/system/orch-edge-runner-loop.service
SRC=$(cd "$(dirname "$0")" && pwd)

if [ "${1:-}" = register ]; then
  [ -f "$B/template/config.sh" ] || { echo "Run 'sudo bash $0' (the install) first." >&2; exit 1; }
  if [ ! -f "$B/creds/.runner" ]; then
    if [ -t 0 ]; then printf 'Runner registration token (from GitHub, not stored): '; IFS= read -rs TOKEN; echo
    else IFS= read -r TOKEN || true; fi
    [ -n "${TOKEN:-}" ] || { echo "No token; stopped. Run it again with the token on stdin." >&2; exit 1; }
    systemctl stop orch-edge-runner-loop.service orch-edge-runner.service 2>/dev/null || true
    rm -rf /usr/local/orch-edge-runner/job; cp -a "$B/template" "$B/job"; chown -R "$U:$U" "$B/job"
    ( cd "$B/job" && sudo -u "$U" -H ./config.sh --unattended --replace --disableupdate --url "$REPO_URL" \
        --token "$TOKEN" --name "$NAME" --labels orch-edge --work "$B/job/_work" )
    unset TOKEN
    rm -rf /usr/local/orch-edge-runner/creds.new; install -d -o root -g root -m 0700 "$B/creds.new"
    for f in .runner .credentials .credentials_rsaparams; do
      if [ -f "$B/job/$f" ] && [ ! -L "$B/job/$f" ]; then install -o root -g root -m 0600 "$B/job/$f" "$B/creds.new/$f"; fi
    done
    [ -f "$B/creds.new/.runner" ] || { echo "The runner did not sign up; stopped." >&2; exit 1; }
    rm -rf /usr/local/orch-edge-runner/creds; mv "$B/creds.new" "$B/creds"; rm -rf /usr/local/orch-edge-runner/job
  fi
  "$B/runner-loop.sh" --check
  systemctl enable --now orch-edge-runner-loop.service
  echo "Done. '$NAME' runs; GitHub shows it under Settings > Actions > Runners as Idle within a minute."
  echo "It takes the Linux jobs once the repository variable EDGE_RUNNER is orch-edge (docs/ci-checks.md)."
  exit 0
fi
[ -z "${1:-}" ] || { echo "usage: sudo bash $0 [register]" >&2; exit 2; }

# nothing of the runner runs while setup changes it (the loop also holds a lock, runner-loop.sh)
systemctl stop orch-edge-runner-loop.service orch-edge-runner.service 2>/dev/null || true

echo "== 1/6 packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq faketime build-essential pkg-config git curl tmux nodejs npm jq nftables >/dev/null

# orch edge gets an IPv6 default route from its network but no public IPv6 address: a download from a host with
# IPv6 addresses (pypi, raw.githubusercontent.com) then fails with "No route to host". Prefer IPv4 (RFC 6724 table).
grep -q '^precedence ::ffff:0:0/96' /etc/gai.conf 2>/dev/null || echo 'precedence ::ffff:0:0/96  100   # orch edge runner: prefer IPv4' >> /etc/gai.conf

echo "== 2/6 user $U"
id "$U" >/dev/null 2>&1 || useradd --create-home --home-dir "$H" --shell /bin/bash --user-group "$U"
chmod 700 "$H"
loginctl enable-linger "$U"
# no cron or at jobs for it: a job must not leave work that starts after it
for f in /etc/cron.deny /etc/at.deny; do touch "$f"; grep -qx "$U" "$f" || echo "$U" >> "$f"; done
crontab -r -u "$U" 2>/dev/null || true
# after every job the clean-up hook restarts this user's own service manager: that one command, nothing else
SUDO=/etc/sudoers.d/orch-ci-runner
printf '%s ALL=(root) NOPASSWD: /usr/bin/systemctl restart user@%s.service\n' "$U" "$(id -u "$U")" > "$SUDO.new"
chmod 0440 "$SUDO.new"; visudo -cqf "$SUDO.new" && mv -f "$SUDO.new" "$SUDO" || { rm -f /etc/sudoers.d/orch-ci-runner.new; echo "sudoers rule invalid; stopped." >&2; exit 1; }
# user services a job starts (systemd --user) live outside the runner's own cap: give them one of their own, so the
# runner (5 GB) and its user services (1.5 GB) together leave room for the test copies of relay, publish and hub
mkdir -p "/etc/systemd/system/user-$(id -u "$U").slice.d"
printf '[Slice]\nMemoryMax=1536M\nTasksMax=2048\n' > "/etc/systemd/system/user-$(id -u "$U").slice.d/orch-ci.conf"
for d in /home/* /root; do   # the runner should not read other people's files; say so, change nothing of theirs
  [ "$d" = "$H" ] || [ ! -d "$d" ] && continue
  sudo -u "$U" ls "$d" >/dev/null 2>&1 && echo "  note: $U can read $d (chmod o-rwx $d closes it)"
done
# an earlier install kept the runner and a shared download cache in the runner's home and its work folder in /srv:
# both were writable by every job (security review ORCH-1233 M2). The loop empties the home before each job.
systemctl disable --now orch-edge-runner.service 2>/dev/null || true
rm -rf /srv/orch-ci

echo "== 3/6 Chromium's system libraries (Playwright $PW_VER)"
npx -y "playwright@$PW_VER" install-deps chromium >/dev/null 2>&1 || echo "  note: Playwright could not install Chromium's libraries; the Services click-through may fail here"

echo "== 4/6 hooks, bash, network rule and loop in $B (owned by root)"
[ -L "$B" ] && { echo "$B is a symlink; stopped." >&2; exit 1; }
install -d -o root -g root -m 0755 "$B" "$B/bin"
install -m 0755 -o root -g root "$SRC/job-started.sh" "$SRC/job-completed.sh" "$SRC/runner-loop.sh" "$B/"
install -m 0644 -o root -g root "$SRC/nft-orch-ci.nft" "$B/"
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

echo "== 6/6 start at boot: the loop as root, the runner under $U (one job per start)"
# The hooks and settings live in this root-owned unit, never in a file in the runner's own folder.
cat > "$UNIT.new" <<EOF
[Unit]
Description=orch CI runner for the Linux jobs, one job per start (ORCH-1126, label orch-edge); never production
After=network-online.target
Wants=network-online.target

[Service]
User=$U
Group=$U
WorkingDirectory=$B/job
ExecStart=$B/job/run.sh --once
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
MemoryMax=5G
KillMode=control-group
TimeoutStopSec=30
EOF
cat > "$LOOP.new" <<EOF
[Unit]
Description=orch CI runner loop: a fresh runner, home and closed private network before every job (ORCH-1126)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=$B/runner-loop.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
for f in "$UNIT" "$LOOP"; do chmod 0644 "$f.new"; mv -f "$f.new" "$f"; done
systemctl daemon-reload
if [ -f "$B/creds/.runner" ]; then
  "$B/runner-loop.sh" --check
  systemctl enable orch-edge-runner-loop.service; systemctl restart orch-edge-runner-loop.service
else
  echo "Installed. Before registering: Settings > Actions > General > 'Fork pull request workflows from outside"
  echo "collaborators' must be the strictest choice (docs/ci-checks.md). Then: <token> | sudo bash $0 register"
fi
