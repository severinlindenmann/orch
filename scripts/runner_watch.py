#!/usr/bin/env python3
"""Runner watch: a run whose jobs wait for our own runners while those runners are offline falls back (ORCH-1932).

check-runner.yml and route (ci.yml) send jobs to our own runners (orch edge, this Mac) only when one is online when
the run starts. A runner that goes offline later, or hangs while it still looks fine on its machine (27 Nov: all four
listeners sat on dead connections after a network drop, GitHub showed them offline for 40+ minutes), leaves those
jobs queued for up to a day: develop stays red and the merge queue builds no groups.

This watch runs on GitHub's machines next to such a run (ci.yml, job `runner-watch`). Every POLL seconds it reads the
run's jobs (GITHUB_TOKEN) and the runner list (the read-only MAC_RUNNER_STATUS_TOKEN). When a job of the run waits for
a self-hosted runner and NO runner that could take it has been online for GRACE seconds in a row, it writes the file
`runner-fallback/why.txt` and the step output fallback=true; the workflow uploads the file as the artifact
`runner-fallback`, then cancels the run.
runner-fallback.yml then starts the whole run again; its first jobs read the runner list again and send everything to
GitHub's machines. A busy runner counts as online (it works, the job only waits its turn); one "online" answer
starts the count again, so a short blip never cancels anything.

Usage: python3 scripts/runner_watch.py   env: REPO, RUN_ID, GH_TOKEN (the run's jobs), STATUS_TOKEN (runners),
SELF (this job's name, left out). Exits 0 when the run's other jobs are all done, or once the run must fall back.
Never red on its own: an API error is logged and the watch tries again next round.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mac_route import fetch_runners  # the same read-only runner list as the routing

GRACE = 10 * 60  # seconds with no runner online before the run falls back (owner brief 27 Nov: "~10 minutes")
POLL = 30
MARK = Path("runner-fallback") / "why.txt"


def waiting_self_hosted(jobs: list[dict], self_name: str = "") -> list[dict]:
    """The run's jobs that wait (queued) for a self-hosted runner. Pure."""
    return [
        j
        for j in jobs
        if j.get("status") in ("queued", "waiting", "pending")
        and "self-hosted" in (j.get("labels") or [])
        and j.get("name") != self_name
    ]


def can_take(runner: dict, labels: list[str]) -> bool:
    """A runner can take a job when it has every label the job asks for. Pure."""
    have = {str(lb.get("name")) for lb in runner.get("labels") or []}
    return set(labels) <= have


def stuck(jobs: list[dict], runners: list[dict]) -> list[dict]:
    """The waiting self-hosted jobs that no online runner could take. Pure."""
    online = [r for r in runners if r.get("status") == "online"]
    return [j for j in jobs if not any(can_take(r, j.get("labels") or []) for r in online)]


def others_done(jobs: list[dict], self_name: str) -> bool:
    """Every job of the run but this watch has finished. Pure."""
    return all(j.get("status") == "completed" for j in jobs if j.get("name") != self_name)


class Watch:
    """The count: since when have waiting self-hosted jobs had no runner? Pure apart from the clock it is given."""

    def __init__(self, grace: int = GRACE):
        self.grace = grace
        self.since: float | None = None

    def step(self, now: float, jobs: list[dict], runners: list[dict], self_name: str = "") -> list[dict]:
        """The stuck jobs once they waited `grace` seconds with no runner in a row; [] before that."""
        bad = stuck(waiting_self_hosted(jobs, self_name), runners)
        if not bad:
            self.since = None
            return []
        if self.since is None:
            self.since = now
        return bad if now - self.since >= self.grace else []


def _api(method: str, url: str, token: str):
    req = urllib.request.Request(
        url,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:  # fixed https URL
        body = resp.read()
    return json.loads(body) if body else {}


def fetch_jobs(repo: str, run_id: str, token: str) -> list[dict]:
    jobs: list[dict] = []
    for page in range(1, 6):
        got = _api("GET", f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs?per_page=100&page={page}", token)
        jobs += got.get("jobs") or []
        if len(got.get("jobs") or []) < 100:
            break
    return jobs


def main() -> int:
    repo, run_id = os.environ["REPO"], os.environ["RUN_ID"]
    token, status = os.environ.get("GH_TOKEN", ""), os.environ.get("STATUS_TOKEN", "")
    self_name = os.environ.get("SELF", "runner-watch")
    if not status:
        print("runner watch: no MAC_RUNNER_STATUS_TOKEN, nobody can see the runners; not watching")
        return 0
    watch = Watch()
    while True:
        try:
            jobs = fetch_jobs(repo, run_id, token)
            if jobs and others_done(jobs, self_name):
                print("runner watch: every job of the run finished; nothing to watch")
                return 0
            bad = watch.step(time.time(), jobs, fetch_runners(repo, status), self_name)
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"runner watch: GitHub did not answer ({type(e).__name__}); trying again")
            bad = []
        if bad:
            names = ", ".join(sorted(j.get("name", "?") for j in bad))
            why = f"no runner for {names} for {GRACE // 60} minutes in a row; the run starts again on GitHub's machines"
            MARK.parent.mkdir(parents=True, exist_ok=True)
            MARK.write_text(why + "\n", encoding="utf-8")
            print(f"::warning title=runner fallback::{why}")
            out = os.environ.get("GITHUB_OUTPUT")
            if out:
                with open(out, "a", encoding="utf-8") as f:
                    f.write("fallback=true\n")
            return 0
        time.sleep(POLL)


if __name__ == "__main__":
    sys.exit(main())
