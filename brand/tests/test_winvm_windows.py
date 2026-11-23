"""Windows checks on our own Windows VM after the merge (ORCH-1127).

The repository variable WINDOWS_RUNNER=winvm takes the Windows parts of develop pushes and of the nightly run off
GitHub's machines (e2e/winvm/dispatch.py runs them in a fresh winvm clone); unset or any other value brings them
back. Release checks and pull requests keep GitHub's x86-64 Windows run. Plain text over ci.yml, like
test_ci_queue_skip.py, plus the dispatcher's pick order.
"""

import datetime as dt
import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _dispatch():
    spec = importlib.util.spec_from_file_location("winvm_dispatch", ROOT / "e2e" / "winvm" / "dispatch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_variable_moves_only_develop_pushes_and_the_nightly_run():
    windows = re.search(r"^      windows: (.+)$", CI, re.MULTILINE).group(1)
    assert (
        "(vars.WINDOWS_RUNNER != 'winvm' && (github.event_name == 'schedule' || "
        "(github.event_name == 'push' && github.ref == 'refs/heads/develop')))"
    ) in windows
    # the release check (manual run with windows=true) and pull requests that change OS code keep GitHub's run
    assert "(github.event_name == 'workflow_dispatch' && inputs.windows)" in windows
    assert "needs.changes.outputs.oscode == 'true'" in windows
    assert windows.count("WINDOWS_RUNNER") == 1


def test_a_proven_push_with_windows_on_the_vm_runs_no_empty_workspace_job():
    # the whole condition is guarded, so no other branch (workspace files changed, ...) starts an empty matrix
    cond = re.search(r"^  workspace:\n(?:    #.*\n)*    needs: (?:changes|\[changes, route\])\n(?:    #.*\n)*    if: (.+)$", CI,
                     re.MULTILINE).group(1)
    # wrapped so a failed Mac route still runs it (ORCH-1125)
    wrap = "${{ !cancelled() && needs.changes.result == 'success' && ("
    if cond.startswith(wrap):
        cond = cond[len(wrap) : -len(") }}")]
    assert cond.startswith("(needs.changes.outputs.proven != 'true' || vars.WINDOWS_RUNNER != 'winvm') && (")
    assert cond.endswith(")") and cond.count("(") == cond.count(")")


NOW = dt.datetime(2026, 11, 21, 9, 0, tzinfo=dt.timezone.utc)


def test_pick_order_release_then_nightly_then_newest_develop():
    pick = _dispatch().pick
    assert pick("github", ["r"], "d", {}, None, NOW) is None  # the switch back: nothing runs on the VM
    assert pick("winvm", ["r"], "d", {}, None, NOW) == ("r", "release pull request")
    assert pick("winvm", ["r"], "d", {"r": "success"}, None, NOW) == ("d", "nightly")
    assert pick("winvm", [], "d", {}, "2026-11-21", NOW) == ("d", "develop push")
    assert pick("winvm", [], "d", {"d": "failure"}, "2026-11-21", NOW) is None


def test_nightly_waits_for_its_hour_and_runs_once_a_day():
    pick = _dispatch().pick
    early = NOW.replace(hour=0, minute=30)
    assert pick("winvm", [], "d", {"d": "success"}, "2026-11-20", early) is None
    assert pick("winvm", [], "d", {"d": "success"}, "2026-11-20", NOW) == ("d", "nightly")
    assert pick("winvm", [], "d", {"d": "success"}, "2026-11-21", NOW) is None


def test_a_pending_status_counts_as_not_run():
    pick = _dispatch().pick
    assert pick("winvm", ["r"], "d", {"r": "pending", "d": "success"}, "2026-11-21", NOW) == ("r", "release pull request")


def test_the_vm_run_keeps_the_standard_user_install_and_the_junction_check():
    run_sh = (ROOT / "e2e" / "winvm" / "run.sh").read_text(encoding="utf-8")
    assert "standard-user.ps1" in run_sh and "smoke.ps1" in run_sh and "tests.ps1" in run_sh
    assert "junction" in (ROOT / "e2e" / "winvm" / "smoke.ps1").read_text(encoding="utf-8")


def test_only_own_develop_release_pull_requests_reach_the_mac():
    ok = _dispatch().trusted_release
    assert ok({"headRefName": "develop", "isCrossRepository": False, "isDraft": False})
    assert not ok({"headRefName": "develop", "isCrossRepository": True, "isDraft": False})  # a fork's "develop"
    assert not ok({"headRefName": "feature", "isCrossRepository": False, "isDraft": False})
    assert not ok({"headRefName": "develop", "isDraft": False})  # unknown = not trusted


def test_the_host_scripts_never_come_from_the_tested_commit():
    src = (ROOT / "e2e" / "winvm" / "dispatch.py").read_text(encoding="utf-8")
    assert "tarfile" not in src and '"archive", "--format=tar"' not in src
    assert 'HERE / "run.sh"' in src and "TOKEN_VARS" in src


FAKE_WINVM = r"""#!/usr/bin/env bash
# Fake winvm: every call is logged; the first two waits lose the ssh connection (255), the third finds the job done.
echo "$*" >> "$HOME/calls"
case $1 in
  ls) exit 0 ;;
  run) case " $* " in *" --detach "*) echo "job j42 started" ;; esac; exit 0 ;;
  wait) n=$(cat "$HOME/waits" 2>/dev/null || echo 0); n=$((n + 1)); echo $n > "$HOME/waits"
        if [ $n -le 2 ]; then echo "Connection timed out during banner exchange" >&2; exit 255; fi
        echo "42 passed"; exit 0 ;;
  *) exit 0 ;;
esac
"""


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="run.sh is a bash script")
def test_a_dropped_ssh_connection_keeps_waiting_for_the_tests(tmp_path):
    # ORCH-1653: a busy clone missed the ssh banner once, run.sh counted the tests as failed and started the smoke
    # beside the still-running tests ("still in use"). A 255 from winvm wait now waits again.
    bin_dir = tmp_path / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    fake = bin_dir / "winvm"
    fake.write_text(FAKE_WINVM, encoding="utf-8")
    fake.chmod(0o755)
    out = tmp_path / "out"
    env = {"PATH": "/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin", "HOME": str(tmp_path),
           "WINVM_LOCK": str(tmp_path / "lock"), "WINVM_DROP_PAUSE": "0", "WINVM_REPO": str(ROOT)}
    r = subprocess.run(["bash", str(ROOT / "e2e" / "winvm" / "run.sh"), "HEAD", str(out)],
                       env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "tests rc=0 smoke rc=0 standard-user rc=0" in (out / "timings.txt").read_text()
    assert (tmp_path / "waits").read_text().strip() == "3"
    log = (out / "tests.log").read_text()
    assert "42 passed" in log and "connection drops while waiting for the tests: 2" in log


def test_setup_retries_a_download_on_a_fresh_clone():
    setup = (ROOT / "e2e" / "winvm" / "setup.ps1").read_text(encoding="utf-8")
    body = setup.split("function Get-Checked", 1)[1].split("function Step", 1)[0]
    assert "for ($try = 1;" in body and "Start-Sleep" in body and "if ($try -ge 5) { throw }" in body
