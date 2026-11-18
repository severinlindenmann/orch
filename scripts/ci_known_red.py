#!/usr/bin/env python3
"""Known-red checks: which systems are known red, who owns each one and until when (docs/ci-checks.md).

The one source of WHICH systems are known red is KNOWN_RED in .github/workflows/workspace.yml (the plan job reads
it). docs/ci-checks.md, the written list of required checks, holds one row per known-red system with its owner and
end date. This script reads both:

- `known_red()`: the systems in KNOWN_RED, such as {"windows-latest"}; an empty set once Windows is green.
- `rows()`: the known-red table of docs/ci-checks.md, {system: {"owner": ..., "until": "YYYY-MM-DD", ...}}.
- `problems(today)`: a known-red system with no row, no owner or no end date, or an end date that has passed.

Usage: python3 scripts/ci_known_red.py           prints the known-red systems, one per line (none: nothing)
       python3 scripts/ci_known_red.py --warn    also writes a GitHub warning per problem (never fails the job:
                                                 a passed end date is a reminder to its owner, not a red check)
Plain text, no packages, like check_ci_timeouts.py.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_YML = ROOT / ".github" / "workflows" / "workspace.yml"
CHECKS_MD = ROOT / "docs" / "ci-checks.md"
KNOWN_RED_LINE = re.compile(r"^\s*KNOWN_RED\s*=\s*(.+?)\s*$", re.M)
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def known_red(text: str | None = None) -> set[str]:
    """The systems in KNOWN_RED of workspace.yml (`{"windows-latest"}`, `set()` or `{}` for none)."""
    if text is None:
        text = WORKSPACE_YML.read_text(encoding="utf-8")
    m = KNOWN_RED_LINE.search(text)
    if not m:
        raise ValueError("workspace.yml has no KNOWN_RED line")
    value = m.group(1).split("#", 1)[0].strip()
    if value in ("set()", "{}"):
        return set()
    return {str(s) for s in ast.literal_eval(value)}


def rows(text: str | None = None) -> dict[str, dict[str, str]]:
    """The table under '## Known red' in docs/ci-checks.md: first column the system, then the named columns."""
    if text is None:
        text = CHECKS_MD.read_text(encoding="utf-8")
    part = text.split("\n## Known red", 1)
    if len(part) < 2:
        return {}
    lines = [ln for ln in part[1].split("\n## ", 1)[0].splitlines() if ln.startswith("|")]
    if len(lines) < 2:
        return {}
    head = [c.strip().lower() for c in lines[0].strip("|").split("|")]
    out: dict[str, dict[str, str]] = {}
    for ln in lines[2:]:
        cells = [c.strip().strip("`") for c in ln.strip("|").split("|")]
        row = dict(zip(head, cells))
        system = cells[0] if cells else ""
        if system and system != "(none)":
            out[system] = row
    return out


def problems(today: dt.date, red: set[str] | None = None, table: dict | None = None) -> list[str]:
    red = known_red() if red is None else red
    table = rows() if table is None else table
    found: list[str] = []
    for system in sorted(red):
        row = table.get(system)
        if not row:
            found.append(f"{system} is known red but docs/ci-checks.md has no row for it (owner, end date)")
            continue
        if not row.get("owner"):
            found.append(f"{system} is known red with no owner in docs/ci-checks.md")
        until = row.get("end date", "")
        if not DATE.match(until):
            found.append(f"{system} is known red with no end date (YYYY-MM-DD) in docs/ci-checks.md")
        elif dt.date.fromisoformat(until) < today:
            found.append(f"{system} is known red past its end date {until} (owner: {row.get('owner')}): fix it or set a new date")
    for system in sorted(set(table) - red):
        found.append(f"{system} has a known-red row in docs/ci-checks.md but is not in KNOWN_RED: remove the row")
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--warn", action="store_true", help="write a GitHub warning per problem (exit stays 0)")
    args = ap.parse_args(argv)
    for system in sorted(known_red()):
        print(system)
    if args.warn:
        for p in problems(dt.datetime.now(dt.timezone.utc).date()):
            print(f"::warning title=Known red::{p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
