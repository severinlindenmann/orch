"""The CI check at 10,000 tickets (ORCH-525): seed a throwaway workspace, measure, fail when a limit is passed.

usage: python e2e/perf/check_limits.py <base folder> [--limits e2e/perf/limits.json] [--idle 60] [--skip dash]
         [--against <develop's out/limits.json>]

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

--against (the merge queue, ORCH-1609, R8.3): the owner's limits are only shown, never fail the run. It fails only
when a row is more than 30% slower or costlier than develop's numbers (the out/limits.json of develop's newest perf
run) and by more than a small noise floor, or when a page develop loads fails here. No develop numbers: it says so
and passes.
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
# R8.3: fail only on a regression of more than 30% against develop. Below the floor a difference is runner noise.
REGRESSION = 1.3
FLOOR_SECONDS = 0.2
FLOOR_BYTES = 20 * 1024


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


def _numbers(cmds: dict[str, float], dash: dict | None) -> dict[str, tuple[float | None, str]]:
    """{row: (value, unit)}: seconds for commands and pages (None = failed), bytes for an idle Home minute."""
    rows: dict[str, tuple[float | None, str]] = {f"orch {k}": (v, "s") for k, v in cmds.items()}
    for r in (dash or {}).get("rows", []):
        if r["page"].startswith("Idle Home"):
            rows["Idle Home minute"] = (r["enc"] * 60 / int(r["page"].split()[2]), "B")
        else:
            ms = None if r.get("err") or r.get("ms") is None else r["ms"] / 1000
            rows[r["page"]] = (ms, "s")
    return rows


def _shown(v: float | None, unit: str) -> str:
    if v is None:
        return "fails"
    return f"{v:.2f} s" if unit == "s" else f"{v / 1024:.0f} KB"


def regressions(cmds: dict[str, float], dash: dict | None, develop: dict) -> tuple[list[str], list[str]]:
    """(table lines, the rows more than 30% worse than develop in plain words). A row develop has no number for
    (it failed there too, or it is new) is shown and never fails."""
    now, before = _numbers(cmds, dash), _numbers(develop.get("commands") or {}, develop.get("dash"))
    lines = ["| What | Measured | develop | Change |", "|---|---:|---:|---:|"]
    bad: list[str] = []
    for name, (v, unit) in now.items():
        b = before.get(name, (None, unit))[0]
        change = "-" if v is None or not b else f"{(v / b - 1) * 100:+.0f}%"
        lines.append(f"| {name} | {_shown(v, unit)} | {_shown(b, unit)} | {change} |")
        if b is None:
            continue
        floor = FLOOR_SECONDS if unit == "s" else FLOOR_BYTES
        if v is None:
            bad.append(f"{name} fails here but works on develop ({_shown(b, unit)})")
        elif v > b * REGRESSION and v - b > floor:
            bad.append(f"{name}: {_shown(v, unit)}, {change} against develop ({_shown(b, unit)})")
    return lines, bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--limits", default=str(HERE / "limits.json"))
    ap.add_argument("--idle", type=int, default=60)
    ap.add_argument("--skip", default="", help="dash: commands only")
    ap.add_argument("--tickets", type=int, default=None, help="another size for a local try (CI: the limits file)")
    ap.add_argument("--against", default=None, help="develop's out/limits.json: fail only on a >30%% regression")
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
    stand_in = baseline.seed(ws, lim["tickets"], orch, py) if not ws.exists() else None
    print(f"seeded {lim['tickets']} tickets in {time.monotonic() - t0:.0f} s", flush=True)
    try:
        turn_on(ws, orch)
        cmds = commands(ws, orch, py, list(lim["command_seconds"]), out / "commands.json")
        dash = None if "dash" in a.skip else baseline.dash(ws, orch, a.idle, out / "dash.json")
    finally:
        baseline.stand_in_end(stand_in)
    lines, bad = check(lim, cmds, dash)
    text = f"### orch at {lim['tickets']:,} tickets\n\n" + "\n".join(lines) + "\n"
    (out / "limits.json").write_text(json.dumps({"commands": cmds, "dash": dash, "too_slow": bad}, indent=1) + "\n")
    if a.against is not None:
        return against_develop(Path(a.against), cmds, dash, text, bad)
    print(text)
    summarize(text + ("\n**Too slow:**\n" + "\n".join(f"- {b}" for b in bad) + "\n" if bad else ""))
    if bad:
        print("Too slow:\n" + "\n".join(f"- {b}" for b in bad))
        return 1
    print("Every command and page is within its limit.")
    return 0


def summarize(text: str) -> None:
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text)


def against_develop(path: Path, cmds: dict[str, float], dash: dict | None, limits_text: str, over: list[str]) -> int:
    """The merge queue's verdict (R8.3): only a >30% regression against develop fails; the limits are information."""
    info = limits_text + (f"\n{len(over)} over the owner's limit (shown only, R8.3).\n" if over else "")
    try:
        develop = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        text = "No develop numbers to compare with (no finished nightly perf run): nothing to fail on.\n\n" + info
        print(text)
        summarize(text)
        return 0
    lines, bad = regressions(cmds, dash, develop)
    head = f"### Against develop (fails on more than {round((REGRESSION - 1) * 100)}% slower)\n\n"
    text = head + "\n".join(lines) + "\n"
    if bad:
        text += "\n**Slower than develop:**\n" + "\n".join(f"- {b}" for b in bad) + "\n"
    print(text + "\n" + info)
    summarize(text + "\n" + info)
    if bad:
        print("Fix the slowdown, or measure develop again (perf workflow, run by hand) if develop got slower too.")
        return 1
    print("Nothing is more than 30% slower than develop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
