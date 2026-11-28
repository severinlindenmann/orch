"""ORCH-2407: orch limits its own power. One budget of background tasks per workspace, no background start
on a busy computer, and no background process that starts another one (release 52's endless `orch needs`,
ORCH-2372, filled a computer until it had to be restarted)."""

import ast
import itertools
import json
import os
import re
import threading
import time
from pathlib import Path

import pytest

from orch import cli, doctorpass, health, procs, services, stuck, worktrees
from orch import needs as needs_mod

SRC = Path(procs.__file__).resolve().parent
FAKE_PIDS = 1_000_000_000  # above every real process id on any system


@pytest.fixture
def ws(proj, run, monkeypatch):
    """A workspace where every background start is allowed to happen (the test fakes Popen itself)."""
    assert run("init")[0] == 0
    for k in ("ORCH_NO_NEEDS_REFRESH", "ORCH_NO_PULL_LOOK", "ORCH_NO_HEALTH_CHECK", "ORCH_NO_DETACHED_CLEAN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv(procs.BG_DEPTH, raising=False)
    return proj


class _Fakes:
    """Fake child processes: Popen is replaced, and a pid is alive until its fake child ends."""

    def __init__(self, monkeypatch, pull_seconds=0.05, job_seconds=0.2):
        self.alive: set[int] = set()
        self.kinds: dict[int, bool] = {}
        self.started: list[list[str]] = []
        self.envs: list[dict] = []
        self.most = {True: 0, False: 0}  # the most alive at once: detached tasks (True), asked add-ons
        self.lock = threading.Lock()
        ids = itertools.count(FAKE_PIDS)
        real_alive = services.pid_alive
        fakes = self

        class Child:
            returncode = 0

            def __init__(self, argv, **kw):
                self.pid = next(ids)
                # a detached task of the budget; an asked add-on and the refresh of one share the other pool
                self.detached = kw.get("stdout") != procs.subprocess.PIPE and "--refresh-addon" not in argv
                self.waited_for = kw.get("stdout") == procs.subprocess.PIPE
                self.ended = threading.Event()
                with fakes.lock:
                    fakes.started.append(list(argv))
                    fakes.envs.append(dict(kw.get("env") or {}))
                    fakes.alive.add(self.pid)
                    fakes.kinds[self.pid] = self.detached
                    now = sum(1 for p in fakes.alive if fakes.kinds[p] == self.detached)
                    fakes.most[self.detached] = max(fakes.most[self.detached], now)
                if not self.waited_for:  # nobody waits for it: it ends by itself
                    t = threading.Timer(job_seconds, self._end)
                    t.daemon = True  # never keeps the test run open
                    t.start()

            def _end(self):
                with fakes.lock:
                    fakes.alive.discard(self.pid)
                self.ended.set()

            def communicate(self, timeout=None):
                time.sleep(pull_seconds)
                self._end()
                return "[]", ""

            def poll(self):
                return None if self.pid in fakes.alive else 0

            def kill(self):
                self._end()

            def wait(self, timeout=None):
                self.ended.wait(timeout)
                return 0

        monkeypatch.setattr(procs.subprocess, "Popen", Child)
        monkeypatch.setattr(needs_mod, "_kill_tree", lambda p: p.kill())
        # a fake pid is alive until its fake child ends; every real one (this test process, which holds a
        # slot between taking it and starting the child) is asked for real. Linux pids go up to 4 million.
        monkeypatch.setattr(
            services, "pid_alive", lambda pid: pid in self.alive if pid >= FAKE_PIDS else real_alive(pid)
        )


# ---- 1. the budget -----------------------------------------------------------------------------------


def test_a_start_over_the_budget_is_skipped_and_a_dead_slot_is_taken_over(ws, monkeypatch):
    f = _Fakes(monkeypatch, job_seconds=3600)
    argv = procs.orch_python_argv("needs", "--look-at-pulls")
    assert [procs.background_start(ws, argv) for _ in range(6)] == [True] * 4 + [False] * 2
    assert len(f.started) == 4 and procs.bg_count(ws) == 4
    f.alive.discard(min(f.alive))  # one of them ends: its slot is free again
    assert procs.bg_count(ws) == 3
    assert procs.background_start(ws, argv) is True and procs.background_start(ws, argv) is False
    assert procs.bg_count(ws) == 4


def test_the_budget_is_a_setting(ws, run, monkeypatch):
    f = _Fakes(monkeypatch, job_seconds=3600)
    assert run("config", "set", "workspace.background_max", "2")[0] == 0
    assert run("config", "get", "workspace.background_max")[1].strip() == "2"
    assert [procs.background_start(ws, ["x"]) for _ in range(4)] == [True, True, False, False]
    assert len(f.started) == 2
    for bad in ("0", "-1", "65", "many"):
        assert run("config", "set", "workspace.background_max", bad)[0] != 0
    assert procs.bg_limits(ws)[0] == 2


def test_a_start_a_person_asked_for_is_counted_but_never_skipped(ws, monkeypatch):
    f = _Fakes(monkeypatch, job_seconds=3600)
    monkeypatch.delenv("ORCH_NO_LOAD_HOLD", raising=False)
    assert all(procs.background_start(ws, ["x"]) for _ in range(4))
    monkeypatch.setattr(procs, "_load_per_core", lambda: 50.0)
    assert procs.background_start(ws, ["x"]) is False
    assert procs.background_start(ws, ["x"], person=True) is True
    assert len(f.started) == 5 and procs.bg_count(ws) == 5


def test_a_start_that_fails_gives_its_slot_back(ws, monkeypatch):
    def boom(*a, **k):
        raise OSError("no such program")

    monkeypatch.setattr(procs.subprocess, "Popen", boom)
    with pytest.raises(OSError):
        procs.background_start(ws, ["x"])
    assert procs.bg_count(ws) == 0 and not list((ws / ".orch/run/bg").glob("*.slot"))


def test_an_old_slot_whose_pid_now_belongs_to_another_program_is_free(ws, monkeypatch):
    slot = procs.bg_claim(ws)
    assert slot is not None and procs.bg_count(ws) == 1  # this test process holds it
    old = time.time() - procs.BG_OLD - 60
    os.utime(slot, (old, old))
    assert procs.bg_count(ws) == 0  # this process started after the slot was written: not the holder
    monkeypatch.setattr(procs, "pid_started", lambda pid: None)
    assert procs.bg_count(ws) == 1  # start time unknown: held (never over the limit)


def test_200_needs_calls_at_once_stay_under_the_budget(ws, monkeypatch):
    """200 `orch needs` at once, each asking one add-on in line, starting the refresh of a late one and the
    look at pull requests: never more background tasks than the budget, and never more add-ons asked at
    once than their pool, however many callers there are."""
    f = _Fakes(monkeypatch)
    manifests = {n: {"name": n, "run": f"orch_{n}", "needs": True} for n in ("hello", "late")}
    monkeypatch.setattr(needs_mod.addons, "active_manifests", lambda root: manifests)
    monkeypatch.setattr(needs_mod.addons, "orch_bin", lambda: "orch")
    monkeypatch.setattr(needs_mod, "core_rows", lambda root: [])
    needs_mod._write_cache(ws, "late", [])
    needs_mod._write_cache(ws, "hello", [])
    needs_mod._set_late(ws, "late", True)
    go = threading.Barrier(200)
    errors = []

    def call():
        try:
            go.wait()
            needs_mod.needs(ws)
            stuck._spawn_look(ws)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=call) for _ in range(200)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not errors and not any(t.is_alive() for t in threads)
    cap = procs.bg_limits(ws)[0]
    assert cap == procs.BG_MAX_DEFAULT == 4
    tasks, asks = f.most[True], f.most[False]
    assert 1 <= tasks <= cap, f"{tasks} background tasks at once, the budget is {cap}"
    assert 1 <= asks <= cap * procs.BG_ASK_TIMES, (
        f"{asks} add-ons asked at once, {cap * procs.BG_ASK_TIMES} may be"
    )
    assert tasks + asks <= 36  # 200 callers, two add-ons each: never the 400 processes of release 52
    assert len(f.started) < 400
    assert any("--look-at-pulls" in a for a in f.started) and any("needs" in a for a in f.started)


