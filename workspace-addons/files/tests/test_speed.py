"""The plan's speed targets on a generated 100,000-file workspace. Writes 100,000 files and takes about two
minutes, so it runs only with ORCH_FILES_PERF=1 (ORCH_FILES_PERF_FILES sets another count)."""

import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ORCH_FILES_PERF") != "1", reason="set ORCH_FILES_PERF=1 to run"
)

sys.path.insert(0, str(Path(__file__).parent))


def test_speed_targets(tmp_path):
    import perf_files

    n = int(os.environ.get("ORCH_FILES_PERF_FILES") or 100_000)
    root = tmp_path / "big"
    root.mkdir()
    got = perf_files.measure(root, perf_files.make(root, n))
    print(got)
    assert got["files"] == n
    assert got["names_p95_ms"] < 50
    assert got["content_p95_ms"] < 150
    assert got["recheck_s"] < 2 and got["recheck_read"] == 0 and got["recheck_changed"] == 0
