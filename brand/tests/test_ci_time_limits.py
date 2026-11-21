"""Workspace test parts stay away from their time limit (ORCH-1050).

Windows part 12 of 16 was killed at exactly 15m0s with all its tests passed (releases 35 and 38): the hash
split had put most of the slow bring-back tests into it. Windows now splits by measured time, its limit has
room, and every part warns once it passes 70 percent of its limit. Plain text over the workflow file, like
test_ci_known_red.py.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEXT = (ROOT / ".github" / "workflows" / "workspace.yml").read_text()
TEST_JOB = TEXT.split("\n  test:\n", 1)[1].split("\n  windows-standard-user:", 1)[0]


def test_the_limit_of_every_part_comes_from_the_plan():
    assert "\n    timeout-minutes: ${{ matrix.limit }}\n" in TEST_JOB
    assert '"limit": LIMIT.get(o, 15)' in TEXT
    assert re.search(r'LIMIT = \{"windows-latest": 20\}', TEXT)


def test_windows_is_split_by_measured_time_and_keeps_its_times():
    step = next(s for s in TEST_JOB.split("\n      - ") if s.startswith("id: tests-windows"))
    assert "--part-times tests/ci_times_windows.json" in step and "--times-out" in step
    assert "name: ci-times-windows-${{ matrix.part }}" in TEST_JOB
    data = json.loads((ROOT / "workspace" / "tests" / "ci_times_windows.json").read_text())
    assert data["tests"] and data["default_s"] > 0


def test_every_part_warns_past_70_percent_of_its_limit_and_never_fails_for_it():
    step = next(s for s in TEST_JOB.split("\n      - ") if s.startswith("name: Time used"))
    assert "if: always()" in step and "continue-on-error: true" in step
    assert "-gt 70 ]" in step and "::warning title=Near the time limit::" in step
    assert "LIMIT_MIN: ${{ matrix.limit }}" in step
    first = TEST_JOB.split("\n    steps:\n", 1)[1].split("\n      - ")[0]
    assert "PART_START=" in first  # counted from the very first step
