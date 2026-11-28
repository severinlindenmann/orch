#!/usr/bin/env python3
"""How fast is this runner? A fixed piece of work, so perf / limits compares like with like (ORCH-2399, ORCH-2388 c2).

perf.yml compares a queue group's times with develop's newest numbers and fails on more than 30% slower (R8.3). Both
runs are "ubuntu-latest", but GitHub's machines differ up to 2x in speed: on a slow one every page was 30 to 100%
"slower than develop" with no change in orch (seen twice on check pull request 3437, and on release 52).

  perf_calibrate.py measure <out/calibration.json>
      does the same fixed work ROUNDS times (JSON files written, read and parsed, as orch does with tickets; sorting;
      hashing) and keeps the fastest round, the one the machine's other tenants disturbed least. The file goes into
      the perf artifact next to limits.json, so develop's numbers carry the speed of the runner that made them.
  perf_calibrate.py scale <develop's limits.json> <this run's calibration.json>
      rewrites develop's times (commands and pages, never the idle minute's bytes) for this runner: times the
      factor this runner's seconds / develop's runner's seconds. Only a slower runner counts, at most MAX_FACTOR:
      on a faster or equal one nothing changes, so the check is never stricter than before. No calibration
      next to develop's numbers (an older run), or another version of the work: nothing changes, and it says so.

No AI call, no network. The measuring itself (e2e/perf/check_limits.py) is not changed: it reads the rewritten file.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

WORK = 1  # the version of the fixed work: numbers of different versions are never compared
ROUNDS = 5
FILES = 3000
MAX_FACTOR = 3.0  # a runner "more than 3x slower" is something else than a slow machine
NAME = "calibration.json"


def work(folder: Path) -> None:
    """One round: FILES ticket-like JSON files written, read and parsed three times, then sorting and hashing."""
    rows = [
        {"id": f"t_{i:05d}", "title": f"Ticket {i} " + "word " * 12, "status": ("ready", "active", "done")[i % 3],
         "checklist": [{"id": f"c{k}", "text": "step " * 6, "done": k % 2 == 0} for k in range(8)],
         "history": [{"at": f"2026-11-{1 + k % 28:02d}T10:00:00Z", "text": "line " * 10} for k in range(12)]}
        for i in range(FILES)
    ]  # fmt: skip
    for r in rows:
        (folder / f"{r['id']}.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
    seen = 0
    for _ in range(3):
        got = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.iterdir())]
        got.sort(key=lambda r: (r["status"], r["title"][::-1]))
        seen += sum(len(r["history"]) for r in got)
    digest = hashlib.sha256()
    for r in rows:
        digest.update(json.dumps(r, sort_keys=True).encode())
    assert seen == 3 * FILES * 12 and digest.hexdigest()


def measure(rounds: int = ROUNDS) -> float:
    """Seconds of the fastest of `rounds` rounds."""
    best = None
    for _ in range(rounds):
        with tempfile.TemporaryDirectory(prefix="orch-perf-cal-") as d:
            t0 = time.perf_counter()
            work(Path(d))
            took = time.perf_counter() - t0
        best = took if best is None else min(best, took)
    return round(best, 4)


def _read(path: Path) -> dict | None:
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def _seconds(cal: dict | None) -> float | None:
    """The calibration's seconds, or None when it is missing, of another version of the work, or no number."""
    if not cal or cal.get("work") != WORK:
        return None
    s = cal.get("seconds")
    return float(s) if isinstance(s, (int, float)) and not isinstance(s, bool) and s > 0 else None


def factor(here: dict | None, develop: dict | None) -> tuple[float, str]:
    """(what develop's times are multiplied by on this runner, one plain line why)."""
    a, b = _seconds(here), _seconds(develop)
    if a is None or b is None:
        who = "this run" if a is None else "develop's run"
        return 1.0, f"No runner speed for {who}: develop's times are compared as they are."
    f = a / b
    said = f"This runner did the fixed work in {a:.2f} s, develop's runner in {b:.2f} s"
    if f <= 1.0:
        return 1.0, f"{said}: not slower, so develop's times are compared as they are."
    if f > MAX_FACTOR:
        return MAX_FACTOR, f"{said}: develop's times count {MAX_FACTOR:.2f}x here (the most a slower runner gets)."
    return round(f, 3), f"{said}: develop's times count {f:.2f}x here."


def scaled(numbers: dict, f: float) -> dict:
    """develop's out/limits.json with every time multiplied by f: commands (seconds) and pages (ms). The idle
    minute is bytes, not time, and stays; so does everything this does not know."""
    out = dict(numbers)
    cmds = numbers.get("commands")
    if isinstance(cmds, dict):
        out["commands"] = {
            k: (v * f if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for k, v in cmds.items()
        }
    dash = numbers.get("dash")
    if isinstance(dash, dict) and isinstance(dash.get("rows"), list):
        rows = []
        for r in dash["rows"]:
            ms = r.get("ms") if isinstance(r, dict) else None
            idle = isinstance(r, dict) and str(r.get("page") or "").startswith("Idle Home")
            if not idle and isinstance(ms, (int, float)) and not isinstance(ms, bool):
                r = {**r, "ms": ms * f}
            rows.append(r)
        out["dash"] = {**dash, "rows": rows}
    return out


def say(line: str) -> None:
    print(line)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(line + "\n\n")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "measure":
        out = Path(argv[1])
        out.parent.mkdir(parents=True, exist_ok=True)
        got = {"work": WORK, "seconds": measure(), "rounds": ROUNDS}
        out.write_text(json.dumps(got, indent=1) + "\n", encoding="utf-8")
        print(f"This runner does the fixed work in {got['seconds']:.2f} s (the fastest of {ROUNDS} rounds).")
        return 0
    if len(argv) == 3 and argv[0] == "scale":
        path, here = Path(argv[1]), _read(Path(argv[2]))
        numbers = _read(path)
        if numbers is None:
            print("No develop numbers to rewrite.")  # check_limits.py says there is nothing to compare with
            return 0
        f, why = factor(here, _read(path.with_name(NAME)))
        if f != 1.0:
            path.write_text(json.dumps({**scaled(numbers, f), "runner_factor": f}, indent=1) + "\n", encoding="utf-8")
        say(why)
        return 0
    print(__doc__.split("\n\n")[2], file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
