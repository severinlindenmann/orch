#!/usr/bin/env python3
"""The light check set of a pull request into develop: one job, about 5 minutes (ORCH-556, ORCH-545).

A pull request on its own runs only what its files can break: the words and style checks, ruff and the workspace
tests that read the modules it changed, and the suite of every add-on it changed. The full suite (all add-ons,
click-throughs, clock, e2e smoke, CLI smoke, both Linux workspace parts) runs once per merge queue group on top of
develop (`orch-queue/...` branches), so nothing reaches develop without it (docs/ci-checks.md).

On 18 Nov nearly every pull request ran the full set (any change under workspace/ turned on everything): 365 ci
runs for 62 merges, and GitHub ran about two full runs at once, so pull requests waited up to two hours.

Which workspace tests: every changed test file, and every test file that imports a changed module of
workspace/src/orch (`orch.<module>` or `from orch import ..., <module>`). A change to what all tests share
(conftest, fakes, pyproject, uv.lock), a changed module no test imports, or test files bigger than one part runs
one hash part of the suite (--part 1/BROAD_PARTS) instead: a sample in about 4 minutes; the queue group runs all.

Usage: python3 scripts/ci_light.py --base origin/develop --plan   prints the steps as JSON, runs nothing
       python3 scripts/ci_light.py --base origin/develop          runs the steps in order, stops at the first red
Plain Python, no packages.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BROAD_PARTS = 4  # the sample is one part of this many (workspace/tests/ci_parts.py; 2 parts take 7-9 min each)
# picked test files bigger than one sample part (by text size): the sample instead. Measured 18 Nov: worktrees.py
# picks 12 files, 13 % of the suite, 947 tests.
MAX_SHARE = 1 / BROAD_PARTS
# what every workspace test reads: a change here can break any of them
BROAD = re.compile(
    r"^workspace/(pyproject\.toml|uv\.lock|tests/(conftest|fakes|ci_parts|_orch_test_guard)\.py|tests/fakes/.*"
    r"|src/orch/__init__\.py)$"
)
TEST_FILE = re.compile(r"^workspace/tests/(test_[^/]+\.py)$")
CORE_MODULE = re.compile(r"^workspace/src/orch/([A-Za-z0-9_]+)\.py$")
ADDON = re.compile(r"^workspace-addons/([^/]+)/")
UI = re.compile(r"^workspace/src/orch_ui/")
OTHER_PY = re.compile(r"^workspace/src/.*\.py$")  # a module the picker cannot name (a sub-package): the sample


def changed(base: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", "-z", f"{base}...HEAD"], capture_output=True, text=True, check=True, cwd=ROOT
    ).stdout
    return [x for x in out.split("\0") if x]  # -z: no quoting of unusual names


def imports(module: str) -> re.Pattern[str]:
    """A test reads <module> when it names orch.<module> or imports it from the orch package."""
    m = re.escape(module)
    return re.compile(rf"\borch\.{m}\b|^\s*from orch import (?:\([^)]*|[^\n(]*)\b{m}\b", re.MULTILINE)


def test_texts() -> dict[str, str]:
    return {
        p.name: p.read_text(encoding="utf-8", errors="replace") for p in (ROOT / "workspace/tests").glob("test_*.py")
    }


def addons_known() -> set[str]:
    return {p.name for p in (ROOT / "workspace-addons").iterdir() if (p / "pyproject.toml").is_file()}


def pick_tests(files: list[str], texts: dict[str, str]) -> tuple[list[str], bool]:
    """(test files to run, broad) for the changed files. broad: run the hash sample instead."""
    if any(BROAD.match(f) for f in files):
        return [], True
    picked: set[str] = set()
    for f in files:
        t = TEST_FILE.match(f)
        if t and t.group(1) in texts:
            picked.add(t.group(1))
            continue
        c = CORE_MODULE.match(f)
        if c:
            rx = imports(c.group(1))
            found = {name for name, text in texts.items() if rx.search(text)}
            if not found:  # no test imports it (read through the CLI): the sample instead
                return [], True
            picked.update(found)
            continue
        if OTHER_PY.match(f) and not UI.match(f):
            return [], True
    total = sum(len(x) for x in texts.values()) or 1
    if sum(len(texts[n]) for n in picked) / total > MAX_SHARE:
        return [], True
    return sorted(picked), False


def plan(files: list[str], texts: dict[str, str], addons: set[str]) -> list[dict]:
    """The steps in order: {name, cwd, cmd}. Pure: reads nothing but its arguments."""
    steps: list[dict] = [
        {"name": "brand: words, tokens, CI time limits", "cwd": ".", "cmd": "python -m pytest -q brand/tests"},
        {"name": "style rules", "cwd": ".", "cmd": "python scripts/check_style.py"},
    ]
    if any(f.startswith("workspace/") for f in files):
        steps += [
            {
                "name": "workspace: ruff",
                "cwd": "workspace",
                "cmd": "uv run ruff check . && uv run ruff format --check .",
            },
        ]
        tests, broad = pick_tests(files, texts)
        if broad:
            steps.append(
                {
                    "name": f"workspace: test sample (part 1/{BROAD_PARTS}; the queue group runs all)",
                    "cwd": "workspace",
                    "cmd": f"uv run pytest -q -n auto --part 1/{BROAD_PARTS} --budget 90",
                }
            )
        elif tests:
            steps.append(
                {
                    "name": f"workspace: {len(tests)} test file(s) that read the changed code",
                    "cwd": "workspace",
                    "cmd": "uv run pytest -q -n auto --budget 90 " + " ".join(shlex.quote(f"tests/{t}") for t in tests),
                }
            )
    ui = any(UI.match(f) for f in files)
    touched = sorted({m.group(1) for f in files if (m := ADDON.match(f)) and m.group(1) in addons})
    if ui and "dashboard" in addons and "dashboard" not in touched:
        touched.append("dashboard")  # the dashboard job runs the orch_ui page tests
    for name in touched:
        cmd = "uv sync -q && uv run ruff check . && uv run ruff format --check . && uv run pytest -q -n auto"
        if name == "dashboard":
            cmd += (
                " && node --check src/orch_dashboard/web/app.js && node --check src/orch_dashboard/web/blocks.js"
                " && node --test tests/*.test.js ../../workspace/src/orch_ui/tests/*.test.mjs"
            )
        steps.append({"name": f"add-on {name}", "cwd": f"workspace-addons/{name}", "cmd": cmd})
    return steps


def step_env(base: dict[str, str]) -> dict[str, str]:
    """The environment of every step: uv runs the tests with its own Python (in the runner user's home), never the
    job's setup-python one in /opt/hostedtoolcache. That folder is writable by a group the runner user is not in, so
    `orch secret exec` refuses its interpreter (secretrun._check_chain) and test_cli_secret.py goes red whenever a
    pull request picks it (#1566). The full workspace job never installs that Python, so it never saw this."""
    return {**base, "UV_PYTHON_PREFERENCE": "only-managed"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="origin/develop")
    ap.add_argument("--plan", action="store_true", help="print the steps as JSON, run nothing")
    a = ap.parse_args(argv)
    steps = plan(changed(a.base), test_texts(), addons_known())
    if a.plan:
        print(json.dumps(steps, indent=1))
        return 0
    for s in steps:
        print(f"::group::{s['name']}", flush=True)
        print(f"$ (cd {s['cwd']} && {s['cmd']})", flush=True)
        env = step_env(dict(os.environ))
        got = subprocess.run(s["cmd"], check=False, shell=True, cwd=ROOT / s["cwd"], env=env)
        print("::endgroup::", flush=True)
        if got.returncode != 0:
            print(f"::error title=Light check red::{s['name']}", flush=True)
            return got.returncode
    print(f"{len(steps)} light step(s) green; the full suite runs once in the merge queue group.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
