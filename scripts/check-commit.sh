#!/bin/bash
# scripts/check-commit.sh <commit> [-- command...] : run the before-merge checks on one commit in a fresh copy of it,
#   with a throwaway home, then remove the copy and the home by exact path (on pass and on fail).
#   - Copy: `git clone --shared` of the shared clone into a temp folder (no `git worktree add`, which writes into the
#     shared .git), its origin/* refs taken from the shared clone, the commit fetched from origin when the shared clone
#     does not have it yet, then checked out detached. The shared clone is only read.
#   - Home: env -i with HOME and ORCH_HOME in the temp folder under ~/.orch-test, ORCH_HOME_STRICT=1, so nothing reaches
#     the real ~/.orch-tool; the real uv and npm caches are shared (a fresh cache re-downloads gigabytes per run).
#   - Command: the words after `--`, else $CHECK_CMD, else the copy's scripts/ci_light.py (run through uv) against $BASE (default origin/develop).
#     It runs in the copy.
#   Exit: the command's exit code; 2 when the commit cannot be found or the copy cannot be made.
#   Last line: "check-commit: PASS <sha> in <n>s" or "check-commit: FAIL (exit <rc>) <sha> in <n>s".
# Env: CHECK_SRC (git folder to copy from, default the shared clone of this script's repo), CHECK_CMD, BASE, LANE.
set -u
usage() { echo "usage: scripts/check-commit.sh <commit> [-- command...]" >&2; exit 2; }
[ $# -ge 1 ] && [ -n "$1" ] && [ "$1" != "--" ] || usage
REV=$1; shift
if [ $# -gt 0 ]; then [ "$1" = "--" ] || usage; shift; fi

REAL_HOME=$HOME
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SRC=${CHECK_SRC:-$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)} || exit 2
mkdir -p "$REAL_HOME/.orch-test"
TMP=$(mktemp -d "$REAL_HOME/.orch-test/commit-XXXX") || exit 2
case "$TMP" in "$REAL_HOME"/.orch-test/commit-????*) ;; *) echo "check-commit: unexpected temp path $TMP" >&2; exit 2;; esac
COPY="$TMP/copy"; THOME="$TMP/home"
cleanup() {
  # exact paths only, each checked to sit inside this run's temp folder
  case "$COPY" in "$TMP"/copy) rm -rf "$COPY";; esac
  case "$THOME" in "$TMP"/home) rm -rf "$THOME";; esac
  rmdir "$TMP" 2>/dev/null || echo "check-commit: could not remove $TMP" >&2
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
start=$(date +%s)
mkdir -p "$THOME" || exit 2

git clone -q --shared --no-checkout "$SRC" "$COPY" || { echo "check-commit: could not copy $SRC" >&2; exit 2; }
G() { git -C "$COPY" "$@"; }
# origin/* as the shared clone sees it (local diffs use origin/develop as their base), then point origin at the real
# remote so a commit the shared clone lacks comes from there (into the copy, never into the shared clone)
G fetch -q "$SRC" '+refs/remotes/origin/*:refs/remotes/origin/*' 2>/dev/null
url=$(git -C "$SRC" config --get remote.origin.url 2>/dev/null) && G remote set-url origin "$url"
sha=$(G rev-parse -q --verify "$REV^{commit}" 2>/dev/null)
if [ -z "$sha" ] && [ -n "${url:-}" ]; then
  G fetch -q origin "$REV" 2>/dev/null && sha=$(G rev-parse -q --verify "FETCH_HEAD^{commit}" 2>/dev/null)
fi
[ -n "$sha" ] || { echo "check-commit: commit not found: $REV" >&2; exit 2; }
G -c advice.detachedHead=false checkout -q --detach "$sha" || { echo "check-commit: could not check out $sha" >&2; exit 2; }

if [ $# -gt 0 ]; then cmd=("$@"); elif [ -n "${CHECK_CMD:-}" ]; then cmd=("$CHECK_CMD"); else
  # ci_light.py's steps call `python` with pytest (as on CI); this Mac has neither on PATH, uv provides both
  cmd=(uv run -q --no-project --python '>=3.11' --with pytest python scripts/ci_light.py --base "${BASE:-origin/develop}")
fi
echo "check-commit: $sha in $COPY"
(cd "$COPY" && env -i HOME="$THOME" PATH="$PATH" ORCH_HOME="$THOME/.orch-tool" ORCH_HOME_STRICT=1 \
  UV_CACHE_DIR="$REAL_HOME/.cache/uv" npm_config_cache="$REAL_HOME/.npm" XDG_CACHE_HOME="$THOME/.cache" \
  LANG="${LANG:-en_US.UTF-8}" REAL_HOME="$REAL_HOME" \
  RUSTUP_HOME="${RUSTUP_HOME:-$REAL_HOME/.rustup}" CARGO_HOME="${CARGO_HOME:-$REAL_HOME/.cargo}" \
  ${LANE:+LANE="$LANE"} ${BASE:+BASE="$BASE"} \
  "${cmd[@]}")
rc=$?
secs=$(( $(date +%s) - start ))
if [ "$rc" = 0 ]; then echo "check-commit: PASS $sha in ${secs}s"; else echo "check-commit: FAIL (exit $rc) $sha in ${secs}s"; fi
exit $rc
