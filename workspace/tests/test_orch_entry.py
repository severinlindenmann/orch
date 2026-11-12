import contextlib
import os
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

import orch_entry
from orch import addons, winfinish


def test_paths_agree(monkeypatch, tmp_path):
    home = addons.real_home() / "toolhome"
    home.mkdir()
    monkeypatch.setenv("ORCH_HOME", str(home))
    monkeypatch.setattr(orch_entry, "real_home", addons.real_home)
    assert orch_entry.home_candidates() == addons.home_candidates()
    assert orch_entry.marker_path(tmp_path) == winfinish.marker_path(tmp_path)
    # Outside pytest's account-home fixture, verify the duplicated account lookup too.
    r = _entry(
        tmp_path,
        "import orch_entry; from orch import addons; assert orch_entry.real_home() == addons.real_home()",
        fake_home=False,
    )
    assert r.returncode == 0, r.stderr


def _entry(tmp_path, code, *, fake_home=True):
    env = dict(os.environ, ORCH_HOME=str(tmp_path))
    if fake_home:
        code = (
            "import orch_entry; from pathlib import Path; "
            f"orch_entry.real_home = lambda: Path({str(tmp_path.parent)!r}); " + code
        )
    return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=10)


@pytest.mark.parametrize(
    "case", ["normal", "outside", "home", "cwd", ".git", ".orch", ".agents", "world-writable", "symlink"]
)
def test_resolved_home_marker_blocks_entry(monkeypatch, tmp_path, case):
    top = addons.real_home()
    home = top / "tool"
    home.mkdir()
    if case == "outside":
        home = tmp_path
    elif case == "home":
        home = top
    elif case == "cwd":
        monkeypatch.chdir(home)
    elif case.startswith("."):
        (home / case).mkdir()
    elif case == "world-writable":
        if sys.platform == "win32":
            pytest.skip("POSIX permissions")
        home.chmod(0o777)
    elif case == "symlink":
        link = top / "link"
        try:
            link.symlink_to(home, target_is_directory=True)
        except OSError:
            if sys.platform != "win32":
                raise
            pytest.skip("symlinks require Windows privileges")
        home = link
    monkeypatch.setattr(orch_entry, "real_home", lambda: top)
    monkeypatch.setenv("ORCH_HOME", str(home))
    monkeypatch.delenv("ORCH_HOME_STRICT")  # a normal install: the account default is guarded too
    orch_entry.marker_path(home).write_text(str(os.getpid()))
    assert orch_entry.home_candidates() == [home.resolve(), (top / ".orch-tool").resolve()]
    assert orch_entry.main() == 3
    # The default remains guarded even when the override has no marker.
    orch_entry.marker_path(home).unlink()
    default = top / ".orch-tool"
    default.mkdir()
    orch_entry.marker_path(default).write_text(str(os.getpid()))
    assert orch_entry.main() == 3


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX home ownership")
@pytest.mark.parametrize("symlink", [False, True])
def test_foreign_home_owner_runs_normally(monkeypatch, symlink):
    top = addons.real_home()
    home = top / "tool"
    home.mkdir()
    override = home
    if symlink:
        override = top / "link"
        override.symlink_to(home, target_is_directory=True)
    orch_entry.marker_path(home).write_text(str(os.getpid()))
    original = Path.stat

    def foreign_stat(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path == home:
            return types.SimpleNamespace(st_mode=result.st_mode, st_uid=os.getuid() + 1)
        return result

    monkeypatch.setattr(Path, "stat", foreign_stat)
    monkeypatch.setattr(orch_entry, "real_home", lambda: top)
    monkeypatch.setenv("ORCH_HOME", str(override))
    monkeypatch.delenv("ORCH_HOME_STRICT")
    cli = types.ModuleType("orch.cli")
    cli.main = lambda: 17
    monkeypatch.setitem(sys.modules, "orch.cli", cli)
    assert orch_entry.home_candidates() == [(top / ".orch-tool").resolve()]
    assert orch_entry.main() == 17
    # Even with a foreign-owned override, the account default remains guarded.
    default = top / ".orch-tool"
    default.mkdir()
    orch_entry.marker_path(default).write_text(str(os.getpid()))
    assert orch_entry.main() == 3


def _strict_setup(monkeypatch, tmp_path):
    top = tmp_path / "account"
    (top / ".orch-tool").mkdir(parents=True)
    home = tmp_path / "lane"
    home.mkdir()
    monkeypatch.setattr(orch_entry, "real_home", lambda: top)
    monkeypatch.setenv("ORCH_HOME", str(home))
    monkeypatch.setenv("ORCH_HOME_STRICT", "1")
    cli = types.ModuleType("orch.cli")
    cli.main = lambda: 17
    monkeypatch.setitem(sys.modules, "orch.cli", cli)
    return top, home


def test_strict_home_ignores_real_home_marker(monkeypatch, tmp_path):
    """A lane's strict ORCH_HOME is not blocked by an update marker in the account's real ~/.orch-tool."""
    top, home = _strict_setup(monkeypatch, tmp_path)
    orch_entry.marker_path(top / ".orch-tool").write_text(str(os.getpid()))
    assert orch_entry.updating(top / ".orch-tool")  # the marker itself is live
    assert orch_entry.home_candidates() == [home.resolve()]
    assert addons.home_candidates() == [home.resolve()]
    assert orch_entry.main() == 17
    # non-strict: the account default is still a candidate and still blocks
    for off in ("", "0"):
        monkeypatch.setenv("ORCH_HOME_STRICT", off)
        assert orch_entry.home_candidates() == [home.resolve(), (top / ".orch-tool").resolve()]
        assert orch_entry.main() == 3


def test_strict_home_marker_still_blocks(monkeypatch, tmp_path):
    _, home = _strict_setup(monkeypatch, tmp_path)
    orch_entry.marker_path(home).write_text(str(os.getpid()))
    assert orch_entry.main() == 3


def test_strict_bad_home_has_no_candidates(monkeypatch, tmp_path):
    top, _ = _strict_setup(monkeypatch, tmp_path)
    monkeypatch.setenv("ORCH_HOME", str(tmp_path / "missing"))
    orch_entry.marker_path(top / ".orch-tool").write_text(str(os.getpid()))
    assert orch_entry.home_candidates() == []
    assert orch_entry.main() == 17


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX marker ownership")
@pytest.mark.parametrize("stage", ["lstat", "fstat"])
def test_foreign_marker_owner_runs_normally(monkeypatch, tmp_path, stage):
    orch_entry.marker_path(tmp_path).write_text(str(os.getpid()))
    original = Path.lstat if stage == "lstat" else os.fstat

    def foreign_stat(*args, **kwargs):
        result = original(*args, **kwargs)
        fields = list(result)
        fields[4] = os.getuid() + 1
        return os.stat_result(fields)

    monkeypatch.setattr(Path if stage == "lstat" else os, stage, foreign_stat)
    monkeypatch.setattr(orch_entry, "home_candidates", lambda: [tmp_path])
    cli = types.ModuleType("orch.cli")
    cli.main = lambda: 17
    monkeypatch.setitem(sys.modules, "orch.cli", cli)
    assert orch_entry.main() == 17


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
        os.utime(mark, (time.time() + (900 if stale == "future" else -(orch_entry.MAX_AGE + 1)),) * 2)
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
