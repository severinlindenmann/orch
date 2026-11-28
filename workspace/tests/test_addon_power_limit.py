"""ORCH-2409 (follow-up of ORCH-2407): the add-ons' own detached starts pass the core's door too, so nothing
orch starts by itself can start more of orch, and a start that comes again and again ends at a limit.

A long-running process of an add-on (its service loop, the merge queue's runner) starts through
procs.service_start: never from inside background work, one slot of the "service" pool while it runs. Every
other place in an add-on that starts a process in a session of its own is named here with the rule that
bounds it. A NEW detached start fails this test until it uses the door or is named."""

import ast
import re
import subprocess
from pathlib import Path

import pytest

from orch import procs

REPO = Path(__file__).resolve().parents[2]
ADDONS = REPO / "workspace-addons"
DOORS = {"service_start", "background_start"}

# (file under workspace-addons, function): the add-on's long-running process, through procs.service_start
THROUGH_THE_DOOR = {
    ("automation/src/orch_automation/service.py", "start"),
    ("dashboard/src/orch_dashboard/service.py", "start"),
    ("factory/src/orch_factory/service.py", "_spawn"),
    ("files/src/orch_files/service.py", "start"),
    ("insights/src/orch_insights/service.py", "start"),
    ("personal/src/orch_personal/service.py", "start"),
    ("pull-requests/src/orch_pull_requests/cli.py", "start_runner"),
    ("pull-requests/src/orch_pull_requests/service.py", "start"),
    ("services/src/orch_services/service.py", "start"),
    ("skills/src/orch_skills/service.py", "start"),
    ("sync/src/orch_sync/orchcli.py", "spawn"),
    ("usage/src/orch_usage/service.py", "start"),
}
# also starts it the old way where the core is not installed beside the add-on (the add-on's own test env)
WITHOUT_A_CORE = {("factory/src/orch_factory/service.py", "_spawn")}
OWN_RULE = {
    ("automation/src/orch_automation/scripts.py", "_start_runner"): (
        "a person's own script on a ticket: one at a time per ticket and group member (its lock), under "
        "automation's run cap and `orch pause`; held back it would lose a planned run"
    ),
    ("browse/src/orch_browse/cli.py", "_start_broker"): (
        "one browser broker per ticket (its state file), started by a browse command on that ticket and "
        "waited for until it answers; it ends by itself when idle"
    ),
    ("pull-requests/src/orch_pull_requests/precheck.py", "_shell"): (
        "the person's own precheck command, waited for (not detached), with a time limit that stops its "
        "whole process group"
    ),
    ("pull-requests/src/orch_pull_requests/localcheck.py", "_call"): (
        "the queue runner waits for it (not detached): one check at a time, with a time limit that stops "
        "its whole process group"
    ),
    ("services/src/orch_services/keeper.py", "keep"): (
        "the keeper owns and waits for the one program a person set up, and starts it again with a growing "
        "delay"
    ),
}


def _detached_starts() -> dict[tuple[str, str], set[str]]:
    """(file, function) -> the start calls of every add-on function that starts a process in a session of its
    own (start_new_session, creationflags, background_popen_kwargs) or builds an orch command line."""
    found = {}
    for f in sorted(ADDONS.glob("*/src/**/*.py")):
        rel = f.relative_to(ADDONS).as_posix()
        for fn in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            calls, own_session = set(), False
            for n in ast.walk(fn):
                if isinstance(n, ast.Call):
                    calls.add(n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", ""))
                    own_session = own_session or any(
                        k.arg in ("start_new_session", "creationflags") for k in n.keywords
                    )
                elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                    own_session = own_session or bool(
                        re.fullmatch(r"orch(\.\w+)?|start_new_session|creationflags", n.value)
                    )
            own_session = own_session or bool(calls & {"background_popen_kwargs", "orch_python_argv"})
            starts = calls & {"Popen", "_popen", *DOORS}
            if own_session and starts:
                found[(rel, fn.name)] = starts
    return found


def test_every_detached_start_of_an_addon_is_known_and_the_long_running_ones_use_the_door():
    found = _detached_starts()
    unknown = set(found) - THROUGH_THE_DOOR - set(OWN_RULE)
    assert not unknown, (
        f"New detached start(s) in an add-on {sorted(unknown)}: start a long-running process with "
        "procs.service_start and background work with procs.background_start (budget, load check, "
        "ORCH_BG_DEPTH), or name it in OWN_RULE with the rule that bounds it."
    )
    for site in sorted(THROUGH_THE_DOOR):
        ways = found.get(site, set()) - ({"Popen"} if site in WITHOUT_A_CORE else set())
        assert ways and ways <= DOORS, f"{site} must start only through the core's door"
    gone = (THROUGH_THE_DOOR | set(OWN_RULE)) - set(found)
    assert not gone, f"No longer a detached start, take it off the list: {sorted(gone)}"
    assert all(OWN_RULE.values())


# ---- the door itself --------------------------------------------------------------------------------


class _Child:
    pid = 0

    def __init__(self, argv, **kw):
        _Child.pid += 1
        self.pid, self.argv, self.kw = 1_000_000_000 + _Child.pid, argv, kw

    def wait(self, timeout=None):
        import threading

        threading.Event().wait()  # never ends in the test: its slot stays held


@pytest.fixture
def ws(proj, run, monkeypatch):
    assert run("init")[0] == 0
    monkeypatch.delenv(procs.BG_DEPTH, raising=False)
    monkeypatch.setattr(procs.subprocess, "Popen", _Child)
    from orch import services

    real = services.pid_alive
    monkeypatch.setattr(services, "pid_alive", lambda pid: True if pid >= 1_000_000_000 else real(pid))
    return proj


def test_a_service_starts_as_a_root_and_holds_one_service_slot(ws):
    p = procs.service_start(ws, ["svc"], cwd=ws, env={"A": "1"})
    assert p.argv == ["svc"] and p.kw["env"] == {
        "A": "1"
    }  # no depth marker: the service is no background work
    assert procs.bg_count(ws, "service") == 1
    assert procs.bg_count(ws) == 0, "a service is never one of the background tasks orch doctor counts"
    assert procs.background_start(ws, ["task"]) is True  # and takes no place of the task budget


@pytest.mark.parametrize("depth", ["1", "2", "nonsense"])
def test_background_work_never_starts_a_service(ws, monkeypatch, depth):
    monkeypatch.setenv(procs.BG_DEPTH, depth)
    with pytest.raises(procs.NotStarted, match="orch start"):
        procs.service_start(ws, ["svc"])
    assert procs.bg_count(ws, "service") == 0


def test_the_service_pool_has_an_end(ws, monkeypatch):
    monkeypatch.setattr(procs, "BG_SERVICES", 3)
    for _ in range(3):
        procs.service_start(ws, ["svc"])
    with pytest.raises(procs.NotStarted, match="3 long-running processes"):
        procs.service_start(ws, ["svc"])
    assert procs.bg_count(ws, "service") == 3


def test_a_start_that_fails_gives_its_slot_back_and_a_callers_own_popen_is_used(ws):
    def broken(argv, **kw):
        raise OSError("no such program")

    with pytest.raises(OSError):
        procs.service_start(ws, ["svc"], start=broken)
    assert procs.bg_count(ws, "service") == 0
    seen = []
    assert procs.service_start(ws, ["svc"], start=lambda argv, **kw: seen.append(argv)) is None
    assert seen == [["svc"]] and procs.bg_count(ws, "service") == 0  # nothing to hold a slot for
    assert subprocess.Popen is _Child  # the fake of this test, never a real process
