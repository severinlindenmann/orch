#!/bin/sh
# TestFlight upload for orch mobile: testflight.sh <git-sha> <whats-new-file>
# Archives <git-sha> from a detached worktree, uploads with the ASC API key, waits for VALID, adds the build to the
# beta group (default "Owner") and sets "What to test". The key stays outside the repo (never copied or printed).
# Env (all optional): ORCH_REPO (git clone that holds <git-sha>, default ~/orch-dev/orch), TF_WORKTREE (default $ORCH_REPO/../.worktrees/tf),
# TF_HEAVY (wrapper for heavy commands, default: run directly), ASC_KEY_PATH, ASC_KEY_ID, ASC_ISSUER_ID, ASC_APP_ID,
# ASC_BETA_GROUP, ASC_TEAM_ID.
set -eu
[ $# -eq 2 ] || { echo "usage: $0 <git-sha> <whats-new-file>" >&2; exit 2; }
SHA=$1; WTT=$2
[ -f "$WTT" ] || { echo "notes file not found: $WTT" >&2; exit 2; }
WTT=$(cd "$(dirname "$WTT")" && pwd)/$(basename "$WTT")
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=${ORCH_REPO:-$HOME/orch-dev/orch}
WT=${TF_WORKTREE:-$REPO/../.worktrees/tf}
HEAVY=${TF_HEAVY:-}
KEY_ID=${ASC_KEY_ID:-HVML779F7U}
ISS=${ASC_ISSUER_ID:-8f9968b2-a219-4890-8574-0822ad510d85}
TEAM=${ASC_TEAM_ID:-77D4THRYUN}
KP=${ASC_KEY_PATH:-$HOME/.appstoreconnect/private_keys/AuthKey_$KEY_ID.p8}
case $KP in "~/"*) KP=$HOME/${KP#"~/"};; esac
[ -f "$KP" ] || { echo "ASC key not found: $KP (set ASC_KEY_PATH)" >&2; exit 1; }
export ASC_KEY_PATH=$KP ASC_KEY_ID=$KEY_ID ASC_ISSUER_ID=$ISS
D=$(mktemp -d "${TMPDIR:-/tmp}/tf-XXXXXX")
[ -d "$WT" ] || git -C "$REPO" worktree add -q --detach "$WT" "$SHA"
git -C "$WT" checkout -q --detach "$SHA"
BN=$(uv run --quiet --with pyjwt --with cryptography python "$HERE/tf-next-build.py")
echo "build $BN from $SHA (work dir $D)"
cat > "$D/export.plist" <<E
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>method</key><string>app-store-connect</string>
<key>destination</key><string>upload</string>
<key>teamID</key><string>$TEAM</string>
<key>signingStyle</key><string>automatic</string>
</dict></plist>
E
AUTH="-allowProvisioningUpdates -authenticationKeyPath $KP -authenticationKeyID $KEY_ID -authenticationKeyIssuerID $ISS"
cd "$WT/mobile" || { echo "no mobile/ in $SHA" >&2; exit 1; }
xcodegen generate -q
BUILD="cd '$WT/mobile' && xcodebuild archive -scheme OrchMobile -destination 'generic/platform=iOS' -archivePath $D/orch.xcarchive CURRENT_PROJECT_VERSION=$BN $AUTH > $D/archive.log 2>&1 && xcodebuild -exportArchive -archivePath $D/orch.xcarchive -exportOptionsPlist $D/export.plist -exportPath $D/out $AUTH > $D/export.log 2>&1"
# shellcheck disable=SC2086
$HEAVY sh -c "$BUILD"
tail -3 "$D/export.log"
uv run --quiet --with pyjwt --with cryptography python "$HERE/testflight_asc.py" "$BN" "$WTT"
echo "done: build $BN, work dir $D, worktree $WT"
