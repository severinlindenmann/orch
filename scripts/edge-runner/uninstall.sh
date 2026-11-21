#!/bin/bash
# scripts/edge-runner/uninstall.sh : undo setup.sh on the orch edge test server (ORCH-1126). Run as root.
# Stops the runner and removes its start-at-boot entry and the job hooks. The runner's registration on GitHub is removed
# by hand (Settings > Actions > Runners > the runner > Remove); until then GitHub shows it offline and ci.yml sends
# the Linux jobs to GitHub's machines by itself. The user orch-ci and its home stay unless you add --remove-user.
# The packages (faketime, build tools, tmux, Node) stay.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run it as root: sudo bash $0" >&2; exit 1; }
systemctl disable --now orch-edge-runner.service 2>/dev/null || true
rm -f /etc/systemd/system/orch-edge-runner.service /etc/sudoers.d/orch-ci-runner
uid=$(id -u orch-ci 2>/dev/null || true)
[ -n "$uid" ] && rm -f "/etc/systemd/system/user-$uid.slice.d/orch-ci.conf" && rmdir "/etc/systemd/system/user-$uid.slice.d" 2>/dev/null || true
systemctl daemon-reload
rm -f /usr/local/orch-edge-runner/job-started.sh /usr/local/orch-edge-runner/job-completed.sh /usr/local/orch-edge-runner/repo
rmdir /usr/local/orch-edge-runner 2>/dev/null || true
if [ "${1:-}" = "--remove-user" ]; then
  loginctl disable-linger orch-ci 2>/dev/null || true
  userdel --remove orch-ci 2>/dev/null || true
  echo "User orch-ci removed."
fi
echo "Runner stopped and removed from orch edge. Remove it on GitHub too: Settings > Actions > Runners."
