#!/usr/bin/env python3
"""Was this develop commit already proven by a green merge queue group? Then its push runs no suite (ORCH-559).

The merge queue checks a group of pull requests on top of develop (branch `orch-queue/...`, the full suite) and
merges the group with a merge commit. When that merge commit has exactly the files of the group commit (same git
tree), the push to develop would run the very same tests on the very same files again. This answers `true` then,
and ci.yml skips every suite of that push; macOS still runs nightly and in the release check. For now (ORCH-1106)
the click-throughs and the Windows parts still run on that push, because queue groups skip them.

Proven = the commit has two parents, its tree equals the tree of its second parent, and a `ci` pull request run of
that second parent on an `orch-queue/` branch finished green with its `gate` job run and green (not skipped: a group the
local check checked, ORCH-1124, skips every job, and that run proves nothing). Anything else (a lone pull request merged on its own light
checks, a merge by a person, develop moved in between, GitHub did not answer) is `false`: the push runs as before.

Usage: python3 scripts/ci_proven.py --sha <commit> --repo <owner/name>   prints true or false (exit 0)
Reads git and `gh api` (GH_TOKEN with actions: read).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def decide(parents: list[str], tree: str, tree_of_second: str, runs: list[dict]) -> tuple[bool, str]:
    """(proven, why). Pure."""
    if len(parents) != 2:
        return False, "not a merge commit"
    if tree != tree_of_second:
        return False, "its files differ from the group commit"
    for r in runs:
        if (
            r.get("name") == "ci"
            and r.get("event") == "pull_request"  # a manual run on a queue branch skips the smoke jobs
            and str(r.get("head_branch") or "").startswith("orch-queue/")
            and r.get("status") == "completed"
            and r.get("conclusion") == "success"
            and r.get("rollup") == "success"  # its gate job ran (main() reads it); a skipped run proves nothing
        ):
            return True, f"same files as the green queue group run {r.get('html_url') or r.get('id')}"
    return False, "no green ci run of a queue group for its second parent"


def runs_of(repo: str, sha: str) -> list[dict]:
    got = subprocess.run(
        ["gh", "api", f"repos/{repo}/actions/runs?head_sha={sha}&per_page=20"],
        capture_output=True,
        text=True,
        check=False,
    )
    if got.returncode != 0:
        return []
    try:
        return list(json.loads(got.stdout).get("workflow_runs") or [])
    except ValueError:
        return []


def rollup_of(repo: str, run_id) -> str:
    """The conclusion of the run's `gate` job ('' when GitHub did not answer or there is none)."""
    got = subprocess.run(
        ["gh", "api", f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100"],
        capture_output=True,
        text=True,
        check=False,
    )
    if got.returncode != 0:
        return ""
    try:
        jobs = json.loads(got.stdout).get("jobs") or []
    except ValueError:
        return ""
    return next((str(j.get("conclusion") or "") for j in jobs if j.get("name") == "gate"), "")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sha", required=True)
    ap.add_argument("--repo", required=True)
    a = ap.parse_args(argv)
    try:
        parents = git("rev-list", "--parents", "-n", "1", a.sha).split()[1:]
        tree = git("rev-parse", f"{a.sha}^{{tree}}")
        second = git("rev-parse", f"{parents[1]}^{{tree}}") if len(parents) == 2 else ""
    except (subprocess.CalledProcessError, IndexError):
        print("false")
        print("git could not read the commit", file=sys.stderr)
        return 0
    runs = runs_of(a.repo, parents[1]) if len(parents) == 2 and tree == second else []
    for r in runs:
        if r.get("name") == "ci" and str(r.get("head_branch") or "").startswith("orch-queue/"):
            r["rollup"] = rollup_of(a.repo, r.get("id"))
    ok, why = decide(parents, tree, second, runs)
    print("true" if ok else "false")
    print(why, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
