#!/bin/bash
# usage: .t799-run.sh <outfile> <pytest args...>
out=$1; shift
until [ $(uptime | sed 's/.*averages: *//; s/[.,].*//') -lt 30 ]; do sleep 20; done
export UV_CACHE_DIR=$HOME/.cache/uv
export HOME=/Users/lume/orch-dev/.t799p1-grdO
cd /Users/lume/orch-dev/.worktrees/rules-799p1/workspace
uv run pytest "$@" -q -n 2 -p no:cacheprovider -x --maxfail=15 > "$out" 2>&1
tail -60 "$out"
