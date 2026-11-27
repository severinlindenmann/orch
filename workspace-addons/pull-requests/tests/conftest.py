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


from prpage_util import prws  # noqa: F401  (the Pull requests page tests' workspace)


@pytest.fixture(autouse=True)
def no_outside_env(monkeypatch):
    """The tests run the same inside an agent tool (Claude Code, Copilot ...): core counts a `human:` actor as
    that agent when the tool's variables are set. The git config a tool injects (GIT_CONFIG_*, e.g.
    safe.bareRepository=explicit) is not the test's either."""
    import os

    from orch import adapters

    for k in set(os.environ) - set(adapters.human_environ(os.environ)):
        monkeypatch.delenv(k)
    for k in [k for k in os.environ if k.startswith("GIT_CONFIG_")]:
        monkeypatch.delenv(k)


@pytest.fixture(autouse=True)
def woke(monkeypatch):
    """No test ever starts a real helper: the queue's wake only records (ticket, text)."""
    from orch_pull_requests import runner

    seen: list = []
    monkeypatch.setattr(runner, "_wake", lambda root, tid, text: (seen.append((tid, text)), "woken")[1])
    return seen
