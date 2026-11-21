"""The session guard in conftest fails the whole run when anything under the (real) orch home changes."""

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _inner(fake_home: Path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "ORCH_TEST_SESSION"))}
    env["ORCH_TEST_GUARD_HOME"] = str(fake_home)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(HERE / "guard_probe.py")],
        env=env, cwd=HERE.parent, capture_output=True, text=True, timeout=120,
    )  # fmt: skip


def test_guard_fails_the_session_on_a_change(tmp_path):
    (tmp_path / ".orch-tool").mkdir()
    r = _inner(tmp_path)
    assert (tmp_path / ".orch-tool" / "keys" / "x" / "delivered.json").exists()  # the probe did write
    assert "1 passed" in r.stdout  # the test itself passed ...
    assert r.returncode != 0, r.stdout  # ... and the session still failed
    assert "REAL ~/.orch-tool CHANGED" in r.stderr + r.stdout


def test_trace_ownership_is_by_pid_only(tmp_path, monkeypatch):
    import conftest

    reg = tmp_path / "pids"
    reg.write_text("111\n222\n")
    monkeypatch.setenv("ORCH_TEST_SESSION_PIDS", str(reg))
    pytest_cwd = "/private/var/T/pytest-of-someone/pytest-1/test_x0"
    assert conftest._ours({"pid": 111, "ppid": 1, "cwd": "/x"})
    assert conftest._ours({"pid": 9, "ppid": 222, "cwd": "/x"})
    assert not conftest._ours({"pid": 9, "ppid": 8, "cwd": pytest_cwd})  # a parallel session's line
    monkeypatch.delenv("ORCH_TEST_SESSION_PIDS")
    assert not conftest._ours({"pid": 111, "ppid": 1, "cwd": pytest_cwd})


def test_override_only_adds_a_location(tmp_path, monkeypatch):
    import conftest

    real = tmp_path / "realacct"
    extra = tmp_path / "extra"
    monkeypatch.setattr(conftest, "_REAL_HOME_FN", lambda: real)
    monkeypatch.delenv("ORCH_TEST_GUARD_HOME", raising=False)
    assert conftest._guard_bases() == [real / ".orch-tool"]
    monkeypatch.setenv("ORCH_TEST_GUARD_HOME", str(extra))  # a stray override
    assert conftest._guard_bases() == [real / ".orch-tool", extra / ".orch-tool"]
    (real / ".orch-tool").mkdir(parents=True)
    (real / ".orch-tool" / "f").write_text("a")
    files, _ = conftest._snapshot_real_tool_home()
    assert str(real / ".orch-tool" / "f") in files  # the real home is still watched


def test_guard_only_watches_a_throwaway_home_inside_the_local_check(tmp_path, monkeypatch):
    """ORCH-1180: the local check runs with a throwaway home under ~/.orch-test while the production orch
    keeps writing the real home; ORCH_TEST_GUARD_ONLY moves the guard there, only with ORCH_HOME_STRICT=1."""
    import conftest

    real = tmp_path / "realacct"
    throwaway = real / ".orch-test" / "commit-ab12" / "home"
    throwaway.mkdir(parents=True)
    monkeypatch.setattr(conftest, "_REAL_HOME_FN", lambda: real)
    monkeypatch.delenv("ORCH_TEST_GUARD_HOME", raising=False)
    monkeypatch.setenv("ORCH_HOME_STRICT", "1")
    monkeypatch.setenv("ORCH_TEST_GUARD_ONLY", str(throwaway))
    assert conftest._guard_bases() == [throwaway.resolve() / ".orch-tool"]
    monkeypatch.setenv("ORCH_HOME_STRICT", "0")  # not strict: the real home stays watched
    assert conftest._guard_bases() == [real / ".orch-tool"]


def test_guard_only_refuses_a_folder_outside_orch_test(tmp_path, monkeypatch):
    import conftest

    real = tmp_path / "realacct"
    (real / ".orch-test").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(conftest, "_REAL_HOME_FN", lambda: real)
    monkeypatch.setenv("ORCH_HOME_STRICT", "1")
    top = real / ".orch-test"
    for bad in (elsewhere, top, top / "missing", top / ".." / ".."):
        monkeypatch.setenv("ORCH_TEST_GUARD_ONLY", str(bad))
        assert conftest.guard_only_home(real) == real, bad
