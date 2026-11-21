#!/bin/bash
# scripts/mac-runner/setup.sh : make this Mac a GitHub runner for orch's Mac jobs (ORCH-1125). Run ONCE, as an admin:
#     sudo bash scripts/mac-runner/setup.sh
# It asks for a runner registration token (GitHub: the repository > Settings > Actions > Runners > New self-hosted
# runner > macOS; the token in the ./config.sh line, valid for one hour). The token is read from the keyboard, used
# once and never stored; the runner keeps only its own credentials, which can take jobs and do nothing else.
#
# What it sets up:
# - a hidden standard macOS user `orch-ci` with its own group (not in `staff`, so it cannot read /Users/<you> or the
#   orch you use, ~/.orch-tool); the developer group so it may run Simulators and UI tests
# - the GitHub runner 2.338.2 (checksum checked) in /Users/orch-ci/actions-runner, label orch-mac, started at boot
#   by launchd under that user, at lower priority than your own work
# - job hooks in /usr/local/orch-mac-runner (owned by root, the runner cannot change them): before each job they
#   refuse anything but develop pushes, the nightly run, manual runs and release pull requests and take the shared
#   heavy lock; after each job they stop leftovers and clean up. Each job gets a throwaway home in its temp folder.
# - the shared lock folder /Users/Shared/orch-locks, group orch-locks = you and orch-ci (helpers and the runner wait
#   for each other there; log in again, or restart the helpers, so your shells get the new group)
# Undo everything: sudo bash scripts/mac-runner/uninstall.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run it with sudo: sudo bash $0" >&2; exit 1; }
[ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ] || { echo "This is for an Apple silicon Mac." >&2; exit 1; }

