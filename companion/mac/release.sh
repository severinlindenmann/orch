#!/bin/sh
# Signed and notarized orch Companion (ORCH-1195 step 5): build, sign with the Developer ID certificate (hardened
# runtime), notarize with the App Store Connect key, staple, zip as orch-Companion-<version>.zip for a
# "companion-v<version>" release. Needs (from Proton Pass, never in git):
#   COMPANION_SIGN_IDENTITY   "Developer ID Application: <name> (<team>)", in the keychain this runs with
#   ASC_KEY_FILE ASC_KEY_ID ASC_ISSUER   the App Store Connect API key for notarytool
# companion/mac/release.sh [out-dir]
set -eu
here=$(cd "$(dirname "$0")" && pwd)
out=${1:-"$here/build"}
: "${COMPANION_SIGN_IDENTITY:?set COMPANION_SIGN_IDENTITY}"
: "${ASC_KEY_FILE:?set ASC_KEY_FILE}" "${ASC_KEY_ID:?set ASC_KEY_ID}" "${ASC_ISSUER:?set ASC_ISSUER}"
app=$("$here/build.sh" "$out")
version=$(/usr/libexec/PlistBuddy -c "Print CFBundleShortVersionString" "$app/Contents/Info.plist")
codesign --force --timestamp --options runtime --entitlements "$here/entitlements.plist" \
  -s "$COMPANION_SIGN_IDENTITY" "$app"
codesign --verify --strict --deep "$app"
zip="$out/orch-Companion-$version.zip"
ditto -c -k --keepParent "$app" "$zip"
xcrun notarytool submit "$zip" --key "$ASC_KEY_FILE" --key-id "$ASC_KEY_ID" --issuer "$ASC_ISSUER" --wait
xcrun stapler staple "$app"
spctl --assess --type execute "$app"
rm "$zip"
ditto -c -k --keepParent "$app" "$zip"
echo "$zip"
