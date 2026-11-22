#!/bin/bash
# scripts/mac-runner/setup.sh : make this Mac a GitHub runner for orch's Mac jobs (ORCH-1125). Run ONCE, as an admin:
#     sudo bash scripts/mac-runner/setup.sh
# It asks for a runner registration token (GitHub: the repository > Settings > Actions > Runners > New self-hosted
# runner > macOS; the token in the ./config.sh line, valid for one hour). The token is read from the keyboard, used
# once and never stored; the runner keeps only its own credentials, which can take jobs and do nothing else.
#
# What it sets up:
# - a hidden standard macOS user `orch-ci` with its own group (not in `staff`, so it cannot read /Users/<you> or the
#   orch you use, ~/.orch-tool); the developer group so it may run Simulators and UI tests. Its home is
#   /private/var/orch-ci/home, made by root once (no Desktop, Documents or Downloads) in a folder of root's. macOS
#   guards a user's home even against root, so root leaves it alone: the runner user empties it before every job.
#   The runner and its jobs get HOME=/private/var/orch-ci/run instead, made anew by root before every job.
#   An older setup's /Users/orch-ci is removed once (what macOS keeps of it goes to root with no access).
# - everything of the runner in /usr/local/orch-mac-runner, owned by root (orch-ci can change none of it): the GitHub
#   runner 2.338.2 (checksum checked) as a read-only copy, its sign-up (label orch-mac), the job hooks and a `bash`
#   that starts the hooks without the job's settings (bash), the network rule (pf-orch-ci.conf) and the loop
# - the loop (runner-loop.sh, root, started at boot): before EVERY job it closes the private and the local network to
#   orch-ci, stops everything of orch-ci, makes a fresh runner folder from the copy and empties orch-ci's home, then
#   starts the runner for one job, under orch-ci, at lower priority than your own work
# - job hooks: before each job they refuse anything but develop pushes, the nightly run, manual runs and release pull
#   requests and take the shared heavy lock; after each job they stop leftovers. Each job gets a throwaway home.
# - the shared lock folder /Users/Shared/orch-locks, group orch-locks = you and orch-ci (helpers and the runner wait
#   for each other there; log in again, or restart the helpers, so your shells get the new group)
# Run it again to take a new runner version (VER below): the sign-up stays. The runner never updates itself (each job
# starts from the copy), so bump VER when GitHub asks for a newer runner.
# Off at once: sudo bash scripts/mac-runner/uninstall.sh (and remove the runner on GitHub)
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run it with sudo: sudo bash $0" >&2; exit 1; }
[ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ] || { echo "This is for an Apple silicon Mac." >&2; exit 1; }

