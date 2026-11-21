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

The group set (--group, ORCH-1177): the before-merge checks of a merge queue group, run on this computer in a clean
copy of the group commit (the queue's local check, ORCH-1123/1124). Every text check, brand wording, contracts,
ruff check and format check of the workspace and of every add-on CI checks, the workspace tests that are not slow,
then the suites of the add-ons the group touched; at most WORKERS test workers. It stops at the first red and ends
with one line: "local check: PASS (...)" or "local check: FAIL at <step> (...)"; exit 0 green, 1 red. The failed
step's name goes to the file named by ORCH_CHECK_FAILED when that is set.

Usage: python3 scripts/ci_light.py --base origin/develop --plan   prints the steps as JSON, runs nothing
       python3 scripts/ci_light.py --base origin/develop          runs the steps in order, stops at the first red
       python3 scripts/ci_light.py --base <base> --group [--plan]  the group set
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
import time
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
# Rule tests that read the whole tree (source text, skills, commands, tool names), not one module, so the picker
# never chooses them. In the night of 18-19 Nov they made most red queue groups (cli_seams 6, tool names 6, skills
# and history lint 3 each, next_step 1): each red group costs a full run. Together about 15 s, so every pull
# request that changes workspace/ or workspace-addons/ runs them (ORCH-545).
RULE_TESTS = (
    "test_adapters.py",  # tool names only in the adapter (also reads workspace-addons/)
    "test_cli_seams.py",
    "test_skills_lint.py",
    "test_history_lint.py",
    "test_guarded_reads_lint.py",
    "test_next_step.py",
    "test_core_names_no_addon.py",
    "test_no_ui_import.py",
    "test_record_io.py",
)


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


GENERATED = {
    "name": "generated files are current (shipped_addons.json)",
    "cwd": "workspace",
    "cmd": "uv run python ../scripts/gen_shipped_addons.py --check"
    " || { echo 'run: python3 scripts/gen_shipped_addons.py and commit the result'; exit 1; }",
}


def plan(files: list[str], texts: dict[str, str], addons: set[str]) -> list[dict]:
    """The steps in order: {name, cwd, cmd}. Pure: reads nothing but its arguments."""
    steps: list[dict] = [
        {"name": "brand: words, tokens, CI time limits", "cwd": ".", "cmd": "python -m pytest -q brand/tests"},
        {"name": "style rules", "cwd": ".", "cmd": "python scripts/check_style.py"},
    ]
    if any(f.startswith(("workspace/", "workspace-addons/")) for f in files):
        # generated files (ORCH-699): two pull requests that are each fine can leave one out of date together
        steps.append(dict(GENERATED))
    if any(f.startswith("workspace/") for f in files):
        steps += [
            {
                "name": "workspace: ruff",
                "cwd": "workspace",
                "cmd": "uv run ruff check . && uv run ruff format --check .",
            },
        ]
    if any(f.startswith(("workspace/", "workspace-addons/")) for f in files):
        steps.append(
            {
                "name": "rule tests over the whole tree",
                "cwd": "workspace",
                "cmd": "uv run pytest -q -n auto --budget 90 " + " ".join(f"tests/{t}" for t in RULE_TESTS),
            }
        )
    if any(f.startswith("workspace/") for f in files):
        tests, broad = pick_tests(files, texts)
        tests = [t for t in tests if t not in RULE_TESTS]  # they ran in the step above
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


# -- the group set (--group) -----------------------------------------------------------------------------------
WORKERS = 8  # test workers at most: this Mac is a 12-core machine other helpers share (ORCH-1123)
ADDON_JOB = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
ADDON_DIR = re.compile(r"^\s+working-directory:\s*workspace-addons/([A-Za-z0-9_-]+)\s*$")
ADDON_PYTEST = re.compile(r"^\s+- run:\s*uv run pytest\b.*?-n\s+(\S+)")
SHARED_ADDON_TEST = "workspace-addons/_orch_test_guard.py"  # every add-on's tests import it


def ci_addons(text: str) -> dict[str, int]:
    """{add-on folder: test workers} for every add-on job of addons.yml: CI's own -n, at most WORKERS (auto =
    WORKERS). Plain text over the block style of our workflow files, like check_ci_timeouts.py."""
    found: dict[str, int] = {}
    name = None
    for line in text.splitlines():
        if ADDON_JOB.match(line):
            name = None
        elif d := ADDON_DIR.match(line):
            name = d.group(1)
            found.setdefault(name, WORKERS)
        elif name and (p := ADDON_PYTEST.match(line)):
            n = p.group(1)
            found[name] = min(int(n), WORKERS) if n.isdigit() else WORKERS
    return found


def _workers(n: int) -> int:
    return max(1, min(n, WORKERS))


def group_plan(files: list[str], addons: dict[str, int], base: str, labels: str = "") -> list[dict]:
    """The group set in order, cheap first: {name, cwd, cmd}. Pure: reads nothing but its arguments.
    addons: {add-on folder: test workers} of the add-ons CI checks (ci_addons). labels: the group's pull request
    labels, comma separated, as rules.yml passes them (owner-approved lifts the banned words)."""
    q = shlex.quote
    words = f"python3 scripts/check_banned_words.py --base {q(base)}" + (f" --labels {q(labels)}" if labels else "")
    steps: list[dict] = [
        {"name": "banned words", "cwd": ".", "cmd": words},
        {"name": "style rules", "cwd": ".", "cmd": "python3 scripts/check_style.py"},
        {"name": "CI time limits", "cwd": ".", "cmd": "python3 scripts/check_ci_timeouts.py"},
        {"name": "headless launch", "cwd": ".", "cmd": "python3 scripts/check_headless_launch.py"},
        {"name": "Windows paths", "cwd": ".", "cmd": "python3 scripts/check_windows_paths.py"},
        {
            "name": "brand wording and tokens",
            "cwd": ".",
            "cmd": "uv run -q --no-project --with pytest python -m pytest -q -p no:cacheprovider brand/tests",
        },
        {
            "name": "contracts",
            "cwd": ".",
            "cmd": "uv run -q --no-project --python '>=3.11' --with jsonschema --with rfc3339-validator"
            " --with cryptography python contracts/validate.py",
        },
    ]
    if any(f.startswith(("workspace/", "workspace-addons/")) for f in files):
        # generated files (ORCH-699): a group is exactly where two fine pull requests leave one out of date
        steps.append(dict(GENERATED))
    steps.append(
        {
            "name": "workspace: ruff",
            "cwd": "workspace",
            "cmd": "uv sync -q && uv run ruff check . && uv run ruff format --check .",
        }
    )
    for name in sorted(addons):
        steps.append(
            {
                "name": f"add-on {name}: ruff",
                "cwd": f"workspace-addons/{name}",
                "cmd": "uv sync -q && uv run ruff check . && uv run ruff format --check .",
            }
        )
    steps.append(
        {
            "name": "workspace: tests (not slow)",
            "cwd": "workspace",
            "cmd": f'uv run pytest -q -n {WORKERS} -m "not slow"',
        }
    )
    every = SHARED_ADDON_TEST in files
    touched = {m.group(1) for f in files if (m := ADDON.match(f))}
    if any(UI.match(f) for f in files):
        touched.add("dashboard")  # the dashboard suite runs the orch_ui page tests
    for name in sorted(addons):
        if not (every or name in touched):
            continue
        cmd = f"uv run pytest -q -n {_workers(addons[name])}"
        if name == "dashboard":
            cmd = (
                "node --check src/orch_dashboard/web/app.js && node --check src/orch_dashboard/web/blocks.js"
                " && node --test tests/*.test.js ../../workspace/src/orch_ui/tests/*.test.mjs && " + cmd
            )
        steps.append({"name": f"add-on {name}: tests", "cwd": f"workspace-addons/{name}", "cmd": cmd})
    return steps


def run_group(steps: list[dict], env: dict[str, str], out=lambda line: print(line, flush=True)) -> int:
    """Run the steps in order; stop at the first red. Last line: PASS or FAIL. 0 green, 1 red."""
    start = time.monotonic()
    for i, s in enumerate(steps, 1):
        out(f"== [{i}/{len(steps)}] {s['name']}  $ (cd {s['cwd']} && {s['cmd']})")
        got = subprocess.run(s["cmd"], check=False, shell=True, cwd=ROOT / s["cwd"], env=env)
        if got.returncode != 0:
            took = time.monotonic() - start
            if env.get("ORCH_CHECK_FAILED"):
                try:
                    Path(env["ORCH_CHECK_FAILED"]).write_text(s["name"] + "\n", encoding="utf-8")
                except OSError as e:  # the marker is extra; the FAIL line must still come
                    out(f"(could not write ORCH_CHECK_FAILED: {e})")
            out(f"local check: FAIL at {s['name']} (step {i} of {len(steps)}, exit {got.returncode}, {took:.0f} s)")
            return 1
    out(f"local check: PASS ({len(steps)} steps, {time.monotonic() - start:.0f} s)")
    return 0


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
    ap.add_argument("--group", action="store_true", help="the before-merge set of a merge queue group")
    ap.add_argument("--labels", default="", help="--group: the pull request labels, comma separated")
    a = ap.parse_args(argv)
    if a.group:
        addons = ci_addons((ROOT / ".github/workflows/addons.yml").read_text(encoding="utf-8"))
        steps = group_plan(changed(a.base), addons, a.base, a.labels)
        if a.plan:
            print(json.dumps(steps, indent=1))
            return 0
        return run_group(steps, step_env(dict(os.environ)))
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
