import sys
from pathlib import Path

# No test may touch the real ~/.orch-tool (shared helper).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _orch_test_guard import check_real_home, isolated_orch_home  # noqa: F401

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "workspace" / "src"))  # the core (orch), found by path like the other add-ons


def pytest_sessionfinish(session, exitstatus):
    check_real_home(session)
