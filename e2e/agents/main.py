"""Driver for the real-agent scenarios (AG-*). Started by agents/run.sh inside `env -i`. Reuses the e2e harness."""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

E2E = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(E2E))
sys.path.insert(0, str(Path(__file__).resolve().parent))
spec = importlib.util.spec_from_file_location("e2e_base_main", E2E / "main.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
import lib  # noqa: E402

ORDER = ["AG-W2", "AG-W7", "AG-R12", "AG-W5", "AG-R6", "AG-A45", "AG-F1"]
ADH = ["AG-ADH"]  # adherence benchmark: slow and costly, only by id (never part of `agents`/`all`)
V2_REAL = ["V2-R3", "V2-R4", "V2-R5", "V2-R7", "V2-R8", "V2-R9"]  # opt-in: only when named (or `v2real`), never part of `agents`


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what")
    ap.add_argument("--mode", default="live")
    ap.add_argument("--tmp", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--repeats", type=int, help="AG-ADH repeats (default 3)")
    ap.add_argument("--quick", action="store_true", help="AG-ADH smoke: 1 repeat, 2 prompts")
    a = ap.parse_args()
    if a.repeats:
        os.environ["ADH_REPEATS"] = str(a.repeats)
    if a.quick:
        os.environ["ADH_QUICK"] = "1"
    import scenarios  # noqa: F401,E402
    # same file name as e2e/scenarios_v2.py: load the agents one by its path
    v2 = importlib.util.spec_from_file_location("agents_scenarios_v2", Path(__file__).resolve().parent / "scenarios_v2.py")
    v2.loader.exec_module(importlib.util.module_from_spec(v2))

    ids = ORDER if a.what in ("agents", "all") else V2_REAL if a.what == "v2real" else a.what.split(",")
    for s in ids:
        if s not in lib.REGISTRY:
            print(f"unknown scenario {s}; known: {', '.join(ORDER + ADH + V2_REAL)}")
            return 2
    tmp, repo = Path(a.tmp), Path(a.repo)
    e = base.E(a.mode, tmp, repo, tmp.name.rsplit("-", 1)[-1].lower())
    out_dir = repo / "e2e" / "out" / ("agents-" + time.strftime("%Y%m%d-%H%M%S"))
    out_dir.mkdir(parents=True, exist_ok=True)
    os.environ["E2E_OUT_DIR"] = str(out_dir)  # AG-ADH writes adh.json / adh.md here
    out_md = out_dir / "results.md"
    out_md.write_text(f"# e2e agents {a.mode} {a.what} {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    e.home.mkdir(parents=True, exist_ok=True)
    (e.home / ".gitconfig").write_text("[init]\n\tdefaultBranch = main\n")
    res = {}
    try:
        r = subprocess.run(["uv", "tool", "install", str(repo / "workspace")], env=e.env, capture_output=True, text=True)
        if r.returncode:
            print("orch install failed:", r.stderr[-400:])
            return 1
        if any(not s.startswith(("V2-", "AG-ADH")) for s in ids):  # the V2 real-agent scenarios need no servers
            e.pub, e.rel = base.live_servers(e)
            if e.pub is None:
                print("live servers are not up")
                return 1
        res = base.run_scenarios(e, ids, out_md)
    finally:
        for fn in reversed(e.cleanup):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass
        base.stop_automation(e)
        for pid in e.pids:
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
        shutil.rmtree(tmp / "codex", ignore_errors=True)
    n = {k: sum(1 for v in res.values() if v == k) for k in ("PASS", "FAIL", "SKIP")}
    print(f"\nSUMMARY agents: {n['PASS']} pass, {n['FAIL']} fail, {n['SKIP']} skip")
    print(f"results: {out_md}")
    if (out_dir / "adh.json").exists():
        print(f"adherence json: {out_dir / 'adh.json'}")
    return 1 if n["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
