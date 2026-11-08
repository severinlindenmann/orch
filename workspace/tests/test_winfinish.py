"""Windows reinstall after orch exits (winfinish.py). The finisher is plain Python and runs anywhere."""

import json
import subprocess
import sys

import pytest

from orch import addons, winfinish
from orch.errors import Refused


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
        "uv_timeout": 30,
        "registry": [str(tmp_path / "addons.json"), '[{"name": "dashboard"}]'],
        "then": [{"argv": [sys.executable, "-c", then_code, "x"], "cwd": str(tmp_path)}],
        "log": str(tmp_path / "finish.log"),
        "done": "dashboard installed and turned on",
        "pending": str(tmp_path / "finish.pending"),
    }


def test_finisher_reinstalls_saves_the_list_and_runs_the_next_step(tmp_path):
    (tmp_path / "finish.pending").write_text("1")
    assert _run_finisher(tmp_path, _job(tmp_path)).returncode == 0
    assert not (tmp_path / "finish.pending").exists()  # the next install may start
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


@pytest.mark.skipif(sys.platform == "win32", reason="the lock is simulated with POSIX folder permissions")
def test_orch_still_running_changes_nothing(tmp_path):
    """The tool folder can not be renamed (orch still runs from it): give up, change nothing."""
    job = _job(tmp_path)
    job["wait"] = 1
    locked = tmp_path / "locked"
    locked.mkdir()
    job["free"] = [str(locked / "tool-env")]
    (locked / "tool-env").mkdir()
    locked.chmod(0o500)  # no rename inside: like Windows while orch runs
    try:
        assert _run_finisher(tmp_path, job).returncode == 1
    finally:
        locked.chmod(0o700)
    assert "did not exit in time" in (tmp_path / "finish.log").read_text()
    assert not (tmp_path / "addons.json").exists()


def test_a_failing_next_step_is_reported(tmp_path):
    job = _job(tmp_path, then_code="import sys; print('no consent'); sys.exit(2)")
    assert _run_finisher(tmp_path, job).returncode == 1
    log = (tmp_path / "finish.log").read_text()
    assert "no consent" in log and "RESULT fail:" in log


def test_a_crash_is_logged_and_clears_the_pending_mark(tmp_path):
    job = _job(tmp_path)
    job["registry"] = [str(tmp_path / "no-such-dir" / "addons.json"), "[]"]  # the write fails
    (tmp_path / "finish.pending").write_text("1")
    assert _run_finisher(tmp_path, job).returncode == 1
    assert "RESULT fail: Traceback" in (tmp_path / "finish.log").read_text()
    assert not (tmp_path / "finish.pending").exists()


def test_a_second_install_waits_for_the_first(proj, monkeypatch, uv_calls):
    """Each job carries the whole add-on list: a second one could undo the first (security review)."""
    monkeypatch.setattr(winfinish, "needed", lambda: True)
    addons.home().mkdir(parents=True, exist_ok=True)
    (addons.home() / "finish.pending").write_text("starting")
    with pytest.raises(Refused, match="still finishing"):
        addons._reinstall([], save=True, then=[], root=proj, done="x")


def test_start_writes_its_files_in_orchs_home_and_marks_pending(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(winfinish, "_popen", lambda argv, **k: calls.append(argv) or 4242)
    monkeypatch.setattr(winfinish.sys, "_base_executable", "/base/python", raising=False)
    log = winfinish.start(tmp_path, ["uv", "tool"], [["update", "--project-only"]], tmp_path, "done")
    assert log == tmp_path / "finish.log"
    assert (tmp_path / "finish.pending").read_text() == "4242"  # the finisher's pid
    assert calls[0][:2] == ["/base/python", "-I"] and calls[0][2] == str(tmp_path / "finish" / "finish.py")
    job = json.loads((tmp_path / "finish" / "job.json").read_text())
    assert job["then"][0]["argv"][1:] == ["-P", "-m", "orch", "update", "--project-only"]


def test_start_refuses_without_an_outside_python(tmp_path, monkeypatch):
    monkeypatch.setattr(winfinish.sys, "prefix", str(tmp_path / "tool-env"))
    monkeypatch.setattr(
        winfinish.sys,
        "_base_executable",
        str(tmp_path / "tool-env" / "Scripts" / "python.exe"),
        raising=False,
    )
    with pytest.raises(RuntimeError):
        winfinish.start(tmp_path, ["uv"], [], tmp_path, "done")


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


def test_a_dead_finisher_does_not_block(tmp_path):
    """It died with the SSH session that started it: its mark must not block the next install."""
    import subprocess as sp

    p = sp.Popen([sys.executable, "-c", "pass"])
    p.wait()
    (tmp_path / "finish.pending").write_text(str(p.pid))
    assert winfinish.pending(tmp_path) is False
    (tmp_path / "finish.pending").write_text(str(__import__("os").getpid()))  # alive
    assert winfinish.pending(tmp_path) is True
    (tmp_path / "finish.pending").write_text("starting")
    assert winfinish.pending(tmp_path) is True


def test_start_falls_back_when_breaking_away_is_not_allowed(tmp_path, monkeypatch):
    seen = []

    def popen(argv, creationflags=0, **kw):
        seen.append(creationflags)
        if creationflags & 0x01000000:
            raise PermissionError("not allowed")
        return 77

    monkeypatch.setattr(winfinish, "_popen", popen)
    monkeypatch.setattr(winfinish.sys, "_base_executable", "/base/python", raising=False)
    winfinish.start(tmp_path, ["uv"], [], tmp_path, "done")
    assert seen[0] & 0x01000000 and not seen[1] & 0x01000000
    assert (tmp_path / "finish.pending").read_text() == "77"


def test_only_one_start_gets_the_mark(tmp_path, monkeypatch):
    """Two orch commands at the same moment: the second one is refused, never a second job."""
    monkeypatch.setattr(winfinish, "_popen", lambda argv, **k: __import__("os").getpid())  # alive
    monkeypatch.setattr(winfinish.sys, "_base_executable", "/base/python", raising=False)
    winfinish.start(tmp_path, ["uv"], [], tmp_path, "done")
    with pytest.raises(winfinish.Busy):
        winfinish.start(tmp_path, ["uv"], [], tmp_path, "done")


def test_a_dead_mark_is_taken_over(tmp_path, monkeypatch):
    import subprocess as sp

    p = sp.Popen([sys.executable, "-c", "pass"])
    p.wait()
    (tmp_path / "finish.pending").write_text(str(p.pid))
    monkeypatch.setattr(winfinish, "_popen", lambda argv, **k: 99)
    monkeypatch.setattr(winfinish.sys, "_base_executable", "/base/python", raising=False)
    winfinish.start(tmp_path, ["uv"], [], tmp_path, "done")
    assert (tmp_path / "finish.pending").read_text() == "99"


def test_any_start_failure_frees_the_mark(tmp_path, monkeypatch):
    def boom(argv, **kw):
        raise ValueError("bad argument")

    monkeypatch.setattr(winfinish, "_popen", boom)
    monkeypatch.setattr(winfinish.sys, "_base_executable", "/base/python", raising=False)
    with pytest.raises(RuntimeError):
        winfinish.start(tmp_path, ["uv"], [], tmp_path, "done")
    assert not (tmp_path / "finish.pending").exists()
