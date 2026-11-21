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
       python3 scripts/ci_light.py --rules                        only the whole-tree rule checks (seconds; the
                                                                  merge queue's precheck on a group's tree)
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
# an add-on's skill text (ORCH-536): a change of only these runs the add-on tests that read skill files, not its
# whole suite. A header line added to every shipped skill otherwise ran all add-on suites and passed the 10 minutes.
ADDON_SKILL = re.compile(r"^workspace-addons/[^/]+/(.*/)?skills/.*\.md$")
READS_SKILLS = re.compile(r"SKILL\.md|skills/")
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
# Every rule test by its name, so a new one runs on each pull request by itself (owner 19 Nov: of 20 red queue
# groups, 7 were tool names and others history lint, core names, skills lint and spawn argv): a file named
# test_no_<thing>.py, test_<thing>_lint.py, test_<thing>_seams.py, test_<thing>_scan_doors.py, test_<...>names<...>.py
# or test_spawn_argv.py (not test_relay_secret_scan.py: it tests the scanner itself, 10 s). A rule test that sits in a
# bigger file is named here by its node id.
RULE_NAME = re.compile(r"^test_(no_.+|.+_lint|.+_seams|.+_scan_doors|.*names.*|spawn_argv)\.py$")
RULE_NODES = ("test_cli_status_start.py::test_no_function_reimports_a_module_level_orch_name",)
CLICK = re.compile(r"^workspace-addons/dashboard/clickthrough/features/([^/]+)\.cjs$")
PAGE_SMOKE = re.compile(r"^(workspace-addons/(focus|insights)/|e2e/focus_insights)")
PLAYWRIGHT = "1.64.1"  # the version of the page-smoke and dashboard-clickthroughs jobs (addons.yml)


def rule_tests(texts: dict[str, str]) -> list[str]:
    """The rule tests over the whole tree (pytest arguments relative to workspace/), in a stable order."""
    names = list(RULE_TESTS) + sorted(n for n in texts if RULE_NAME.match(n) and n not in RULE_TESTS)
    return names + [n for n in RULE_NODES if n.split("::")[0] not in names]


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


def addon_test_texts(addons: set[str]) -> dict[str, dict[str, str]]:
    """{add-on: {test file: text}}: what the skill-only pick reads."""
    out: dict[str, dict[str, str]] = {}
    for name in addons:
        tests = ROOT / "workspace-addons" / name / "tests"
        out[name] = {
            p.relative_to(tests).as_posix(): p.read_text(encoding="utf-8", errors="replace")
            for p in sorted(tests.rglob("test_*.py"))
        }
    return out


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