# ---- 2. back off on a busy computer -------------------------------------------------------------------


def test_background_work_waits_while_the_computer_is_busy(ws, monkeypatch):
    f = _Fakes(monkeypatch)
    monkeypatch.delenv("ORCH_NO_LOAD_HOLD", raising=False)
    load = {"now": 9.0}
    monkeypatch.setattr(procs, "_load_per_core", lambda: load["now"])
    assert procs.bg_busy(ws) is True
    stuck._spawn_look(ws)
    worktrees._spawn_clean(ws, "--trash")
    assert health.soon(ws, force=True) is False
    assert _doctorpass_soon(ws) is False
    assert procs.background_start(ws, ["x"]) is False
    assert f.started == []
    load["now"] = 0.4  # the load is gone: the next command starts the work
    assert procs.bg_busy(ws) is False
    stuck._spawn_look(ws)
    assert len(f.started) == 1 and "--look-at-pulls" in f.started[0]


def test_the_refresh_of_needs_is_light_and_not_held_back_by_the_load(ws, monkeypatch):
    """Seen in the Focus page smoke on a busy machine: with the refresh held back, a late add-on's rows went
    out of date and the page drew itself again and again. The refresh is what `orch needs` would otherwise
    wait for itself, so only its pool bounds it."""
    f = _Fakes(monkeypatch, job_seconds=3600)
    monkeypatch.delenv("ORCH_NO_LOAD_HOLD", raising=False)
    assert all(procs.background_start(ws, ["x"]) for _ in range(4))  # the task budget is used up as well
    monkeypatch.setattr(procs, "_load_per_core", lambda: 9.0)
    needs_mod._write_cache(ws, "hello", [])
    assert needs_mod._spawn_refresh(ws, "hello") is True
    assert f.started[-1][-2:] == ["--refresh-addon", "hello"] and f.envs[-1][procs.BG_DEPTH] == "1"
    assert procs.bg_count(ws) == 4 and procs.bg_count(ws, "ask") == 1  # in the pool of the asked add-ons
    pool = procs.bg_limits(ws)[0] * procs.BG_ASK_TIMES
    assert (
        sum(needs_mod._spawn_refresh(ws, f"a{i}") for i in range(pool + 5)) == pool - 1
    )  # bounded all the same
    assert not needs_mod._refresh_mark(ws, f"a{pool + 4}").exists()  # a skipped one leaves no mark behind


