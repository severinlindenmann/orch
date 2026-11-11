import contextlib
import os
import subprocess
import sys
import time

import pytest

import orch_entry
from orch import addons, winfinish


def test_paths_agree(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_HOME", str(tmp_path))
    monkeypatch.setattr(orch_entry, "real_home", addons.real_home)
    assert orch_entry.home_candidates() == addons.home_candidates()
    assert orch_entry.marker_path(tmp_path) == winfinish.marker_path(tmp_path)
    # Outside pytest's account-home fixture, verify the duplicated account lookup too.
    r = _entry(
        tmp_path,
        "import orch_entry; from orch import addons; "
        "assert orch_entry.home_candidates() == addons.home_candidates()",
    )
    assert r.returncode == 0, r.stderr


def _entry(tmp_path, code):
    env = dict(os.environ, ORCH_HOME=str(tmp_path))
    return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=10)


def test_live_marker_never_imports_orch(tmp_path):
    orch_entry.marker_path(tmp_path).write_text(str(os.getpid()))
    r = _entry(
        tmp_path,
        "import sys, orch_entry; code = orch_entry.main(); assert 'orch' not in sys.modules; sys.exit(code)",
    )
    assert r.returncode == 3
    assert r.stderr == "orch is still updating, try again in a moment.\n"


@pytest.mark.parametrize(
    "stale",
    ["age", "future", "dead", "absent", "text", "pid1", "invalid", "huge", "long", "fifo", "link", "dir"],
)
def test_stale_marker_runs_cli_and_preserves_argv_and_exit(tmp_path, stale):
    mark = orch_entry.marker_path(tmp_path)
    if stale == "dead":
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        mark.write_text(str(p.pid))
    elif stale in {"age", "future"}:
        mark.write_text(str(os.getpid()))
        os.utime(mark, (time.time() + (900 if stale == "future" else -901),) * 2)
    elif stale in {"text", "pid1", "invalid", "huge", "long"}:
        mark.write_bytes(
            {
                "text": b"starting",
                "pid1": b"1",
                "invalid": b"\xff",
                "huge": b"9" * 63,
                "long": str(os.getpid()).encode() + b" " * 64,
            }[stale]
        )
    elif stale == "fifo":
        if sys.platform == "win32":
            pytest.skip("POSIX FIFO")
        os.mkfifo(mark)
    elif stale == "link":
        target = tmp_path / "owner"
        target.write_text(str(os.getpid()))
        try:
            mark.symlink_to(target)
        except OSError:
            if sys.platform != "win32":
                raise
            pytest.skip("symlinks require Windows privileges")
    elif stale == "dir":
        mark.mkdir()
    r = _entry(
        tmp_path,
        "import sys, types, orch_entry; "
        "cli = types.ModuleType('orch.cli'); "
        "cli.main = lambda: 17 if sys.argv[1:] == ['start'] else 19; "
        "sys.modules['orch.cli'] = cli; sys.argv = ['orch', 'start']; "
        "sys.exit(orch_entry.main())",
    )
    assert r.returncode == 17, r.stderr
    assert not winfinish.updating(tmp_path)


@pytest.mark.parametrize("fail", [False, True])
def test_posix_marker_lifecycle(tmp_path, fail):
    with pytest.raises(ValueError) if fail else contextlib.nullcontext():
        with winfinish.replacing(tmp_path):
            assert orch_entry.updating(tmp_path)
            if fail:
                raise ValueError("boom")
    assert not orch_entry.marker_path(tmp_path).exists()
    assert f"RESULT {'fail' if fail else 'ok'}:" in winfinish.log_path(tmp_path).read_text()
