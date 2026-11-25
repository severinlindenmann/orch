"""Measure orch at several workspace sizes and write the table (ORCH-518).

usage: python e2e/perf/baseline.py <base folder> --sizes 500,2000,10000,50000 [--repeat 3] [--idle 60]
         [--skip dash,phone,sync,cli] [--out table.md]

Run it inside a throwaway home where orch is installed as a tool (PATH finds that orch; ORCH_HOME under
~/.orch-test with ORCH_HOME_STRICT=1, HOME a temp folder; PW_DIR for Playwright). Per size it uses
<base>/ws<N>, seeding it first (e2e/perf/seed.py) when it does not exist, turns on the dashboard, focus,
factory, insights and sync add-ons, then measures:
- the CLI (measure_cli.py): ticket list / list --all / show / new / status and needs, time and peak memory;
- the phone's share of a relay pull (measure_phone.py);
- sync on this computer (orch sync set --mode local, then orch sync now twice);
- the dashboard (measure_dash.cjs): every page's time to usable, bytes, browser memory, an idle Home minute;
- the size of .orch on disk and its file count.
Writes <base>/out/result-<N>.json per size and the markdown table to --out (default <base>/out/table.md).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from seed import stand_in_end  # noqa: E402

ADDONS = ("dashboard", "focus", "factory", "insights", "sync")


def sh(args: list[str], cwd: Path, timeout: int = 3600, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise SystemExit(f"{' '.join(args[:5])} failed ({r.returncode}): {(r.stderr or r.stdout)[-800:]}")
    return r


def orch_python(orch: str) -> str:
    """The Python of the installed orch tool (first line of its launcher), to import orch in the probes."""
    first = Path(orch).resolve().read_text(errors="replace").splitlines()[0]
    return first[2:].strip().split()[0] if first.startswith("#!") else sys.executable


def seed(ws: Path, n: int, orch: str, py: str) -> int | None:
    """Seed <ws>; returns the pid of the stand-in its live records name (end it with stand_in_end)."""
    ws.mkdir(parents=True)
    sh(["git", "init", "-q", "-b", "main"], ws)
    sh([orch, "init"], ws)
    r = sh([py, str(HERE / "seed.py"), str(ws), "--tickets", str(n), "--now", "2026-11-18T12:00:00Z"], ws, timeout=7200)
    return json.loads(r.stdout.strip().splitlines()[-1]).get("live_pid")


def disk(ws: Path) -> dict:
    kb = int(sh(["du", "-sk", str(ws / ".orch")], ws).stdout.split()[0])
    files = sum(len(f) for _, _, f in os.walk(ws / ".orch"))
    return {"mb": round(kb / 1024), "files": files}


def sync(ws: Path, orch: str) -> dict:
    sh([orch, "sync", "set", "--mode", "local"], ws)
    out = {}
    for name in ("first", "again"):
        t0 = time.monotonic()
        r = sh([orch, "sync", "now", "--json"], ws, check=False)
        out[name] = {"seconds": round(time.monotonic() - t0, 2), "ok": r.returncode == 0}
        if r.returncode != 0:
            out[name]["error"] = (r.stderr or r.stdout).strip()[-300:]
    return out


def dash(ws: Path, orch: str, idle: int, out: Path) -> dict:
    r = sh([orch, "start", "--print-launch-url", "--no-open", "--json"], ws, timeout=300)
    launch = next(x["url"] for x in json.loads(r.stdout)["launch"] if x.get("addon") == "dashboard")
    live = sorted((ws / ".orch" / "run" / "tickets").glob("t_*.json"))
    tid = live[0].stem if live else sorted((ws / ".orch" / "tickets").glob("t_*.json"))[0].stem
    try:
        sh(["node", str(HERE / "measure_dash.cjs"), launch, tid, "--idle-seconds", str(idle),
            "--timeout-ms", "120000", "--out", str(out)], ws, timeout=3600)  # fmt: skip
    finally:
        sh([orch, "stop"], ws, check=False, timeout=120)
    return json.loads(out.read_text())


def measure(base: Path, n: int, a, orch: str, py: str) -> dict:
    ws = base / f"ws{n}"
    done = base / "out" / f"result-{n}.json"
    if a.resume and done.is_file():  # measured in an earlier run that stopped later
        return json.loads(done.read_text())
    stand_in = seed(ws, n, orch, py) if not ws.exists() else None
    try:
        return _measure(base, ws, n, a, orch, py)
    finally:
        stand_in_end(stand_in)


def _measure(base: Path, ws: Path, n: int, a, orch: str, py: str) -> dict:
    for name in ADDONS:
        for _ in range(3):  # an add-on install right after another can meet "orch is still updating"
            sh([orch, "addon", "add", name, "--yes"], ws, timeout=900, check=False)
            listed = sh([orch, "addon", "list"], ws).stdout
            if any(line.split()[:2] == [name, "on"] for line in listed.splitlines()):
                break
            time.sleep(5)
        else:
            raise SystemExit(f"Could not turn on {name} in {ws}.")
    res: dict = {"tickets": n, "disk": disk(ws)}
    outdir = base / "out"
    if "cli" not in a.skip and not (a.resume and (outdir / f"cli-{n}.json").is_file()):
        f = outdir / f"cli-{n}.json"
        sh([py, str(HERE / "measure_cli.py"), str(ws), "--orch", orch, "--repeat", str(a.repeat if n <= 10000 else 1),
            "--json", str(f)], ws, timeout=14400)  # fmt: skip
        res["cli"] = json.loads(f.read_text())
    elif (outdir / f"cli-{n}.json").is_file():  # measured before: kept in the table
        res["cli"] = json.loads((outdir / f"cli-{n}.json").read_text())
    if "phone" not in a.skip:
        probe = base / f"phone{n}"
        if probe.exists():
            shutil.rmtree(probe)
        sh([orch, "stop"], ws, check=False, timeout=120)  # no add-on process changes files while copying

        def link(src, dst):  # hard links: a quick copy; a file that vanished meanwhile is left out
            try:
                os.link(src, dst)
            except FileNotFoundError:
                pass

        shutil.copytree(ws, probe, symlinks=True, copy_function=link,
                        ignore=shutil.ignore_patterns(".lock-*", ".tmp-*", "*.tmp"))  # fmt: skip
        try:
            res["phone"] = json.loads(sh([py, str(HERE / "measure_phone.py"), str(probe)], probe, timeout=7200).stdout.strip().splitlines()[-1])
        finally:
            shutil.rmtree(probe)
    if "sync" not in a.skip:
        res["sync"] = sync(ws, orch)
    if "dash" not in a.skip:
        res["dash"] = dash(ws, orch, a.idle, outdir / f"dash-{n}.json")
    (outdir / f"result-{n}.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    return res


def table(results: list[dict]) -> str:
    sizes = [r["tickets"] for r in results]
    head = "| | " + " | ".join(f"{n:,}" for n in sizes) + " |\n|---|" + "---:|" * len(sizes) + "\n"
    rows: list[str] = []

    def row(label, cell):
        rows.append(f"| {label} | " + " | ".join(cell(r) for r in results) + " |")

    def cli(name):
        def cell(r):
            c = next((x for x in r.get("cli", []) if x["command"] == name), None)
            return f"{c['seconds']:.2f} s / {c['peak_mb']} MB" if c else "-"
        return cell

    for name in ("ticket list", "ticket list --all", "ticket show", "ticket new", "ticket status", "needs"):
        row(f"orch {name}", cli(name))

    def page(name, what):
        def cell(r):
            p = next((x for x in r.get("dash", {}).get("rows", []) if x["page"].startswith(name)), None)
            if not p:
                return "-"
            if what == "time":
                return "fails" if p.get("err") else (f"{p['ms'] / 1000:.1f} s" if p.get("ms") is not None else "-")
            if what == "bytes":
                return f"{p['enc'] / 1048576:.1f} MB ({p['dec'] / 1048576:.0f} MB unpacked)"
            return f"{p.get('heapMb')} MB"
        return cell

    for name in ("First load", "Home", "Tickets list", "Tickets board", "Search", "Review", "One ticket", "Focus",
                 "Factory", "Insights"):  # fmt: skip
        row(f"{name}: usable after", page(name, "time"))
        row(f"{name}: fetched", page(name, "bytes"))
    row("Idle Home minute: fetched", page("Idle Home", "bytes"))
    row("Browser memory on Home (idle)", page("Idle Home", "heap"))

    def phone(key):
        def cell(r):
            p = r.get("phone", {}).get(key)
            if not p:
                return "-"
            if key == "first pull views":
                return f"{p['bytes'] / 1024:.0f} KB for {p['tickets']} tickets"
            return f"{p['seconds']:.1f} s, {p['full_reads']} full reads"
        return cell

    row("Phone: relay pull work (first)", phone("first pull"))
    row("Phone: relay pull work (quiet)", phone("quiet pull"))
    row("Phone: first pull payload", phone("first pull views"))
    row(".orch on disk", lambda r: f"{r['disk']['mb']:,} MB, {r['disk']['files']:,} files")

    def syn(key):
        def cell(r):
            s = r.get("sync", {}).get(key)
            return "-" if not s else (f"{s['seconds']:.1f} s" if s["ok"] else "fails")
        return cell

    row("Sync now (first)", syn("first"))
    row("Sync now (again)", syn("again"))
    return head + "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--sizes", default="500,2000,10000,50000")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--idle", type=int, default=60)
    ap.add_argument("--skip", default="")
    ap.add_argument("--out", default=None)
    ap.add_argument("--resume", action="store_true", help="keep the sizes an earlier run finished")
    a = ap.parse_args(argv)
    if os.environ.get("ORCH_HOME_STRICT") != "1":
        raise SystemExit("Run it in a throwaway home: ORCH_HOME=<folder under ~/.orch-test>, ORCH_HOME_STRICT=1.")
    orch = shutil.which("orch")
    if not orch:
        raise SystemExit("No orch on PATH (install it as a tool in the throwaway home first).")
    py = orch_python(orch)
    base = Path(a.base).resolve()
    (base / "out").mkdir(parents=True, exist_ok=True)
    results = []
    for n in [int(x) for x in a.sizes.split(",") if x.strip()]:
        print(f"== {n} tickets", flush=True)
        results.append(measure(base, n, a, orch, py))
    text = table(results)
    out = Path(a.out) if a.out else base / "out" / "table.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
