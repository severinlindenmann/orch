#!/bin/bash
# scripts/mac-runner/uninstall.sh : undo setup.sh (ORCH-1125). Run as an admin: sudo bash scripts/mac-runner/uninstall.sh
# Stops the runner and removes its start-at-boot entry and the job hooks. The runner's sign-up on GitHub is removed
# by hand (Settings > Actions > Runners > the runner > Remove); until then GitHub shows it offline and ci.yml sends
# the Mac jobs to GitHub's machines by itself. The user orch-ci and its home stay unless you add --remove-user.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run it with sudo: sudo bash $0" >&2; exit 1; }
PLIST=/Library/LaunchDaemons/io.orch.mac-runner.plist
launchctl bootout system "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
rm -f /usr/local/orch-mac-runner/lock.sh /usr/local/orch-mac-runner/job-started.sh /usr/local/orch-mac-runner/job-completed.sh
rmdir /usr/local/orch-mac-runner 2>/dev/null || true
rm -f /Users/Shared/orch-locks/heavy/holder; rmdir /Users/Shared/orch-locks/heavy 2>/dev/null || true
if [ "${1:-}" = "--remove-user" ]; then
  sysadminctl -deleteUser orch-ci >/dev/null 2>&1 || dscl . -delete /Users/orch-ci
  dscl . -delete /Groups/orch-ci 2>/dev/null || true
  echo "User orch-ci removed."
fi
echo "Runner stopped and removed from this Mac. Remove it on GitHub too: Settings > Actions > Runners."
