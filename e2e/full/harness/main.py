"""orch full e2e: bring up, run lanes S -> parallel -> serial, review, report, tear down.

Invoked by e2e/full/run.sh inside `env -i` (python via uv). Lane order (PLAN-B section 2):
  S setup, then {A, C, D, B} in parallel (B alone when --real-agents), then {W, U} serial, then P (phone, only with --phone),
  X (Windows, weekly --full only), then Q (review), Z (production smoke, read only).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FULL = HERE.parent
sys.path.insert(0, str(HERE))
import env as envmod  # noqa: E402
import findings as findmod  # noqa: E402
import lanes_py  # noqa: E402
import report  # noqa: E402
import review  # noqa: E402
from lane import Lane  # noqa: E402

REAL_HOME = Path(os.environ.get("E2E_REAL_HOME") or Path.home())
STATE = REAL_HOME / "orch-dev/state/e2e-full"
BROWSER_LANES = {"A": "lanes/A.json", "C": "lanes/C.json", "D": "lanes/D.json", "F": "lanes/F.json"}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def status(task: str, st: str, note: str = ""):
    """Status page line (best effort, never fails the run)."""
    u = REAL_HOME / ".claude/skills/status-page/update.py"
    if not u.exists() or os.environ.get("E2E_FULL_NO_STATUS"):
        return
    try:
        subprocess.run(["python3", "-I", str(u), "--dir", str(REAL_HOME / "orch-dev/state/status"), "--session", "v2-build",
                        "--lane", "e2e-full", "--group", "next", "task", task, "--status", st, "--note", note[:140]],
                       capture_output=True, timeout=20)
    except Exception:  # noqa: BLE001
        pass


def run_browser_lane(lane: str, env_json: Path, outdir: Path, quick: bool, viewports: str) -> dict:
    spec = json.loads((FULL / BROWSER_LANES[lane]).read_text())
    cmd = ["node", str(FULL / "web/stepper.mjs"), "--lane", str(FULL / BROWSER_LANES[lane]), "--env", str(env_json),
           "--out", str(outdir), "--viewports", viewports]
    if quick:
        ids = [s["id"] for s in spec["steps"] if s.get("quick")]
        if ids:
            cmd += ["--only", ",".join(ids)]
    outdir.mkdir(parents=True, exist_ok=True)
    t = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600,
                       env={"HOME": os.environ["E2E_REAL_HOME"], "PATH": os.environ["PATH"], "LANG": "en_US.UTF-8"})
    (outdir / "stepper.log").write_text(p.stdout + "\n" + p.stderr)
    rj = outdir / "result.json"
    if not rj.exists():
        return {"lane": lane, "title": spec.get("title", lane), "ms": int((time.time() - t) * 1000), "notes": [],
                "steps": [{"id": f"{lane}00", "name": "stepper ran", "status": "fail", "error": (p.stderr or p.stdout)[-300:],
                           "actions": [], "shots": []}]}
    d = json.loads(rj.read_text())
    d.setdefault("title", spec.get("title", lane))
    d.setdefault("notes", [])
    return d


def load_history() -> dict:
    try:
        return json.loads((STATE / "history.json").read_text())
    except (OSError, ValueError):
        return {"runs": []}


def main() -> int:
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # the finally block still tears the environment down
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["quick", "full"], default="quick")
    ap.add_argument("--sha", default="")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--lanes", default="")
    ap.add_argument("--no-windows", action="store_true")
    ap.add_argument("--phone", action="store_true", help="run lane P (Simulator); only after the mobile v3 lanes merged")
    ap.add_argument("--real-agents", action="store_true", help="lane B with real Claude (needs E2E_CLAUDE_TOKEN)")
    ap.add_argument("--udid", default="", help="Simulator for lane P (default: the first booted one)")
    ap.add_argument("--real-runs", type=int, default=6, help="runs of lane B with a real agent in --full")
    ap.add_argument("--build-label", default="", help="shown in the report header, e.g. the TestFlight build number the phone lane runs against")
    ap.add_argument("--no-review", action="store_true")
    ap.add_argument("--review-shots", type=int, default=24)
    ap.add_argument("--viewports", default="1280,720,390")
    ap.add_argument("--prod", default="", help="read-only smoke: relay=URL,publish=URL")
    ap.add_argument("--no-build", action="store_true", help="reuse the relay/publish binaries in the shared cargo target (dry runs)")
    ap.add_argument("--hold", action="store_true", help="after setup keep the environment up until <root>/stop exists (to explore by hand)")
    ap.add_argument("--keep-root", action="store_true")
    ap.add_argument("--no-history", action="store_true", help="a dry run: do not count it for the timing gate")
    ap.add_argument("--serve-port", type=int, default=8796)
    a = ap.parse_args()

    t_start = time.time()
    quick = a.mode == "quick"
    root, src = Path(a.root), Path(a.repo)
    repo = src
    head = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    sha = a.sha or head
    wt = None
    if a.sha and subprocess.run(["git", "-C", str(src), "rev-parse", a.sha], capture_output=True, text=True).stdout.strip() != head:
        wt = root / "src"  # the sha is not the checkout: install and build from a detached worktree of it (removed at the end)
        subprocess.run(["git", "-C", str(src), "worktree", "add", "--detach", str(wt), a.sha], check=True, capture_output=True)
        repo = wt
        sha = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    want = [x for x in (a.lanes.split(",") if a.lanes else
                        (["A", "B", "G", "Z"] if quick else ["A", "B", "C", "D", "F", "W", "G", "R", "N", "M", "U", "Z"] + ([] if a.no_windows else ["X"])))]
    if a.phone and "P" not in want:
        want.append("P")
    hist = load_history()
    n = len(hist["runs"]) + 1
    timing_fail = len(hist["runs"]) >= 2  # report-only for the first 2 runs, then fail on the worst case
    ts = time.strftime("%Y%m%d-%H%M%S")
    runname = f"{ts}-{sha[:8]}-{a.mode}"
    outdir = STATE / "reports" / runname
    outdir.mkdir(parents=True, exist_ok=True)
    status("e2e full run " + a.mode, "running", f"sha {sha[:8]} lanes {','.join(want)}")
    lanes: list[dict] = []
    findings: list[dict] = []
    env = None
    rcv = None
    aborted = False
    leaked: list = []
    try:
        # S: setup
        S = Lane("S", "Setup", outdir / "S")
        bins: dict = {}

        def build(st):
            nonlocal bins
            bins = envmod.build_bins(repo) if not a.no_build else {
                "publish": str(REAL_HOME / "orch-dev/.cargo-target-v2/release/orch-publish"),
                "relay": str(REAL_HOME / "orch-dev/.cargo-target-v2/release/orch-relay")}
            for b in bins.values():
                if not Path(b).exists():
                    raise RuntimeError(f"missing binary {b} (run without --no-build)")
        S.step("S01", "Relay and publish binaries from the sha", build, expect="both servers built")
        env = envmod.Env(root, repo, bins, sha)
        S.step("S02", "Install orch, start relay + publish, 3 workspaces, add-ons, relay/publish connect", lambda st: env.up(log),
               expect="relay, publish, dashboards of Pilatus, Reports, Home all answer")

        def alive(st):
            for k in ("pilatus", "reports", "home", "relay", "publish"):
                u = env.urls.get(k)
                if not u:
                    raise RuntimeError(f"no URL for {k}")
                if not envmod.lib.wait_http(u + ("/" if k in ("pilatus", "reports", "home") else "/health"), 15):
                    raise RuntimeError(f"{k} {u} does not answer")
        S.step("S03", "Every server answers", alive)
        for k, v in env.timings.items():
            S.notes.append(f"{k} = {v}")
        sres = S.save()
        lanes.append({**sres, "dir": "S"})
        findings += findmod.from_lane(sres, "S", timing_fail)
        if any(s["status"] == "fail" for s in sres["steps"]):
            raise RuntimeError("setup failed; later lanes blocked")
        envj = root / "env.json"
        if a.hold:
            log(f"HOLD: environment up, env {envj}; touch {root}/stop to end")
            while not (root / "stop").exists():
                time.sleep(2)
            raise RuntimeError("hold ended")

        rcv = lanes_py.Receiver()
        rcv.start()
        env.urls["receiver"] = rcv.url
        env.env_json()
        if "D" in want:
            try:
                lanes_py.d_prep(env)
            except Exception as x:  # noqa: BLE001
                log("lane D prep failed:", x)
        # parallel browser + B
        results: dict[str, dict] = {}
        threads = []

        def wrap(lane, fn):
            def go():
                status(f"lane {lane}", "running")
                try:
                    results[lane] = fn()
                except Exception as x:  # noqa: BLE001
                    results[lane] = {"lane": lane, "title": lane, "notes": [], "steps": [
                        {"id": f"{lane}00", "name": "lane crashed", "status": "fail", "error": f"{type(x).__name__}: {x}", "actions": [], "shots": []}]}
                status(f"lane {lane}", "done")
            return threading.Thread(target=go)

        par = [l for l in want if l in BROWSER_LANES]
        for l in par:
            threads.append(wrap(l, lambda l=l: run_browser_lane(l, envj, outdir / l, quick, a.viewports)))
        if "B" in want and not a.real_agents:
            threads.append(wrap("B", lambda: _save(lanes_py.lane_b(env, outdir / "B", False, 1 if quick else 5))))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if "B" in want and a.real_agents:
            results["B"] = _save(lanes_py.lane_b(env, outdir / "B", True, 1 if quick else a.real_runs))
        for l in ("A", "B", "C", "D", "F"):
            if l in results:
                lanes.append({**results[l], "dir": l})
        # serial
        if "W" in want:
            lanes.append({**_save(lanes_py.lane_w(env, outdir / "W")), "dir": "W"})
        if "N" in want:
            lanes.append({**_save(lanes_py.lane_n(env, outdir / "N")), "dir": "N"})
        if "R" in want:
            lanes.append({**_save(lanes_py.lane_r(env, outdir / "R")), "dir": "R"})
        if "G" in want:
            lanes.append({**_save(lanes_py.lane_g(env, outdir / "G")), "dir": "G"})
        if "M" in want:
            lanes.append({**_save(lanes_py.lane_m(env, outdir / "M")), "dir": "M"})
        if "U" in want:
            lanes.append({**_save(lanes_py.lane_u(env, outdir / "U", rcv)), "dir": "U"})
        if "P" in want:
            lanes.append({**_save(lanes_py.lane_p(env, outdir / "P", repo, a.udid)), "dir": "P"})
        if "X" in want:
            lanes.append({**_windows_lane(env, outdir / "X"), "dir": "X"})
        if "Z" in want:
            prod = dict(kv.split("=", 1) for kv in a.prod.split(",") if "=" in kv)
            lanes.append({**_save(lanes_py.lane_z(env, outdir / "Z", prod)), "dir": "Z"})
    except Exception as x:  # noqa: BLE001
        aborted = True
        log("run aborted:", x)
        findings.append({"lane": "S", "kind": "run", "severity": "blocking", "step": "", "shots": [], "title": "Run aborted",
                         "now": f"{type(x).__name__}: {x}", "proposal": "Fix the environment bring-up, rerun."})
    finally:
        if rcv:
            rcv.stop()
        if env:
            leaked = env.down(log) or []
        if wt:
            subprocess.run(["git", "-C", str(src), "worktree", "remove", "--force", str(wt)], capture_output=True)
    for l in lanes:
        if l["lane"] != "S":
            findings += findmod.from_lane(l, l["dir"], timing_fail)
    # Q: LLM review of the most informative shots
    if not a.no_review and not quick:
        shots = []
        for l in lanes:
            for s in l["steps"]:
                got = s.get("shots") or []
                if got:
                    shots.append((f"{s['id']} {s['name']}", outdir / l["dir"] / got[0]["file"]))
        shots = shots[: a.review_shots]
        status("lane Q", "running", f"{len(shots)} shots to review")
        if shots:
            q = review.review(shots, log=log)
            for f in q:
                f["shots"] = [os.path.relpath(p, outdir) for p in f["shots"]]
            findings += q
    # findings other lanes/sessions dropped as JSON in state/e2e-full/extra-findings (shots are absolute paths, copied into the report)
    for jf in sorted((STATE / "extra-findings").glob("*.json")) if (STATE / "extra-findings").exists() else []:
        try:
            for f in json.loads(jf.read_text()):
                shots = []
                for sp in f.get("shots", []):
                    src = Path(sp)
                    if src.exists():
                        dst = outdir / "extra" / jf.stem
                        dst.mkdir(parents=True, exist_ok=True)
                        shutil.copy(src, dst / src.name)
                        shots.append(f"extra/{jf.stem}/{src.name}")
                findings.append({**f, "shots": shots, "kind": f.get("kind", "external")})
        except (OSError, ValueError) as x:
            log("extra findings", jf, "unreadable:", x)
    if leaked:
        findings.append({"lane": "S", "kind": "run", "severity": "blocking", "step": "", "shots": [], "title": "Processes left running after tear-down",
                         "now": f"{len(leaked)} add-on server(s) were still running and were ended: {leaked}", "proposal": "Stop every add-on server on `orch stop`."})
    bad = _secrets_in(outdir, env)
    if bad:
        findings.append({"lane": "S", "kind": "run", "severity": "blocking", "step": "", "shots": [], "title": "A secret was found in the report folder",
                         "now": f"{bad}", "proposal": "Never write typed keys into step results, shots or traces."})
    seen, uniq = set(), []
    for f in findings:
        k = (f.get("lane"), f.get("kind"), f.get("title"))
        if k not in seen:
            seen.add(k)
            f["count"] = 1
            uniq.append(f)
        else:
            first = next(u for u in uniq if (u.get("lane"), u.get("kind"), u.get("title")) == k)
            first["count"] += 1
            first["step"] = f"{first['step']}, {f['step']}" if f["step"] not in first["step"] else first["step"]
    findings = uniq
    # census totals
    found = sum(l.get("coverage", {}).get("found", 0) for l in lanes)
    clicked = sum(l.get("coverage", {}).get("clicked", 0) for l in lanes)
    census = {"found": found, "clicked": clicked, "percent": round(100 * clicked / found) if found else 0}
    runinfo = {"sha": sha, "mode": a.mode, "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t_start)),
               "elapsed": f"{int((time.time() - t_start) // 60)} min {int((time.time() - t_start) % 60)} s", "n": n,
               "timing_fail": timing_fail, "build_label": a.build_label,
               "manual": ["Push notifications and the real iPhone: 5-minute checklist FULL-CHECKLIST.md iPhone steps 1 to 8",
                          "Real microphone and Deepgram accuracy", "Camera QR scan on a device", "Judging if a design is nice"]}
    page = report.render(runinfo, lanes, findings, census, outdir)
    steps = [s for l in lanes for s in l["steps"]]
    if not a.no_history:
        hist["runs"].append({"run": runname, "sha": sha, "mode": a.mode, "pass": sum(s["status"] == "pass" for s in steps),
                         "fail": sum(s["status"] == "fail" for s in steps), "findings": len(findings),
                         "probes": {p["id"]: p["median"] for l in lanes for p in l.get("probes", {}).values()}})
    STATE.mkdir(parents=True, exist_ok=True)
    if not a.no_history:
        (STATE / "history.json").write_text(json.dumps(hist, indent=1))
    _prune(STATE / "reports", 40)
    url = f"http://develop.netbird.cloud:{a.serve_port}/{runname}/"
    log(f"REPORT {url}  ({page})")
    nfail = sum(s["status"] == "fail" for s in steps)
    missing = [l for l in want if l not in {x["lane"] for x in lanes}]
    nblocked = sum(s["status"] == "blocked" for s in steps)
    status("e2e full run " + a.mode, "done", f"{len(steps)} steps, {nfail} fail, {len(findings)} findings: {url}")
    return 1 if (nfail or aborted or nblocked or missing or leaked or bad) else 0


def _secrets_in(outdir: Path, env) -> list[str]:
    """Names of secrets whose value appears in a file of the report folder (text files and archives are read as bytes)."""
    if not env:
        return []
    names = {k: v for k, v in env.vars.items() if k.endswith("_token") and v}
    if os.environ.get("E2E_CLAUDE_TOKEN"):
        names["claude_login"] = os.environ["E2E_CLAUDE_TOKEN"]
    found = []
    for p in outdir.rglob("*"):
        if p.is_file() and p.stat().st_size < 50_000_000:
            data = p.read_bytes()
            for k, v in names.items():
                if v.encode() in data:
                    found.append(f"{k} in {p.relative_to(outdir)}")
    return found


def _save(L: Lane) -> dict:
    return L.save()


def _prune(reports: Path, keep: int):
    import re
    dirs = sorted(p for p in reports.iterdir() if p.is_dir() and not p.is_symlink() and re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{8}-(quick|full)", p.name))
    for d in dirs[:-keep]:
        shutil.rmtree(d)  # exact report folders of this harness only


def _windows_lane(env, out: Path) -> dict:
    """Lane X: weekly only, through the windows-vm skill (winvm). Runs e2e/windows/*.ps1 as a standard user."""
    L = Lane("X", "Windows", out)
    from lane import Skipped

    def s(st):
        if not shutil.which("winvm"):
            raise Skipped("winvm not on PATH")
        raise Skipped("Windows lane runs from the weekly launchd job through winvm (see launchd/README); not started in this run")
    L.step("X00", "Windows standard-user flow", s)
    return L.save()


if __name__ == "__main__":
    sys.exit(main())