def test_the_load_limit_is_a_setting_and_a_system_without_load_is_never_busy(ws, run, monkeypatch):
    monkeypatch.delenv("ORCH_NO_LOAD_HOLD", raising=False)
    monkeypatch.setattr(procs, "_load_per_core", lambda: 2.0)
    assert procs.bg_limits(ws) == (4, 1.5) and procs.bg_busy(ws) is True
    assert run("config", "set", "workspace.background_load", "3")[0] == 0
    assert run("config", "get", "workspace.background_load")[1].strip() == "3.0"
    assert procs.bg_busy(ws) is False
    assert run("config", "set", "workspace.background_load", "0")[0] != 0
    monkeypatch.setattr(procs, "_load_per_core", lambda: None)  # Windows: no load average
    assert procs.bg_busy(ws) is False
    monkeypatch.setattr(procs, "_load_per_core", lambda: 99.0)
    monkeypatch.setenv("ORCH_NO_LOAD_HOLD", "1")  # the test runners' switch
    assert procs.bg_busy(ws) is False


def test_a_broken_settings_file_gives_the_safe_defaults(ws):
    (ws / ".orch" / "config.toml").write_text("[workspace\nbackground_max = 900\n", encoding="utf-8")
    assert procs.bg_limits(ws) == (procs.BG_MAX_DEFAULT, procs.BG_LOAD_DEFAULT)
    (ws / ".orch" / "config.toml").write_text(
        '[workspace]\nbackground_max = 900\nbackground_load = "high"\n', encoding="utf-8"
    )
    assert procs.bg_limits(ws) == (procs.BG_MAX_DEFAULT, procs.BG_LOAD_DEFAULT)


