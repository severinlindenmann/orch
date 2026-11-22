#!/bin/bash
# scripts/edge-runner/uninstall.sh : undo setup.sh on the orch edge test server (ORCH-1126). Run as root.
# Stops the loop and the runner and removes their start-at-boot entries, the network rule and everything in
# /usr/local/orch-edge-runner (the runner copy, its sign-up, the hooks). This is the off switch: the repository
# variable EDGE_RUNNER only steers where ci.yml sends the jobs. The runner's registration on GitHub is removed by
# hand (Settings > Actions > Runners > the runner > Remove); until then GitHub shows it offline and ci.yml sends the
# Linux jobs to GitHub's machines by itself. The users orch-ci, orch-ci-2 ... stay unless you add --remove-user.
# The packages (faketime, build tools, tmux, Node, nftables) stay.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run it as root: sudo bash $0" >&2; exit 1; }
# every runner: orch-ci with orch-edge-runner(-loop).service, orch-ci-K with orch-edge-runner(-loop)-K.service
systemctl disable --now orch-edge-runner-loop.service 2>/dev/null || true
systemctl disable --now orch-edge-runner.service 2>/dev/null || true
rm -f /etc/systemd/system/orch-edge-runner-loop.service /etc/systemd/system/orch-edge-runner.service /etc/sudoers.d/orch-ci-runner
for k in 2 3 4 5 6 7 8 9; do
  systemctl disable --now "orch-edge-runner-loop-$k.service" "orch-edge-runner-$k.service" 2>/dev/null || true
  rm -f "/etc/systemd/system/orch-edge-runner-loop-$k.service" "/etc/systemd/system/orch-edge-runner-$k.service"
done
for u in orch-ci orch-ci-2 orch-ci-3 orch-ci-4 orch-ci-5 orch-ci-6 orch-ci-7 orch-ci-8 orch-ci-9; do
  uid=$(id -u "$u" 2>/dev/null || true)
  [ -n "$uid" ] || continue
  rm -f "/etc/systemd/system/user-$uid.slice.d/orch-ci.conf"; rmdir "/etc/systemd/system/user-$uid.slice.d" 2>/dev/null || true
  pkill -KILL -u "$u" 2>/dev/null || true
  if [ "${1:-}" = "--remove-user" ]; then
    loginctl disable-linger "$u" 2>/dev/null || true
    userdel --remove "$u" 2>/dev/null || true
    echo "User $u removed."
  fi
done
systemctl daemon-reload
nft delete table inet orch_ci_runner 2>/dev/null || true
rm -rf /usr/local/orch-edge-runner
echo "Runner stopped and removed from orch edge. Remove it on GitHub too: Settings > Actions > Runners."
