"""For now, merge queue groups skip the click-throughs and the Windows parts (ORCH-1106, owner 20 Nov).

Groups merge without 'addons / dashboard-clickthroughs' and 'workspace / test (windows-latest, n/N)'. Both still run
and count on every push to develop (also one a green group proved, where the other suites are skipped), at night and
on a release pull request into main. The switch back is written at the top of ci.yml.
Plain text over the workflow files (no YAML package), like test_ci_known_red.py.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
JOB = re.compile(r"^  ([a-z0-9-]+):\n", re.MULTILINE)


def jobs(text: str) -> dict[str, str]:
    """{job name: its block} for the jobs of a workflow file (keys indented two spaces under `jobs:`)."""
    body = text[text.index("\njobs:\n") :]
    found = list(JOB.finditer(body))
    return {
        m.group(1): body[m.end() : (found[i + 1].start() if i + 1 < len(found) else len(body))]
        for i, m in enumerate(found)
    }


def line(block: str, key: str) -> str:
    m = re.search(rf"^      {key}: (.+)$|^    {key}: (.+)$", block, re.MULTILINE)
    assert m, f"no {key} in the job"
    return (m.group(1) or m.group(2)).strip()


# A job that also waits for the Mac route keeps running when the route failed (ORCH-1125): its condition is wrapped.
ROUTE_WRAP = "${{ !cancelled() && needs.changes.result == 'success' && ("


def unwrap(cond: str) -> str:
    return cond[len(ROUTE_WRAP) : -len(") }}")] if cond.startswith(ROUTE_WRAP) else cond


CI = (WORKFLOWS / "ci.yml").read_text()
CI_JOBS = jobs(CI)


def test_the_note_at_the_top_says_when_to_switch_back():
    top = CI.split("\non:", 1)[0]
    for word in ("ORCH-1106", "ORCH-555", "ORCH-1050", "20 queue groups in a row", "SWITCH BACK"):
        assert word in top, word


def test_queue_groups_skip_the_click_throughs_and_every_other_place_runs_them():
    addons = CI_JOBS["addons"]
    assert line(addons, "clickthroughs") == "${{ needs.changes.outputs.queue != 'true' }}"
    assert line(addons, "suites") == "${{ needs.changes.outputs.proven != 'true' }}"
    # a push to develop that a green group proved still calls the add-on workflow (for the click-throughs)
    assert unwrap(line(addons, "if")).startswith("needs.changes.outputs.proven == 'true' ||")


def test_the_addon_workflow_honours_both_inputs():
    text = (WORKFLOWS / "addons.yml").read_text()
    assert "clickthroughs:" in text.split("\njobs:", 1)[0]
    for name, block in jobs(text).items():
        want = "inputs.clickthroughs" if name == "dashboard-clickthroughs" else "inputs.suites"
        assert line(block, "if") == want, name


def test_windows_parts_skip_queue_groups_and_run_on_every_develop_push():
    ws = CI_JOBS["workspace"]
    windows = line(ws, "windows")
    assert "!startsWith(github.head_ref, 'orch-queue/')" in windows
    assert "(github.event_name == 'push' && github.ref == 'refs/heads/develop')" in windows
    assert unwrap(line(ws, "if")).startswith("needs.changes.outputs.proven == 'true' ||")
    # on a proven push only the Windows parts run: no Linux, no macOS again
    assert line(ws, "linux") == "${{ needs.changes.outputs.proven != 'true' }}"
    assert "needs.changes.outputs.proven != 'true'" in line(ws, "full")
    plan = (WORKFLOWS / "workspace.yml").read_text()
    assert 'parts = {"ubuntu-latest": 2} if os.environ["LINUX"] == "true" else {}' in plan


def test_both_still_count_for_the_final_check():
    last = list(CI_JOBS.values())[
        -1
    ]  # the roll-up job GitHub requires: green when every called job passed or was skipped
    assert line(last, "if") == "always()"
    needs = line(last, "needs")
    assert "addons" in needs and "workspace" in needs
