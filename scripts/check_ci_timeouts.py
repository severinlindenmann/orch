#!/usr/bin/env python3
"""Every CI job needs a time limit (timeout-minutes).

Without one GitHub stops a hung job only after 6 hours; a hung dashboard JS test once held CI that long.
A job that calls another workflow (`uses:` at job level) gets its limits from the called jobs and is skipped.

Usage: python3 scripts/check_ci_timeouts.py [workflow dir]   (default: .github/workflows)
Exit 0 = every job has a limit, 1 = the jobs without one are listed.
Plain text parsing (no YAML package), for the block style our workflow files use.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

JOB = re.compile(r"^  ([A-Za-z0-9_-]+):\s*(#.*)?$")
TOP = re.compile(r"^\S")


def jobs_without_limit(text: str) -> list[str]:
    missing: list[str] = []
    in_jobs = False
    name: str | None = None
    has_limit = calls_workflow = False

    def close() -> None:
        if name and not has_limit and not calls_workflow:
            missing.append(name)

    for line in text.splitlines():
        if TOP.match(line):
            if in_jobs:
                close()
                name = None
            in_jobs = line.split("#", 1)[0].strip() == "jobs:"
            continue
        if not in_jobs:
            continue
        m = JOB.match(line)
        if m:
            close()
            name, has_limit, calls_workflow = m.group(1), False, False
            continue
        if name is None:
            continue
        stripped = line.strip()
        # job-level keys sit at 4 spaces
        if line.startswith("    ") and not line.startswith("     "):
            if stripped.startswith("timeout-minutes:"):
                has_limit = True
            elif stripped.startswith("uses:"):
                calls_workflow = True
    if in_jobs:
        close()
    return missing


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else ".github/workflows")
    files = sorted([*root.glob("*.yml"), *root.glob("*.yaml")])
    if not files:
        print(f"no workflow files in {root}")
        return 1
    bad = [f"{f.name}: {job}" for f in files for job in jobs_without_limit(f.read_text(encoding="utf-8"))]
    if bad:
        print("These CI jobs have no timeout-minutes (GitHub would wait 6 hours on a hang):")
        for b in bad:
            print(f"  {b}")
        print("Add timeout-minutes: about twice the job's normal run time.")
        return 1
    print(f"every job in {len(files)} workflow files has a time limit")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
