#!/usr/bin/env bash
# The commit the CI changes filter compares against on main: the previous release.
#
# Without it dorny/paths-filter compares main with the default branch (develop). After a release main's tree
# equals develop, so the filter found 0 changed files and skipped relay and publish: no binaries to deploy
# (releases 32 and 33, ORCH-370). A release build must see everything that changed since the last release.
#
# Usage: ci_changes_base.sh [before-sha]   (the push event's "before"; empty for a manual run)
# Prints the base commit: "before" when it is a commit this clone has, else the first parent of HEAD (the
# previous main tip of a release merge). Prints nothing when neither exists (the filter then keeps its default).
#
#        ci_changes_base.sh --since-main   (a manual run on any branch but main, #2559)
# Prints where HEAD meets origin/main: everything since the last release counts as changed. Without it the
# filter compared the release keeper's manual run with develop, found 0 changed files and skipped most jobs.
set -u
if [ "${1:-}" = --since-main ]; then
  git merge-base origin/main HEAD 2>/dev/null || true
  exit 0
fi
before="${1:-}"
if [ -n "$before" ] && git cat-file -e "${before}^{commit}" 2>/dev/null; then
  echo "$before"
  exit 0
fi
git rev-parse --verify --quiet 'HEAD^1' || true
