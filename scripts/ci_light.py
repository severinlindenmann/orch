#!/usr/bin/env python3
"""The light check set of a pull request into develop: one job, about 5 minutes (ORCH-556, ORCH-545).

A pull request on its own runs only what its files can break: the words and style checks, ruff and the workspace
tests that read the modules it changed, and the suite of every add-on it changed. Next to it ci.yml runs the e2e
smoke and the CLI smoke when their files changed (R3.4, ORCH-1118 q6). The full suite (all add-ons, click-throughs,
page smoke, both Linux workspace parts, Windows for file, process or path code, relay, publish) runs once per
merge queue group on top of develop (`orch-queue/...` branches), so nothing reaches develop without it
(docs/ci-checks.md).

On 18 Nov nearly every pull request ran the full set (any change under workspace/ turned on everything): 365 ci
runs for 62 merges, and GitHub ran about two full runs at once, so pull requests waited up to two hours.

Which workspace tests: every changed test file, and every test file that imports a changed module of
workspace/src/orch (`orch.<module>` or `from orch import ..., <module>`). A change to what all tests share
(conftest, fakes, pyproject, uv.lock), a changed module no test imports, or test files bigger than one part runs
one hash part of the suite (--part 1/BROAD_PARTS) instead: a sample in about 4 minutes; the queue group runs all.

The group set (--group, ORCH-1177): the before-merge checks of a merge queue group, run on this computer in a clean
copy of the group commit (the queue's local check, ORCH-1123/1124). Every text check, brand wording, contracts,
ruff check and format check of the workspace and of every add-on CI checks, the whole-tree rule tests and the
workspace tests that read the changed code (or a 1/4 sample; --all-tests: every not-slow one), then the suites of the
add-ons the group touched; at most WORKERS test workers. The rest runs after the merge (ORCH-1120). It stops at the
first red and ends with one line: "local check: PASS (...)" or "local check: FAIL at <step> (...)"; exit 0 green,
1 red, 2 a smoke still running past its limit (TIMEOUT line: GitHub checks the group). The failed step's name
goes to the file named by ORCH_CHECK_FAILED when that is set.

Usage: python3 scripts/ci_light.py --base origin/develop --plan   prints the steps as JSON, runs nothing
       python3 scripts/ci_light.py --base origin/develop          runs the steps in order, stops at the first red
       python3 scripts/ci_light.py --rules                        only the whole-tree rule checks (seconds; the
                                                                  merge queue's precheck on a group's tree)
       python3 scripts/ci_light.py --base <base> --group [--plan]  the group set
Plain Python, no packages.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
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
RULE_NODES = (
    "test_cli_status_start.py::test_no_function_reimports_a_module_level_orch_name",
    # core text names no add-on: both red queue groups of 21 Nov that ORCH-1180 measured (61ada1974, c4bc60751)
    "test_addons.py::test_core_text_names_no_addon",
)
# A rule test inside any other file is found by itself (ORCH-1124: the queue's local check passed group 2402 of 21 Nov,
# GitHub failed it on test_pagesession_remote.py::test_no_same_computer_limit_is_left_in_the_product): a top-level
# test that takes no fixture and walks the tree (rglob, os.walk or git ls-files) in its own body.
TREE_WALK = re.compile(r"\.rglob\(|\bos\.walk\(|\bls-files\b")
CLICK = re.compile(r"^workspace-addons/dashboard/clickthrough/features/([^/]+)\.cjs$")
# An add-on's documentation (contracts/docs-pages.md): its docs.json, or an orch-addon.toml whose change is only the
# docs = line. orch's own tests/test_docs.py checks every docs file, so such a change runs that file, not the add-on's
# suite (owner 21 Nov, ORCH-735: one docs file in each of 11 add-ons ran every suite past light's 10 minutes).
DOCS_FILE = re.compile(r"^workspace-addons/[^/]+/src/[^/]+/docs\.json$")
ADDON_TOML = re.compile(r"^workspace-addons/[^/]+/src/[^/]+/orch-addon\.toml$")
DOCS_LINE = re.compile(r"^[+-]\s*docs\s*=")
PLAYWRIGHT = "1.64.1"  # the version of the page-smoke and dashboard-clickthroughs jobs (addons.yml)
# The group set's two smokes (ORCH-1124, manager 22 Nov): of the four red queue groups of 21 Nov, three were red on
# GitHub only in e2e-smoke or page-smoke, and a red develop puts the queue back to one at a time. They wait on
# servers and the browser more than they compute, so they run next to the other steps (background).
E2E_SMOKE = re.compile(r"^(workspace/|workspace-addons/|e2e/|install\.sh$)")  # ci.yml's e2e filter
# smoke-offline: e2e-smoke.yml's set without W0 (it installs GitHub's develop, not the group, and needs the internet)
E2E_SMOKE_STEP = {"name": "e2e smoke", "cwd": ".", "cmd": "e2e/run.sh smoke-offline --mode local", "background": True}
# What only GitHub's group run can check (ORCH-1124): the Rust servers and the phone app (relay.yml, publish.yml,
# mobile.yml, and what those read: contracts, tokens.css, the page templates), the Windows installer, and the
# services add-on, whose job also runs a real Linux service and its browser click-through (SVC-1); on this Mac that
# would go through launchd, which is the real user's. Group 2445 of 22 Nov passed here and was red there in SVC-1.
# A group that changes one of them ends with exit 2 = broken: the local check sends it to GitHub, unchecked here.
# Of contracts/ only what those servers and the phone app read (manager 22 Nov: add-on manifests and the ticket
# schema sent groups to GitHub that no server reads); the rest is checked here by contracts/validate.py and the
# workspace tests. brand/tests/test_ci_group_set.py fails when server or phone code names a contract not listed.
SERVER_CONTRACTS = (
    r"contracts/(look|relay-api|publish-api|crypto|msgsig|tool-alert|blocks|chat-groups|transcription)[^/]*$"
    r"|contracts/(message|phone-api|workspaces|subscriber-event)\.schema\.json$"
    r"|contracts/(look|vectors|review|examples/message)/|contracts/examples/ticket/valid-refs\.json$"
)
GITHUB_ONLY = re.compile(
    r"^(relay/|publish/|mobile/|transcription/|install\.ps1$|workspace-addons/services/|e2e/walkthrough/"
    r"|e2e/scenarios_services\.py$|e2e/dash_services_tab\.cjs$|workspace/src/orch_ui/static/tokens\.css$"
    r"|workspace/src/orch/templates/|" + SERVER_CONTRACTS + ")"
)
GITHUB_ONLY_EXIT = 2  # the local check's code for broken: the group is checked on GitHub as before
# Focus or Insights, or a script the page smoke itself runs (group 2409 of 21 Nov: red in e2e/focus_d/ on GitHub),
# or the dashboard's own code: Focus is served by the dashboard (its Chat, sessions, live panes), and group 2718 of
# 23 Nov changed only the dashboard's Chat data and was red on GitHub in the Focus Chat step
GROUP_PAGE_SMOKE = re.compile(
    r"^(workspace-addons/(focus|insights)/|workspace-addons/dashboard/src/"
    r"|e2e/(focus_insights|focus_d/|headless\.cjs$|dash_[^/]+\.cjs$))"
)
# Playwright in a folder of the check's own home, never a global install on a shared Mac. The browser goes to
# PLAYWRIGHT_BROWSERS_PATH when the runner sets it (then it is kept between checks); else it is downloaded into the
# throwaway home each time (about a minute; only groups that touch Focus or Insights run this)
PAGE_SMOKE_PARTS = ("pages", "focus-1", "focus-2")  # e2e/focus_insights_smoke.cjs --part, together all of it
PAGE_SMOKE_STEP = {
    "name": "Focus and Insights pages load in a browser",
    "cwd": ".",
    "cmd": 'P="$HOME/.orch-check-pw" && npm install -s --no-audit --no-fund --prefix "$P" playwright@'
    + PLAYWRIGHT
    + ' && export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$P/browsers}"'
    + ' && "$P/node_modules/.bin/playwright" install chromium'
    + ' && export NODE_PATH="$P/node_modules" PW_DIR="$P/node_modules" && D="$(mktemp -d)" && rc=0'
    # the three parts CI runs as jobs of their own, here at once (ORCH-1124, 24 Nov: run one after another they took
    # about 6 of the 9 minutes of every group that touches the dashboard). Each part has its own free port and temp
    # folders; the step is one process group, so a red elsewhere still stops all three. Output in part order.
    + " && { for p in "  # braces: a failed install above ends the step red, never runs these
    + " ".join(PAGE_SMOKE_PARTS)
    + '; do node e2e/focus_insights_smoke.cjs --part "$p" >"$D/$p.log" 2>&1 & done'
    + "; for j in $(jobs -p); do wait $j || rc=1; done"
    + "; for p in "
    + " ".join(PAGE_SMOKE_PARTS)
    + '; do echo "-- page smoke part $p"; cat "$D/$p.log"; done; rm -rf "$D"; exit $rc; }',
    "background": True,
}


def rule_tests(texts: dict[str, str]) -> list[str]:
    """The rule tests over the whole tree (pytest arguments relative to workspace/), in a stable order."""
    names = list(RULE_TESTS) + sorted(n for n in texts if RULE_NAME.match(n) and n not in RULE_TESTS)
    nodes = [n for n in RULE_NODES if n.split("::")[0] not in names]
    nodes += [n for n in tree_walk_nodes(texts, set(names)) if n not in nodes]
    return names + nodes


def tree_walk_nodes(texts: dict[str, str], skip: set[str] = frozenset()) -> list[str]:
    """Node ids of the tests that walk the whole tree in files not run whole (see TREE_WALK), in a stable order."""
    out = []
    for name in sorted(texts):
        text = texts[name]
        if name in skip or not TREE_WALK.search(text):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue  # the test run itself names a broken file
        lines = text.splitlines()
        for fn in tree.body:
            a = getattr(fn, "args", None)
            test = isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name.startswith("test_")
            if not test or a is None:
                continue
            if a.args or a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg:
                continue  # fixtures or parameters: a test of one piece, not of the tree
            if TREE_WALK.search("\n".join(lines[fn.lineno - 1 : fn.end_lineno])):
                out.append(f"{name}::{fn.name}")
    return out


def changed(base: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", "-z", f"{base}...HEAD"], capture_output=True, text=True, check=True, cwd=ROOT
    ).stdout
    return [x for x in out.split("\0") if x]  # -z: no quoting of unusual names


def toml_docs_only(diff: str) -> bool:
    """A `git diff -U0` of one orch-addon.toml changes nothing but its docs = line."""
    lines = [x for x in diff.splitlines() if x[:1] in "+-" and not x.startswith(("+++", "---"))]
    return bool(lines) and all(DOCS_LINE.match(x) for x in lines)


def docs_only(files: list[str], base: str) -> frozenset[str]:
    """The changed add-on files that are only documentation (DOCS_FILE, or an orch-addon.toml per toml_docs_only)."""
    renamed = subprocess.run(  # a file renamed to docs.json (from code) is not documentation
        ["git", "diff", "--name-only", "-z", "--diff-filter=R", f"{base}...HEAD"],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    ).stdout.split("\0")
    out = {f for f in files if DOCS_FILE.match(f) and f not in renamed}
    for f in files:
        if ADDON_TOML.match(f):
            diff = subprocess.run(
                ["git", "diff", "-U0", f"{base}...HEAD", "--", f], capture_output=True, text=True, check=True, cwd=ROOT
            ).stdout
            if toml_docs_only(diff):
                out.add(f)
    return frozenset(out)


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
    """Add-on folders with code. A placeholder for a removed add-on (pyproject.toml only, no src/, ORCH-1369)
    has nothing to lint or test."""
    return {
        p.name
        for p in (ROOT / "workspace-addons").iterdir()
        if (p / "pyproject.toml").is_file() and (p / "src").is_dir()
    }


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


def plan(
    files: list[str],
    texts: dict[str, str],
    addons: set[str],
    addon_texts: dict[str, dict[str, str]] | None = None,
    docs: frozenset[str] = frozenset(),
) -> list[dict]:
    """The steps in order: {name, cwd, cmd}. Pure: reads nothing but its arguments. addon_texts (add-on test files
    and their text) lets an add-on whose only change is skill text run just its tests that read skill files.
    docs: the changed add-on files that are only documentation (docs_only): they run orch's docs test instead of
    their add-on's suite."""
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
    if docs:
        steps.append(
            {
                "name": "add-on documentation files (orch's docs test)",
                "cwd": "workspace",
                "cmd": "uv run pytest -q tests/test_docs.py",
            }
        )
    code = [f for f in files if f not in docs]  # what can break an add-on's suite or its pages
    ui = any(UI.match(f) for f in files)
    touched = sorted({m.group(1) for f in code if (m := ADDON.match(f)) and m.group(1) in addons})
    if ui and "dashboard" in addons and "dashboard" not in touched:
        touched.append("dashboard")  # the dashboard job runs the orch_ui page tests
    for name in touched:
        own = [f for f in code if f.startswith(f"workspace-addons/{name}/")]  # its docs files left out
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
    # The Focus and Insights page smoke (e2e/focus_insights_smoke.cjs, with the whole Focus click-through: about
    # 6 minutes) is not a step here: it runs in the queue group (addons.yml page-smoke, ORCH-1118 q6).
    if clicks:  # the browser only when a click-through of this pull request needs it (about a minute)
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


