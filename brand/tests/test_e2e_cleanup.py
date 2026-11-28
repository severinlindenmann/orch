"""The end of an e2e run never turns a passing run red (ORCH-2397).

Run 46073797159 passed all 112 scenarios; then the EXIT trap of e2e/run.sh failed to remove the temporary workspace
("Directory not empty": a writer of the run was still alive) and the run went red. e2e/cleanup.sh ends what is still
alive (with a limit), removes the folders with a short retry and keeps the exit code of the run.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLEANUP = ROOT / "e2e" / "cleanup.sh"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="e2e/run.sh is a POSIX shell script (Linux and macOS)")

# a writer that outlives the run: its own session, deaf to TERM when asked, a new file every few milliseconds
WRITER = """
import os, signal, sys, time
if sys.argv[2] == "deaf":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
os.chdir(sys.argv[1])
n = 0
while True:
    n += 1
    os.makedirs("ws/deep", exist_ok=True)
    open(f"ws/deep/f{n}", "w").write("x")
    time.sleep(0.002)
"""


STARTED: list[int] = []


@pytest.fixture(autouse=True)
def no_writer_outlives_its_test():
    yield
    while STARTED:
        pid = STARTED.pop()
        if not gone(pid):
            os.kill(pid, signal.SIGKILL)


def run_end(tmp_path, code: int, deaf: str = "no", by_cwd: bool = True):
    """A stand-in for run.sh: makes the two folders, starts a writer in the workspace, leaves with `code`."""
    tmp, ohome = tmp_path / "e2e-AbCd", tmp_path / "e2e-home-AbCd"
    tmp.mkdir()
    ohome.mkdir()
    (tmp_path / "writer.py").write_text(WRITER)
    pidfile = tmp_path / "writer.pid"
    where = "." if by_cwd else str(tmp)  # found by its working folder, or by its command line
    script = f"""
set -eu
TMP='{tmp}'; OHOME='{ohome}'
. '{CLEANUP}'
trap e2e_cleanup EXIT
cd "$TMP"
'{sys.executable}' '{tmp_path / "writer.py"}' {where} {deaf} >/dev/null 2>&1 &
echo $! > '{pidfile}'
cd /
sleep 0.5
exit {code}
"""
    t0 = time.monotonic()
    p = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=60)
    STARTED.append(int(pidfile.read_text()))
    return p, tmp, ohome, STARTED[-1], time.monotonic() - t0


def gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    try:  # ended but not yet collected (its parent, the shell, is gone): the kernel still lists it for a moment
        return os.waitpid(pid, os.WNOHANG) != (0, 0)
    except ChildProcessError:
        out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout
        return not out.strip() or out.strip().startswith("Z")


@pytest.mark.parametrize("by_cwd", [True, False])
def test_a_passing_run_with_a_writer_still_alive_stays_green_and_leaves_nothing(tmp_path, by_cwd):
    p, tmp, ohome, pid, _ = run_end(tmp_path, 0, by_cwd=by_cwd)
    assert p.returncode == 0, p.stderr
    assert not tmp.exists() and not ohome.exists()
    assert gone(pid)


def test_a_failed_run_keeps_its_own_exit_code(tmp_path):
    p, tmp, _, pid, _ = run_end(tmp_path, 1)
    assert p.returncode == 1 and not tmp.exists() and gone(pid)


def test_a_writer_that_ignores_the_first_signal_is_ended_within_the_limit(tmp_path):
    p, tmp, ohome, pid, took = run_end(tmp_path, 0, deaf="deaf")
    assert p.returncode == 0, p.stderr
    assert gone(pid) and not tmp.exists() and not ohome.exists()
    assert took < 20  # three rounds of one second, then the removal


def test_a_folder_that_cannot_be_removed_is_one_line_and_never_the_exit_code(tmp_path):
    """Nothing to end, the folder cannot go (its parent is read-only): the run's own result stands."""
    if os.geteuid() == 0:
        pytest.skip("root removes it anyway")
    box = tmp_path / "box"
    tmp, ohome = box / "e2e-AbCd", tmp_path / "e2e-home-AbCd"
    tmp.mkdir(parents=True)
    ohome.mkdir()
    box.chmod(0o500)
    try:
        script = f"set -eu\nTMP='{tmp}'; OHOME='{ohome}'\n. '{CLEANUP}'\ntrap e2e_cleanup EXIT\nexit 0\n"
        p = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=60)
        assert p.returncode == 0
        assert "could not remove" in p.stderr and tmp.exists() and not ohome.exists()
    finally:
        box.chmod(0o700)


def test_run_sh_uses_it_for_exit_and_keeps_the_signal_codes():
    run = (ROOT / "e2e" / "run.sh").read_text()
    assert '. "$HERE/cleanup.sh"' in run and "trap e2e_cleanup EXIT" in run
    assert "trap 'exit 130' INT" in run and "trap 'exit 143' TERM" in run
    assert "rm -rf \"$TMP\" \"$OHOME\"' EXIT" not in run