# ---- 3. no background process starts another one ------------------------------------------------------

# Every place in the core that starts an orch process and does not wait for it. A start of orch's own
# background work goes through procs.background_start (the budget, the load check, the depth marker). The
# others are started by a person's action or carry a ticket's work, with their own one-at-a-time rule: named
# here with the reason. A NEW detached start fails this test until it uses background_start or is named.
THROUGH_THE_BUDGET = {
    ("needs.py", "_spawn_refresh"): ["needs", "--refresh-addon"],
    ("stuck.py", "_spawn_look"): ["needs", "--look-at-pulls"],
    ("health.py", "soon"): ["logins", "--json"],
    ("doctorpass.py", "soon"): ["doctor", "pass", "--json"],
    ("worktrees.py", "_spawn_clean"): ["copy", "clean"],
    ("renew.py", "start"): ["logins", "renew"],
}
OWN_RULE = {
    ("runs.py", "start"): "a helper's run on a ticket: the run lock, the brake's cap per ticket, live_max",
    ("runs_live.py", "resume_soon"): "one start after a person's answer; it starts a run (above)",
    (
        "mobile_mode.py",
        "_spawn_keeper",
    ): "one keeper per workspace, started by a person turning phone mode on",
    ("addons.py", "_restart_later"): "one restart of the services after a person's add-on command",
    ("pagesession.py", "start_detached"): "a page session a person opened",
    ("readworker.py", "__init__"): "a worker this process owns, reads and stops (not detached)",
    ("seccall.py", "spawn"): "a worker this process owns and waits for (not detached)",
    ("winfinish.py", "start"): "Windows: one finishing step after a person's install or update",
}


