#!/usr/bin/env python3
"""Where do this run's Mac jobs go: this Mac's own runner or GitHub's machines? (ORCH-1125)

The Mac jobs are the phone build and UI tests, the macOS part of the workspace suite, the dashboard
click-throughs, the page smoke, the dashboard pictures and the Python 3.11 checks. They run on this Mac's
self-hosted runner (label `orch-mac`) only when ALL of these hold, else on GitHub's machines as before:

1. The repository variable MAC_RUNNER is `this-mac`. Any other value or none: GitHub's machines. This is the one
   setting that moves the jobs back (Settings > Secrets and variables > Actions > Variables). `this-mac-manual`
   sends only manual runs there (a trial before develop pushes and the nightly go there, like orch edge did). The
   release keeper's test runs (release-test/... branches) never go to the Mac, whatever the setting.
2. The run is trusted: a push to develop, the nightly run, a manual run (only people with write access can start
   one) or a release pull request (into main, from a branch of this repository). Ordinary pull requests, merge
   queue groups and every pull request from a fork never reach the Mac (the repository is public). The runner's
   job-started hook (scripts/mac-runner/job-started.sh) refuses the same once more on the machine.
3. The runner is online. The repository secret MAC_RUNNER_STATUS_TOKEN (read-only "Administration" for this
   repository; it lives in GitHub, never on the Mac) reads the runner list. No secret, an error, or no online
   runner with the label: GitHub's machines, so an offline Mac never leaves a job waiting.
4. For a push to develop: the runner is not busy, unless MAC_RUNNER_WHEN_BUSY is `wait`. The nightly run, manual
   runs and release pull requests always wait for the Mac.

Usage (ci.yml, job `route`): python3 scripts/mac_route.py   reads the env below, writes GITHUB_OUTPUT:
  mac=<runs-on JSON for jobs that need macOS>  linux=<runs-on JSON for the Linux jobs that move with them>
  where=mac|github  why=<one line>
Env: EVENT, REF, BASE_REF, HEAD_REPO, REPO, MAC_RUNNER, MAC_RUNNER_WHEN_BUSY, STATUS_TOKEN.
Always exits 0: a routing problem must never turn CI red; it falls back to GitHub's machines.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

LABEL = "orch-mac"
MAC_LABELS = ["self-hosted", LABEL]
GITHUB_MAC = "macos-latest"
GITHUB_LINUX = "ubuntu-latest"
SETTING_ON = "this-mac"
SETTING_MANUAL = "this-mac-manual"  # only manual runs (workflow_dispatch) go to the Mac
# The release keeper's test runs (manual runs on release-test/... branches) decide a release: always GitHub's
# machines, whatever MAC_RUNNER says (manager 22 Nov: a new runner turned the release test red twice that day).
RELEASE_TEST_PREFIX = "refs/heads/release-test/"


def trusted(event: str, ref: str, base_ref: str, head_repo: str, repo: str) -> tuple[bool, str]:
    """(trusted, why) for the run's event. Pure."""
    if event == "push":
        if ref == "refs/heads/develop":
            return True, "push to develop"
        return False, f"push to {ref or 'an unknown branch'} (only develop goes to the Mac)"
    if event == "schedule":
        return True, "nightly run"
    if event == "workflow_dispatch":
        return True, "manual run"
    if event == "pull_request":
        if base_ref != "main":
            return False, "pull request into " + (base_ref or "an unknown branch") + " (only release pull requests go to the Mac)"
        if not head_repo or head_repo != repo:
            return False, "pull request from a fork (never on the Mac)"
        return True, "release pull request"
    return False, f"event {event or 'unknown'} (never on the Mac)"


def pick(runners: list[dict], event: str, when_busy: str) -> tuple[bool, str]:
    """(use the Mac, why) from GitHub's runner list. Pure."""
    mine = [r for r in runners if LABEL in {str(lb.get("name")) for lb in r.get("labels") or []}]
    online = [r for r in mine if r.get("status") == "online"]
    if not online:
        return False, "this Mac's runner is offline" if mine else "no runner with the label orch-mac"
    if all(r.get("busy") for r in online) and event == "push" and when_busy != "wait":
        return False, "this Mac's runner is busy with an earlier run"
    return True, "this Mac's runner is online" + (" (busy: the job waits for it)" if all(r.get("busy") for r in online) else "")


def fetch_runners(repo: str, token: str) -> list[dict]:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/actions/runners?per_page=100",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:  # fixed https URL
        return list(json.load(resp).get("runners") or [])


def route(env: dict[str, str], fetch=fetch_runners) -> tuple[bool, str]:
    """(use the Mac, why) for a run."""
    setting = (env.get("MAC_RUNNER") or "").strip()
    if (env.get("REF") or "").startswith(RELEASE_TEST_PREFIX):
        return False, "the release keeper's test run: always GitHub's machines (the release waits for it)"
    if setting == SETTING_MANUAL and env.get("EVENT") != "workflow_dispatch":
        return False, f"setting MAC_RUNNER is {SETTING_MANUAL}: only manual runs go to this Mac"
    if setting not in (SETTING_ON, SETTING_MANUAL):
        return False, f"setting MAC_RUNNER is {setting or 'not set'} (set it to {SETTING_ON} to use this Mac)"
    ok, why = trusted(env.get("EVENT", ""), env.get("REF", ""), env.get("BASE_REF", ""), env.get("HEAD_REPO", ""), env.get("REPO", ""))
    if not ok:
        return False, why
    token = env.get("STATUS_TOKEN") or ""
    if not token:
        return False, f"{why}, but the secret MAC_RUNNER_STATUS_TOKEN is missing, so nobody can see whether the runner is online"
    try:
        runners = fetch(env.get("REPO", ""), token)
    except (urllib.error.URLError, OSError, ValueError) as e:
        return False, f"{why}, but GitHub's runner list did not answer ({type(e).__name__})"
    use, state = pick(runners, env.get("EVENT", ""), (env.get("MAC_RUNNER_WHEN_BUSY") or "").strip())
    return use, f"{why}; {state}"


def outputs(use_mac: bool, why: str) -> dict[str, str]:
    return {
        "mac": json.dumps(MAC_LABELS if use_mac else GITHUB_MAC),
        "linux": json.dumps(MAC_LABELS if use_mac else GITHUB_LINUX),
        "where": "mac" if use_mac else "github",
        "why": why.replace("\n", " "),
    }


def main() -> int:
    use, why = route(dict(os.environ))
    out = outputs(use, why)
    print(f"Mac jobs go to {'this Mac' if use else 'GitHub machines'}: {why}")
    for path_var in ("GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY"):
        path = os.environ.get(path_var)
        if not path:
            continue
        with open(path, "a", encoding="utf-8") as f:
            if path_var == "GITHUB_OUTPUT":
                f.writelines(f"{k}={v}\n" for k, v in out.items())
            else:
                f.write(f"Mac jobs: **{'this Mac' if use else 'GitHub machines'}** ({why})\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
