#!/bin/bash
# scripts/mac-runner/uninstall.sh : undo setup.sh (ORCH-1125). Run as an admin: sudo bash scripts/mac-runner/uninstall.sh
# This is the off switch in an emergency: it stops the loop and the runner, removes their start-at-boot entries, the
# runner with its sign-up, the hooks and the network rule. Then remove the runner on GitHub too (Settings > Actions >
# Runners > the runner > Remove); until then GitHub shows it offline and ci.yml sends the Mac jobs to GitHub's
# machines by itself. The repository variable MAC_RUNNER alone only steers orch's own workflows, it does not close the
# runner. The user orch-ci and its home (/private/var/orch-ci) stay unless you add --remove-user.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run it with sudo: sudo bash $0" >&2; exit 1; }
launchctl bootout system /Library/LaunchDaemons/io.orch.mac-runner-loop.plist 2>/dev/null || true
launchctl bootout system /Library/LaunchDaemons/io.orch.mac-runner.plist 2>/dev/null || true
rm -f /Library/LaunchDaemons/io.orch.mac-runner-loop.plist /Library/LaunchDaemons/io.orch.mac-runner.plist
pkill -KILL -U orch-ci 2>/dev/null || true   # the runner user only; it exists for nothing else
rm -rf /usr/local/orch-mac-runner
pfctl -a com.apple/orch-ci -F all >/dev/null 2>&1 || true
rm -f /Users/Shared/orch-locks/heavy/holder; rmdir /Users/Shared/orch-locks/heavy 2>/dev/null || true
if [ "${1:-}" = "--remove-user" ]; then
  sysadminctl -deleteUser orch-ci >/dev/null 2>&1 || dscl . -delete /Users/orch-ci
  dscl . -delete /Groups/orch-ci 2>/dev/null || true
  rm -rf /private/var/orch-ci
  echo "User orch-ci removed."
fi
echo "Runner stopped and removed from this Mac. Remove it on GitHub too: Settings > Actions > Runners."
