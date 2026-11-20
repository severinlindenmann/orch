"""e2e/main.py refuses V3-SIM in a list: it never ends and sorts first (ORCH-1012)."""

import subprocess
import sys
from pathlib import Path

import pytest

E2E = Path(__file__).resolve().parents[2] / "e2e"


def _run(what, tmp_path):
    return subprocess.run(
        [
            sys.executable,
            str(E2E / "main.py"),
            what,
            "--tmp",
            str(tmp_path / "t-x"),
            "--repo",
            str(E2E.parent),
        ],
        capture_output=True,
        text=True,
        cwd=E2E,
        timeout=60,
    )


def test_sim_in_a_list_is_refused_before_anything_runs(tmp_path):
    r = _run("V3-P1,V3-SIM", tmp_path)
    if "ModuleNotFoundError" in r.stderr:
        pytest.skip("e2e harness modules not installed here")
    assert r.returncode == 2
    assert "runs alone" in r.stdout
