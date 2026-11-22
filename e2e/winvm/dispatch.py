#!/usr/bin/env python3
"""Windows checks on our own Windows VM after the merge (ORCH-1127).

Runs on this Mac as a long-lived job (an orch service). While the repository variable WINDOWS_RUNNER is 'winvm'
(set by the owner; unset or any other value = GitHub's machines run them, see ci.yml), it picks ONE commit at a time
and runs e2e/winvm/run.sh on it in a fresh winvm clone that is removed afterwards. The result goes on the commit as
the status 'windows (winvm)' (bot rights only; no runner, no admin key on this Mac). Order (owner 21 Nov):
  1. the head of every open release pull request (into main) without a status of its own,
  2. the nightly run: the develop head once per day after 01:00 UTC (the time of ci.yml's schedule),
  3. the newest develop commit without a status (commits pushed while the clone was busy are skipped).
The scripts that run on this Mac are the dispatcher's own copy; only the tested source goes into the VM.
Only release pull requests develop -> main of this repository count (public repository: never a fork).
The release keeper reads a failed status on develop like a red develop run (releasekeeper.winvm_red).

    dispatch.py [--once] [--dry-run]       env: ORCH_REPO_DIR (git clone to fetch into), WINVM_OUT (results)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = "severinlindenmann/orch"
CONTEXT = "windows (winvm)"
VARIABLE = "WINDOWS_RUNNER"
NIGHTLY_HOUR_UTC = 1
HERE = Path(__file__).resolve().parent
TOKEN_VARS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")


def pick(mode: str, release_heads: list[str], develop_head: str | None, statuses: dict[str, str],
         nightly_done: str | None, now: dt.datetime) -> tuple[str, str] | None:
    """The next (sha, why) to run, or None. statuses: {sha: state of CONTEXT} for the shas above (missing = none).
    'pending' counts as not run: this one process runs one commit at a time, so a pending status it sees while
    picking was left by a run that was stopped or could not write its result."""
    statuses = {k: v for k, v in statuses.items() if v != "pending"}
    if mode != "winvm":
        return None
    for sha in release_heads:
        if sha not in statuses:
            return sha, "release pull request"
    today = now.astimezone(dt.timezone.utc).date().isoformat()
    if develop_head and now.astimezone(dt.timezone.utc).hour >= NIGHTLY_HOUR_UTC and nightly_done != today:
        return develop_head, "nightly"
    if develop_head and develop_head not in statuses:
        return develop_head, "develop push"
    return None


def gh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=check)


def runner_mode() -> str:
    r = gh("api", f"repos/{REPO}/actions/variables/{VARIABLE}", "--jq", ".value", check=False)
    return r.stdout.strip() if r.returncode == 0 else "github"


def release_heads() -> list[str]:
    """Heads of open release pull requests: develop -> main of THIS repository only. The repository is public: a
    pull request from a fork (or any other branch) never reaches this Mac."""
    r = gh("pr", "list", "--repo", REPO, "--base", "main", "--head", "develop", "--state", "open", "--json",
           "headRefOid,headRefName,isDraft,isCrossRepository")
    return [p["headRefOid"] for p in json.loads(r.stdout or "[]") if trusted_release(p)]


def trusted_release(p: dict) -> bool:
    return p.get("headRefName") == "develop" and p.get("isCrossRepository") is False and not p.get("isDraft")


def develop_head() -> str | None:
    r = gh("api", f"repos/{REPO}/commits/develop", "--jq", ".sha", check=False)
    return r.stdout.strip() or None


def status_of(sha: str) -> str | None:
    r = gh("api", f"repos/{REPO}/commits/{sha}/statuses", "--jq",
           f'[.[] | select(.context == "{CONTEXT}")][0].state // ""', check=False)
    return r.stdout.strip() or None


def post(sha: str, state: str, text: str) -> None:
    """Write the status; three tries. A final result that cannot be written raises: the commit then keeps its
    'pending', which pick() treats as not run, so the next loop runs it again."""
    for i in range(3):
        r = gh("api", "-X", "POST", f"repos/{REPO}/statuses/{sha}", "-f", f"state={state}", "-f",
               f"context={CONTEXT}", "-f", f"description={text[:140]}", check=False)
        if r.returncode == 0:
            return
        time.sleep(10 * (i + 1))
    if state != "pending":
        raise RuntimeError(f"could not write the status {state} on {sha[:10]}: {r.stderr.strip()[:200]}")


def run(sha: str, why: str, repo_dir: Path, out_root: Path) -> tuple[bool, str]:
    """Run e2e/winvm/run.sh on commit sha in a fresh clone; (passed, one-line text). The scripts that run on this
    Mac are this dispatcher's own (its checkout, updated by deploying develop), never the tested commit's: the
    tested code only runs inside the throwaway VM. No GitHub login reaches the run."""
    subprocess.run(["git", "-C", str(repo_dir), "fetch", "-q", "origin", sha], check=True)
    out = out_root / f"{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}-{sha[:10]}"
    out.mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if k not in TOKEN_VARS}
    env["WINVM_REPO"] = str(repo_dir)
    t0 = time.monotonic()
    with open(out / "run.log", "w") as log:
        rc = subprocess.run(["bash", str(HERE / "run.sh"), sha, str(out)], env=env, stdin=subprocess.DEVNULL,
                            stdout=log, stderr=subprocess.STDOUT).returncode
    mins = round((time.monotonic() - t0) / 60)
    return rc == 0, f"{why}: {'passed' if rc == 0 else f'failed (exit {rc})'} in {mins} min on a fresh Windows VM"


def attempt(sha: str, why: str, repo_dir: Path, out_root: Path) -> tuple[bool, str]:
    try:
        return run(sha, why, repo_dir, out_root)
    except Exception as e:  # a broken set-up is a failed check, never a silent one
        return False, f"{why}: could not run ({type(e).__name__})"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="one pick (and run), then exit")
    ap.add_argument("--dry-run", action="store_true", help="print the pick, run nothing, post nothing")
    a = ap.parse_args()
    repo_dir = Path(os.environ.get("ORCH_REPO_DIR", Path(__file__).resolve().parents[2]))
    out_root = Path(os.environ.get("WINVM_OUT", Path.home() / ".orch-test" / "winvm-runs"))
    state_file = out_root / "dispatch-state.json"
    out_root.mkdir(parents=True, exist_ok=True)
    while True:
        st = json.loads(state_file.read_text()) if state_file.exists() else {}
        mode = runner_mode()
        heads = release_heads() if mode == "winvm" else []
        dev = develop_head() if mode == "winvm" else None
        statuses = {s: v for s in {*heads, *([dev] if dev else [])} if (v := status_of(s))}
        nxt = pick(mode, heads, dev, statuses, st.get("nightly_done"), dt.datetime.now(dt.timezone.utc))
        if nxt and a.dry_run:
            print(f"would run {nxt[0]} ({nxt[1]})")
        elif nxt:
            sha, why = nxt
            post(sha, "pending", f"{why}: running on a fresh Windows VM")
            ok, text = attempt(sha, why, repo_dir, out_root)
            if not ok:  # a test that failed by chance does not count: one re-run before the status says failure
                post(sha, "pending", f"{why}: failed once, running again")
                ok, text = attempt(sha, why, repo_dir, out_root)
                text += " (after one re-run)"
            try:
                post(sha, "success" if ok else "failure", text)
            except RuntimeError as e:  # left pending: the next loop runs this commit again
                print(e, flush=True)
                continue
            print(text, flush=True)
            if why == "nightly":
                st["nightly_done"] = dt.datetime.now(dt.timezone.utc).date().isoformat()
                state_file.write_text(json.dumps(st))
        if a.once or a.dry_run:
            return 0
        if not nxt:
            time.sleep(60)


if __name__ == "__main__":
    sys.exit(main())