# -- the group set (--group) -----------------------------------------------------------------------------------
WORKERS = 8  # test workers at most: this Mac is a 12-core machine other helpers share (ORCH-1123)
ADDON_JOB = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
ADDON_DIR = re.compile(r"^\s+working-directory:\s*workspace-addons/([A-Za-z0-9_-]+)\s*$")
ADDON_PYTEST = re.compile(r"^\s+(?:- )?run:\s*uv run pytest\b.*?-n\s+(\S+)")  # a step line or a run: under a named step
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


def github_only(files: list[str]) -> list[str]:
    """The changed files only GitHub's group run can check (GITHUB_ONLY), in order."""
    return [f for f in files if GITHUB_ONLY.match(f)]


def group_plan(
    files: list[str], addons: dict[str, int], base: str, labels: str = "", texts: dict[str, str] | None = None
) -> list[dict]:
    """The group set in order, cheap first: {name, cwd, cmd}. Pure: reads nothing but its arguments.
    addons: {add-on folder: test workers} of the add-ons CI checks (ci_addons). labels: the group's pull request
    labels, comma separated, as rules.yml passes them (owner-approved lifts the banned words).
    texts: {workspace test file: its text} picks the workspace tests (workspace_steps); None runs every not-slow
    workspace test (--all-tests: 12-21 min on this Mac, measured by ORCH-1180)."""
    q = shlex.quote
    words = f"python3 scripts/check_banned_words.py --base {q(base)}" + (f" --labels {q(labels)}" if labels else "")
    steps: list[dict] = [
        {"name": "banned words", "cwd": ".", "cmd": words},
        {"name": "style rules", "cwd": ".", "cmd": "python3 scripts/check_style.py"},
        {"name": "CI time limits", "cwd": ".", "cmd": "python3 scripts/check_ci_timeouts.py"},
        {"name": "headless launch", "cwd": ".", "cmd": "python3 scripts/check_headless_launch.py"},
        {"name": "Windows paths", "cwd": ".", "cmd": "python3 scripts/check_windows_paths.py"},
        {"name": "contract vectors", "cwd": ".", "cmd": f"python3 scripts/check_contracts.py --base {q(base)}"},
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
    if texts is None:
        steps.append(
            {
                "name": "workspace: tests (not slow)",
                "cwd": "workspace",
                "cmd": f'uv run pytest -q -n {WORKERS} -m "not slow"',
            }
        )
    else:
        steps += workspace_steps(files, texts)
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
    if any(E2E_SMOKE.match(f) for f in files):
        steps.append(dict(E2E_SMOKE_STEP))
    if any(GROUP_PAGE_SMOKE.match(f) for f in files):
        steps.append(dict(PAGE_SMOKE_STEP))
    return steps


def workspace_steps(files: list[str], texts: dict[str, str]) -> list[dict]:
    """The workspace tests of the group set (ORCH-1123): every not-slow workspace test took 12-21 min here, no faster
    than GitHub (ORCH-1180), so before the merge only what the group can break runs, the rest after it:
    the rule tests over the whole tree (always, about 15 s), then the test files that read the changed code, or the
    1/BROAD_PARTS hash sample when the change is broad (what all tests share, an unknown module, contracts, or more
    than one part). A group that changes nothing under workspace/ or contracts/ runs the rule tests only."""
    rules = rule_tests(texts)
    steps = [
        {
            "name": "workspace: rule tests over the whole tree",
            "cwd": "workspace",
            "cmd": f"uv run pytest -q -n {WORKERS} " + " ".join(shlex.quote(f"tests/{t}") for t in rules),
        }
    ]
    core = [f for f in files if f.startswith("workspace/")]
    broad = any(f.startswith("contracts/") for f in files)
    tests: list[str] = []
    if core and not broad:
        tests, broad = pick_tests(core, texts)
    if broad:
        steps.append(
            {
                "name": f"workspace: test sample (part 1/{BROAD_PARTS}; the rest runs after the merge)",
                "cwd": "workspace",
                "cmd": f'uv run pytest -q -n {WORKERS} -m "not slow" --part 1/{BROAD_PARTS}',
            }
        )
        return steps
    whole = {r.split("::")[0] for r in rules if "::" not in r}
    tests = [t for t in tests if t not in whole]
    if tests:
        steps.append(
            {
                "name": f"workspace: {len(tests)} test file(s) that read the changed code",
                "cwd": "workspace",
                "cmd": f'uv run pytest -q -n {WORKERS} -m "not slow" '
                + " ".join(shlex.quote(f"tests/{t}") for t in tests),
            }
        )
    return steps


# A smoke still running this long after it started ends the check with exit 2 (broken: GitHub checks the group;
# the check's own limit is 15). The e2e smoke takes about 2 min; groups 2579 and 2582 of 22 Nov hit this limit on
# this Mac while the same smoke on the same commit passed here in 108 s later and on GitHub: not a red of the group.
BACKGROUND_SECS = 10 * 60


def _kill(p: subprocess.Popen) -> None:
    """Stop a step's whole process group (its servers, its browser): TERM, a short wait, then KILL in any case,
    since the shell may end at TERM while a child that ignores it lives on."""
    if p.poll() is None:
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except (OSError, AttributeError):  # gone already; no process groups on Windows
            p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    try:
        os.killpg(p.pid, signal.SIGKILL)  # what is left of the group, even when its shell has ended
    except (OSError, AttributeError):
        if p.poll() is None:
            p.kill()


def _tail(log, lines: int = 60) -> str:
    try:
        log.seek(0)
        text = log.read().decode("utf-8", "replace").rstrip()
    except (OSError, ValueError):
        return ""
    return "\n".join(text.splitlines()[-lines:])


def run_group(steps: list[dict], env: dict[str, str], out=lambda line: print(line, flush=True)) -> int:
    """Run the steps in order; stop at the first red. Last line: PASS or FAIL. 0 green, 1 red, 2 a smoke past its limit.
    A step with background=True starts before the others and runs next to them; its output is printed when it ends.
    Every step runs in a process group of its own, so a red anywhere (or the check being stopped) stops everything
    still running, servers and browsers included. A background step running BACKGROUND_SECS is red."""
    start, n = time.monotonic(), len(steps)
    order = {id(s): i for i, s in enumerate(steps, 1)}
    back: list[list] = []  # [step, process, log, started]
    running: list[subprocess.Popen] = []

    def spawn(s: dict, **kw) -> subprocess.Popen:
        p = subprocess.Popen(s["cmd"], shell=True, cwd=ROOT / s["cwd"], env=env, stdin=subprocess.DEVNULL,
                             start_new_session=True, **kw)  # fmt: skip
        running.append(p)
        return p

    def red(s: dict, code: int | str) -> int:
        for b in back:
            _kill(b[1])
        for b in back:  # what each smoke said, also when it was stopped
            if b[0] is not s:
                text = _tail(b[2], 20)
                if text:
                    out(f"-- {b[0]['name']} (stopped or done; last lines):\n{text}")
        if code == "timeout":  # this computer stalled, not the group: exit 2 = broken, GitHub checks the group
            took = time.monotonic() - start
            out(
                f"local check: TIMEOUT at {s['name']} (step {order[id(s)]} of {n}, still running after "
                f"{BACKGROUND_SECS} s, {took:.0f} s in): GitHub checks this group"
            )
            return 2
        if env.get("ORCH_CHECK_FAILED"):
            try:
                Path(env["ORCH_CHECK_FAILED"]).write_text(s["name"] + "\n", encoding="utf-8")
            except OSError as e:  # the marker is extra; the FAIL line must still come
                out(f"(could not write ORCH_CHECK_FAILED: {e})")
        took = time.monotonic() - start
        out(f"local check: FAIL at {s['name']} (step {order[id(s)]} of {n}, exit {code}, {took:.0f} s)")
        return 1

    def ended(b: list) -> str | int | None:
        """A background step's exit code once it ended (its output printed), 'timeout' past its limit, else None."""
        code = b[1].poll()
        if code is None and time.monotonic() - b[3] > BACKGROUND_SECS:
            _kill(b[1])
            code = "timeout"
        if code is None:
            return None
        out(f"== [{order[id(b[0])]}/{n}] {b[0]['name']} (ran next to the others, {time.monotonic() - start:.0f} s in)")
        out(_tail(b[2], 10_000))
        return code

    def stopped(signum, frame):  # the caller stops the check: nothing of it may keep running
        raise SystemExit(128 + signum)

    try:
        old = signal.signal(signal.SIGTERM, stopped)
    except (ValueError, AttributeError):  # not the main thread: the finally below still stops every step
        old = None
    try:
        for s in steps:
            if s.get("background"):
                out(f"== [{order[id(s)]}/{n}] {s['name']} starts next to the others  $ (cd {s['cwd']} && {s['cmd']})")
                log = tempfile.TemporaryFile()
                back.append([s, spawn(s, stdout=log, stderr=subprocess.STDOUT), log, time.monotonic()])
        for s in steps:
            if s.get("background"):
                continue
            out(f"== [{order[id(s)]}/{n}] {s['name']}  $ (cd {s['cwd']} && {s['cmd']})")
            p = spawn(s)
            while p.poll() is None:  # a smoke that turns red stops this step at once, not when it ends
                try:
                    p.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
                for b in list(back):
                    # red at once: a smoke that ended red, or one still running past its limit. A smoke that ended
                    # green waits for its turn below, however long this step takes (groups 2579, 2582 and 2628 of
                    # 22 Nov: a green e2e smoke was called red, exit 0, when a long step passed its 600 s mark)
                    done = b[1].poll()
                    late = done is None and time.monotonic() - b[3] > BACKGROUND_SECS
                    if done is not None and done != 0 or late:
                        _kill(p)
                        return red(b[0], ended(b))
            if p.returncode != 0:
                return red(s, p.returncode)
        while back:
            code = ended(back[0])
            if code is None:
                time.sleep(1)
                continue
            b = back.pop(0)
            b[2].close()
            if code != 0:
                return red(b[0], code)
        out(f"local check: PASS ({n} steps, {time.monotonic() - start:.0f} s)")
        return 0
    finally:
        for p in running:  # an error, a stop or a red: no step of this check outlives it
            _kill(p)
        for b in back:
            try:
                b[2].close()
            except OSError:
                pass
        if old is not None:
            signal.signal(signal.SIGTERM, old)


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
    ap.add_argument("--group", action="store_true", help="the before-merge set of a merge queue group")
    # the merge queue's local check hands a member's owner-approved label over in ORCH_CHECK_LABELS (ORCH-1363)
    ap.add_argument(
        "--labels",
        default=os.environ.get("ORCH_CHECK_LABELS", ""),
        help="--group: the pull request labels, comma separated (default: ORCH_CHECK_LABELS)",
    )
    ap.add_argument(
        "--all-tests", action="store_true", help="--group: every not-slow workspace test, not the picked ones"
    )
    a = ap.parse_args(argv)
    if a.group:
        files = changed(a.base)
        only = github_only(files)
        if only and not a.plan:  # first: nothing else is read or run for a group GitHub checks
            print(f"local check: GitHub only: the group changes {', '.join(only[:3])}", flush=True)
            return GITHUB_ONLY_EXIT
        addons = ci_addons((ROOT / ".github/workflows/addons.yml").read_text(encoding="utf-8"))
        steps = group_plan(files, addons, a.base, a.labels, None if a.all_tests else test_texts())
        if a.plan:
            print(json.dumps(steps, indent=1))
            return 0
        return run_group(steps, step_env(dict(os.environ)))
    addons = addons_known()
    if a.rules:
        steps = rules_plan(test_texts())
    else:
        files = changed(a.base)
        steps = plan(files, test_texts(), addons, addon_test_texts(addons), docs_only(files, a.base))
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
