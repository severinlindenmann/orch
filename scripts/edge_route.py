#!/usr/bin/env python3
"""Where do this run's Linux jobs go: the orch edge test server's own runner or GitHub's machines? (ORCH-1126)

The Linux jobs are the clock tests (fake wall clock), relay, publish, the short e2e set and the Services add-on
with its real Linux run. They run on the orch edge runner (label `orch-edge`, ARM64) only when ALL of these hold,
else on GitHub's machines as before. The rules are the Mac's (scripts/mac_route.py, ORCH-1125):

1. The repository variable EDGE_RUNNER is `orch-edge`. Any other value or none: GitHub's machines. This is the one
   setting that moves the jobs back (Settings > Secrets and variables > Actions > Variables).
2. The run is trusted: a push to develop, the nightly run, a manual run or a release pull request (into main, from a
   branch of this repository). Ordinary pull requests, queue groups and pull requests from forks never; the
   runner's job-started hook (scripts/edge-runner/job-started.sh) refuses the same once more on the machine.
3. The runner is online (read with the repository secret MAC_RUNNER_STATUS_TOKEN, the read-only runner list of
   the whole repository; no secret, an error or no online runner: GitHub's machines).
4. For a push to develop: the runner is not busy, unless EDGE_RUNNER_WHEN_BUSY is `wait`. The nightly run, manual
   runs and release pull requests always wait for it.

orch edge is ARM64 and GitHub's Linux machines are x86-64: a release pull request runs the Linux jobs on BOTH, so
a release is never cut without an x86-64 run.

Usage (ci.yml, job `route`): python3 scripts/edge_route.py   reads the env below, writes GITHUB_OUTPUT:
  edge=<JSON list of runs-on values, one matrix leg each>  edge_where=edge|github|both  edge_why=<one line>
Env: EVENT, REF, BASE_REF, HEAD_REPO, REPO, EDGE_RUNNER, EDGE_RUNNER_WHEN_BUSY, STATUS_TOKEN.
Always exits 0: a routing problem must never turn CI red; it falls back to GitHub's machines.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mac_route import fetch_runners, trusted  # same rules as the Mac, one place

LABEL = "orch-edge"
EDGE_LABELS = ["self-hosted", LABEL]
GITHUB_LINUX = "ubuntu-latest"
SETTING_ON = "orch-edge"


def pick(runners: list[dict], event: str, when_busy: str) -> tuple[bool, str]:
    """(use orch edge, why) from GitHub's runner list. Pure."""
    mine = [r for r in runners if LABEL in {str(lb.get("name")) for lb in r.get("labels") or []}]
    online = [r for r in mine if r.get("status") == "online"]
    if not online:
        return False, "the orch edge runner is offline" if mine else "no runner with the label orch-edge"
    busy = all(r.get("busy") for r in online)
    if busy and event == "push" and when_busy != "wait":
        return False, "the orch edge runner is busy with an earlier run"
    return True, "the orch edge runner is online" + (" (busy: the jobs wait for it)" if busy else "")


def route(env: dict[str, str], fetch=fetch_runners) -> tuple[bool, str]:
    """(use orch edge, why) for a run."""
    setting = (env.get("EDGE_RUNNER") or "").strip()
    if setting != SETTING_ON:
        return False, f"setting EDGE_RUNNER is {setting or 'not set'} (set it to {SETTING_ON} to use orch edge)"
    ok, why = trusted(env.get("EVENT", ""), env.get("REF", ""), env.get("BASE_REF", ""), env.get("HEAD_REPO", ""), env.get("REPO", ""))
    if not ok:
        return False, why.replace("the Mac", "orch edge")
    token = env.get("STATUS_TOKEN") or ""
    if not token:
        return False, f"{why}, but the secret MAC_RUNNER_STATUS_TOKEN is missing, so nobody can see whether the runner is online"
    try:
        runners = fetch(env.get("REPO", ""), token)
    except (urllib.error.URLError, OSError, ValueError) as e:
        return False, f"{why}, but GitHub's runner list did not answer ({type(e).__name__})"
    use, state = pick(runners, env.get("EVENT", ""), (env.get("EDGE_RUNNER_WHEN_BUSY") or "").strip())
    return use, f"{why}; {state}"


def is_release_pr(env: dict[str, str]) -> bool:
    return env.get("EVENT") == "pull_request" and env.get("BASE_REF") == "main"


def outputs(use_edge: bool, why: str, release: bool) -> dict[str, str]:
    legs: list = [EDGE_LABELS] if use_edge else [GITHUB_LINUX]
    if use_edge and release:
        legs.append(GITHUB_LINUX)  # orch edge is ARM64: a release also gets its x86-64 run on GitHub's machines
    return {
        "edge": json.dumps(legs),
        "edge_where": ("both" if len(legs) == 2 else "edge") if use_edge else "github",
        "edge_why": why.replace("\n", " "),
    }


def main() -> int:
    env = dict(os.environ)
    use, why = route(env)
    out = outputs(use, why, is_release_pr(env))
    where = {"edge": "orch edge", "both": "orch edge and GitHub machines (x86-64)", "github": "GitHub machines"}[out["edge_where"]]
    print(f"Linux jobs go to {where}: {why}")
    for path_var in ("GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY"):
        path = os.environ.get(path_var)
        if not path:
            continue
        with open(path, "a", encoding="utf-8") as f:
            if path_var == "GITHUB_OUTPUT":
                f.writelines(f"{k}={v}\n" for k, v in out.items())
            else:
                f.write(f"Linux jobs: **{where}** ({why})\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
