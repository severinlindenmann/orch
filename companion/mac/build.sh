#!/bin/sh
# Build "orch Companion.app" (ad-hoc signed; the signed and notarized build is ORCH-1195 step 5).
#   companion/mac/build.sh [out-dir]      default: companion/mac/build
set -eu
here=$(cd "$(dirname "$0")" && pwd)
out=${1:-"$here/build"}
app="$out/orch Companion.app"
mkdir -p "$app/Contents/MacOS"
swiftc -O -swift-version 5 -target arm64-apple-macos14.2 -framework AppKit -framework CoreAudio \
  -o "$app/Contents/MacOS/orch-companion" "$here/main.swift"
cp "$here/Info.plist" "$app/Contents/Info.plist"
codesign -s - --force "$app" >/dev/null 2>&1
echo "$app"
