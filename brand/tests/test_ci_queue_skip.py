"""Queue groups run and count the click-throughs again; the Windows parts stay out of them (ORCH-1107).

ORCH-1106 (owner 20 Nov) let groups merge without 'addons / dashboard-clickthroughs' for a while; ORCH-1107 switched
that back on 22 Nov. A push to develop that a green group proved runs no click-throughs again, only page-smoke
(ORCH-1457). 'workspace / test (windows-latest, n/N)' stays out of groups (PR 1473) and runs after the merge on every
push to develop (our own Windows VM, ORCH-1127, or GitHub's machines), at night and in the release check.
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


def test_the_note_at_the_top_says_groups_run_the_click_throughs_again():
    top = CI.split("\non:", 1)[0]
    for word in ("ORCH-1107", "Queue groups run and count the dashboard click-throughs again", "Windows parts stay out"):
        assert word in top, word
    assert "FOR NOW" not in top and "SWITCH BACK" not in top


def test_queue_groups_run_the_click_throughs_and_a_proven_push_does_not():
    addons = CI_JOBS["addons"]
    # the click-throughs run everywhere the suites run: in queue groups too, never again on a proven push
    assert line(addons, "clickthroughs") == "${{ needs.changes.outputs.proven != 'true' }}"
    assert line(addons, "suites") == "${{ needs.changes.outputs.proven != 'true' }}"
    assert "queue != 'true'" not in addons
    # a push to develop that a green group proved still calls the add-on workflow (for page-smoke, ORCH-1457)
    assert unwrap(line(addons, "if")).startswith("needs.changes.outputs.proven == 'true' ||")


def test_the_addon_workflow_honours_both_inputs():
    text = (WORKFLOWS / "addons.yml").read_text()
    assert "clickthroughs:" in text.split("\njobs:", 1)[0]
    # page-smoke (it runs the Focus click-through) has no condition: it runs in queue groups and on a develop push that
    # a green group proved, so a break there shows red on develop and opens its fix ticket (ORCH-1457)
    # services: its own input, so it also runs after a merge when it goes to orch edge (ORCH-1126)
    special = {"dashboard-clickthroughs": "inputs.clickthroughs", "services": "inputs.services"}
    for name, block in jobs(text).items():
        if name == "page-smoke":
            assert not re.search(r"^    if: ", block, re.MULTILINE), name
            continue
        assert line(block, "if") == special.get(name, "inputs.suites"), name


def test_windows_parts_skip_queue_groups_and_run_on_every_develop_push():
    ws = CI_JOBS["workspace"]
    windows = line(ws, "windows")
    assert "!startsWith(github.head_ref, 'orch-queue/')" in windows
    assert "(github.event_name == 'push' && github.ref == 'refs/heads/develop')" in windows
    # (unless the Windows parts run on our own Windows VM, ORCH-1127, test_winvm_windows.py)
    assert unwrap(line(ws, "if")).startswith("(needs.changes.outputs.proven != 'true' || vars.WINDOWS_RUNNER != 'winvm') && (needs.changes.outputs.proven == 'true' ||")
    # on a proven push only the Windows parts run: no Linux, no macOS again
    assert line(ws, "linux") == "${{ needs.changes.outputs.proven != 'true' }}"
    assert "needs.changes.outputs.proven != 'true'" in line(ws, "full")
    plan = (WORKFLOWS / "workspace.yml").read_text()
    assert 'parts = {"ubuntu-latest": 2} if os.environ["LINUX"] == "true" else {}' in plan


def test_both_still_count_for_the_final_check():
    last = list(CI_JOBS.values())[
        -1
    ]  # the roll-up job GitHub requires: green when every called job passed or was skipped
    cond = line(last, "if")
    # always(), except a queue group the local check already decided (group_check = local, ORCH-1124): the queue
    # posts the roll-up status itself there
    assert cond == "always()" or (
        cond.startswith('"${{ always() && !(')
        and "contains(github.event.pull_request.body, 'orch-group-check: local')" in cond
    ), cond
    needs = line(last, "needs")
    assert "addons" in needs and "workspace" in needs


def test_the_docs_table_says_groups_run_the_click_throughs():
    doc = (ROOT / "docs" / "ci-checks.md").read_text()
    row = next(r for r in doc.splitlines() if r.startswith("| dashboard click-throughs |"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[2] == "required, always", row  # queue group
    assert "proven" in cells[3] and "also when proven" not in cells[3], row  # push to develop
    assert "ORCH-1106, owner 20 Nov): queue groups skip" not in doc


def test_queue_groups_that_touch_orch_run_perf_against_develop_and_the_gate_needs_it():
    """ORCH-1609: the 10,000-ticket check runs in queue groups that touch orch and counts for the final check; there it
    fails only on more than 30% slower than develop (R8.3), never on the owner's absolute limits."""
    perf = CI_JOBS["perf"]
    assert line(perf, "if") == "needs.changes.outputs.queue == 'true' && needs.changes.outputs.perf == 'true'"
    assert line(perf, "uses") == "./.github/workflows/perf.yml"
    assert line(perf, "against_develop") == "true"
    assert "actions: read" in perf
    assert re.search(r"^            perf: \['workspace/\*\*', 'workspace-addons/\*\*'", CI, re.MULTILINE)
    assert "perf" in [n.strip() for n in line(list(CI_JOBS.values())[-1], "needs").strip("[]").split(",")]
    wf = (WORKFLOWS / "perf.yml").read_text()
    assert "against_develop:" in wf.split("\njobs:", 1)[0]
    assert '--against "$AGAINST"' in wf and "--branch develop" in wf
