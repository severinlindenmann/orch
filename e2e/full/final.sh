#!/bin/sh
# The owner's morning run in ONE command (everything on one commit, real agents, phone, workspace look, upgrade from production):
#   e2e/full/final.sh <sha-or-develop> "<build label>" [production-sha]
# e.g. e2e/full/final.sh origin/develop "TF 261107.1810" 23e19f4
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
SHA=${1:-origin/develop}; LABEL=${2:-}; PROD=${3:-23e19f4}
git -C "$HERE/../.." fetch -q origin 2>/dev/null || true
FULL=$(git -C "$HERE/../.." rev-parse "$SHA")
set -- --full --phone --real-agents --no-windows --real-runs 6 --review-shots 40 --sha "$FULL" --upgrade-from "$PROD"
[ -n "$LABEL" ] && set -- "$@" --build-label "$LABEL"
exec "$HERE/run.sh" "$@"