def _orch_starts() -> dict[tuple[str, str], set[str]]:
    """(file, function) -> the start calls it makes, for every function that builds an orch command line
    (procs.orch_python_argv, orch_cmd, or `-m orch…`) and starts a process."""
    found = {}
    for f in sorted(SRC.rglob("*.py")):
        if "tests" in f.parts:
            continue
        for fn in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            calls, orch_argv = set(), False
            for n in ast.walk(fn):
                if isinstance(n, ast.Call):
                    calls.add(n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", ""))
                elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                    orch_argv = orch_argv or bool(re.fullmatch(r"orch(\.\w+)?", n.value))
            orch_argv = orch_argv or bool(calls & {"orch_python_argv", "orch_cmd"})
            starts = calls & {"Popen", "_popen", "background_start"}
            if orch_argv and starts:
                found[(f.name, fn.name)] = starts
    return found


def test_every_detached_orch_start_is_known_and_orchs_own_go_through_the_budget():
    found = _orch_starts()
    unknown = set(found) - set(THROUGH_THE_BUDGET) - set(OWN_RULE)
    assert not unknown, (
        f"New detached orch start(s) {sorted(unknown)}: start it with procs.background_start (budget, load "
        "check, ORCH_BG_DEPTH), or name it in OWN_RULE with the rule that stops it from starting itself."
    )
    for site in THROUGH_THE_BUDGET:
        assert found.get(site) == {"background_start"}, f"{site} must start only through background_start"
    gone = (set(THROUGH_THE_BUDGET) | set(OWN_RULE)) - set(found)
    assert not gone, f"No longer a detached start, take it off the list: {sorted(gone)}"
    # no other way to the depth marker's door: only procs.py itself calls Popen for a budgeted start
    for (file, fn), why in OWN_RULE.items():
        assert why and "background_start" not in found[(file, fn)]


def _spawners(ws, monkeypatch):
    return {
        ("needs.py", "_spawn_refresh"): lambda: needs_mod._spawn_refresh(ws, "hello"),
        ("stuck.py", "_spawn_look"): lambda: stuck._spawn_look(ws),
        ("health.py", "soon"): lambda: health.soon(ws, force=True),
        ("doctorpass.py", "soon"): lambda: _doctorpass_soon(ws),
        ("worktrees.py", "_spawn_clean"): lambda: worktrees._spawn_clean(ws, "--trash"),
        ("renew.py", "start"): lambda: _renew_start(ws, monkeypatch),
    }


def _doctorpass_soon(ws):
    doctorpass.save_setup(ws, {"every_min": 15})
    return doctorpass.soon(ws)


def _renew_start(ws, monkeypatch):
    from orch import renew
    from orch.errors import Refused

    monkeypatch.setattr(renew.shutil, "which", lambda name: f"/opt/tools/{name}")  # the tool is installed
    monkeypatch.setattr(renew, "_real_tool_in_test", lambda found: False)
    monkeypatch.setattr(
        renew, "person_only", lambda root, by=None, reading=False: None
    )  # a person pressed it
    try:
        renew.start(ws, "claude")
    except Refused:
        return False
    return True


def test_each_budgeted_start_really_starts_its_command_with_the_depth_marker(ws, monkeypatch):
    f = _Fakes(monkeypatch)
    monkeypatch.setattr(procs, "BG_MAX_DEFAULT", 16)
    spawners = _spawners(ws, monkeypatch)
    assert set(spawners) == set(THROUGH_THE_BUDGET)
    for site, start in spawners.items():
        before = len(f.started)
        start()
        assert len(f.started) == before + 1, f"{site} did not start"
        argv, env = f.started[-1], f.envs[-1]
        want = THROUGH_THE_BUDGET[site]
        at = argv.index("orch") + 1
        assert argv[:at] == procs.orch_python_argv() and argv[at : at + len(want)] == want
        assert env[procs.BG_DEPTH] == "1" and env["ORCH_ROOT"] == str(ws)


@pytest.mark.parametrize("depth", ["1", "2", "nonsense"])
def test_a_background_process_never_starts_another_one(ws, monkeypatch, depth):
    """The walk: inside a background process (the marker is set) not one of orch's detached starts starts
    anything, so no command can start itself again, whatever calls what."""
    f = _Fakes(monkeypatch)
    monkeypatch.setenv(procs.BG_DEPTH, depth)
    for site, start in _spawners(ws, monkeypatch).items():
        assert not start(), site
        assert f.started == [], f"{site} started {f.started} from inside a background process"
    assert procs.background_start(ws, ["x"], person=True) is False and f.started == []


def test_the_background_commands_themselves_start_nothing(ws, run, monkeypatch):
    """Each background command, run as it runs detached (marker set): no orch process is started by it."""
    f = _Fakes(monkeypatch)
    monkeypatch.setenv(procs.BG_DEPTH, "1")
    monkeypatch.setenv("ORCH_ROOT", str(ws))
    for argv in (
        ["needs", "--refresh-addon", "hello"],
        ["needs", "--look-at-pulls"],
        ["copy", "clean", "--trash"],
    ):
        cli.main(argv)
        assert f.started == [], f"orch {' '.join(argv)} started {f.started}"


def test_an_addon_asked_for_its_needs_is_one_level_deeper_and_the_deepest_asks_nobody(ws, monkeypatch):
    f = _Fakes(monkeypatch)
    monkeypatch.setattr(needs_mod.addons, "orch_bin", lambda: "orch")
    m = {"name": "hello", "run": "orch_hello", "needs": True}
    assert needs_mod._pull(ws, "hello", m) == []
    assert f.envs[-1][procs.BG_DEPTH] == "1"
    assert procs.bg_count(ws, "ask") == 0 and procs.bg_count(ws) == 0  # its slot is given back
    monkeypatch.setenv(procs.BG_DEPTH, "1")  # the background refresh asks its add-on, in its own slot
    assert needs_mod._pull(ws, "hello", m) == []
    assert f.envs[-1][procs.BG_DEPTH] == "2" and len(f.started) == 2
    monkeypatch.setenv(procs.BG_DEPTH, "2")  # that add-on's own orch commands ask nobody
    assert needs_mod._pull(ws, "hello", m) is None and len(f.started) == 2


# ---- 4. orch doctor names the limits ------------------------------------------------------------------


def test_doctor_names_the_limits_and_the_count(ws, run, monkeypatch):
    monkeypatch.delenv("ORCH_NO_LOAD_HOLD", raising=False)
    monkeypatch.setattr(procs, "_load_per_core", lambda: 0.3)
    assert procs.power_words(ws) == (
        "orch runs at most 4 background tasks at once in this workspace (none runs now). "
        "It waits while the load per processor core is over 1.5 (now 0.3, under it)."
    )
    assert procs.bg_claim(ws) is not None  # one background task runs (this test process holds its slot)
    monkeypatch.setattr(procs, "_load_per_core", lambda: 2.26)
    assert "(1 runs now)" in procs.power_words(ws)
    assert "(now 2.3, over it: background work waits)" in procs.power_words(ws)
    monkeypatch.setattr(procs, "_load_per_core", lambda: None)
    assert procs.power_words(ws).endswith("This system reports no load, so only that limit counts.")
    code, out, _ = run("doctor", "--json")
    row = next(r for r in json.loads(out)["checks"] if r["name"] == "background work")
    assert row["ok"] is True and row["fact"] == procs.power_words(ws)
    assert "orch runs at most 4 background tasks at once" in run("doctor")[1]


# ---- what the first version got wrong (the Focus page smoke went red) -----------------------------------


def test_one_needs_asks_all_its_addons_side_by_side_even_with_the_task_budget_used_up(ws, monkeypatch):
    """Seven add-ons answer needs. One `orch needs` asks them all at once and none waits behind orch's
    background tasks, even when those hold their whole budget."""
    f = _Fakes(monkeypatch, pull_seconds=0.2, job_seconds=3600)
    assert all(procs.background_start(ws, ["x"]) for _ in range(4)) and procs.bg_count(ws) == 4
    names = [f"a{i}" for i in range(7)]
    manifests = {n: {"name": n, "run": f"orch_{n}", "needs": True} for n in names}
    monkeypatch.setattr(needs_mod.addons, "active_manifests", lambda root: manifests)
    monkeypatch.setattr(needs_mod.addons, "orch_bin", lambda: "orch")
    monkeypatch.setattr(needs_mod, "core_rows", lambda root: [])
    began = time.monotonic()
    assert needs_mod.needs(ws) == []
    assert time.monotonic() - began < 1.5  # side by side: about one add-on's time, not seven
    assert f.most[False] == 7 and len(f.started) == 4 + 7
    assert not any(needs_mod._late_mark(ws, n).exists() for n in names)


def test_an_ended_task_frees_its_slot_at_once_in_a_long_running_starter(ws, monkeypatch):
    """A page's service starts background tasks and lives on: an ended task must not keep its slot."""
    f = _Fakes(monkeypatch, job_seconds=0.05)
    for _ in range(3):  # three rounds of the whole budget, one after the other
        assert all(procs.background_start(ws, ["x"]) for _ in range(4))
        end = time.monotonic() + 5
        while list((ws / ".orch/run/bg").glob("*.slot")) and time.monotonic() < end:
            time.sleep(0.02)
        assert not list((ws / ".orch/run/bg").glob("*.slot"))  # given back by the reaper, not only found dead
    assert len(f.started) == 12


def test_a_start_a_person_asked_for_takes_no_task_slot(ws, monkeypatch):
    f = _Fakes(monkeypatch, job_seconds=3600)
    assert procs.background_start(ws, ["x"], person=True) is True  # a sign-in that waits for its code
    assert [procs.background_start(ws, ["x"]) for _ in range(5)] == [True] * 4 + [False]
    assert procs.bg_count(ws) == 5 and len(f.started) == 5


def test_a_late_release_never_frees_a_slot_another_start_took_meanwhile(ws):
    """Seen on Windows (5 tasks with a budget of 4): a task ended, its slot was taken by the next start, and
    only then the first task's release came. It must leave the slot alone."""
    slot = procs.bg_claim(ws)  # the next start holds it (this process, until its child is bound)
    procs.bg_release(slot, 654_321)  # the release for the task that held it before
    assert slot.exists() and procs.bg_count(ws) == 1
    procs.bg_bind(slot, 654_322)
    procs.bg_release(slot)  # "my start never happened": not true any more, the child has it
    assert slot.exists()
    procs.bg_release(slot, 654_322)
    assert not slot.exists()
