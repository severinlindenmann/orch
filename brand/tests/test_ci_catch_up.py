"""Catch-up for scheduled runs GitHub dropped (#2657, scripts/ci_catch_up.py)."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("ci_catch_up", ROOT / "scripts" / "ci_catch_up.py")
cu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cu)

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
EV = ("schedule", "workflow_dispatch")


def run(at, event="schedule", concl="success", branch="develop"):
    return {"created_at": at, "event": event, "conclusion": concl, "head_branch": branch}


def test_on_time_run_starts_nothing():
    assert cu.overdue([run("2026-11-24T11:00:00Z")], EV, 2, NOW)[0] is False


def test_dropped_slots_start_a_run():
    assert cu.overdue([run("2026-11-24T09:17:00Z")], EV, 2, NOW)[0] is True
    assert cu.overdue([], EV, 2, NOW)[0] is True


def test_cancelled_push_and_other_branch_runs_do_not_count():
    runs = [
        run("2026-11-24T11:30:00Z", concl="cancelled"),
        run("2026-11-24T11:30:00Z", event="push"),
        run("2026-11-24T11:30:00Z", branch="feat/x"),
        run("2026-11-23T08:00:00Z"),
    ]
    assert cu.overdue(runs, EV, 26, NOW)[0] is True  # only the 28 h old nightly counts


def test_a_run_still_going_counts():
    assert cu.overdue([run("2026-11-24T10:00:00Z", concl=None)], EV, 26, NOW)[0] is False


def test_github_not_answering_never_fails(monkeypatch, capsys):
    monkeypatch.setattr(cu, "runs_of", lambda repo, wf: None)
    assert cu.main(["--repo", "o/r"], now=NOW) == 0
    assert "did not answer" in capsys.readouterr().out


def test_dispatches_with_the_catch_up_input(monkeypatch):
    calls = []
    monkeypatch.setattr(cu, "runs_of", lambda repo, wf: [])
    monkeypatch.setattr(cu, "gh", lambda *a: calls.append(a) or type("R", (), {"returncode": 0, "stderr": ""})())
    cu.main(["--repo", "o/r"], now=NOW)
    assert ("workflow", "run", "e2e.yml", "--repo", "o/r", "--ref", "develop", "-f", "catch_up=true") in calls
    assert ("workflow", "run", "live-check.yml", "--repo", "o/r", "--ref", "develop") in calls


def test_wired_into_ci_and_e2e():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    e2e = (ROOT / ".github/workflows/e2e.yml").read_text()
    assert "scripts/ci_catch_up.py" in ci and "actions: write" in ci
    assert "catch_up:" in e2e and "(catch-up)" in e2e
