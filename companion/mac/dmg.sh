#!/bin/sh
# Pack "orch Companion.app" into a disk image people open and drag to Applications (ORCH-1497).
#   companion/mac/dmg.sh <app> <out.dmg> [volume name]
# The window layout comes from dmg_settings.py via dmgbuild (pinned; runs through uvx, no install).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
app=$1
dmg=$2
name=${3:-"orch Companion"}
rm -f "$dmg"
# one background picture with a sharp copy for Retina screens
bg="$dmg.background.tiff"
tiffutil -cathidpicheck "$here/dmg-background.png" "$here/dmg-background@2x.png" -out "$bg" >/dev/null 2>&1
uvx --quiet --from "dmgbuild==1.6.7" dmgbuild -s "$here/dmg_settings.py" -D app="$app" -D background="$bg" \
  "$name" "$dmg" >&2
rm -f "$bg"
echo "$dmg"
