"""Flaky checks quarantined out of the merge queue (ORCH-2363, owner 27 Nov).

The suites at a fake clock (clock.yml) and the click-throughs on QUARANTINED in the click-through runner leave every
run of ci.yml (so queue groups, pull requests and the final ci check) and run in quarantine.yml instead: nightly on
develop, on every push to a release branch and by hand, never on a pull request. Plain text over the workflow files
(no YAML package), like test_ci_queue_skip.py.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
CI = (WORKFLOWS / "ci.yml").read_text()
QUARANTINE = (WORKFLOWS / "quarantine.yml").read_text()
JOB = re.compile(r"^  ([a-z0-9-]+):\n", re.MULTILINE)


def jobs(text: str) -> dict[str, str]:
    """{job name: its block} for the jobs of a workflow file (as in test_ci_queue_skip.py)."""
    body = text[text.index("\njobs:\n") :]
    found = list(JOB.finditer(body))
    return {
        m.group(1): body[m.end() : (found[i + 1].start() if i + 1 < len(found) else len(body))]
        for i, m in enumerate(found)
    }


def needs_of_last(text: str) -> list[str]:
    last = list(jobs(text).values())[-1]
    return [n.strip() for n in re.search(r"^    needs: \[(.*)\]$", last, re.MULTILINE).group(1).split(",")]


RUNNER = (ROOT / "workspace-addons" / "dashboard" / "clickthrough" / "run.cjs").read_text()


def test_ci_no_longer_calls_the_clock_suites_and_the_final_check_does_not_wait_for_them():
    assert "clock.yml" not in "\n".join(x for x in CI.splitlines() if not x.lstrip().startswith("#"))
    ci_jobs = jobs(CI)
    assert "clock" not in ci_jobs
    assert "clock" not in needs_of_last(CI) and "addons" in needs_of_last(CI)
    assert "outputs.clock" not in CI


def test_quarantine_runs_nightly_on_release_branches_and_by_hand_never_on_a_pull_request():
    on = QUARANTINE.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    assert re.search(r"^  schedule:\n    - cron: ", on, re.MULTILINE)
    assert 'branches: ["release/**"]' in on
    assert "workflow_dispatch:" in on
    assert "pull_request" not in on and "merge_group" not in on
    assert re.search(r"^name: quarantine$", QUARANTINE, re.MULTILINE)


def test_quarantine_runs_the_clock_suites_and_only_the_quarantined_click_throughs():
    q = jobs(QUARANTINE)
    assert "uses: ./.github/workflows/clock.yml" in q["clock"]
    assert "clickthrough/run.cjs --quarantined" in q["clickthroughs"]
    # the queue's click-through job runs the default set, which leaves the quarantined ones out
    click = jobs((WORKFLOWS / "addons.yml").read_text())["dashboard-clickthroughs"]
    assert "--quarantined" not in click and "--only" not in click


def test_the_runner_and_the_release_keeper_know_the_quarantine():
    for name in ("a-board-families.cjs", "f-sync-page.cjs", "q-automation-repeats.cjs"):
        assert f"'{name}': 'ORCH-" in RUNNER, name
    keeper = (ROOT / "workspace" / "src" / "orch" / "releasekeeper.py").read_text()
    assert 'QUARANTINE_WORKFLOW = "quarantine"' in keeper and 'QUARANTINE_FILE = "quarantine.yml"' in keeper


def test_the_docs_say_where_the_quarantined_checks_run():
    doc = (ROOT / "docs" / "ci-checks.md").read_text()
    assert "## Quarantine (ORCH-2363)" in doc
    row = next(r for r in doc.splitlines() if r.startswith("| clock "))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[1] == "" and cells[2] == "", row  # no pull request, no queue group
    assert "quarantine" in row
