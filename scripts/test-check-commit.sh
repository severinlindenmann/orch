#!/bin/bash
# Test for check-commit.sh, all in a temp folder with a pretend real home, shared clone and remote:
#   the command runs in a fresh copy of exactly the given commit, with a throwaway home (env -i, ORCH_HOME_STRICT=1)
#   and the real uv and npm caches; the copy and the home are gone afterwards on pass and on fail; a commit only the
#   remote has is fetched into the copy; the pretend real ~/.orch-tool and the shared clone are not changed.
# Run: scripts/test-check-commit.sh
set -u
D=$(cd "$(dirname "$0")" && pwd); C="$D/check-commit.sh"; mkdir -p "$HOME/.orch-test"
S=$(mktemp -d "$HOME/.orch-test/ctest-XXXX"); trap 'rm -rf "$S"' EXIT
fail() { echo "FAIL: $*"; exit 1; }
R="$S/realhome"; mkdir -p "$R/.orch-tool" "$R/.cache/uv" "$R/.npm"; echo keep > "$R/.orch-tool/config"
g() { git -c user.name=t -c user.email=t@example.invalid -c init.defaultBranch=develop "$@"; }

# remote with commits A, B (develop) and X (only on the remote); shared clone has A and B, origin/develop = A
g init -q --bare "$S/remote.git"
g init -q "$S/seed"; g -C "$S/seed" commit -q --allow-empty -m A; A=$(g -C "$S/seed" rev-parse HEAD)
echo b > "$S/seed/file"; g -C "$S/seed" add file; g -C "$S/seed" commit -q -m B; B=$(g -C "$S/seed" rev-parse HEAD)
g -C "$S/seed" push -q "$S/remote.git" develop
g clone -q "$S/remote.git" "$S/shared"; g -C "$S/shared" update-ref refs/remotes/origin/develop "$A"
g -C "$S/seed" commit -q --allow-empty -m X; X=$(g -C "$S/seed" rev-parse HEAD); g -C "$S/seed" push -q "$S/remote.git" develop:refs/heads/queue

cat > "$S/probe.sh" <<'EOF'
#!/bin/sh
out=$1; code=$2
{ echo "pwd=$(pwd)"; echo "head=$(git rev-parse HEAD)"; echo "base=$(git rev-parse -q --verify origin/develop)"
  echo "home=$HOME"; echo "orch_home=$ORCH_HOME"; echo "strict=$ORCH_HOME_STRICT"; echo "guard_only=$ORCH_TEST_GUARD_ONLY"; echo "uv=$UV_CACHE_DIR"
  echo "npm=$npm_config_cache"; echo "user=${USER:-unset}"; } > "$out"
mkdir -p "$ORCH_HOME" && echo x > "$ORCH_HOME/config" && touch "$HOME/marker" "$(pwd)/made-by-check"
exit "$code"
EOF
chmod +x "$S/probe.sh"
snap() { (cd "$S/shared" && git for-each-ref; git rev-parse HEAD; git status --porcelain; git worktree list --porcelain
  find . -type f | sort | xargs shasum) > "$1"; (cd "$R/.orch-tool" && find . -type f | sort | xargs shasum) >> "$1"; }
snap "$S/before"
run() { HOME="$R" CHECK_SRC="$S/shared/.git" "$C" "$@"; }
v() { sed -n "s/^$1=//p" "$S/out"; }

# 1. pass: the given (older) commit, throwaway home, shared caches, origin/develop from the shared clone
run "$A" -- "$S/probe.sh" "$S/out" 0 > "$S/log" 2>&1 || { cat "$S/log"; fail "pass run exited non-zero"; }
[ "$(v head)" = "$A" ] || fail "copy is at $(v head), not $A"
[ "$(v base)" = "$A" ] || fail "origin/develop in the copy is not the shared clone's"
case "$(v pwd)" in "$R"/.orch-test/commit-*/copy) ;; *) fail "command did not run in a fresh copy: $(v pwd)";; esac
case "$(v home)" in "$R"/.orch-test/commit-*/home) ;; *) fail "home is not throwaway: $(v home)";; esac
[ "$(v orch_home)" = "$(v home)/.orch-tool" ] && [ "$(v strict)" = 1 ] || fail "ORCH_HOME / ORCH_HOME_STRICT wrong"
[ "$(v guard_only)" = "$(v home)" ] || fail "ORCH_TEST_GUARD_ONLY is not the throwaway home"
[ "$(v uv)" = "$R/.cache/uv" ] && [ "$(v npm)" = "$R/.npm" ] || fail "caches are not the shared ones"
[ "$(v user)" = unset ] || fail "environment not cleared (env -i)"
[ ! -e "$(v pwd)" ] && [ ! -e "$(v home)" ] || fail "copy or home left after pass"
tail -1 "$S/log" | grep -q "^check-commit: PASS $A in " || fail "no PASS line: $(tail -1 "$S/log")"

# 2. fail: exit code passed through, copy and home still removed
run "$B" -- "$S/probe.sh" "$S/out" 3 > "$S/log" 2>&1; rc=$?
[ $rc = 3 ] || fail "failing command gave exit $rc, not 3"
[ "$(v head)" = "$B" ] || fail "copy is not at $B"
[ ! -e "$(v pwd)" ] && [ ! -e "$(v home)" ] || fail "copy or home left after fail"
tail -1 "$S/log" | grep -q "^check-commit: FAIL (exit 3) $B in " || fail "no FAIL line: $(tail -1 "$S/log")"

# 3. a commit only the remote has is fetched into the copy
run "$X" -- "$S/probe.sh" "$S/out" 0 > "$S/log" 2>&1 || { cat "$S/log"; fail "remote-only commit not checked"; }
[ "$(v head)" = "$X" ] || fail "remote-only commit: copy is at $(v head)"

# 4. a local branch of the shared clone (not on the remote) and a CHECK_CMD with arguments
g -C "$S/shared" branch -q local-only "$A"; snap "$S/before"
CHECK_CMD="'$S/probe.sh' '$S/out' 0" run local-only > "$S/log" 2>&1 || { cat "$S/log"; fail "local branch or CHECK_CMD run failed"; }
[ "$(v head)" = "$A" ] || fail "local branch: copy is at $(v head), not $A"

# 5. unknown commit: exit 2, nothing left behind
run 0123456789abcdef0123456789abcdef01234567 -- "$S/probe.sh" "$S/out" 0 > "$S/log" 2>&1; rc=$?
[ $rc = 2 ] || fail "unknown commit gave exit $rc, not 2"

# nothing left under the pretend ~/.orch-test, real orch home and shared clone unchanged
[ -z "$(ls -A "$R/.orch-test")" ] || fail "left in .orch-test: $(ls -A "$R/.orch-test")"
snap "$S/after"
diff "$S/before" "$S/after" > /dev/null || { diff "$S/before" "$S/after"; fail "shared clone or real orch home changed"; }
echo "test-check-commit: PASS"
