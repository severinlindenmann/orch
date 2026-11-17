import sys
from pathlib import Path

import pytest

# No test may touch the real ~/.orch-tool (shared helper), and the core (orch) is found by path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _orch_test_guard import check_real_home, isolated_orch_home  # noqa: F401

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[2] / "workspace" / "src"))


def pytest_sessionfinish(session, exitstatus):
    check_real_home(session)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    (root / ".orch" / "tickets").mkdir(parents=True)
    monkeypatch.chdir(root)
    for k in ("ORCH_RUN", "ORCH_AGENT"):
        monkeypatch.delenv(k, raising=False)
    return root
