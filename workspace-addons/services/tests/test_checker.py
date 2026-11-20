"""The regular check (report r-1118-1737-t_ghbbgu-3): Services runs `check` by itself in its background process, so a
service that keeps stopping raises its one question without anyone setting up a repeat. Two passes never overlap."""

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from orch_services import cli, service
from orch_services.store import Refused

ADDON = Path(__file__).resolve().parents[1]
REPO = ADDON.parents[1]


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    (root / ".orch").mkdir(parents=True)
    monkeypatch.setattr(service, "still_on", lambda r: True)
    return root


def _never_sleep(_s):
    pass


def test_the_add_on_has_a_background_process_so_orch_start_and_turning_it_on_start_the_check():
    m = tomllib.loads((ADDON / "src/orch_services/orch-addon.toml").read_text(encoding="utf-8"))
    assert m["background"] is True
    shipped = json.loads((REPO / "workspace/src/orch/shipped_addons.json").read_text(encoding="utf-8"))
    assert shipped["services"]["background"] is True


def test_watch_runs_the_check_every_round_and_frees_its_lock(ws):
    calls = []
    slept = []
    assert service.watch(ws, lambda: calls.append(1), sleep=slept.append, rounds=3, log=lambda m: None) == 0
    assert len(calls) == 3
    assert slept == [service.EVERY_SECS] * 2
    assert not (ws / ".orch/addons/services/checker.lock").exists()
    assert not (ws / ".orch/addons/services/check.lock").exists()
    assert service.running_pid(ws) is None


def test_watch_ends_when_services_is_turned_off(ws, monkeypatch):
    calls = []
    on = iter([True, False])
    monkeypatch.setattr(service, "still_on", lambda r: next(on))
    assert service.watch(ws, lambda: calls.append(1), sleep=_never_sleep, rounds=10, log=lambda m: None) == 0
    assert calls == [1]


def test_one_bad_round_never_ends_the_checker(ws):
    n = []
    said = []

    def check():
        n.append(1)
        if len(n) == 1:
            raise OSError("launchctl went away")

    service.watch(ws, check, sleep=_never_sleep, rounds=2, log=said.append)
    assert len(n) == 2
    assert any("OSError" in s for s in said)


def test_a_second_checker_does_not_run(ws):
    lock = ws / ".orch/addons/services/checker.lock"
    assert service.take_lock(lock)  # this process (alive) holds it
    calls = []
    said = []
    assert service.watch(ws, lambda: calls.append(1), sleep=_never_sleep, rounds=1, log=said.append) == 0
    assert calls == []
    assert said == ["The regular check runs already."]
    assert service.running_pid(ws) == os.getpid()


def test_a_person_s_check_and_the_checker_never_overlap(ws):
    with service.check_pass(ws):
        calls = []
        service.watch(ws, lambda: calls.append(1), sleep=_never_sleep, rounds=1, log=lambda m: None)
        assert calls == []  # the round was the person's
        with pytest.raises(Refused, match="Another check runs"), service.check_pass(ws, wait=0):
            pass
    with service.check_pass(ws, wait=0):  # freed again
        pass


def test_a_lock_left_by_a_dead_process_is_taken_over(ws):
    lock = ws / ".orch/addons/services/check.lock"
    lock.mkdir(parents=True)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (lock / "owner").write_text(f"{dead.pid} -", encoding="utf-8")
    with service.check_pass(ws, wait=0):
        pass


def _main(capsys, *argv):
    rc = cli.main([*argv, "--json"])
    out = capsys.readouterr().out.strip().splitlines()
    return rc, json.loads(out[-1])


def test_start_stop_status_without_an_id_drive_the_checker(ws, monkeypatch, capsys):
    monkeypatch.setenv("ORCH_ROOT", str(ws))
    monkeypatch.setattr(service, "start", lambda root: 4242)
    monkeypatch.setattr(service, "stop", lambda root: True)
    assert _main(capsys, "start") == (0, {"running": True, "pid": 4242})
    assert _main(capsys, "stop") == (0, {"stopped": True})
    assert _main(capsys, "status") == (1, {"running": False})


def test_start_with_an_id_still_starts_that_service(ws, monkeypatch, capsys):
    monkeypatch.setenv("ORCH_ROOT", str(ws))
    seen = []
    monkeypatch.setattr(cli, "cmd_simple", lambda args, root, verb, sid: seen.append((verb, sid)) or 0)
    monkeypatch.setattr(service, "start", lambda root: pytest.fail("the checker must not start"))
    assert cli.main(["start", "web", "--json"]) == 0
    assert cli.main(["stop", "web", "--json"]) == 0
    assert seen == [("start", "web"), ("stop", "web")]


def test_check_refuses_while_another_pass_runs(ws, monkeypatch, capsys):
    monkeypatch.setenv("ORCH_ROOT", str(ws))
    monkeypatch.setattr(service, "CHECK_WAIT", 0)
    with service.check_pass(ws):
        rc = cli.main(["check", "--json"])
    assert rc != 0
    assert "Another check runs" in capsys.readouterr().out


def test_the_checker_runs_and_stops_as_a_real_process(ws, tmp_path, monkeypatch):
    """Start through the real Popen path: the checker takes its lock, runs, and stop ends it."""
    env_pp = os.pathsep.join([str(ADDON / "src"), str(REPO / "workspace" / "src")])
    monkeypatch.setenv("PYTHONPATH", env_pp)
    real_popen = subprocess.Popen
    children = []

    def popen(
        argv, **kw
    ):  # -I ignores PYTHONPATH: run the same module without it here (no installed package)
        argv = [a for a in argv if a != "-I"]
        stub = (
            "import sys, orch_services.service as s;"
            "s.still_on = lambda r: (r / '.orch').is_dir();"
            "from orch_services import cli; sys.exit(cli.main(sys.argv[1:]))"
        )
        i = argv.index("-m")
        argv = [*argv[:i], "-c", stub, *argv[i + 2 :]]
        children.append(real_popen(argv, **kw))
        return children[-1]

    monkeypatch.setattr(service.subprocess, "Popen", popen)
    pid = service.start(ws)
    try:
        assert service.running_pid(ws) == pid
        assert service.start(ws) == pid  # a second start keeps the one that runs
    finally:
        assert service.stop(ws) is True
    assert [c.wait(timeout=10) for c in children]  # reap it (in real use the core's call has ended already)
    assert service.stop(ws) is False
    assert service.running_pid(ws) is None
