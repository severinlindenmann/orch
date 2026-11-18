"""Known red never reports a failed check (ORCH-315).

A job-level `continue-on-error` keeps the run green but still reports the job's check as FAILURE on the pull
request, and the merge queue drops every group with a failed check (18 Nov, after PR 1428: every group was
dropped while Windows was known red). So known red goes on the steps, where the job's check stays green.
Plain text over the workflow files (no YAML package), like check_ci_timeouts.py.
"""

import datetime as dt
import re
import sys
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


# ORCH-453: every known-red system has an owner and an end date in the written list (docs/ci-checks.md)
sys.path.insert(0, str(ROOT / "scripts"))
import ci_known_red as k  # noqa: E402


def test_known_red_reads_the_workflow_line():
    assert k.known_red('          KNOWN_RED = {"windows-latest"}\n') == {"windows-latest"}
    assert k.known_red("          KNOWN_RED = set()  # Windows is green\n") == set()
    assert k.known_red("          KNOWN_RED = {}\n") == set()


def test_every_known_red_system_has_an_owner_and_an_end_date_in_the_list():
    red, table = k.known_red(), k.rows()
    assert set(table) == red, f"docs/ci-checks.md known-red rows {sorted(table)} != KNOWN_RED {sorted(red)}"
    for system in red:
        assert table[system]["owner"], system
        assert k.DATE.match(table[system]["end date"]), system


def test_a_passed_end_date_or_a_missing_row_is_named():
    row = {"owner": "owner", "end date": "2026-11-30"}
    assert k.problems(dt.date(2026, 11, 30), {"windows-latest"}, {"windows-latest": row}) == []
    late = k.problems(dt.date(2026, 12, 1), {"windows-latest"}, {"windows-latest": row})
    assert len(late) == 1 and "past its end date 2026-11-30" in late[0]
    assert "no row" in k.problems(dt.date(2026, 11, 1), {"macos-latest"}, {})[0]
    assert "not in KNOWN_RED" in k.problems(dt.date(2026, 11, 1), set(), {"windows-latest": row})[0]
    assert "no owner" in k.problems(dt.date(2026, 11, 1), {"w"}, {"w": {"owner": "", "end date": "2026-12-01"}})[0]


def test_the_warning_never_fails_the_job(capsys):
    assert k.main(["--warn"]) == 0
