"""The shared real-home guard (workspace-addons/_orch_test_guard.py): isolation is on, and a change is noticed."""

import os
from pathlib import Path

import _orch_test_guard as g


def test_every_test_runs_in_a_private_strict_home():
    assert os.environ["ORCH_HOME_STRICT"] == "1"
    assert not Path(os.environ["ORCH_HOME"]).resolve().is_relative_to(g._REAL_TOOL_HOME.resolve())
    assert not Path(os.environ["HOME"]).resolve().is_relative_to(g._real_home().resolve())


def test_guard_sees_created_changed_and_removed_files(tmp_path):
    (tmp_path / "a.json").write_text("1")
    (tmp_path / "b.json").write_text("1")
    before = g.snapshot(tmp_path)
    (tmp_path / "a.json").write_text("2")
    (tmp_path / "b.json").unlink()
    (tmp_path / "c.json").write_text("1")
    assert [x.split(": ")[1] for x in g.diff(before, g.snapshot(tmp_path))] == [
        "changed",
        "removed",
        "created",
    ]
    assert g.diff(before, before) == []
