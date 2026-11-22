import json
import os
import sys
from pathlib import Path

import pytest

# No test may touch the real ~/.orch-tool (shared helper).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _orch_test_guard import check_real_home, isolated_orch_home  # noqa: F401

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))


def pytest_sessionfinish(session, exitstatus):
    check_real_home(session)


def browser_ready() -> bool:
    """The pinned headless browser is downloaded (CI: playwright install; here: PLAYWRIGHT_BROWSERS_PATH)."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists() or _shell_exists()
    except Exception:  # noqa: BLE001
        return False


def _shell_exists() -> bool:
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    return bool(base) and any(Path(base).glob("chromium_headless_shell-*"))


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    (root / ".orch" / "tickets").mkdir(parents=True)
    (root / ".orch" / "tickets" / "t_abc123.json").write_text(
        json.dumps({"id": "t_abc123", "key": "DM1-12"}), encoding="utf-8"
    )
    monkeypatch.setenv("ORCH_ROOT", str(root))
    for k in ("ORCH_RUN", "ORCH_AGENT", "ORCH_TICKET"):
        monkeypatch.delenv(k, raising=False)
    return root