REPO_URL=${ORCH_RUNNER_REPO_URL:-https://github.com/severinlindenmann/orch}
REPO=${REPO_URL#https://github.com/}
U=orch-ci; H=/Users/$U; NAME=${ORCH_RUNNER_NAME:-orch-mac-$(scutil --get LocalHostName 2>/dev/null || hostname -s)}
VER=2.338.2; SHA=25a065af409ffa317ab4d5a3b614dd15fc9c40f2172bc1b35a1b1258e919a388
TAR=actions-runner-osx-arm64-$VER.tar.gz
HOOKS=/usr/local/orch-mac-runner; LOCKS=/Users/Shared/orch-locks; LG=orch-locks
OWNER=${SUDO_USER:-}; [ -n "$OWNER" ] && [ "$OWNER" != root ] || { echo "Run it with sudo from your own account." >&2; exit 1; }
PLIST=/Library/LaunchDaemons/io.orch.mac-runner.plist
SRC=$(cd "$(dirname "$0")" && pwd)

echo "== 1/6 user $U"
if ! dscl . -read "/Users/$U" >/dev/null 2>&1; then
  uid=550; while dscl . -search /Users UniqueID "$uid" | grep -q .; do uid=$((uid + 1)); done
  gid=$uid; while dscl . -search /Groups PrimaryGroupID "$gid" | grep -q .; do gid=$((gid + 1)); done
  dscl . -create "/Groups/$U"; dscl . -create "/Groups/$U" PrimaryGroupID "$gid"; dscl . -create "/Groups/$U" RealName "orch CI"
  dscl . -create "/Users/$U"
  dscl . -create "/Users/$U" UniqueID "$uid"; dscl . -create "/Users/$U" PrimaryGroupID "$gid"
  dscl . -create "/Users/$U" RealName "orch CI runner"; dscl . -create "/Users/$U" UserShell /bin/zsh
  dscl . -create "/Users/$U" NFSHomeDirectory "$H"; dscl . -create "/Users/$U" IsHidden 1
  dscl . -create "/Users/$U" Password '*'   # no password: nobody logs in as it
  createhomedir -c -u "$U" >/dev/null 2>&1 || { mkdir -p "$H"; chown "$U:$U" "$H"; }
fi
chmod 700 "$H"
dseditgroup -o edit -a "$U" -t user _developer 2>/dev/null || true
DevToolsSecurity -enable >/dev/null 2>&1 || true
# it must NOT be able to read your home or the orch you use
for d in /Users/*; do
  [ "$d" = "$H" ] || [ "$d" = /Users/Shared ] || [ ! -d "$d" ] && continue
  if sudo -u "$U" test -r "$d/.orch-tool" 2>/dev/null || sudo -u "$U" ls "$d" >/dev/null 2>&1; then
    echo "  note: $U can read $d; closing it (chmod o-rwx)"; chmod o-rwx "$d"
  fi
done

echo "== 2/6 shared lock folder $LOCKS (group $LG: $OWNER and $U)"
if ! dscl . -read "/Groups/$LG" >/dev/null 2>&1; then
  g=560; while dscl . -search /Groups PrimaryGroupID "$g" | grep -q .; do g=$((g + 1)); done
  dscl . -create "/Groups/$LG"; dscl . -create "/Groups/$LG" PrimaryGroupID "$g"; dscl . -create "/Groups/$LG" RealName "orch shared locks"
fi
dseditgroup -o edit -a "$OWNER" -t user "$LG"; dseditgroup -o edit -a "$U" -t user "$LG"
[ -L "$LOCKS" ] && { echo "$LOCKS is a symlink; stopped." >&2; exit 1; }
mkdir -p "$LOCKS"; chown root:"$LG" "$LOCKS"; chmod 2770 "$LOCKS"

echo "== 3/6 job hooks in $HOOKS"
mkdir -p "$HOOKS"
install -m 0755 -o root -g wheel "$SRC/lock.sh" "$SRC/job-started.sh" "$SRC/job-completed.sh" "$HOOKS/"
printf '%s\n' "$REPO" > "$HOOKS/repo.new"; chown root:wheel "$HOOKS/repo.new"; chmod 0644 "$HOOKS/repo.new"
mv -f "$HOOKS/repo.new" "$HOOKS/repo"   # the hooks trust this file, never the job's environment

echo "== 4/6 GitHub runner $VER"
R=$H/actions-runner
if [ ! -x "$R/config.sh" ]; then
  sudo -u "$U" mkdir -p "$R"
  tmp=$(mktemp -d); curl -fsSL -o "$tmp/$TAR" "https://github.com/actions/runner/releases/download/v$VER/$TAR"
  echo "$SHA  $tmp/$TAR" | shasum -a 256 -c - >/dev/null || { echo "Checksum of the runner download is wrong; stopped." >&2; exit 1; }
  # root's temp folder is closed to orch-ci: unpack from a pipe instead of handing it the file
  sudo -u "$U" tar xzf - -C "$R" < "$tmp/$TAR"; rm -f "$tmp/$TAR"; rmdir "$tmp"
fi
sudo -u "$U" mkdir -p "$H/ci-cache"
# The hooks and settings go into the start-at-boot entry (owned by root, step 6), never into a file in the runner's
# own folder: root never writes into a folder orch-ci owns (a planted link there could point anywhere).

echo "== 5/6 register with GitHub ($REPO, name $NAME, label orch-mac)"
if [ ! -f "$R/.runner" ]; then
  printf 'Runner registration token (from GitHub, not stored): '; IFS= read -rs TOKEN; echo
  [ -n "$TOKEN" ] || { echo "No token; stopped. Run it again with the token." >&2; exit 1; }
  ( cd "$R" && sudo -u "$U" ./config.sh --unattended --replace --url "$REPO_URL" \
      --token "$TOKEN" --name "$NAME" --labels orch-mac --work "$H/_work" )
  unset TOKEN
fi

echo "== 6/6 start at boot under $U"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>io.orch.mac-runner</string>
  <key>UserName</key><string>$U</string>
  <key>GroupName</key><string>$U</string>
  <key>InitGroups</key><true/>
  <key>SessionCreate</key><true/>
  <key>WorkingDirectory</key><string>$R</string>
  <key>ProgramArguments</key><array><string>$R/run.sh</string></array>
  <key>EnvironmentVariables</key><dict>
    <key>HOME</key><string>$H</string>
    <key>ACTIONS_RUNNER_HOOK_JOB_STARTED</key><string>$HOOKS/job-started.sh</string>
    <key>ACTIONS_RUNNER_HOOK_JOB_COMPLETED</key><string>$HOOKS/job-completed.sh</string>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>LANG</key><string>en_US.UTF-8</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>Nice</key><integer>5</integer>
  <key>StandardOutPath</key><string>/var/log/orch-mac-runner.log</string>
  <key>StandardErrorPath</key><string>/var/log/orch-mac-runner.log</string>
</dict></plist>
EOF
chmod 0644 "$PLIST"; chown root:wheel "$PLIST"
launchctl bootout system "$PLIST" 2>/dev/null || true
launchctl bootstrap system "$PLIST"
echo
echo "Done. The runner '$NAME' starts now; GitHub shows it under Settings > Actions > Runners as Idle within a minute."
echo "It takes Mac jobs once the repository variable MAC_RUNNER is set to this-mac (docs/ci-checks.md, 'Mac jobs')."
