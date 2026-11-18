#!/usr/bin/env python3
"""Does this change touch time code? Then its pull request also runs the whole suites at a fake hour (CI job clock).

The clock job runs the add-on, page and day-naming workspace suites at 22:30 and 23:59:40 UTC (ORCH-390). In the
night of 17/18 Nov it ran on every pull request that touched workspace/ or workspace-addons/: 110 jobs, 1526
minutes, 16 % of all pull request minutes (ORCH-446). It now runs on merge queue groups, at night and on releases;
on a pull request only when this script says the change reads the clock, names a day or works with time zones
(ORCH-451). Everything else is covered by the shared test clock (workspace/tests/testclock.*) and the focused
midnight and time-zone tests, which run on every pull request.

Answers `true` when a changed line under workspace/ or workspace-addons/ (code or tests, Python or JavaScript) uses
such a call or word, or when a file whose job is the clock changed (WHOLE_FILES). Comment lines and imports are
not read.

Usage: python3 scripts/touches_time_code.py --base origin/develop        prints true or false (exit 0)
       python3 scripts/touches_time_code.py --base origin/develop --why  also names the first lines that matched
Plain text over `git diff`; no packages.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

# files that are about the clock through and through: any change runs the fake-hour suites
WHOLE_FILES = re.compile(
    r"^(scripts/at-clock\.sh|scripts/touches_time_code\.py|\.github/workflows/clock\.yml"
    r"|workspace/tests/testclock\.(py|cjs)|workspace/src/orch_ui/static/date\.js)$"
)
# what the clock job runs: the code and tests of the core and the add-ons (not mockups or click-through scripts)
CODE = re.compile(r"^workspace(/|-addons/[^/]+/)(src|tests)/.*\.(py|js|mjs|cjs)$")
# comments and imports change nothing at any hour
SKIP = re.compile(r"^\s*(#|//|/\*|\*|import\s|from\s\S+\s+import\s|const\s+\{[^}]*\}\s*=\s*require\()")
# Calls and words that depend on the day or the zone. Plain "now" (time.time, Date.now, datetime.now(UTC)) is left
# out on purpose: it measures durations and stamps everywhere and does not change at midnight by itself; what turns
# a stamp into a day (a format, a local date, a day label) is what is matched.
TIME = re.compile(
    # Python: local days, day formats and zones
    r"\b(date\.today|\.today\(\)|\.date\(\)|time\.(strftime|gmtime|localtime|ctime|mktime|tzset)|strftime|strptime"
    r"|astimezone|utcoffset|tzinfo|zoneinfo|ZoneInfo|timedelta\(\s*(days|weeks)"
    # JavaScript: local days, day formats and zones; a page test's own clock
    r"|get(Hours|Date|Day|Month|FullYear|TimezoneOffset)\(|set(Hours|Date)\(|toLocale(Date|Time)?String"
    r"|Intl\.DateTimeFormat|toDateString|setFixedTime|testclock"
    # a day label as pages and tests show it ("today 10:15", 'yesterday ' + hm, == "tomorrow"), midnight, TZ
    r"|[Mm]idnight|\bTZ\b)"
    r"|\b([Tt]oday|[Yy]esterday|[Tt]omorrow)(\s?['\"`]|\s+\d|\s*\+)"
)


def changed(base: str) -> list[tuple[str, str]]:
    """(path, line) for every added or removed line; ('path', '') for a file with no line diff (a rename)."""
    out = subprocess.run(
        ["git", "diff", "--no-color", "-U0", f"{base}...HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return parse(out)


def parse(diff: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    path = ""
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            path = line.split(" b/", 1)[-1]
            rows.append((path, ""))
        elif line.startswith("+++ ") or line.startswith("--- "):
            continue
        elif line[:1] in "+-" and path:
            rows.append((path, line[1:]))
    return rows


def reasons(rows: list[tuple[str, str]]) -> list[str]:
    found: list[str] = []
    for path, line in rows:
        if WHOLE_FILES.match(path):
            found.append(f"{path} changed")
        elif line and CODE.match(path) and not SKIP.match(line):
            code = line.split(" # ", 1)[0] if path.endswith(".py") else line.split(" // ", 1)[0]
            if TIME.search(code):
                found.append(f"{path}: {line.strip()[:120]}")
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True, help="the base branch, such as origin/develop")
    ap.add_argument("--why", action="store_true", help="name the first lines that matched")
    args = ap.parse_args(argv)
    found = reasons(changed(args.base))
    print("true" if found else "false")
    if args.why:
        for r in list(dict.fromkeys(found))[:10]:
            print("  " + r, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
