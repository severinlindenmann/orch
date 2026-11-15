#!/bin/sh
# usage: h.sh <oldwt> <home> <cwd> orch args...
WT=$1; HM=$2; CW=$3; shift 3
cd "$CW" && exec env -i HOME="$HM" PATH="$PATH" uv run --project "$WT/workspace" orch "$@"
