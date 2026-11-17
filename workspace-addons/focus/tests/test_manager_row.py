"""ORCH-147: the always-on Manager in Focus: its own start-page row, never in the helper list."""

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from orch_focus import actions, livedata, server


def test_manager_start_argv():
    assert actions.build_argv("manager.start", {}) == ["manager", "start", "--by", "focus", "--json"]
    assert actions.build_argv("manager.start", {"fresh": True}) == [
        "manager", "start", "--fresh", "--by", "focus", "--json",
    ]  # fmt: skip
    assert not actions.needs_session("manager.start")  # like run.start: a start is the page's
    with pytest.raises(actions.BadRequest):
        actions.build_argv("manager.start", {"ticket": "t_abcdef"})


def test_the_manager_is_not_in_the_helper_list(tmp_path):
    d = tmp_path / ".orch" / "tickets"
    d.mkdir(parents=True)
    (d / "t_man001.json").write_text(json.dumps({"id": "t_man001", "manager": True}))
    r = tmp_path / ".orch" / "run" / "tickets"
    r.mkdir(parents=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (r / "t_man001.json").write_text(
        json.dumps({"ticket": "t_man001", "run": "r_1", "pid": 1, "renewed_at": now})
    )
    assert [x["ticket"] for x in livedata.records(tmp_path)] == []


@pytest.mark.parametrize(
    "code,out,want",
    [
        (
            0,
            '{"ticket": "t_man001", "running": true, "attach": "x"}',
            {"ticket": "t_man001", "running": True},
        ),
        (0, '{"ticket": null, "running": false}', {"ticket": None, "running": False}),
        (0, '{"ticket": "../evil", "running": true}', {"ticket": None, "running": True}),
        (2, "", None),  # an older orch without the Manager: no row
    ],
)
def test_tracker_manager(tmp_path, monkeypatch, code, out, want):
    monkeypatch.setattr(actions, "orch", lambda root, orch_bin, argv, timeout=60: (code, out, ""))
    tr = server.Tracker.__new__(server.Tracker)
    tr.root, tr.orch_bin = tmp_path, "orch"
    assert tr.manager() == want
