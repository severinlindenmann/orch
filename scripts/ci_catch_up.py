#!/usr/bin/env python3
"""Start a scheduled workflow that GitHub dropped (#2657). No new service: every push to develop runs this once.

GitHub creates the scheduled runs of this repository late or not at all: live-check (hourly) ran 7 times in about 100
slots, ci and e2e (nightly) start 7-8 hours late. A push to develop happens many times a day, so its ci run looks at
the newest run of each workflow below and starts it by hand (`workflow_dispatch` on develop) when it is overdue:

- live-check: no run for LIVE_DUE_H hours (it is cheap, a few seconds on Linux);
- e2e: no scheduled or manual full run on develop for NIGHTLY_DUE_H hours (a dropped nightly, not a late one: a late
  one still comes and would run twice). The run is named "e2e (catch-up)" so the Development expert reads its result
  like a nightly (devexpert.CATCH_UP).

The schedules stay as they are (the cron is the first try). Cancelled and skipped runs do not count. GitHub not
answering is never an error: it prints why and exits 0, so a develop push never goes red because of this.

Usage: python3 scripts/ci_catch_up.py --repo <owner/name> [--dry-run]   (GH_TOKEN with actions: write)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime

BRANCH = "develop"
LIVE_DUE_H = 2
NIGHTLY_DUE_H = 26  # the same as devexpert.NIGHTLY_DUE_H: a nightly that did not come for this long was dropped
# (workflow file, the events that count as a run of it, hours after which it is overdue, inputs for the manual run)
WATCH = (
    ("live-check.yml", ("schedule", "workflow_dispatch"), LIVE_DUE_H, {}),
    ("e2e.yml", ("schedule", "workflow_dispatch"), NIGHTLY_DUE_H, {"catch_up": "true"}),
)


def _ts(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def overdue(runs: list[dict], events: tuple[str, ...], due_h: float, now: datetime) -> tuple[bool, str]:
    """(start it, why) from the workflow's newest runs on develop. Pure."""
    counted = [
        r
        for r in runs
        if r.get("event") in events
        and r.get("head_branch") == BRANCH
        and r.get("conclusion") not in ("cancelled", "skipped")
        and _ts(r.get("created_at"))
    ]
    if not counted:
        return True, "no run on develop yet"
    newest = max(_ts(r.get("created_at")) for r in counted)  # type: ignore[type-var]
    age = (now - newest).total_seconds() / 3600
    if age < due_h:
        return False, f"newest run {age:.1f} h ago (due after {due_h} h)"
    return True, f"newest run {age:.1f} h ago, due after {due_h} h"


def gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=False)


def runs_of(repo: str, wf: str) -> list[dict] | None:
    got = gh("api", f"repos/{repo}/actions/workflows/{wf}/runs?branch={BRANCH}&per_page=30")
    if got.returncode != 0:
        return None
    try:
        return list(json.loads(got.stdout).get("workflow_runs") or [])
    except ValueError:
        return None


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--dry-run", action="store_true", help="only print what it would start")
    a = ap.parse_args(argv)
    now = now or datetime.now(UTC)
    for wf, events, due_h, inputs in WATCH:
        runs = runs_of(a.repo, wf)
        if runs is None:
            print(f"{wf}: GitHub did not answer, nothing started (the next push to develop looks again)")
            continue
        start, why = overdue(runs, events, due_h, now)
        if not start:
            print(f"{wf}: on time, {why}")
            continue
        if a.dry_run:
            print(f"{wf}: would start it, {why}")
            continue
        args = ["workflow", "run", wf, "--repo", a.repo, "--ref", BRANCH]
        for k, v in inputs.items():
            args += ["-f", f"{k}={v}"]
        got = gh(*args)
        if got.returncode == 0:
            print(f"{wf}: started a catch-up run, {why}")
        else:
            print(f"{wf}: could not start it ({got.stderr.strip()[:200]}); the next push to develop tries again")
    return 0


if __name__ == "__main__":
    sys.exit(main())
