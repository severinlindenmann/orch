"""Several add-ons in one run (orch addon add a b c) and the add-on job file a page reads (ORCH-1739)."""

import json
import os
import subprocess
import sys
import time

import pytest
from test_addons import make_addon

from orch import addonjob, addons, autoupdate, cli, diag_incident, restartlater, winfinish
from orch.errors import Refused


def _titled(name):
    return lambda text: text.replace('label = "Hello"', f'label = "{name.capitalize()}"')


@pytest.fixture
def run(capfd):
    def _run(*argv):
        code = cli.main(list(argv))
        cap = capfd.readouterr()
        return code, cap.out, cap.err

    return _run


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A local source with alpha, beta (needs alpha) and gamma. 'Installing' makes the packages named in the
    uv call importable and registers their entry points; the project step runs in process."""
    base = tmp_path / "repo"
    make_addon(base / "workspace-addons", "alpha", mutate=_titled("alpha"))
    make_addon(base / "workspace-addons", "beta", extra='requires = ["alpha"]', mutate=_titled("beta"))
    make_addon(base / "workspace-addons", "gamma", mutate=_titled("gamma"))
    monkeypatch.setenv("ORCH_REPO", str(base))
    monkeypatch.setattr(winfinish, "needed", lambda: False)
    eps = {}
    monkeypatch.setattr(addons, "_entry_points", lambda: dict(eps))
    calls, added = [], []

    def fake_uv(args):
        calls.append(args)
        eps.clear()
        for n in ("alpha", "beta", "gamma"):
            src = base / "workspace-addons" / n
            if any(str(src.resolve()) in a for a in args):
                if str(src / "src") not in sys.path:
                    sys.path.insert(0, str(src / "src"))
                    added.append(str(src / "src"))
                eps[n] = f"orch_{n}"

    monkeypatch.setattr(addons, "run_uv", fake_uv)
    steps = []

    def reexec(args):
        steps.append(args)
        if os.environ.get("FAIL_STEP") == args[2]:
            raise Refused("The project step failed (see above).")
        if cli.main(args) != 0:
            raise Refused("project step failed")

    monkeypatch.setattr(addons, "reexec", reexec)
    yield {"uv": calls, "steps": steps}
    for p in added:
        if p in sys.path:
            sys.path.remove(p)


def _job():
    return json.loads((addons.home() / addonjob.FILE).read_text(encoding="utf-8"))


def _states(job):
    return {s["key"]: s["state"] for s in job["steps"]}


def _write(job):
    addons.home().mkdir(parents=True, exist_ok=True)
    (addons.home() / addonjob.FILE).write_text(json.dumps(job), encoding="utf-8")


def _dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _base(proj, **kw):
    job = addonjob._new(proj, ["alpha", "gamma"], os.getpid())
    job.update(kw)
    return job


# ------------------------------------------------------------------ several names in one run


def test_several_names_are_one_reinstall_and_one_restart(proj, run, repo, monkeypatch):
    restarts = []
    monkeypatch.setattr(addons, "_restart_updated", lambda root=None: restarts.append(root) or [])
    code, _, err = run("addon", "add", "alpha", "gamma", "--yes")
    assert code == 0, err
    assert len(repo["uv"]) == 1 and len(restarts) == 1
    assert {"alpha", "gamma"} <= set(addons.active(proj))
    assert sorted(e["name"] for e in addons.registry()) == ["alpha", "gamma"]


def test_a_needed_add_on_picked_together_is_turned_on_first(proj, run, repo):
    code, _, err = run("addon", "add", "beta", "alpha", "--yes")
    assert code == 0, err
    assert [s[2] for s in repo["steps"]] == ["alpha", "beta"]
    assert len(repo["uv"]) == 1 and {"alpha", "beta"} <= set(addons.active(proj))


def test_a_needed_add_on_that_was_not_picked_is_refused_plainly(proj, run, repo):
    code, _, err = run("addon", "add", "beta", "gamma", "--yes")
    assert code == 2 and "Beta needs Alpha. Add it together with Beta." in err
    assert not repo["uv"] and not addons.active(proj)


def test_one_name_still_says_what_to_turn_on_first(proj, run, repo):
    code, _, err = run("addon", "add", "beta", "--yes")
    assert code == 2 and "needs alpha to be on first" in err and not repo["uv"]


def test_several_installed_add_ons_turn_on_without_a_reinstall(proj, run, repo):
    assert run("addon", "add", "alpha", "beta", "--yes")[0] == 0
    run("addon", "remove", "alpha")
    run("addon", "remove", "beta")
    repo["uv"].clear()
    repo["steps"].clear()
    code, _, err = run("addon", "add", "beta", "alpha", "--yes", "--job")
    assert code == 0, err
    assert not repo["uv"] and [s[2] for s in repo["steps"]] == ["alpha", "beta"]
    job = _job()
    assert job["state"] == "finished" and _states(job)["restart"] == "skipped"
    assert _states(job)["on:alpha"] == _states(job)["on:beta"] == "done"


def test_a_folder_is_added_on_its_own(proj, run, repo, tmp_path):
    code, _, err = run("addon", "add", "alpha", str(tmp_path), "--yes")
    assert code == 2 and "on its own" in err and not repo["uv"]


# ------------------------------------------------------------------ the job file from the command


def test_job_file_steps_on_success(proj, run, repo, monkeypatch):
    monkeypatch.setattr(addons, "_restart_updated", lambda root=None: ["Restarted: dashboard"])
    code, _, err = run("addon", "add", "beta", "alpha", "--yes", "--job")
    assert code == 0, err
    job = _job()
    assert job["state"] == "finished" and job["workspace"] == str(proj.resolve()) and job["ended"]
    assert [s["key"] for s in job["steps"]] == ["ready", "on:alpha", "on:beta", "restart"]
    assert set(_states(job).values()) == {"done"}
    assert job["steps"][0]["label"] == "Getting Alpha and Beta ready"
    assert job["steps"][1]["label"] == "Turning on Alpha"
    assert oct((addons.home() / addonjob.FILE).stat().st_mode & 0o777) == "0o600" or os.name == "nt"
    assert addonjob.read(proj)["here"] is True and not addonjob.live()


def test_job_file_steps_on_failure_with_rollback(proj, run, repo, monkeypatch):
    monkeypatch.setenv("FAIL_STEP", "gamma")
    code, _, err = run("addon", "add", "alpha", "gamma", "--yes", "--job")
    assert code == 2
    job = _job()
    assert job["state"] == "failed" and job["failed"] == "gamma"
    assert _states(job) == {
        "ready": "done",
        "on:alpha": "done",
        "on:gamma": "failed",
        "restart": "skipped",
        "rollback": "done",
    }
    assert job["reason"] == "The project step failed (see above)."
    assert len(repo["uv"]) == 2  # the run's install, then the one that puts things back
    assert not addons.active(proj) and addons.registry() == []


def test_a_failed_restart_fails_the_job_with_a_plain_reason(proj, run, repo, monkeypatch):
    monkeypatch.setattr(
        addons, "_restart_updated", lambda root=None: ["Restart dashboard (w) to use the new version (x)"]
    )
    assert run("addon", "add", "alpha", "--yes", "--job")[0] == 0
    job = _job()
    assert job["state"] == "failed" and job["reason"] == addonjob.RESTART_FAILED
    assert _states(job)["restart"] == "failed"


def test_called_by_a_service_the_restart_helper_finishes_the_job(proj, run, repo, monkeypatch):
    handed = []
    monkeypatch.setattr(addons, "_called_by_a_service", lambda: True)
    monkeypatch.setattr(addons, "_restart_later", lambda root, start=(), job=None: handed.append(job))
    assert run("addon", "add", "alpha", "gamma", "--yes", "--job")[0] == 0
    job = _job()
    assert handed == [job["id"]] and job["state"] == "restarting" and _states(job)["restart"] == "running"
    assert addonjob.live()  # the command has ended; the restart is still to come
    monkeypatch.setattr(addons, "_restart_updated", lambda root=None: ["Restarted: dashboard"])
    monkeypatch.setattr(addons, "_start_added", lambda root, names: [])
    monkeypatch.setattr(restartlater.time, "sleep", lambda s: None)
    assert restartlater.main([str(proj), str(_dead_pid()), "alpha", f"--job={job['id']}"]) == 0
    job = _job()
    assert job["state"] == "finished" and _states(job)["restart"] == "done"


def test_restart_helper_marks_a_failed_restart(proj):
    job = _base(proj, state="restarting")
    _write(job)
    addonjob.restarted(["gamma did not start: port in use"], job["id"])
    got = _job()
    assert got["state"] == "failed" and got["reason"] == addonjob.RESTART_FAILED


def test_a_command_attaches_to_the_job_launch_made(proj, repo, run, monkeypatch):
    job = _base(proj)
    _write(job)
    monkeypatch.setenv(addonjob.ENV, job["id"])
    assert run("addon", "add", "alpha", "gamma", "--yes", "--job")[0] == 0
    got = _job()
    assert got["id"] == job["id"] and got["state"] == "finished"


def test_job_refused_while_another_runs(proj, run, repo):
    _write(_base(proj))
    code, _, err = run("addon", "add", "alpha", "--yes", "--job")
    assert code == 2 and addonjob.BUSY in err and not repo["uv"]


# ------------------------------------------------------------------ the page side


def test_stale_pid_is_failed_and_says_nothing_was_changed(proj):
    _write(_base(proj, pid=_dead_pid()))
    job = addonjob.read(proj)
    assert job["state"] == "failed" and job["reason"] == addonjob.STOPPED_UNCHANGED
    assert set(_states(job).values()) == {"skipped"}
    assert _job()["state"] == "failed"  # stored, not only shown


def test_stale_pid_after_the_list_changed_says_check_it(proj):
    _write(_base(proj, pid=_dead_pid()))
    addons.registry_path().parent.mkdir(parents=True, exist_ok=True)
    addons.registry_path().write_text("[]", encoding="utf-8")
    assert addonjob.read()["reason"] == addonjob.STOPPED_CHANGED


def test_a_restart_gets_its_grace_time_after_the_command_ended(proj):
    _write(_base(proj, pid=_dead_pid(), state="restarting"))
    assert addonjob.read()["state"] == "restarting"
    job = _job()
    job["at"] = int(time.time()) - addonjob.RESTART_GRACE - 5
    (addons.home() / addonjob.FILE).write_text(json.dumps(job), encoding="utf-8")
    assert addonjob.read()["state"] == "failed"


def test_a_run_longer_than_30_minutes_is_failed(proj):
    _write(_base(proj, started=int(time.time()) - addonjob.HARD_STOP - 1))
    job = addonjob.read()
    assert job["state"] == "failed" and job["reason"] == addonjob.TOO_LONG


def test_a_result_is_kept_10_minutes(proj):
    job = _base(proj, state="finished", ended=int(time.time()) - addonjob.KEEP + 30)
    _write(job)
    assert addonjob.read(proj)["state"] == "finished"
    assert addonjob.read(proj)["state"] == "finished"  # a second tab sees it too
    job["ended"] = int(time.time()) - addonjob.KEEP - 1
    _write(job)
    assert addonjob.read(proj) is None and not (addons.home() / addonjob.FILE).exists()


def test_here_is_false_for_another_workspace(proj, tmp_path):
    _write(_base(proj))
    assert addonjob.read(tmp_path / "elsewhere")["here"] is False
    assert "registry" not in addonjob.read(proj)


def test_windows_result_comes_from_the_finisher_log(proj, monkeypatch):
    home = addons.home()
    home.mkdir(parents=True, exist_ok=True)
    log = winfinish.log_path(home)
    log.write_text("RESULT fail: old run\n", encoding="utf-8")
    offset = log.stat().st_size
    _write(_base(proj, pid=_dead_pid(), finish_offset=offset))
    monkeypatch.setattr(winfinish, "pending", lambda h: True)
    assert addonjob.read()["state"] == "running"  # the command has exited; the finisher still works
    monkeypatch.setattr(winfinish, "pending", lambda h: False)
    with log.open("a", encoding="utf-8") as f:
        f.write("RESULT ok: alpha, gamma installed and turned on\n")
    job = addonjob.read()
    assert job["state"] == "finished" and set(_states(job).values()) == {"done"}
    assert "finish_offset" not in job


def test_windows_failure_takes_the_finisher_reason(proj, monkeypatch):
    home = addons.home()
    home.mkdir(parents=True, exist_ok=True)
    _write(_base(proj, pid=_dead_pid(), finish_offset=0))
    winfinish.log_path(home).write_text("RESULT fail: reinstall failed\n", encoding="utf-8")
    monkeypatch.setattr(winfinish, "pending", lambda h: False)
    job = addonjob.read()
    assert job["state"] == "failed" and job["reason"] == "The reinstall failed. Run the update again."


def test_windows_command_stores_the_finisher_offset(proj, monkeypatch):
    monkeypatch.setattr(winfinish, "needed", lambda: True)
    monkeypatch.setattr(addons, "_which_uv", lambda: "uv.exe")
    monkeypatch.setattr(addons, "_reinstall_plan", lambda: None)
    monkeypatch.setattr(addons, "_reinstall_anywhere", lambda: True)
    monkeypatch.setattr(addons, "record_consent", lambda *a, **k: None)
    monkeypatch.setattr(winfinish, "start", lambda *a, **k: addons.home())
    addons.home().mkdir(parents=True, exist_ok=True)
    winfinish.log_path(addons.home()).write_text("old\n", encoding="utf-8")
    addonjob.attach(proj, ["alpha", "gamma"])
    try:
        with addons.batch_install(proj):
            for n in ("alpha", "gamma"):
                entry = {"name": n, "source": "built-in", "version": "1"}
                addons._batch_for(proj).items.append((entry, [["addon", "add", n, "--project-only"]]))
        addonjob.finish()  # left to the finisher: still running
    finally:
        addonjob.detach()
    job = _job()
    assert job["finish_offset"] == 4 and job["state"] == "running" and _states(job)["ready"] == "running"


def test_launch_writes_the_job_first_and_starts_the_command(proj, monkeypatch):
    started = []

    class P:
        pid = 4242

    def popen(argv, **kw):
        started.append((argv, kw))
        assert _job()["state"] == "running"  # the file is there before the command starts
        return P()

    monkeypatch.setattr(addonjob, "_popen", popen)
    monkeypatch.setattr(addonjob, "_update_running", lambda: False)
    job = addonjob.launch(proj, ["gamma", "alpha"], "/bin/orch-fake", {"PATH": "/usr/bin"})
    argv, kw = started[0]
    assert argv == ["/bin/orch-fake", "addon", "add", "gamma", "alpha", "--yes", "--job"]
    assert kw["cwd"] == str(proj.resolve()) and kw["env"][addonjob.ENV] == job["id"]
    assert kw["env"]["ORCH_BIN"] == "/bin/orch-fake"
    assert job["pid"] == 4242 and job["here"] is True and _job()["pid"] == 4242
    assert {s["state"] for s in job["steps"]} == {"waiting"}
    assert not (addons.home() / "update-status.json").exists()


def test_launch_refuses_while_a_job_is_live(proj, monkeypatch):
    monkeypatch.setattr(addonjob, "_popen", lambda *a, **k: pytest.fail("started"))
    _write(_base(proj))
    with pytest.raises(Refused, match="already adding add-ons"):
        addonjob.launch(proj, ["alpha"], "/bin/orch-fake", {})


def test_launch_refuses_while_orch_updates(proj, monkeypatch):
    monkeypatch.setattr(addonjob, "_popen", lambda *a, **k: pytest.fail("started"))
    monkeypatch.setattr(addonjob, "_update_running", lambda: True)
    with pytest.raises(Refused, match="being updated"):
        addonjob.launch(proj, ["alpha"], "/bin/orch-fake", {})
    with pytest.raises(Refused, match="Pick at least one"):
        addonjob.launch(proj, ["Bad Name"], "/bin/orch-fake", {})


def test_plain_reason_has_no_paths_or_log_pointer():
    r = addonjob.plain_reason(
        Refused("Still finishing in /Users/x/.orch-tool/here now. Log: /a/b/finish.log")
    )
    assert "/" not in r and "Log" not in r and r.startswith("Still finishing in")
    assert "went wrong" in addonjob.plain_reason(RuntimeError("Traceback /a/b/c"))
    assert len(addonjob.plain_reason(Refused("x" * 500 + " y"))) <= 200


# ------------------------------------------------------------------ the rest of orch sees the job


def test_autoupdate_waits_for_a_live_job(proj, monkeypatch):
    monkeypatch.setattr(autoupdate, "_helpers_at_work", lambda roots: 0)
    monkeypatch.setattr(autoupdate, "_update_under_way", lambda: False)
    monkeypatch.setattr(autoupdate, "_services_busy", lambda: False)
    assert autoupdate.busy_reason(proj) is None
    _write(_base(proj))
    assert autoupdate.busy_reason(proj) == "add-ons are being added"


def test_busy_and_refused_are_not_crash_incidents(proj, monkeypatch):
    seen = []
    monkeypatch.setattr(diag_incident, "capture", lambda root, reason, **k: seen.append(reason) or "x")
    assert diag_incident.on_crash(proj, winfinish.Busy("still finishing")) is None
    assert diag_incident.on_crash(proj, Refused("no")) is None
    assert not seen
    assert diag_incident.on_crash(proj, RuntimeError("real")) == "x" and seen == ["crash"]


def test_a_reinstall_while_another_runs_is_a_plain_refusal(proj, monkeypatch):
    monkeypatch.setattr(addons, "_reinstall_plan", lambda: None)
    monkeypatch.setattr(addons, "_reinstall_anywhere", lambda: True)
    home = addons.home()
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(winfinish, "updating", lambda h: True)
    with pytest.raises(Refused, match="still updating"):
        addons._install_tool([])
