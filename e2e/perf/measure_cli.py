"""Time orch commands in a seeded workspace (ORCH-518): wall time (median of --repeat runs) and peak memory.

usage: python e2e/perf/measure_cli.py <workspace> --orch <path to orch> [--repeat 3] [--json out.json]

Run it with the same throwaway HOME / ORCH_HOME (ORCH_HOME_STRICT=1) the workspace was made with; every
command runs in that environment and in the workspace folder. Writing commands (ticket new, status) change
the seeded workspace a little: a new ticket per run, a status flip back and forth.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path


def run_one(orch: str, ws: Path, args: list[str], env: dict) -> tuple[float, float]:
    """Wall seconds and peak memory (MB) of one command in a fresh child (its own getrusage high-water mark:
    the measuring is done in a grandchild so each command's peak is its own)."""
    code = (
        "import resource,subprocess,sys,time,json\n"
        "t=time.monotonic(); r=subprocess.run(sys.argv[1:],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)\n"
        "w=time.monotonic()-t; m=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss\n"
        "print(json.dumps({'rc':r.returncode,'wall':w,'rss':m,'err':r.stderr.decode(errors='replace')[-400:]}))\n"
    )
    r = subprocess.run([sys.executable, "-c", code, orch, *args], cwd=ws, env=env, capture_output=True, text=True)
    d = json.loads(r.stdout)
    if d["rc"] != 0:
        raise SystemExit(f"orch {' '.join(args)} failed ({d['rc']}): {d['err']}")
    scale = 1 if sys.platform == "darwin" else 1024
    return d["wall"], d["rss"] * scale / 1048576


def commands(ws: Path) -> list[tuple[str, list[str]]]:
    """The commands to time, with real ids from the workspace: one open ticket with steps for show/status."""
    tdir = ws / ".orch" / "tickets"
    pick = None
    for p in sorted(tdir.glob("t_*.json")):
        t = json.loads(p.read_text(encoding="utf-8"))
        if t.get("status") == "open" and t.get("checklist") and not t.get("epic"):
            pick = t["id"]
            break
    if pick is None:
        raise SystemExit("No open ticket with steps in the workspace.")
    return [
        ("ticket list", ["ticket", "list"]),
        ("ticket list --all", ["ticket", "list", "--all"]),
        ("ticket show", ["ticket", "show", pick]),
        ("ticket new", ["ticket", "new", "Measure the new ticket time"]),
        ("ticket status", ["ticket", "status", pick, "waiting"]),
        ("ticket status back", ["ticket", "status", pick, "open"]),
        ("needs", ["needs"]),
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("workspace")
    ap.add_argument("--orch", required=True)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--only", default="", help="comma list of command names to time")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    ws = Path(a.workspace).resolve()
    if os.environ.get("ORCH_HOME_STRICT") != "1":
        raise SystemExit("Run it with ORCH_HOME=<throwaway folder> and ORCH_HOME_STRICT=1.")
    env = dict(os.environ)
    for k in list(env):
        if k.startswith(("CLAUDE", "CODEX_", "ORCH_AGENT", "ORCH_RUN")):
            env.pop(k)
    env["ORCH_NO_PULL_LOOK"] = "1"
    env["ORCH_NO_HEALTH_CHECK"] = "1"
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    rows = []
    n = len(list((ws / ".orch" / "tickets").glob("t_*.json")))
    for name, args in commands(ws):
        if only and name not in only:
            continue
        walls, peaks = [], []
        for _ in range(a.repeat):
            w, m = run_one(a.orch, ws, args, env)
            walls.append(w)
            peaks.append(m)
        row = {"tickets": n, "command": name, "seconds": round(statistics.median(walls), 2),
               "peak_mb": round(max(peaks))}  # fmt: skip
        rows.append(row)
        print(f"{n:>6}  {name:<20} {row['seconds']:>7.2f} s  {row['peak_mb']:>5} MB", flush=True)
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
