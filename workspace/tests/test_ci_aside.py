"""Tests a person set aside (ORCH-455): the pytest plugin .github/pytest/orch_aside.py runs them as an
expected failure (still run, shown) when the repository variable ORCH_ASIDE lists them, and every workflow
that runs pytest hands that variable and the plugin to it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO / ".github" / "pytest"
WORKFLOWS = ("workspace.yml", "addons.yml", "clock.yml")

BROKEN = "def test_broken():\n    assert 21 == 22\n\n\ndef test_mine():\n    assert True\n"


def run(tmp_path: Path, aside, body: str = BROKEN) -> subprocess.CompletedProcess:
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / "test_clock.py").write_text(body, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "ORCH_ASIDE"))}
    env.update(PYTEST_PLUGINS="orch_aside", PYTHONPATH=str(PLUGIN_DIR))
    if aside is not None:
        env["ORCH_ASIDE"] = aside if isinstance(aside, str) else json.dumps(aside)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rxX", "-p", "no:cacheprovider", "tests"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
    )  # fmt: skip


ROW = {
    "check": "ci / workspace / ubuntu",
    "test": "tests/test_clock.py::test_broken",
    "issue": "https://x/issues/9",
}


def test_a_set_aside_test_still_runs_and_shows_but_the_run_is_not_red(tmp_path):
    assert run(tmp_path, None).returncode == 1  # no variable: red as always
    got = run(tmp_path, [ROW])
    assert got.returncode == 0, got.stdout + got.stderr
    assert "1 xfailed" in got.stdout and "set aside until https://x/issues/9" in got.stdout
    assert "set aside (ORCH-455" in got.stdout


def test_a_fixed_set_aside_test_shows_as_passing_and_other_failures_stay_red(tmp_path):
    fixed = BROKEN.replace("21 == 22", "22 == 22")
    got = run(tmp_path, [ROW], fixed)
    assert got.returncode == 0 and "1 xpassed" in got.stdout
    other = BROKEN.replace("assert True", "assert False")
    assert run(tmp_path, [ROW], other).returncode == 1


def test_several_tests_and_bad_values(tmp_path):
    two = dict(ROW, test="tests/test_clock.py::test_broken + tests/test_clock.py::test_mine")
    assert "1 xfailed, 1 xpassed" in run(tmp_path, [two]).stdout
    for bad in ("not json", "{}", "[1, null]", json.dumps([dict(ROW, test="Error: port N refused")])):
        assert run(tmp_path, bad).returncode == 1  # nothing set aside: red as always


def test_every_workflow_that_runs_pytest_hands_over_the_variable_and_the_plugin():
    for name in WORKFLOWS:
        text = (REPO / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "ORCH_ASIDE: ${{ vars.ORCH_ASIDE }}" in text, name
        assert "PYTEST_PLUGINS: orch_aside" in text, name
        assert "PYTHONPATH: ${{ github.workspace }}/.github/pytest" in text, name
