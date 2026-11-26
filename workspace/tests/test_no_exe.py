"""ORCH-2138: orch runs on plain Python. On Windows the orch launcher (orch.exe) never starts orch, and
with no orch on the PATH add-on views, services and needs still start and reach the core."""

import json
import os
import subprocess
import sys

import pytest
from test_addons import install, make_addon, uv_calls  # noqa: F401  (fixture)

from orch import addons, cli_leave, procs, runs, services
from orch import needs as needs_mod

WIN_EXE = r"C:\Users\Anna Müller\.local\bin\orch.exe"


@pytest.fixture
def windows(monkeypatch):
    """os.name as on Windows, only for the code under test (string work, no Path)."""
    with monkeypatch.context() as m:
        m.setattr(procs.os, "name", "nt")
        yield m


def _no_exe(argv):
    """The program started is a Python, never the orch launcher, and no word names orch.exe."""
    prog = str(argv[0]).replace("\\", "/").rsplit("/", 1)[-1].lower()
    return prog not in ("orch", "orch.exe") and not any(str(a).lower().endswith("orch.exe") for a in argv)


@pytest.mark.parametrize("orch_bin", [WIN_EXE, "C:/tools/orch.EXE", "orch", "orch.exe", "", "orch:self"])
def test_windows_never_starts_the_launcher(windows, monkeypatch, orch_bin):
    monkeypatch.setenv("ORCH_BIN", orch_bin)
    for argv in (procs.orch_cmd(), procs.orch_cmd(orch_bin or None)):
        assert argv == procs.orch_python_argv() and _no_exe(argv)
        assert argv[0] == sys.executable and argv[-2:] == ["-m", "orch"]


def test_windows_keeps_a_tests_fake(windows, monkeypatch):
    monkeypatch.setenv("ORCH_BIN", r"C:\fakes\orch_fake.cmd")
    assert procs.orch_cmd() == [r"C:\fakes\orch_fake.cmd"]


def test_no_orch_on_the_path_is_this_python(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    monkeypatch.delenv("ORCH_BIN", raising=False)
    assert procs.orch_cmd() == procs.orch_python_argv()
    monkeypatch.setenv("ORCH_BIN", "orch")  # what the core passes when it found no orch either
    assert procs.orch_cmd() == procs.orch_python_argv()
    monkeypatch.setenv("ORCH_BIN", "/fake/orch")
    assert procs.orch_cmd() == ["/fake/orch"]


def test_launcher_problem(windows, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    assert procs.launcher_problem() == "missing"
    monkeypatch.setattr("shutil.which", lambda *a, **k: WIN_EXE)

    def blocked(*a, **k):
        raise OSError(1260, "This program is blocked by group policy")

    monkeypatch.setattr(procs, "_run", blocked)
    assert procs.launcher_problem() == "blocked"
    monkeypatch.setattr(procs, "_run", lambda *a, **k: subprocess.CompletedProcess(a, 0))
    assert procs.launcher_problem() is None
    windows.setattr(procs.os, "name", "posix")
    assert procs.launcher_problem() is None


@pytest.mark.parametrize("problem", ["blocked", "missing"])
def test_doctor_says_orch_still_works_through_python(monkeypatch, problem):
    monkeypatch.setattr(procs, "launcher_problem", lambda: problem)
    row = cli_leave._launcher_row()
    assert not row["ok"] and "still works through Python" in row["fact"]
    assert ("blocked" in row["fact"]) == (problem == "blocked")
    assert procs.python_command_line() in row["next"] and row["next"].count(".") <= 2


def test_doctor_row_unchanged_when_the_launcher_works(monkeypatch):
    monkeypatch.setattr(procs, "launcher_problem", lambda: None)
    monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/bin/orch")
    assert cli_leave._launcher_row()["fact"] == "orch is on your PATH."


def test_helper_prompt_names_the_python_form(monkeypatch):
    monkeypatch.setattr(runs, "_LAUNCHER", ["blocked"])
    with monkeypatch.context() as m:
        m.setattr(runs.os, "name", "nt")
        (line,) = runs._launcher_plan()
    assert procs.python_command_line() in line and "orch.exe" in line
    monkeypatch.setattr(runs, "_LAUNCHER", [None])
    with monkeypatch.context() as m:
        m.setattr(runs.os, "name", "nt")
        assert runs._launcher_plan() == []
    assert runs._launcher_plan() == []  # not Windows


# ---- end to end: no orch anywhere on the PATH ---------------------------------------------------------

CALLS_ORCH = """\
import json, os, subprocess, sys
from pathlib import Path
from orch import procs
root = Path(os.environ["ORCH_ROOT"])
cmd = [*procs.orch_cmd(), "ticket", "list", "--json"]
r = subprocess.run(cmd, capture_output=True, text=True)
ok = r.returncode == 0 and isinstance(json.loads(r.stdout or "null"), list)
sub = sys.argv[1] if len(sys.argv) > 1 else ""
(root / f"reached-{sub}.json").write_text(json.dumps({"ok": ok, "cmd": cmd, "err": r.stderr[-300:]}))
if sub == "needs":
    print("[]")
elif sub in ("start", "status"):
    print(json.dumps({"running": True, "pid": os.getpid()}))
else:
    print(json.dumps({"ok": ok}))
"""


def test_view_service_and_needs_start_without_orch_on_the_path(proj, run, tmp_path, monkeypatch, uv_calls):  # noqa: F811
    folder = make_addon(tmp_path / "a", bg=True, extra="needs = true")
    (folder / "src/orch_hello/__main__.py").write_text(CALLS_ORCH, encoding="utf-8")
    monkeypatch.syspath_prepend(str(folder / "src"))
    monkeypatch.setenv("PYTHONPATH", str(folder / "src"))
    monkeypatch.setattr(addons, "_entry_points", lambda: {"hello": "orch_hello"})
    assert run("init")[0] == 0
    install(run, folder)
    empty = tmp_path / "no-orch-here"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.delenv("ORCH_BIN", raising=False)
    monkeypatch.setattr(sys, "argv", ["pytest"])  # not started through an orch launcher
    assert addons.orch_bin() == "orch"

    assert run("hello", "view", "--json")[0] == 0  # the add-on's view, through dispatch
    assert services._call(proj, "hello", addons.discover()["hello"], "start")["running"] is True
    pull = needs_mod._Pull(proj, "hello", addons.discover()["hello"])
    pull.run()
    assert pull.rows == []
    for sub in ("view", "start", "needs"):
        got = json.loads((proj / f"reached-{sub}.json").read_text(encoding="utf-8"))
        assert got["ok"], (sub, got["err"])
        assert got["cmd"][:1] == [sys.executable] and _no_exe(got["cmd"]), got["cmd"]
    assert os.environ["PATH"] == str(empty)
