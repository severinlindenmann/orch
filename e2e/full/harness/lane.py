"""Result model shared by every lane (browser lanes write the same JSON from stepper.mjs)."""
from __future__ import annotations

import json
import statistics
import time
import traceback
from pathlib import Path


def pctl(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    if not xs:
        return 0.0
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


class Lane:
    """A python lane: steps run with `step(id, name, fn)`, probes are timing samples, findings are NOW + PROPOSAL."""

    def __init__(self, lane: str, title: str, out: Path):
        self.lane, self.title, self.out = lane, title, out
        out.mkdir(parents=True, exist_ok=True)
        (out / "shots").mkdir(exist_ok=True)
        self.steps: list[dict] = []
        self.probes: dict[str, dict] = {}
        self.findings: list[dict] = []
        self.started = time.time()
        self.notes: list[str] = []

    def step(self, sid: str, name: str, fn, expect: str = "", tags=()):
        t = time.time()
        st = {"id": sid, "name": name, "expect": expect, "status": "pass", "error": "", "tags": list(tags),
              "actions": [], "shots": [], "console": [], "http_errors": [], "axe": [], "lint": []}
        try:
            r = fn(st)
            if isinstance(r, str):
                st["note"] = r
        except Blocked as b:
            st["status"], st["error"] = "blocked", str(b)
        except Skipped as s:
            st["status"], st["error"] = "skipped", str(s)
        except Exception as x:  # noqa: BLE001
            st["status"] = "fail"
            st["error"] = f"{type(x).__name__}: {x}"[:400]
            st["trace"] = traceback.format_exc()[-600:]
        st["ms"] = int((time.time() - t) * 1000)
        self.steps.append(st)
        print(f"[{self.lane}] {st['status'].upper():7} {sid} {name} ({st['ms']} ms) {st['error'][:100]}", flush=True)
        return st

    def probe(self, pid: str, name: str, samples: list[float], target: float, hard: float, unit="s", note=""):
        self.probes[pid] = {"id": pid, "name": name, "lane": self.lane, "samples": [round(s, 3) for s in samples],
                            "median": round(statistics.median(samples), 3) if samples else None,
                            "p95": round(pctl(samples, 0.95), 3) if samples else None,
                            "max": round(max(samples), 3) if samples else None,
                            "target": target, "hard": hard, "unit": unit, "note": note}

    def finding(self, kind: str, title: str, now: str, proposal: str, step: str = "", shots=(), severity="ux"):
        self.findings.append({"lane": self.lane, "kind": kind, "severity": severity, "title": title, "now": now,
                              "proposal": proposal, "step": step, "shots": list(shots)})

    def save(self) -> dict:
        d = {"lane": self.lane, "title": self.title, "ms": int((time.time() - self.started) * 1000), "steps": self.steps,
             "probes": self.probes, "findings": self.findings, "notes": self.notes}
        (self.out / "result.json").write_text(json.dumps(d, indent=1))
        return d


class Blocked(Exception):
    pass


class Skipped(Exception):
    pass
