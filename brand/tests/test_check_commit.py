"""scripts/check-commit.sh checks one commit in a fresh copy with a throwaway home (ORCH-1178).

The behaviour is tested by scripts/test-check-commit.sh in a pretend home, shared clone and remote; this runs it
so CI keeps it green.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEST = ROOT / "scripts" / "test-check-commit.sh"


@pytest.mark.skipif(os.name == "nt" or not shutil.which("bash"), reason="needs bash")
def test_check_commit_copy_home_and_cleanup(tmp_path: Path) -> None:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "ORCH_HOME": str(tmp_path / "orch"),
        "ORCH_HOME_STRICT": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    r = subprocess.run(
        ["bash", str(TEST)],
        check=False,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip().endswith("test-check-commit: PASS")
