"""The full e2e runs in parts that each fit the job time limit (ORCH-2399).

Release 52: one job with every scenario was cut at 60 minutes with no scenario red (A24 alone took 1325 s). e2e.yml
runs the full set as two jobs, `rest` and `long` (e2e/parts.py); together they are exactly `all`, in the same order.
Plain text over the workflow and the scenario files: the scenarios themselves need the e2e environment.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "e2e"))
import parts  # noqa: E402

WF = (ROOT / ".github" / "workflows" / "e2e.yml").read_text()
IDS = sorted(
    {m for f in (ROOT / "e2e").glob("scenarios_*.py") for m in re.findall(r'^@scenario\("([^"]+)"', f.read_text(), re.M)}
)


def test_the_two_parts_are_exactly_the_full_run():
    assert len(IDS) > 100 and parts.ALONE in IDS
    full = parts.select("all", IDS)
    rest, long = parts.select("rest", IDS), parts.select("long", IDS)
    assert sorted(long) == sorted(parts.LONG)  # every long scenario exists under that name
    assert not set(rest) & set(long) and sorted(rest + long) == sorted(full)
    assert parts.ALONE not in full  # the harness that never ends by itself stays by name only
    assert [s for s in full if s in rest] == rest  # the same run order inside a part
    assert set(parts.PARTS) == {"rest", "long"}


def test_names_groups_and_the_smoke_sets_select_as_before():
    assert parts.select("A24", IDS) == ["A24"]
    assert parts.select("W", IDS) == [s for s in parts.select("all", IDS) if s[0] == "W"]
    assert parts.select("A4,W0,A0", IDS) == ["W0", "A0", "A4"]  # run order: W before A, A0 before A4
    v3 = parts.select("V3", IDS)
    assert v3 and all(s.startswith("V3-") for s in v3) and parts.ALONE not in v3
    assert parts.select("V3-SIM", IDS) == ["V3-SIM"]
    assert parts.select("smoke", IDS, smoke=["W3", "A0"], smoke_offline=["A0"]) == ["W3", "A0"]
    assert parts.select("smoke-offline", IDS, smoke=["W3", "A0"], smoke_offline=["A0"]) == ["A0"]
    assert parts.select("NOPE-1", IDS) == ["NOPE-1"]  # main.py names an unknown scenario


def test_the_workflow_runs_the_full_set_as_two_jobs_and_a_named_scenario_as_one():
    job = WF.split("\n  e2e:\n", 1)[1]
    assert "fail-fast: false" in job
    assert """part: ${{ fromJSON((inputs.scenario || 'all') == 'all' && '["1/2", "2/2"]' || '["1/1"]') }}""" in job
    assert "(matrix.part == '2/2' && 'long' || 'rest')" in job
    assert "(inputs.scenario || 'all') != 'all' && inputs.scenario ||" in job
    assert 'e2e/run.sh "$WHAT" --mode local' in job
    assert "${{ inputs" not in job.split("run: PW_DIR=", 1)[1]  # the input reaches the shell as a variable only
    assert "timeout-minutes: 60" in job


def test_run_sh_builds_the_servers_for_both_parts():
    run = (ROOT / "e2e" / "run.sh").read_text()
    assert "    all|rest|long|A22|" in run


def test_the_release_keeper_reads_a_part_as_the_job_it_belongs_to():
    text = (ROOT / "workspace" / "src" / "orch" / "releasekeeper.py").read_text()
    assert 'PART_ONLY = re.compile(r" \\([0-9]{1,3}/[0-9]{1,3}\\)")' in text  # "e2e" covers "e2e (1/2)"
