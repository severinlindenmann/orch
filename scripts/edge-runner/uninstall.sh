#!/bin/bash
# scripts/edge-runner/uninstall.sh : undo setup.sh on the orch edge test server (ORCH-1126). Run as root.
# Stops the loop and the runner and removes their start-at-boot entries, the network rule and everything in
# /usr/local/orch-edge-runner (the runner copy, its sign-up, the hooks). This is the off switch: the repository
# variable EDGE_RUNNER only steers where ci.yml sends the jobs. The runner's registration on GitHub is removed by
# hand (Settings > Actions > Runners > the runner > Remove); until then GitHub shows it offline and ci.yml sends the
# Linux jobs to GitHub's machines by itself. The user orch-ci stays unless you add --remove-user.
# The packages (faketime, build tools, tmux, Node, nftables) stay.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run it as root: sudo bash $0" >&2; exit 1; }
systemctl disable --now orch-edge-runner-loop.service 2>/dev/null || true
systemctl disable --now orch-edge-runner.service 2>/dev/null || true
rm -f /etc/systemd/system/orch-edge-runner-loop.service /etc/systemd/system/orch-edge-runner.service /etc/sudoers.d/orch-ci-runner
uid=$(id -u orch-ci 2>/dev/null || true)
[ -n "$uid" ] && rm -f "/etc/systemd/system/user-$uid.slice.d/orch-ci.conf" && rmdir "/etc/systemd/system/user-$uid.slice.d" 2>/dev/null || true
systemctl daemon-reload
pkill -KILL -u orch-ci 2>/dev/null || true
nft delete table inet orch_ci_runner 2>/dev/null || true
rm -rf /usr/local/orch-edge-runner
if [ "${1:-}" = "--remove-user" ]; then
  loginctl disable-linger orch-ci 2>/dev/null || true
  userdel --remove orch-ci 2>/dev/null || true
  echo "User orch-ci removed."
fi
echo "Runner stopped and removed from orch edge. Remove it on GitHub too: Settings > Actions > Runners."
