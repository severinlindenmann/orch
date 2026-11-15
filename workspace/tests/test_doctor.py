import json
import shutil

import pytest

from orch import adapters, addons, cli_leave, diag


@pytest.fixture(autouse=True)
def tools_found(monkeypatch):
    diag._dropped.clear()  # a process-wide counter other tests may have raised
    monkeypatch.setattr(
        adapters, "detect", lambda: [{"name": "claude", "label": "Claude", "found": True, "version": None}]
    )
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: f"/usr/bin/{n}")
    monkeypatch.setattr(addons, "_which_uv", lambda: "/usr/bin/uv")


def test_fresh_init_reports_nothing_wrong(proj, run):
    assert run("init")[0] == 0
    code, out, _ = run("doctor")
    assert code == 0 and "Nothing wrong." in out.splitlines()[-2:-1], out


def test_a_missing_skill_link_is_one_problem_with_a_next_step(proj, run):
    assert run("init")[0] == 0
    (proj / ".agents/skills/orch").unlink()
    code, out, _ = run("doctor")
    assert code == 0 and "1 thing to fix." in out
    assert "not linked" in out and "Run: orch init" in out


def test_doctor_in_a_folder_without_orch(proj, run):
    code, out, _ = run("doctor")
    assert code == 0 and "not set up" in out and "Run: orch init" in out


def test_doctor_json(proj, run):
    assert run("init")[0] == 0
    code, out, _ = run("doctor", "--json")
    d = json.loads(out)
    assert code == 0 and d["ok"] and d["problems"] == 0, [r for r in d["checks"] if not r["ok"]]
    assert cli_leave.TOOL