def plan(
    files: list[str],
    texts: dict[str, str],
    addons: set[str],
    addon_texts: dict[str, dict[str, str]] | None = None,
) -> list[dict]:
    """The steps in order: {name, cwd, cmd}. Pure: reads nothing but its arguments. addon_texts (add-on test files
    and their text) lets an add-on whose only change is skill text run just its tests that read skill files."""
    steps: list[dict] = [
        {"name": "brand: words, tokens, CI time limits", "cwd": ".", "cmd": "python -m pytest -q brand/tests"},
        {"name": "style rules", "cwd": ".", "cmd": "python scripts/check_style.py"},
    ]
    if any(f.startswith(("workspace/", "workspace-addons/")) for f in files):
        # generated files (ORCH-699): two pull requests that are each fine can leave one out of date together
        steps.append(
            {
                "name": "generated files are current (shipped_addons.json)",
                "cwd": "workspace",
                "cmd": "uv run python ../scripts/gen_shipped_addons.py --check"
                " || { echo 'run: python3 scripts/gen_shipped_addons.py and commit the result'; exit 1; }",
            }
        )
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
                "cmd": "uv run pytest -q -n auto --budget 90 " + " ".join(f"tests/{t}" for t in rule_tests(texts)),
            }
        )
    if any(f.startswith("workspace/") for f in files):
        tests, broad = pick_tests(files, texts)
        tests = [t for t in tests if t not in rule_tests(texts)]  # they ran in the step above
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
        own = [f for f in files if f.startswith(f"workspace-addons/{name}/")]
        page_lib = ui and name == "dashboard"  # the page library needs the whole dashboard suite
        skill_only = bool(own) and all(ADDON_SKILL.match(f) for f in own)
        if addon_texts is not None and name in addon_texts and skill_only and not page_lib:
            picked = sorted(t for t, text in addon_texts[name].items() if READS_SKILLS.search(text))
            if picked:
                steps.append(
                    {
                        "name": f"add-on {name}: {len(picked)} test file(s) that read the skills"
                        " (the queue group runs all)",
                        "cwd": f"workspace-addons/{name}",
                        "cmd": "uv sync -q && uv run pytest -q -n auto "
                        + " ".join(shlex.quote(f"tests/{t}") for t in picked),
                    }
                )
            continue
        cmd = "uv sync -q && uv run ruff check . && uv run ruff format --check . && uv run pytest -q -n auto"
        if name == "dashboard":
            cmd += (
                " && node --check src/orch_dashboard/web/app.js && node --check src/orch_dashboard/web/blocks.js"
                " && node --test tests/*.test.js ../../workspace/src/orch_ui/tests/*.test.mjs"
            )
        steps.append({"name": f"add-on {name}", "cwd": f"workspace-addons/{name}", "cmd": cmd})
    clicks = sorted({m.group(1) for f in files if (m := CLICK.match(f))})
    smoke = any(PAGE_SMOKE.match(f) and not ADDON_SKILL.match(f) for f in files)  # skill text loads no page
    if clicks or smoke:  # the browser only when a page test of this pull request needs it (about a minute)
        steps.append(
            {
                "name": "headless Chromium for the page tests",
                "cwd": ".",
                "cmd": f"npm install -g -s playwright@{PLAYWRIGHT} && playwright install --with-deps chromium",
            }
        )
    if clicks:  # deleted ones are left out: run.cjs refuses a name it does not know
        clicks = [c for c in clicks if (ROOT / f"workspace-addons/dashboard/clickthrough/features/{c}.cjs").is_file()]
    if clicks:
        steps.append(
            {
                "name": f"dashboard: the {len(clicks)} click-through(s) this pull request changed",
                "cwd": ".",
                "cmd": 'PW_DIR="$(npm root -g)" node workspace-addons/dashboard/clickthrough/run.cjs --only '
                + ",".join(clicks),
            }
        )
    if smoke:
        steps.append(
            {
                "name": "Focus and Insights pages load in a browser",
                "cwd": ".",
                "cmd": 'PW_DIR="$(npm root -g)" node e2e/focus_insights_smoke.cjs',
            }
        )
    return steps


def rules_plan(texts: dict[str, str]) -> list[dict]:
    """--rules: the checks of the whole tree that take seconds and need no browser (words, style, generated files,
    ruff, every rule test), whatever changed. The merge queue runs them on a group's merged tree before it pushes
    the group (setting pull_requests.precheck, ORCH-545), so a pull request that breaks one leaves the group at
    once instead of after a 16 minute run."""
    every = plan(["workspace/", "workspace-addons/"], texts, set())
    keep = ("brand:", "style rules", "generated files", "workspace: ruff", "rule tests")
    steps = [s for s in every if s["name"].startswith(keep)]
    for s in steps:  # the computer's own orch writes ~/.orch-tool meanwhile: the guard warns (tests/conftest.py)
        if s["name"].startswith("rule tests"):
            s["cmd"] = "ORCH_TEST_GUARD=warn " + s["cmd"]
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
    ap.add_argument("--rules", action="store_true", help="only the whole-tree rule checks (the merge queue's precheck)")
    a = ap.parse_args(argv)
    addons = addons_known()
    if a.rules:
        steps = rules_plan(test_texts())
    else:
        steps = plan(changed(a.base), test_texts(), addons, addon_test_texts(addons))
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
