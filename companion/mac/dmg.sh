#!/bin/sh
# Pack "orch Companion.app" into a disk image people open and drag to Applications (ORCH-1497).
#   companion/mac/dmg.sh <app> <out.dmg> [volume name]
# The window layout comes from dmg_settings.py via dmgbuild. It runs inside the signing step, so it is installed
# only from dmg-requirements.txt (every file pinned by hash) into a throwaway folder, and runs with a bare
# environment: no signing identity, keychain or App Store Connect key variables reach it.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
app=$1
dmg=$2
name=${3:-"orch Companion"}
rm -f "$dmg"
# one background picture with a sharp copy for Retina screens
bg="$dmg.background.tiff"
tiffutil -cathidpicheck "$here/dmg-background.png" "$here/dmg-background@2x.png" -out "$bg" >/dev/null 2>&1
venv=$(mktemp -d "${TMPDIR:-/tmp}/companion-dmg.XXXXXX")
uv venv --quiet --python 3.12 "$venv/py" >&2
VIRTUAL_ENV="$venv/py" uv pip install --quiet --require-hashes --no-deps -r "$here/dmg-requirements.txt" >&2
env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin HOME="$venv" "$venv/py/bin/python" -I -m dmgbuild \
  -s "$here/dmg_settings.py" -D app="$app" -D background="$bg" "$name" "$dmg" >&2
rm -rf "$venv/py" "$bg"
rmdir "$venv"
echo "$dmg"
