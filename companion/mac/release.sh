#!/bin/sh
# Signed and notarized orch Companion (ORCH-1195 step 5): build, sign with the Developer ID certificate (hardened
# runtime), notarize with the App Store Connect key, staple, zip as orch-Companion-<version>.zip for a
# "companion-v<version>" release. Needs (from Proton Pass, never in git):
#   COMPANION_SIGN_IDENTITY   "Developer ID Application: <name> (<team>)", in the keychain this runs with
#   ASC_KEY_FILE ASC_KEY_ID ASC_ISSUER   the App Store Connect API key for notarytool
#   COMPANION_KEYCHAIN        optional: a keychain file that holds the certificate (a throwaway one made for this
#                             run); without it codesign searches the usual keychains
#   COMPANION_VERSION         optional: build this version instead of the one in Info.plist (X.Y.Z)
# companion/mac/release.sh [out-dir]
set -eu
# The signing key is used only in this release step, from the Agents vault; never in CI or a test home (ORCH-1497).
if [ -n "${CI:-}${GITHUB_ACTIONS:-}${ORCH_HOME_STRICT:-}" ]; then
  echo "release.sh runs only in the owner's release step, not in CI or a test home" >&2
  exit 2
fi
here=$(cd "$(dirname "$0")" && pwd)
out=${1:-"$here/build"}
: "${COMPANION_SIGN_IDENTITY:?set COMPANION_SIGN_IDENTITY}"
: "${ASC_KEY_FILE:?set ASC_KEY_FILE}" "${ASC_KEY_ID:?set ASC_KEY_ID}" "${ASC_ISSUER:?set ASC_ISSUER}"
app=$("$here/build.sh" "$out")
if [ -n "${COMPANION_VERSION:-}" ]; then
  /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $COMPANION_VERSION" "$app/Contents/Info.plist"
fi
version=$(/usr/libexec/PlistBuddy -c "Print CFBundleShortVersionString" "$app/Contents/Info.plist")
codesign --force --timestamp --options runtime --entitlements "$here/entitlements.plist" \
  ${COMPANION_KEYCHAIN:+--keychain "$COMPANION_KEYCHAIN"} -s "$COMPANION_SIGN_IDENTITY" "$app"
codesign --verify --strict --deep "$app"
zip="$out/orch-Companion-$version.zip"
ditto -c -k --keepParent "$app" "$zip"
xcrun notarytool submit "$zip" --key "$ASC_KEY_FILE" --key-id "$ASC_KEY_ID" --issuer "$ASC_ISSUER" --wait
xcrun stapler staple "$app"
/usr/sbin/spctl --assess --type execute "$app"
# the same rule an installed Companion applies before it accepts this build as an update
"$app/Contents/MacOS/orch-companion" --check-update "$app"
rm "$zip"
ditto -c -k --keepParent "$app" "$zip"
echo "$zip"
