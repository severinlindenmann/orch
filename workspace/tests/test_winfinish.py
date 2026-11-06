"""Windows reinstall after orch exits (winfinish.py). The finisher is plain Python and runs anywhere."""

import json
import subprocess
import sys

import pytest

from orch import addons, winfinish


@pytest.fixture
def uv_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(addons, "run_uv", lambda args: calls.append(args))
    return calls


def _run_finisher(tmp_path, job):
    (tmp_path / "finish.py").write_text(winfinish.FINISHER, encoding="utf-8")
    (tmp_path / "job.json").write_text(json.dumps(job), encoding="utf-8")
    return subprocess.run([sys.executable, "-I", str(tmp_path / "finish.py"), str(tmp_path / "job.json")])


def _job(tmp_path, uv_code="print('uv ok')", then_code="print('then ok')"):
    env = tmp_path / "tool-env"
    env.mkdir()
    return {
        "uv": [sys.executable, "-c", uv_code],
        "free": [str(env)],
        "wait": 5,
        "registry": [str(tmp_path / "addons.json"), '[{"name": "dashboard"}]'],
        "then": [{"argv": [sys.executable, "-c", then_code, "x"], "cwd": str(tmp_path)}],
        "log": str(tmp_path / "finish.log"),
        "done": "dashboard installed and turned on",
    }


def test_finisher_reinstalls_saves_the_list_and_runs_the_next_step(tmp_path):
    assert _run_finisher(tmp_path, _job(tmp_path)).returncode == 0
    log = (tmp_path / "finish.log").read_text()
    assert "then ok" in log and log.rstrip().endswith("RESULT ok: dashboard installed and turned on")
    assert json.loads((tmp_path / "addons.json").read_text()) == [{"name": "dashboard"}]
    assert (tmp_path / "tool-env").is_dir()  # the free-check renamed it back


def test_a_failed_reinstall_changes_nothing(tmp_path):
    job = _job(tmp_path, uv_code="import sys; print('boom', file=sys.stderr); sys.exit(3)")
    assert _run_finisher(tmp_path, job).returncode == 1
    log = (tmp_path / "finish.log").read_text()
    assert "boom" in log and "RESULT fail" in log
    assert not (tmp_path / "addons.json").exists()  # the add-on list stays as it was


def test_windows_hands_the_reinstall_to_the_finisher(proj, monkeypatch, uv_calls, capsys):
    """On Windows orch must not run uv on its own folder (it broke itself: 'No module named orch')."""
    started = []
    monkeypatch.setattr(winfinish, "needed", lambda: True)
    monkeypatch.setattr(addons, "_which_uv", lambda: "uv.exe")
    monkeypatch.setattr(
        winfinish,
        "start",
        lambda home, uv, then, cwd, done, reg=None: started.append((uv, then, reg)) or home,
    )
    reexecs = []
    monkeypatch.setattr(addons, "reexec", lambda a: reexecs.append(a))
    entries = [{"name": "dashboard", "source": "built-in", "version": "0.0.0"}]
    assert (
        addons._reinstall(entries, save=True, then=[["update", "--project-only"]], root=proj, done="x")
        is False
    )
    assert not uv_calls and not reexecs and not addons.registry_path().exists()
    (uv, then, reg) = started[0]
    assert uv[0] == "uv.exe" and uv[1:4] == ["tool", "install", "--reinstall"]
    assert then == [["update", "--project-only"]]
    assert json.loads(reg[1])[0]["name"] == "dashboard"
    assert "finishes in the background" in capsys.readouterr().out


def test_other_systems_reinstall_at_once(proj, monkeypatch, uv_calls):
    monkeypatch.setattr(winfinish, "needed", lambda: False)
    reexecs = []
    monkeypatch.setattr(addons, "reexec", lambda a: reexecs.append(a))
    entries = [{"name": "dashboard", "source": "built-in", "version": "0.0.0"}]
    assert addons._reinstall(entries, save=True, then=[["update", "--project-only"]], root=proj, done="x")
    assert uv_calls and reexecs == [["update", "--project-only"]]
    assert addons.registry() == entries
