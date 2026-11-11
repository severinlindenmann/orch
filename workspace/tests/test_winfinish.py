"""Windows reinstall after orch exits (winfinish.py). The finisher is plain Python and runs anywhere."""

import json
import subprocess
import sys

import pytest

from orch import addons, winfinish
from orch.errors import Refused


@pytest.fixture
def uv_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(addons, "run_uv", lambda args: calls.append(args))
    return calls


def _run_finisher(tmp_path, job):
    (tmp_path / "finish.py").write_text(winfinish.FINISHER, encoding="utf-8")
    (tmp_path / "job.json").write_text(json.dumps(job), encoding="utf-8")
    return subprocess.run([sys.executable, "-I", str(tmp_path / "finish.py"), str(tmp_path / "job.json")])


def _job(tmp_path, uv_code="print('uv ok')", then_code="print('then ok')"):
    env = tmp_path / "tool-env"
    env.mkdir()
    return {
        "uv": [sys.executable, "-c", uv_code],
        "free": [str(env)],
        "wait": 5,
        "uv_timeout": 30,
        "registry": [str(tmp_path / "addons.json"), '[{"name": "dashboard"}]'],
        "then": [{"argv": [sys.executable, "-c", then_code, "x"], "cwd": str(tmp_path)}],
        "log": str(tmp_path / "finish.log"),
        "done": "dashboard installed and turned on",
        "pending": str(tmp_path / "finish.pending"),
        "updating": str(winfinish.marker_path(tmp_path)),
    }


def test_finisher_reinstalls_saves_the_list_and_runs_the_next_step(tmp_path):
    (tmp_path / "finish.pending").write_text("1")
    assert _run_finisher(tmp_path, _job(tmp_path)).returncode == 0
    assert not (tmp_path / "finish.pending").exists()  # the next install may start
    log = (tmp_path / "finish.log").read_text()
    assert "then ok" in log and log.rstrip().endswith("RESULT ok: dashboard installed and turned on")
    assert json.loads((tmp_path / "addons.json").read_text()) == [{"name": "dashboard"}]
    assert (tmp_path / "tool-env").is_dir()  # the free-check renamed it back


def test_a_failed_reinstall_changes_nothing(tmp_path):
    job = _job(tmp_path, uv_code="import sys; print('boom', file=sys.stderr); sys.exit(3)")
    assert _run_finisher(tmp_path, job).returncode == 1
    log = (tmp_path / "finish.log").read_text()
    assert "boom" in log and "RESULT fail" in log
    assert not (tmp_path / "addons.json").exists()  # the add-on list stays as it was


@pytest.mark.skipif(sys.platform == "win32", reason="the lock is simulated with POSIX folder permissions")
def test_orch_still_running_changes_nothing(tmp_path):
    """The tool folder can not be renamed (orch still runs from it): give up, change nothing."""
    job = _job(tmp_path)
    job["wait"] = 1
    locked = tmp_path / "locked"
    locked.mkdir()
    job["free"] = [str(locked / "tool-env")]
    (locked / "tool-env").mkdir()
    locked.chmod(0o500)  # no rename inside: like Windows while orch runs
    try:
        assert _run_finisher(tmp_path, job).returncode == 1
    finally:
        locked.chmod(0o700)
    assert "still in use after 1s" in (tmp_path / "finish.log").read_text()
    assert not (tmp_path / "addons.json").exists()


def test_a_failing_next_step_is_reported(tmp_path):
    job = _job(tmp_path, then_code="import sys; print('no consent'); sys.exit(2)")
    assert _run_finisher(tmp_path, job).returncode == 1
    log = (tmp_path / "finish.log").read_text()
    assert "no consent" in log and "RESULT fail:" in log


def test_a_crash_is_logged_and_clears_the_pending_mark(tmp_path):
    job = _job(tmp_path)
    job["registry"] = [str(tmp_path / "no-such-dir" / "addons.json"), "[]"]  # the write fails
    (tmp_path / "finish.pending").write_text("1")
    assert _run_finisher(tmp_path, job).returncode == 1
    assert "RESULT fail: Traceback" in (tmp_path / "finish.log").read_text()
    assert not (tmp_path / "finish.pending").exists()