REPO_URL=${ORCH_RUNNER_REPO_URL:-https://github.com/severinlindenmann/orch}
REPO=${REPO_URL#https://github.com/}
U=orch-ci; HB=/private/var/orch-ci; H=$HB/home; R=$HB/run; NAME=${ORCH_RUNNER_NAME:-orch-mac-$(scutil --get LocalHostName 2>/dev/null || hostname -s)}
VER=2.338.2; SHA=25a065af409ffa317ab4d5a3b614dd15fc9c40f2172bc1b35a1b1258e919a388
TAR=actions-runner-osx-arm64-$VER.tar.gz
B=/usr/local/orch-mac-runner; LOCKS=/Users/Shared/orch-locks; LG=orch-locks
OWNER=${SUDO_USER:-}; [ -n "$OWNER" ] && [ "$OWNER" != root ] || { echo "Run it with sudo from your own account." >&2; exit 1; }
PLIST=/Library/LaunchDaemons/io.orch.mac-runner.plist; LOOP=/Library/LaunchDaemons/io.orch.mac-runner-loop.plist
SRC=$(cd "$(dirname "$0")" && pwd)

# A change of a user record can wait for a macOS window ("... would like to administer your computer") when sudo
# was started by a program that has not been allowed that (seen live 22 Nov: a helper's sudo waited forever).
# Each change gets two minutes; then setup stops and says what to do.
ds() {
  /usr/bin/perl -e 'alarm 120; exec @ARGV' dscl . "$@" && return 0
  echo "macOS did not let this change the user record (dscl $*) within two minutes. Look for a window on this" >&2
  echo "Mac's screen asking to administer the computer and allow it, or run setup again from Terminal yourself." >&2
  exit 1
}

echo "== 1/7 user $U"
# a rerun: stop the loop and the runner first, so nothing moves the home while this changes it (step 7 starts them)
launchctl bootout system "$LOOP" 2>/dev/null || true
launchctl bootout system "$PLIST" 2>/dev/null || true
if ! dscl . -read "/Users/$U" >/dev/null 2>&1; then
  uid=550; while dscl . -search /Users UniqueID "$uid" | grep -q .; do uid=$((uid + 1)); done
  gid=$uid; while dscl . -search /Groups PrimaryGroupID "$gid" | grep -q .; do gid=$((gid + 1)); done
  ds -create "/Groups/$U"; ds -create "/Groups/$U" PrimaryGroupID "$gid"; ds -create "/Groups/$U" RealName "orch CI"
  ds -create "/Users/$U"
  ds -create "/Users/$U" UniqueID "$uid"; ds -create "/Users/$U" PrimaryGroupID "$gid"
  ds -create "/Users/$U" RealName "orch CI runner"; ds -create "/Users/$U" UserShell /bin/zsh
  ds -create "/Users/$U" IsHidden 1
  ds -create "/Users/$U" Password '*'   # no password: nobody logs in as it
fi
# nothing of the runner user runs while root changes its home (a running job could swap a folder for a link)
uid=$(id -u "$U")
launchctl bootout "user/$uid" 2>/dev/null || true; launchctl bootout "gui/$uid" 2>/dev/null || true
pkill -KILL -U "$U" 2>/dev/null || true; sleep 1; pkill -KILL -U "$U" 2>/dev/null || true; sleep 1
if pgrep -U "$U" >/dev/null 2>&1; then echo "Programs of $U still run after a stop; stopped." >&2; exit 1; fi
# the home: root makes it itself (no Desktop, Documents or Downloads in it), in a folder of root's
[ -L "$HB" ] && { echo "$HB is a symlink; stopped." >&2; exit 1; }
mkdir -p "$HB"; chown root:wheel "$HB"; chmod 0755 "$HB"
[ -L "$H" ] && rm -f "$H"
# made once; after that root leaves the registered home alone (macOS guards it even against root, seen 22 Nov)
if [ ! -d "$H" ]; then mkdir "$H"; chown "$U:$U" "$H"; chmod 700 "$H"; fi
[ "$(stat -f %Su "$H")" = "$U" ] || { echo "$H does not belong to $U; stopped." >&2; exit 1; }
unlock_rm() { # a job can lock files or put access rules on them: clear that (never through a link), then remove
  [ -e "$1" ] || [ -L "$1" ] || return 0
  # only what the runner user owns: a hard link a job made to someone else's file is that file (rm only takes the
  # name away), so root never changes its locks or rules
  find -P "$1" -user "$U" -exec chflags -h nouchg,nouappnd {} + -exec chmod -h -N {} + 2>/dev/null || true
  rm -rf "$1" && [ ! -e "$1" ] && [ ! -L "$1" ]
}
# a stopped check of an earlier version left the Simulators aside here; they are made again when needed
unlock_rm "$HB/simulators.keep" || true; unlock_rm "$HB/home.check" || true

# only when it differs: a change of a user record can wait for a macOS window (it took hours on 22 Nov)
cur_home=$(dscl . -read "/Users/$U" NFSHomeDirectory 2>/dev/null | sed -n 's/^NFSHomeDirectory: //p' || true)
[ "$cur_home" = "$H" ] || ds -create "/Users/$U" NFSHomeDirectory "$H"
if [ -d "/Users/$U" ] && [ ! -L "/Users/$U" ]; then
  # the home of an older setup: nothing uses it any more (a job left nothing in it that runs: the loop stopped it all)
  # macOS puts "everyone deny delete" on a home; clear it (and the runner user's own rules and locks) first, never
  # following a link
  find -P "/Users/$U" -user "$U" -exec chflags -h nouchg,nouappnd {} + -exec chmod -h -N {} + 2>/dev/null || true
  if ! rm -rf "/Users/$U" 2>/dev/null; then
    # what macOS keeps goes to root with no access, so no job can leave anything there for a later job
    chown -h root:wheel "/Users/$U"; chmod -h 000 "/Users/$U"
    if [ "$(stat -f %u:%Lp "/Users/$U")" != 0:0 ]; then
      echo "Could not remove or close the old /Users/$U; a job could keep files there. Stopped." >&2; exit 1
    fi
    echo "  note: macOS keeps parts of the old /Users/$U; it now belongs to root and nobody can open it"
  fi
fi
# before every job the runner user empties its registered home and root makes the job's HOME ($R) anew: try both
# here once, so a refusal shows now and not in the log every minute
sudo -u "$U" mkdir -p "$H/Library/Caches/setup-check"
if ! sudo -u "$U" rm -rf "$H/Library/Caches/setup-check" || [ -e "$H/Library/Caches/setup-check" ]; then
  echo "$U could not empty its own home $H; the runner would never start. Stopped." >&2; exit 1
fi
unlock_rm "$R" || { echo "Root could not remove the old job home $R; stopped." >&2; exit 1; }
mkdir "$R"; chown "$U:$U" "$R"; chmod 700 "$R"
sudo -u "$U" mkdir -p "$R/Library/Caches/x" "$R/Desktop" "$R/Documents"
if ! unlock_rm "$R"; then
  echo "Root could not remove the job home $R; the runner would never start. Stopped." >&2; exit 1
fi
mkdir "$R"; chown "$U:$U" "$R"; chmod 700 "$R"
dseditgroup -o edit -a "$U" -t user _developer 2>/dev/null || true
# no timed jobs for it (a job could leave one behind for later)
for f in /usr/lib/cron/cron.deny /usr/lib/cron/at.deny; do
  if [ -d "${f%/*}" ] && ! grep -qx "$U" "$f" 2>/dev/null; then echo "$U" >> "$f"; fi
done
DevToolsSecurity -enable >/dev/null 2>&1 || true
# it must NOT be able to read your home or the orch you use
for d in /Users/*; do
  [ "$d" = "$H" ] || [ "$d" = /Users/Shared ] || [ ! -d "$d" ] && continue
  if sudo -u "$U" test -r "$d/.orch-tool" 2>/dev/null || sudo -u "$U" ls "$d" >/dev/null 2>&1; then
    echo "  note: $U can read $d; closing it (chmod o-rwx)"; chmod o-rwx "$d"
  fi
done

echo "== 2/7 shared lock folder $LOCKS (group $LG: $OWNER and $U)"
if ! dscl . -read "/Groups/$LG" >/dev/null 2>&1; then
  g=560; while dscl . -search /Groups PrimaryGroupID "$g" | grep -q .; do g=$((g + 1)); done
  ds -create "/Groups/$LG"; ds -create "/Groups/$LG" PrimaryGroupID "$g"; ds -create "/Groups/$LG" RealName "orch shared locks"
fi
dseditgroup -o edit -a "$OWNER" -t user "$LG"; dseditgroup -o edit -a "$U" -t user "$LG"
[ -L "$LOCKS" ] && { echo "$LOCKS is a symlink; stopped." >&2; exit 1; }
mkdir -p "$LOCKS"; chown root:"$LG" "$LOCKS"; chmod 2770 "$LOCKS"

echo "== 3/7 hooks, bash, network rule and loop in $B (owned by root)"
[ -L "$B" ] && { echo "$B is a symlink; stopped." >&2; exit 1; }
mkdir -p "$B/bin"; chown root:wheel "$B" "$B/bin"; chmod 0755 "$B" "$B/bin"
install -m 0755 -o root -g wheel "$SRC/lock.sh" "$SRC/job-started.sh" "$SRC/job-completed.sh" "$SRC/runner-loop.sh" "$B/"
install -m 0644 -o root -g wheel "$SRC/pf-orch-ci.conf" "$B/"
install -m 0755 -o root -g wheel "$SRC/bash" "$B/bin/bash"
printf '%s\n' "$REPO" > "$B/repo.new"; chown root:wheel "$B/repo.new"; chmod 0644 "$B/repo.new"
mv -f "$B/repo.new" "$B/repo"   # the hooks trust this file, never the job's environment

echo "== 4/7 GitHub runner $VER (read-only copy)"
if [ "$(cat "$B/template/.orch-version" 2>/dev/null)" != "$VER" ]; then
  tmp=$(mktemp -d); curl -fsSL -o "$tmp/$TAR" "https://github.com/actions/runner/releases/download/v$VER/$TAR"
  echo "$SHA  $tmp/$TAR" | shasum -a 256 -c - >/dev/null || { echo "Checksum of the runner download is wrong; stopped." >&2; exit 1; }
  rm -rf "$B/template.new"; mkdir "$B/template.new"; tar xzf "$tmp/$TAR" -C "$B/template.new"
  rm -f "$tmp/$TAR"; rmdir "$tmp"
  echo "$VER" > "$B/template.new/.orch-version"
  chown -R root:wheel "$B/template.new"; chmod -R go-w "$B/template.new"
  rm -rf "$B/template.old"; [ -d "$B/template" ] && mv "$B/template" "$B/template.old"
  mv "$B/template.new" "$B/template"; rm -rf "$B/template.old"
fi
# The hooks and settings go into the start entries (owned by root, step 7), never into the runner's folder.

echo "== 5/7 outside contributors wait for your click (a fork's workflow file can name any runner)"
policy=$(sudo -u "$OWNER" gh api "repos/$REPO/actions/permissions/fork-pr-contributor-approval" --jq .approval_policy 2>/dev/null || true)
if [ "$policy" = all_external_contributors ]; then
  echo "  ok: every outside contributor's run waits for your click"
elif [ -n "$policy" ]; then
  echo "Settings > Actions > General > 'Fork pull request workflows from outside collaborators' is $policy, not the strictest choice (all external contributors). Choose it, then run this again." >&2; exit 1
else
  echo "  Could not read the setting (gh as $OWNER). Settings > Actions > General > 'Fork pull request workflows from"
  echo "  outside collaborators' must be the strictest choice (all external contributors)."
  printf '  Is it? [y/N] '; IFS= read -r ans; [ "$ans" = y ] || [ "$ans" = Y ] || { echo "Stopped; choose it first." >&2; exit 1; }
fi

echo "== 6/7 register with GitHub ($REPO, name $NAME, label orch-mac)"
if [ ! -f "$B/creds/.runner" ]; then
  printf 'Runner registration token (from GitHub, not stored): '; IFS= read -rs TOKEN; echo
  [ -n "$TOKEN" ] || { echo "No token; stopped. Run it again with the token." >&2; exit 1; }
  rm -rf "$B/job"; cp -R "$B/template" "$B/job"; chown -R "$U:$U" "$B/job"
  ( cd "$B/job" && sudo -u "$U" ./config.sh --unattended --replace --disableupdate --url "$REPO_URL" \
      --token "$TOKEN" --name "$NAME" --labels orch-mac --work "$B/job/_work" )
  unset TOKEN
  mkdir -p "$B/creds.new"; chmod 0700 "$B/creds.new"
  for f in .runner .credentials .credentials_rsaparams; do
    if [ -f "$B/job/$f" ] && [ ! -L "$B/job/$f" ]; then cp "$B/job/$f" "$B/creds.new/$f"; fi
  done
  chown -R root:wheel "$B/creds.new"; chmod 0600 "$B/creds.new"/.[!.]*
  [ -f "$B/creds.new/.runner" ] || { echo "The runner did not sign up; stopped." >&2; exit 1; }
  rm -rf "$B/creds"; mv "$B/creds.new" "$B/creds"; rm -rf "$B/job"
fi

echo "== 7/7 start at boot: the loop as root, the runner under $U"
cat > "$PLIST.new" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>io.orch.mac-runner</string>
  <key>UserName</key><string>$U</string>
  <key>GroupName</key><string>$U</string>
  <key>InitGroups</key><true/>
  <key>SessionCreate</key><true/>
  <key>WorkingDirectory</key><string>$B/job</string>
  <key>ProgramArguments</key><array><string>$B/job/run.sh</string><string>--once</string></array>
  <key>EnvironmentVariables</key><dict>
    <key>HOME</key><string>$R</string>
    <key>TMPDIR</key><string>$R/tmp</string>
    <key>ACTIONS_RUNNER_HOOK_JOB_STARTED</key><string>$B/job-started.sh</string>
    <key>ACTIONS_RUNNER_HOOK_JOB_COMPLETED</key><string>$B/job-completed.sh</string>
    <key>PATH</key><string>$B/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>LANG</key><string>en_US.UTF-8</string>
  </dict>
  <key>RunAtLoad</key><false/>
  <key>KeepAlive</key><false/>
  <key>Nice</key><integer>5</integer>
  <key>StandardOutPath</key><string>/var/log/orch-mac-runner.log</string>
  <key>StandardErrorPath</key><string>/var/log/orch-mac-runner.log</string>
</dict></plist>
EOF
cat > "$LOOP.new" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>io.orch.mac-runner-loop</string>
  <key>ProgramArguments</key><array><string>$B/runner-loop.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/var/log/orch-mac-runner.log</string>
  <key>StandardErrorPath</key><string>/var/log/orch-mac-runner.log</string>
</dict></plist>
EOF
for f in "$PLIST" "$LOOP"; do chmod 0644 "$f.new"; chown root:wheel "$f.new"; mv -f "$f.new" "$f"; done
launchctl bootout system "$LOOP" 2>/dev/null || true
launchctl bootout system "$PLIST" 2>/dev/null || true
launchctl bootstrap system "$PLIST"
launchctl bootstrap system "$LOOP"
echo
echo "Done. The runner '$NAME' starts now; GitHub shows it under Settings > Actions > Runners as Idle within a minute."
echo "It takes Mac jobs once the repository variable MAC_RUNNER is set to this-mac (docs/ci-checks.md, 'Mac jobs')."
