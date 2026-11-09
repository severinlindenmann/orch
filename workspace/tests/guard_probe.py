"""Run only as the inner session of test_session_guard.py (not collected by the normal run)."""

import os
from pathlib import Path


def test_writes_into_the_guarded_home():
    base = Path(os.environ["ORCH_TEST_GUARD_HOME"]) / ".orch-tool" / "keys" / "x"
    base.mkdir(parents=True, exist_ok=True)
    (base / "delivered.json").write_text("{}")
