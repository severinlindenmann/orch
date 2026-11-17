"""Run only as the inner session of test_workspace_guard.py (not collected by the normal run)."""

import json
import os
from pathlib import Path


def test_ticket_lands_in_the_test_folder(proj, run):
    code, out, _ = run("ticket", "new", "Probe", "--json")
    assert code == 0
    assert (proj / ".orch" / "tickets" / f"{json.loads(out)['id']}.json").is_file()
    assert "ORCH_ROOT" not in os.environ


def test_walking_into_the_outer_workspace_fails(proj, run, monkeypatch):
    if not os.environ.get("PROBE_WALK_IN"):
        return
    monkeypatch.chdir(Path(os.environ["PROBE_OUTER"]))
    run("ticket", "new", "Stray", "--json")
