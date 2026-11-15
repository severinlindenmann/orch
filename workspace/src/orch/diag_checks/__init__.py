"""The doctor checks of `orch diag` (one file per check, so each new bug class adds one file).

A check module has `NAME` and `check(snap) -> {name, verdict, fact, evidence[]}`. `snap` is
`{"now": epoch seconds, "collected": {collector: result}, "events": [debug-log events of the last day]}`.
verdict: `problem` | `ok` | `cannot_check`. A check reads the snapshot only: it never touches the
workspace, so it
can never repair or change anything. A check that raises is `cannot_check` (the others still run).
"""

from __future__ import annotations

import importlib
import pkgutil

_MAX_EVIDENCE = 10


def verdict(name: str, v: str, fact: str, evidence=()) -> dict:
    return {"name": name, "verdict": v, "fact": fact, "evidence": list(evidence)[:_MAX_EVIDENCE]}


def data(snap: dict, name: str) -> dict:
    return (snap["collected"].get(name) or {}).get("data") or {}


def modules():
    for m in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        yield importlib.import_module(f"{__name__}.{m.name}")


def run_all(snap: dict) -> list[dict]:
    out = []
    for mod in modules():
        try:
            got = mod.check(snap)
            if got is not None:  # a check may have nothing to say (its part is off): it is left out
                out.append(got)
        except Exception as e:  # noqa: BLE001
            out.append(verdict(mod.NAME, "cannot_check", f"the check failed ({type(e).__name__})"))
    return out
