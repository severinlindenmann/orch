"""The session guard in conftest fails the whole run when anything under the (real) orch home changes."""

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _inner(fake_home: Path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "ORCH_TEST_SESSION"))}
    env["ORCH_TEST_GUARD_HOME"] = str(fake_home)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(HERE / "guard_probe.py")],
        env=env, cwd=HERE.parent, capture_output=True, text=True, timeout=120,
    )  # fmt: skip


def test_guard_fails_the_session_on_a_change(tmp_path):
    (tmp_path / ".orch-tool").mkdir()
    r = _inner(tmp_path)
    assert (tmp_path / ".orch-tool" / "keys" / "x" / "delivered.json").exists()  # the probe did write
    assert "1 passed" in r.stdout  # the test itself passed ...
    assert r.returncode != 0, r.stdout  # ... and the session still failed
    assert "REAL ~/.orch-tool CHANGED" in r.stderr + r.stdout