def test_a_second_install_waits_for_the_first(proj, monkeypatch, uv_calls):
    """Each job carries the whole add-on list: a second one could undo the first (security review)."""
    monkeypatch.setattr(winfinish, "needed", lambda: True)
    addons.home().mkdir(parents=True, exist_ok=True)
    (addons.home() / "finish.pending").write_text("starting")
    with pytest.raises(Refused, match="still finishing"):
        addons._reinstall([], save=True, then=[], root=proj, done="x")


def test_start_writes_its_files_in_orchs_home_and_marks_pending(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(winfinish, "_popen", lambda argv, **k: calls.append(argv) or 4242)
    monkeypatch.setattr(winfinish.sys, "_base_executable", "/base/python", raising=False)
    log = winfinish.start(tmp_path, ["uv", "tool"], [["update", "--project-only"]], tmp_path, "done")
    assert log == tmp_path / "finish.log"
    assert (tmp_path / "finish.pending").read_text() == "4242"  # the finisher's pid
    assert calls[0][:2] == ["/base/python", "-I"] and calls[0][2] == str(tmp_path / "finish" / "finish.py")
    job = json.loads((tmp_path / "finish" / "job.json").read_text())
    assert job["updating"] == str(winfinish.marker_path(tmp_path))
    assert job["then"][0]["argv"][1:] == ["-I", "-P", "-m", "orch", "update", "--project-only"]


def test_start_refuses_without_an_outside_python(tmp_path, monkeypatch):
    monkeypatch.setattr(winfinish.sys, "prefix", str(tmp_path / "tool-env"))
    monkeypatch.setattr(
        winfinish.sys,
        "_base_executable",
        str(tmp_path / "tool-env" / "Scripts" / "python.exe"),
        raising=False,
    )
    with pytest.raises(RuntimeError):
        winfinish.start(tmp_path, ["uv"], [], tmp_path, "done")


def test_windows_hands_the_reinstall_to_the_finisher(proj, monkeypatch, uv_calls, capsys):
    """On Windows orch must not run uv on its own folder (it broke itself: 'No module named orch')."""
    started = []
    monkeypatch.setattr(winfinish, "needed", lambda: True)
    monkeypatch.setattr(addons, "_which_uv", lambda: "uv.exe")
    monkeypatch.setattr(
        winfinish,
        "start",
        lambda home, uv, then, cwd, done, reg=None: started.append((uv, then, reg)) or home,
    )
    reexecs = []
    monkeypatch.setattr(addons, "reexec", lambda a: reexecs.append(a))
    entries = [{"name": "dashboard", "source": "built-in", "version": "0.0.0"}]
    assert (
        addons._reinstall(entries, save=True, then=[["update", "--project-only"]], root=proj, done="x")
        is False
    )
    assert not uv_calls and not reexecs and not addons.registry_path().exists()
    (uv, then, reg) = started[0]
    assert uv[0] == "uv.exe" and uv[1:4] == ["tool", "install", "--reinstall"]
    assert then == [["update", "--project-only"]]
    assert json.loads(reg[1])[0]["name"] == "dashboard"
    assert "finishes in the background" in capsys.readouterr().out


def test_other_systems_reinstall_at_once(proj, monkeypatch, uv_calls):
    monkeypatch.setattr(winfinish, "needed", lambda: False)
    reexecs = []
    monkeypatch.setattr(addons, "reexec", lambda a: reexecs.append(a))
    entries = [{"name": "dashboard", "source": "built-in", "version": "0.0.0"}]
    assert addons._reinstall(entries, save=True, then=[["update", "--project-only"]], root=proj, done="x")
    assert uv_calls and reexecs == [["update", "--project-only"]]
    assert addons.registry() == entries


def test_a_dead_finisher_does_not_block(tmp_path):
    """It died with the SSH session that started it: its mark must not block the next install."""
    import subprocess as sp

    p = sp.Popen([sys.executable, "-c", "pass"])
    p.wait()
    (tmp_path / "finish.pending").write_text(str(p.pid))
    assert winfinish.pending(tmp_path) is False
    (tmp_path / "finish.pending").write_text(str(__import__("os").getpid()))  # alive
    assert winfinish.pending(tmp_path) is True
    (tmp_path / "finish.pending").write_text("starting")
    assert winfinish.pending(tmp_path) is True


def test_start_falls_back_when_breaking_away_is_not_allowed(tmp_path, monkeypatch):
    seen = []

    def popen(argv, creationflags=0, **kw):
        seen.append(creationflags)
        if creationflags & 0x01000000:
            raise PermissionError("not allowed")
        return 77

    monkeypatch.setattr(winfinish, "_popen", popen)
    monkeypatch.setattr(winfinish.sys, "_base_executable", "/base/python", raising=False)
    winfinish.start(tmp_path, ["uv"], [], tmp_path, "done")
    assert seen[0] & 0x01000000 and not seen[1] & 0x01000000
    assert (tmp_path / "finish.pending").read_text() == "77"


def test_only_one_start_gets_the_mark(tmp_path, monkeypatch):
    """Two orch commands at the same moment: the second one is refused, never a second job."""
    monkeypatch.setattr(winfinish, "_popen", lambda argv, **k: __import__("os").getpid())  # alive
    monkeypatch.setattr(winfinish.sys, "_base_executable", "/base/python", raising=False)
    winfinish.start(tmp_path, ["uv"], [], tmp_path, "done")
    with pytest.raises(winfinish.Busy):
        winfinish.start(tmp_path, ["uv"], [], tmp_path, "done")


def test_a_dead_mark_is_taken_over(tmp_path, monkeypatch):
    import subprocess as sp

    p = sp.Popen([sys.executable, "-c", "pass"])
    p.wait()
    (tmp_path / "finish.pending").write_text(str(p.pid))
    monkeypatch.setattr(winfinish, "_popen", lambda argv, **k: 99)
    monkeypatch.setattr(winfinish.sys, "_base_executable", "/base/python", raising=False)
    winfinish.start(tmp_path, ["uv"], [], tmp_path, "done")
    assert (tmp_path / "finish.pending").read_text() == "99"


def test_any_start_failure_frees_the_mark(tmp_path, monkeypatch):
    def boom(argv, **kw):
        raise ValueError("bad argument")

    monkeypatch.setattr(winfinish, "_popen", boom)
    monkeypatch.setattr(winfinish.sys, "_base_executable", "/base/python", raising=False)
    with pytest.raises(RuntimeError):
        winfinish.start(tmp_path, ["uv"], [], tmp_path, "done")
    assert not (tmp_path / "finish.pending").exists()


def _windows_with_one_finisher(monkeypatch):
    started = []
    monkeypatch.setattr(winfinish, "needed", lambda: True)
    monkeypatch.setattr(addons, "_which_uv", lambda: "uv.exe")
    monkeypatch.setattr(addons, "_reinstall_plan", lambda: None)
    monkeypatch.setattr(addons, "_reinstall_anywhere", lambda: True)

    def start(home, uv, then, cwd, done, reg=None, extra=None):
        # like the real one: a second job is refused while the first is pending
        if started:
            raise winfinish.Busy("an add-on install or update is still finishing in the background")
        started.append((uv, then, reg, done))
        return home

    monkeypatch.setattr(winfinish, "start", start)
    return started


def test_init_recommended_hands_all_addons_to_ONE_finisher(proj, monkeypatch, uv_calls):
    """I11b: init --recommended started one finisher per add-on; the second was refused ('still finishing')
    and every retry only got one more add-on."""
    from orch import init

    started = _windows_with_one_finisher(monkeypatch)
    rows = {
        n: {"name": n, "version": "0.1.0", "description": "d", "background": False}
        for n in ("automation", "dashboard", "focus")
    }
    monkeypatch.setattr(addons, "listing", lambda root: [])
    monkeypatch.setattr(addons, "shipped_recommended", lambda fetch=True: rows)
    monkeypatch.setattr(addons, "discover", lambda: {})
    monkeypatch.setattr(addons, "_is_local", lambda r: False)
    monkeypatch.setattr(addons, "preview_builtin", lambda n: rows[n])
    monkeypatch.setattr(addons, "consent_text", lambda m, x: m["name"])
    assert init.recommended(proj, yes=True) == ["automation", "dashboard", "focus"]
    assert len(started) == 1
    uv, then, reg, done = started[0]
    assert [e["name"] for e in json.loads(reg[1])] == ["automation", "dashboard", "focus"]
    assert then == [["addon", "add", n, "--project-only"] for n in ("automation", "dashboard", "focus")]
    assert "automation, dashboard, focus" in done


def _entry(name):
    return {"name": name, "source": "built-in", "version": "1"}


def _collect(root, name):
    """What add() does for a new add-on inside a batch."""
    addons._batch_for(root).items.append((_entry(name), [["addon", "add", name, "--project-only"]]))


def test_batch_install_installs_nothing_when_one_add_fails(proj, monkeypatch):
    started = _windows_with_one_finisher(monkeypatch)
    with pytest.raises(Refused, match="boom"), addons.batch_install(proj):
        _collect(proj, "automation")
        raise Refused("boom")
    assert started == [] and addons._BATCH.get() is None
    assert addons.consented(proj, "automation") is False


def test_batch_install_on_other_systems_is_one_uv_run(proj, monkeypatch, uv_calls):
    monkeypatch.setattr(winfinish, "needed", lambda: False)
    reexecs = []
    monkeypatch.setattr(addons, "reexec", lambda a: reexecs.append(a))
    monkeypatch.setattr(addons, "record_consent", lambda *a, **k: None)
    with addons.batch_install(proj):
        _collect(proj, "automation")
        _collect(proj, "dashboard")
    assert len(uv_calls) == 1 and len(reexecs) == 2
    assert [e["name"] for e in addons.registry()] == ["automation", "dashboard"]


def test_a_refused_batch_leaves_no_consent(proj, monkeypatch):
    """A finisher is still running: refused before anything is confirmed or recorded (M1)."""
    _windows_with_one_finisher(monkeypatch)
    addons.home().mkdir(parents=True, exist_ok=True)
    (addons.home() / "finish.pending").write_text("starting")
    with pytest.raises(Refused, match="still finishing"), addons.batch_install(proj):
        raise AssertionError("the body must not run")
    # and a refusal inside _reinstall drops the consents the batch wrote
    (addons.home() / "finish.pending").unlink()
    monkeypatch.setattr(addons, "_which_uv", lambda: None)
    with pytest.raises(Refused, match="uv is not installed"), addons.batch_install(proj):
        _collect(proj, "automation")
    assert addons.consented(proj, "automation") is False


def test_partial_failure_undoes_only_this_batchs_items_and_says_so(proj, monkeypatch, uv_calls):
    """POSIX: the project step of the 2nd add-on fails after the 1st one is on (H1). A pre-existing
    active add-on is never touched (L1)."""
    from orch import init

    monkeypatch.setattr(winfinish, "needed", lambda: False)
    on = {"focus": True}  # was on before the batch
    removed = []
    monkeypatch.setattr(addons, "active", lambda root: {k: {} for k, v in on.items() if v})
    monkeypatch.setattr(addons, "remove", lambda root, n, purge=False: removed.append(n) or on.pop(n))
    monkeypatch.setattr(addons, "record_consent", lambda *a, **k: None)
    dropped = []
    monkeypatch.setattr(addons, "drop_consent", lambda root, n: dropped.append(n))

    def reexec(args):
        if args[2] == "dashboard":
            raise Refused("The project step failed (see above).")
        on[args[2]] = True

    monkeypatch.setattr(addons, "reexec", reexec)
    monkeypatch.setattr(addons, "listing", lambda root: [])
    rows = {
        n: {"name": n, "version": "1", "description": "d", "background": False}
        for n in ("automation", "dashboard")
    }
    monkeypatch.setattr(addons, "shipped_recommended", lambda fetch=True: rows)
    monkeypatch.setattr(addons, "discover", lambda: {})
    monkeypatch.setattr(addons, "consent_text", lambda m, x: m["name"])

    def add(root, n, yes=False):
        addons._batch_for(root).items.append((_entry(n), [["addon", "add", n, "--project-only"]]))

    monkeypatch.setattr(addons, "add", add)
    with pytest.raises(Refused) as e:
        init.recommended(proj, yes=True)
    assert removed == ["automation"] and "focus" in on  # only this batch's, focus stays on
    assert sorted(dropped) == ["automation", "dashboard"]
    assert "Turned off again: automation" in str(e.value) and "Nothing was changed" not in str(e.value)


def test_a_failed_batch_with_nothing_on_says_nothing_was_changed(proj, monkeypatch):
    from orch import init

    _windows_with_one_finisher(monkeypatch)
    monkeypatch.setattr(addons, "_which_uv", lambda: None)
    rows = {"automation": {"name": "automation", "version": "1", "description": "d", "background": False}}
    monkeypatch.setattr(addons, "listing", lambda root: [])
    monkeypatch.setattr(addons, "shipped_recommended", lambda fetch=True: rows)
    monkeypatch.setattr(addons, "discover", lambda: {})
    monkeypatch.setattr(addons, "consent_text", lambda m, x: m["name"])
    monkeypatch.setattr(addons, "add", lambda root, n, yes=False: _collect(root, n))
    with pytest.raises(Refused, match="Nothing was changed"):
        init.recommended(proj, yes=True)


def test_a_concurrent_caller_is_not_collected(proj, tmp_path):
    """Another thread's add() (e.g. a dashboard hand-off) never joins a running batch (M2); another folder
    does not either."""
    import threading

    seen = {}
    with addons.batch_install(proj):
        t = threading.Thread(target=lambda: seen.update(thread=addons._batch_for(proj)))
        t.start()
        t.join()
        seen["other"] = addons._batch_for(tmp_path / "elsewhere")
        seen["own"] = addons._batch_for(proj)
    assert seen["thread"] is None and seen["other"] is None and seen["own"] is not None


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("crash", [False, True])
def test_failed_project_step_restores_registry(tmp_path, existing, crash):
    path = tmp_path / "addons.json"
    before = b'[ {"name": "automation"} ]\n'
    if existing:
        path.write_bytes(before)
    job = _job(tmp_path, then_code="import sys; sys.exit(2)")
    if crash:
        job["then"][0]["argv"] = [str(tmp_path / "missing-executable")]
    assert _run_finisher(tmp_path, job).returncode == 1
    assert path.read_bytes() == before if existing else not path.exists()
    assert not (tmp_path / "finish.pending").exists()


@pytest.mark.parametrize("failure", [None, "uv", "then"])
def test_a_failed_finisher_drops_the_consents_of_its_job(tmp_path, failure):
    """#437: init --recommended on Windows recorded consents for all its add-ons before the finisher ran;
    a failed finisher drops exactly those (other workspaces and add-ons keep theirs)."""
    cpath = tmp_path / "consent.json"
    keep = [{"workspace_id": "w1", "name": "focus"}, {"workspace_id": "w2", "name": "dashboard"}]
    cpath.write_text(json.dumps([*keep, {"workspace_id": "w1", "name": "dashboard"}]))
    job = _job(
        tmp_path,
        uv_code="import sys; sys.exit(3)" if failure == "uv" else "pass",
        then_code="import sys; sys.exit(2)" if failure == "then" else "pass",
    )
    job["consents"] = [str(cpath), "w1", ["automation", "dashboard"]]
    assert _run_finisher(tmp_path, job).returncode == (1 if failure else 0)
    left = json.loads(cpath.read_text())
    assert left == keep if failure else len(left) == 3


def test_windows_batch_hands_its_new_consents_to_the_finisher(proj, monkeypatch):
    jobs = []
    monkeypatch.setattr(winfinish, "needed", lambda: True)
    monkeypatch.setattr(addons, "_which_uv", lambda: "uv.exe")
    monkeypatch.setattr(addons, "_reinstall_plan", lambda: None)
    monkeypatch.setattr(addons, "_reinstall_anywhere", lambda: True)
    monkeypatch.setattr(
        winfinish, "start", lambda home, uv, then, cwd, done, reg=None, extra=None: jobs.append(extra) or home
    )
    monkeypatch.setattr(addons, "active", lambda root: {"focus": {}})  # on before: its consent stays
    with addons.batch_install(proj):
        for n in ("automation", "dashboard", "focus"):
            _collect(proj, n)
    wid = addons.workspace_id(proj)
    assert jobs == [{"consents": [str(addons.consent_path()), wid, ["automation", "dashboard"]]}]


@pytest.mark.parametrize("failure", ["ok", "exit", "exception"])
def test_updating_marker_covers_reinstall_and_followup(tmp_path, failure):
    mark = winfinish.marker_path(tmp_path)
    check = f"from pathlib import Path; assert Path({str(mark)!r}).read_text().isdigit(); "
    job = _job(
        tmp_path,
        uv_code=check + ("raise SystemExit(2)" if failure == "exit" else "pass"),
        then_code=check + "pass",
    )
    if failure == "exception":
        job["uv"] = [str(tmp_path / "missing-uv")]
    assert _run_finisher(tmp_path, job).returncode == (0 if failure == "ok" else 1)
    assert not mark.exists()
    assert f"RESULT {'ok' if failure == 'ok' else 'fail'}:" in winfinish.log_path(tmp_path).read_text()
