"""Known red never reports a failed check (ORCH-315).

A job-level `continue-on-error` keeps the run green but still reports the job's check as FAILURE on the pull
request, and the merge queue drops every group with a failed check (18 Nov, after PR 1428: every group was
dropped while Windows was known red). So known red goes on the steps, where the job's check stays green.
Plain text over the workflow files (no YAML package), like check_ci_timeouts.py.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
JOB_LEVEL = re.compile(r"^    continue-on-error:", re.M)  # 4 spaces: a key of a job, not of a step


def job_level_continue_on_error(text: str) -> list[int]:
    return [text.count("\n", 0, m.start()) + 1 for m in JOB_LEVEL.finditer(text)]


def test_the_check_finds_a_job_level_continue_on_error():
    bad = "jobs:\n  test:\n    runs-on: x\n    continue-on-error: ${{ matrix.known_red }}\n    steps:\n"
    good = "jobs:\n  test:\n    steps:\n      - run: a\n        continue-on-error: ${{ matrix.known_red }}\n"
    assert job_level_continue_on_error(bad) == [4]
    assert job_level_continue_on_error(good) == []


def test_no_workflow_has_a_job_level_continue_on_error():
    found = {
        f.name: lines
        for f in sorted(WORKFLOWS.glob("*.yml"))
        if (lines := job_level_continue_on_error(f.read_text()))
    }
    assert not found, f"job-level continue-on-error reports a failed check, put it on the steps: {found}"


def test_every_test_step_of_the_workspace_job_honours_known_red():
    text = (WORKFLOWS / "workspace.yml").read_text()
    steps = re.split(r"\n      - ", text.split("\n  test:\n", 1)[1].split("\n  windows-standard-user:", 1)[0])
    runs = [s for s in steps if "uv run pytest" in s or "orch init" in s or "Junction" in s]
    assert len(runs) == 5, runs  # pytest on three systems, the wheel smoke, the junction check
    for s in runs:
        assert "continue-on-error: ${{ matrix.known_red }}" in s, s.splitlines()[0]
    assert '"known_red": o in KNOWN_RED' in text
