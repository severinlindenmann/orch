"""Every CI job has a time limit (no 6-hour GitHub default): planted samples and the real workflow files."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import check_ci_timeouts as cct  # noqa: E402

SAMPLE = """\
name: x
on:
  pull_request:
  push:
jobs:
  limited:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - run: echo hi
  unlimited:  # no limit
    runs-on: ubuntu-latest
    steps:
      - name: a step limit is not a job limit
        timeout-minutes: 3
        run: echo hi
  caller:
    uses: ./.github/workflows/other.yml
  matrix:
    strategy:
      matrix:
        os: [a, b]
    runs-on: ${{ matrix.os }}
    steps:
      - run: echo hi
    timeout-minutes: 9
concurrency:
  group: x
"""


def test_finds_jobs_without_a_limit():
    assert cct.jobs_without_limit(SAMPLE) == ["unlimited"]


def test_last_job_without_a_limit_is_found():
    assert cct.jobs_without_limit("on: push\njobs:\n  a:\n    runs-on: x\n    steps: []\n") == ["a"]


def test_trigger_keys_are_not_jobs():
    assert cct.jobs_without_limit("on:\n  push:\n  schedule:\njobs:\n  a:\n    timeout-minutes: 1\n") == []


def test_every_real_ci_job_has_a_limit(capsys):
    assert cct.main(["x", str(ROOT / ".github" / "workflows")]) == 0, capsys.readouterr().out
