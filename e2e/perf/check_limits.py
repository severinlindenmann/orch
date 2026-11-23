"""The CI check at 10,000 tickets (ORCH-525): seed a throwaway workspace, measure, fail when a limit is passed.

usage: python e2e/perf/check_limits.py <base folder> [--limits e2e/perf/limits.json] [--idle 60] [--skip dash]

Run it like baseline.py: orch installed as a tool and on PATH, ORCH_HOME a throwaway folder with
ORCH_HOME_STRICT=1, PW_DIR the folder holding node_modules/playwright. <base> must be a throwaway folder
(RUNNER_TEMP, temp, ~/.orch-test): seed.py refuses anything else. It measures what the owner set limits for
(limits.json):
- `orch ticket list` and `orch needs`: median of 3 runs after one warm-up run (the warm-up builds the ticket index,
  as the first command of a day does once);
- every dashboard page (first load included): time until usable;
- an idle minute on Home: bytes over the wire.
Prints a table, adds it to the GitHub job summary when there is one, writes <base>/out/limits.json and exits 1 when
a limit is passed (each one named with its number and limit).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import baseline  # noqa: E402  (the same seeding and dashboard measuring as the baseline table)

PAGES_ADDONS = ("dashboard", "focus", "factory", "insights")


def turn_on(ws: Path, orch: str) -> None:
    for name in PAGES_ADDONS:
        for _ in range(3):  # an add-on install right after another can meet "orch is still updating"
            baseline.sh([orch, "addon", "add", name, "--yes"], ws, timeout=900, check=False)
            listed = baseline.sh([orch, "addon", "list"], ws).stdout
            if any(line.split()[:2] == [name, "on"] for line in listed.splitlines()):
                break
            time.sleep(5)
        else:
            raise SystemExit(f"Could not turn on {name}.")


def commands(ws: Path, orch: str, py: str, names: list[str], out: Path) -> dict[str, float]:
    for name in names:  # warm-up: builds the index once
        baseline.sh([orch, *name.split()], ws, timeout=600)
    baseline.sh([py, str(HERE / "measure_cli.py"), str(ws), "--orch", orch, "--repeat", "3", "--only",
                 ",".join(names), "--json", str(out)], ws, timeout=3600)  # fmt: skip
    return {r["command"]: r["seconds"] for r in json.loads(out.read_text())}


def check(lim: dict, cmds: dict[str, float], dash: dict | None) -> tuple[list[str], list[str]]:
    """(table lines, the passed limits in plain words)."""
    lines = ["| What | Measured | Limit |", "|---|---:|---:|"]
    bad: list[str] = []
    for name, limit in lim["command_seconds"].items():
        s = cmds.get(name)
        lines.append(f"| orch {name} | {'-' if s is None else f'{s:.2f} s'} | {limit:.1f} s |")
        if s is None or s > limit:
            bad.append(f"orch {name} took {s} s (limit {limit} s)")
    if dash is not None:
        idle_limit = lim["idle_minute_bytes"]
        for r in dash.get("rows", []):
            if r["page"].startswith("Idle Home"):
                secs = int(r["page"].split()[2])  # "Idle Home 60 s": a shorter local try is scaled to a minute
                per_minute = r["enc"] * 60 / secs
                kb = per_minute / 1024
                lines.append(f"| Idle Home minute | {kb:.0f} KB | {idle_limit / 1024:.0f} KB |")
                if per_minute > idle_limit:
                    bad.append(f"An idle Home minute fetched {kb:.0f} KB (limit {idle_limit / 1024:.0f} KB)")
                continue
            ms, limit = r.get("ms"), lim["page_seconds"]
            shown = "fails" if r.get("err") else f"{ms / 1000:.1f} s"
            lines.append(f"| {r['page']}: usable after | {shown} | {limit:.1f} s |")
            if r.get("err") or ms is None or ms > limit * 1000:
                bad.append(f"{r['page']} was usable after {shown} (limit {limit} s){': ' + r['err'] if r.get('err') else ''}")
    return lines, bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--limits", default=str(HERE / "limits.json"))
    ap.add_argument("--idle", type=int, default=60)
    ap.add_argument("--skip", default="", help="dash: commands only")
    ap.add_argument("--tickets", type=int, default=None, help="another size for a local try (CI: the limits file)")
    a = ap.parse_args(argv)
    if os.environ.get("ORCH_HOME_STRICT") != "1":
        raise SystemExit("Run it in a throwaway home: ORCH_HOME=<throwaway folder>, ORCH_HOME_STRICT=1.")
    orch = shutil.which("orch")
    if not orch:
        raise SystemExit("No orch on PATH (install it as a tool in the throwaway home first).")
    lim = json.loads(Path(a.limits).read_text(encoding="utf-8"))
    if a.tickets:
        lim["tickets"] = a.tickets
    py = baseline.orch_python(orch)
    base = Path(a.base).resolve()
    out = base / "out"
    out.mkdir(parents=True, exist_ok=True)
    ws = base / f"ws{lim['tickets']}"
    t0 = time.monotonic()
    if not ws.exists():
        baseline.seed(ws, lim["tickets"], orch, py)
    print(f"seeded {lim['tickets']} tickets in {time.monotonic() - t0:.0f} s", flush=True)
    turn_on(ws, orch)
    cmds = commands(ws, orch, py, list(lim["command_seconds"]), out / "commands.json")
    dash = None if "dash" in a.skip else baseline.dash(ws, orch, a.idle, out / "dash.json")
    lines, bad = check(lim, cmds, dash)
    text = f"### orch at {lim['tickets']:,} tickets\n\n" + "\n".join(lines) + "\n"
    print(text)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text + ("\n**Too slow:**\n" + "\n".join(f"- {b}" for b in bad) + "\n" if bad else ""))
    (out / "limits.json").write_text(json.dumps({"commands": cmds, "dash": dash, "too_slow": bad}, indent=1) + "\n")
    if bad:
        print("Too slow:\n" + "\n".join(f"- {b}" for b in bad))
        return 1
    print("Every command and page is within its limit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
