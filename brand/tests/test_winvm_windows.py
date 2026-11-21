"""Windows checks on our own Windows VM after the merge (ORCH-1127).

The repository variable WINDOWS_RUNNER=winvm takes the Windows parts of develop pushes and of the nightly run off
GitHub's machines (e2e/winvm/dispatch.py runs them in a fresh winvm clone); unset or any other value brings them
back. Release checks and pull requests keep GitHub's x86-64 Windows run. Plain text over ci.yml, like
test_ci_queue_skip.py, plus the dispatcher's pick order.
"""

import datetime as dt
import importlib.util
import re
from pathlib import Path

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
    cond = re.search(r"^  workspace:\n(?:    #.*\n)*    needs: changes\n(?:    #.*\n)*    if: (.+)$", CI, re.MULTILINE).group(1)
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
