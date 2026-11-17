"""The scheduled health checks and clean-up (doctorpass.py, `orch doctor pass|soon|setup|clean|...`):
one ticket per problem and none when all is fine, a full disk holds new helpers back, clean-up by exact
path only, and the schedule belongs to no ticket (ORCH-104)."""

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from orch import brake, doctorpass, keystore, tickets

SETUP = {
    "disk": {"warn_gb": 20, "hold_gb": 10, "resume_gb": 12},
    "load_max": 30,
    "urls": [{"name": "dash", "label": "Dashboard front", "url": "http://127.0.0.1:1/"}],
    "processes": [{"name": "guard", "label": "Account guard", "match": "guard.sh", "count": 1}],
    "services": [{"name": "fwd", "label": "Port forwarder", "launch_agent": "x.fwd"}],
}
FINE = {
    "disk_free_gb": 100,
    "load": 1.0,
    "http": {},
    "procs": ["/bin/sh /x/guard.sh"],
    "launch_agents": {"x.fwd": True},
    "logins": [{"name": "claude", "label": "Claude", "state": "works"}],
}


@pytest.fixture
def ws(proj, run):
    assert run("init")[0] == 0
    doctorpass.save_setup(proj, SETUP)
    return proj


def _pass(ws, **sim):
    return doctorpass.run_pass(ws, sim={**FINE, **sim}, cleanup=False)


def _titles(ws):
    return sorted(t["title"] for t in tickets.list_all(ws))


# ------------------------------------------------------------------ setup


def test_setup_lives_in_the_guarded_home_not_the_project(ws):
    assert keystore.record_read(ws, "watch")["urls"][0]["url"] == "http://127.0.0.1:1/"
    assert not any("watch" in p.name for p in (ws / ".orch").rglob("*") if p.is_file())
    assert doctorpass.setup(ws)["every_min"] == 15


@pytest.mark.parametrize(
    "bad",
    [
        {"nope": 1},
        {"urls": [{"name": "a", "label": "A", "url": "file:///etc/passwd"}]},
        {"urls": [{"name": "A!", "label": "A", "url": "http://x/"}]},
        {"urls": [{"name": "a", "label": "x\nInjected", "url": "http://x/"}]},
        {"disk": {"hold_gb": 15, "resume_gb": 12}},
        {"clean": {"test_roots": ["relative/path"]}},
        {"clean": {"test_roots": ["~"]}},
        {"clean": {"base": "--upload-pack=x"}},
        {"every_min": 1},
        {"urls": [{"name": "a", "label": "A", "url": "https://user:pw@x/"}]},
        {"urls": [{"name": "a", "label": "A", "url": "https://x/health?token=abc"}]},
    ],
)
def test_a_bad_setup_is_refused(ws, run, tmp_path, bad):
    f = tmp_path / "bad.json"
    f.write_text(json.dumps(bad))
    code, _, err = run("doctor", "setup", str(f))
    assert code == 2, err
    assert doctorpass.setup(ws)["urls"][0]["name"] == "dash"  # the old one stays


def test_setup_off_stops_everything(ws, run):
    assert run("doctor", "setup", "--off")[0] == 0
    assert doctorpass.setup(ws) is None and not doctorpass.due(ws)
    code, _, err = run("doctor", "pass")
    assert code == 2 and "not set up" in err


# ------------------------------------------------------------------ checks and tickets


def test_all_fine_makes_no_ticket(ws):
    res = _pass(ws)
    assert res["problems"] == [] and res["opened"] == [] and _titles(ws) == []


def test_one_ticket_per_problem_never_a_second_while_open(ws):
    res = _pass(ws, http={"http://127.0.0.1:1/": 0}, procs=[], launch_agents={"x.fwd": False})
    assert sorted(res["problems"]) == ["proc-guard", "svc-fwd", "url-dash"]
    assert _titles(ws) == [
        "Account guard is not running",
        "Dashboard front does not answer",
        "Port forwarder is not running",
    ]
    again = _pass(ws, http={"http://127.0.0.1:1/": 0}, procs=[], launch_agents={"x.fwd": False})
    assert again["opened"] == [] and len(again["kept"]) == 3 and len(_titles(ws)) == 3
    t = tickets.load(ws, res["opened"][0]["ticket"])
    assert "No second ticket" in t["note"] and t["history"][0]["by"] == doctorpass.BY


def test_a_closed_ticket_lets_a_new_one_open(ws):
    tid = _pass(ws, procs=[])["opened"][0]["ticket"]
    tickets.set_status(ws, tid, "dropped", "human:owner")
    res = _pass(ws, procs=[])
    assert res["opened"] and res["opened"][0]["ticket"] != tid


def test_a_problem_that_went_away_is_said_once_on_its_ticket(ws):
    tid = _pass(ws, procs=[])["opened"][0]["ticket"]
    _pass(ws)
    _pass(ws)
    said = [h for h in tickets.load(ws, tid)["history"] if "no longer see" in h.get("text", "")]
    assert len(said) == 1


def test_two_processes_where_one_is_wanted(ws):
    res = _pass(ws, procs=["sh guard.sh", "sh guard.sh"])
    assert res["problems"] == ["proc-guard"] and "runs 2 times" in res["opened"][0]["title"]


def test_load_counts_only_on_two_passes_in_a_row(ws):
    assert _pass(ws, load=50)["problems"] == []
    assert _pass(ws, load=50)["problems"] == ["load"]
    assert _pass(ws, load=2)["problems"] == []


def test_a_login_running_out_is_a_problem(ws):
    res = _pass(
        ws, logins=[{"name": "claude", "label": "Claude", "state": "soon", "ends_at": "2026-11-18T10:00:00Z"}]
    )
    assert res["problems"] == ["login-claude"] and "2026-11-18 10:00" in res["opened"][0]["title"]


def test_dry_run_opens_nothing_and_keeps_no_state(ws):
    res = doctorpass.run_pass(ws, sim={**FINE, "procs": []}, apply=False, cleanup=False)
    assert res["opened"][0]["ticket"] is None and _titles(ws) == [] and doctorpass.last(ws) == {}


def test_problem_tickets_go_under_the_parent_when_set(ws):
    parent = tickets.create(ws, "Machine health", "human:owner")
    doctorpass.save_setup(ws, {**SETUP, "parent": parent["key"]})
    tid = _pass(ws, procs=[])["opened"][0]["ticket"]
    assert tickets.load(ws, tid)["parent"] == parent["id"]


# ------------------------------------------------------------------ full disk


def test_full_disk_holds_helpers_and_lets_go_only_when_it_held_them(ws):
    res = _pass(ws, disk_free_gb=8)
    assert res["hold"] == "paused" and brake.paused(ws)["by"] == doctorpass.BY
    assert "Disk almost full: 8 GB free" in _titles(ws)
    assert _pass(ws, disk_free_gb=11)["hold"] is None and brake.paused(ws)  # between hold and resume: stays
    assert _pass(ws, disk_free_gb=13)["hold"] == "resumed" and brake.paused(ws) is None


def test_a_person_s_pause_is_never_lifted(ws):
    brake.pause(ws, "human:owner", "holiday")
    assert _pass(ws, disk_free_gb=8)["hold"] is None
    assert _pass(ws, disk_free_gb=50)["hold"] is None and brake.paused(ws)["by"] == "human:owner"


def test_warning_without_hold_between_the_limits(ws):
    res = _pass(ws, disk_free_gb=15)
    assert res["problems"] == ["disk"] and res["hold"] is None and brake.paused(ws) is None


# ------------------------------------------------------------------ the schedule


def test_due_after_every_min_and_soon_starts_one_background_pass(ws, monkeypatch):
    assert doctorpass.due(ws)
    _pass(ws)
    assert not doctorpass.due(ws)
    assert doctorpass.due(ws, now=time.time() + 15 * 60 + 1)
    started = []
    monkeypatch.delenv("ORCH_NO_HEALTH_CHECK")
    monkeypatch.setattr(doctorpass.subprocess, "Popen", lambda argv, **kw: started.append((argv, kw)))
    later = time.time() + 16 * 60
    assert doctorpass.soon(ws, now=later)
    assert not doctorpass.soon(ws, now=later + 5)  # at most once a minute
    assert len(started) == 1 and started[0][0][-3:] == ["doctor", "pass", "--json"]
    assert started[0][1]["env"]["ORCH_ROOT"] == str(ws)


def test_soon_does_nothing_without_a_setup(proj, run, monkeypatch):
    assert run("init")[0] == 0
    monkeypatch.delenv("ORCH_NO_HEALTH_CHECK")
    monkeypatch.setattr(doctorpass.subprocess, "Popen", lambda *a, **k: pytest.fail("started"))
    assert doctorpass.soon(proj) is False


def test_the_schedule_ignores_ticket_status_and_pause(ws, monkeypatch):
    """No ticket or repeat carries the checks: all tickets closed and automation paused, a pass is due."""
    t = tickets.create(ws, "Old keeper ticket", "human:owner")
    tickets.set_status(ws, t["id"], "dropped", "human:owner")
    brake.pause(ws, "human:owner")
    assert doctorpass.due(ws)


def test_doctor_shows_when_the_scheduled_checks_stopped(ws, run, monkeypatch):
    from orch import cli_diag

    many = [{"name": f"c{i}", "verdict": "ok", "fact": "fine"} for i in range(5)]
    monkeypatch.setattr(cli_diag, "inspect", lambda root: {"checks": many})
    _pass(ws)
    d = json.loads(run("doctor", "--json")[1])
    assert [r["name"] for r in d["checks"]].count("scheduled checks") == 1  # once, whatever the run checks
    row = next(r for r in d["checks"] if r["name"] == "scheduled checks")
    assert row["ok"]
    old = doctorpass.last(ws)
    old["last_pass"]["at"] = "2020-01-01T00:00:00Z"
    doctorpass.net.write_json(doctorpass._path(ws), old)
    d = json.loads(run("doctor", "--json")[1])
    row = next(r for r in d["checks"] if r["name"] == "scheduled checks")
    assert not row["ok"] and row["next"] == "Run: orch start"


def test_pass_cli_with_simulate(ws, run, tmp_path):
    f = tmp_path / "sim.json"
    f.write_text(json.dumps({**FINE, "procs": []}))
    code, out, _ = run("doctor", "pass", "--simulate", str(f), "--json")
    d = json.loads(out)
    assert code == 0 and d["problems"] == ["proc-guard"] and d["opened"][0]["ticket"]


# ------------------------------------------------------------------ clean-up


def _git(*a, cwd):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


def _age(path: Path, hours: float):
    t = time.time() - hours * 3600
    for p in [path, *path.rglob("*")]:
        os.utime(p, (t, t), follow_symlinks=False)


@pytest.fixture
def repo(tmp_path):
    """A repository with an origin/develop and three copies: merged and idle, changed, and merged but busy."""
    origin = tmp_path / "origin.git"
    _git("init", "-q", "--bare", "-b", "develop", str(origin), cwd=tmp_path)
    main = tmp_path / "main"
    _git("clone", "-q", str(origin), str(main), cwd=tmp_path)
    for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
        _git("config", k, v, cwd=main)
    (main / "a.txt").write_text("a")
    _git("add", ".", cwd=main)
    _git("commit", "-q", "-m", "a", cwd=main)
    _git("push", "-q", "origin", "HEAD:develop", cwd=main)
    copies = tmp_path / "copies"
    copies.mkdir()
    for name in ("done", "dirty", "fresh"):
        _git("worktree", "add", "-q", str(copies / name), "-b", name, "origin/develop", cwd=main)
    (copies / "dirty" / "new.txt").write_text("x")
    for name in ("done", "dirty"):
        _age(copies / name, 5)
    build = copies / "dirty" / "target"
    build.mkdir()
    (build / "CACHEDIR.TAG").write_text("cache tag")
    _age(copies / "dirty", 30)
    return main, copies


def test_clean_removes_only_finished_idle_copies(repo, tmp_path, monkeypatch):
    main, copies = repo
    monkeypatch.setattr(doctorpass, "process_dirs", lambda: [])
    cfg = doctorpass.clean_setup({"clean": {"repos": [str(main)], "worktree_roots": [str(copies)]}})
    listed = doctorpass.clean(cfg, apply=False)
    assert any("would remove finished copy" in x and x.split()[4].endswith("done") for x in listed), listed
    assert (copies / "done").is_dir()
    done = doctorpass.clean(cfg, apply=True)
    assert not (copies / "done").exists()
    assert (copies / "dirty" / "new.txt").is_file() and (copies / "fresh").is_dir()  # changed / recent: kept
    assert not (copies / "dirty" / "target").exists() and any("build output" in x for x in done)


def test_clean_keeps_a_copy_a_process_works_in(repo, monkeypatch):
    main, copies = repo
    monkeypatch.setattr(doctorpass, "process_dirs", lambda: [str((copies / "done").resolve() / "sub")])
    cfg = doctorpass.clean_setup({"clean": {"repos": [str(main)], "worktree_roots": [str(copies)]}})
    doctorpass.clean(cfg, apply=True)
    assert (copies / "done").is_dir()


def test_clean_keeps_everything_when_process_folders_are_unknown(repo, monkeypatch):
    main, copies = repo
    monkeypatch.setattr(doctorpass, "process_dirs", lambda: None)
    cfg = doctorpass.clean_setup({"clean": {"repos": [str(main)], "worktree_roots": [str(copies)]}})
    doctorpass.clean(cfg, apply=True)
    assert (copies / "done").is_dir()


def test_clean_removes_old_mktemp_test_folders_only(tmp_path):
    root = tmp_path / "tests"
    root.mkdir()
    old, new, named, gitty = root / "o104.AbC1", root / "o104.XyZ2", root / "keepme", root / "x.Gh3j"
    for d in (old, new, named, gitty):
        (d / "deep").mkdir(parents=True)
    (gitty / ".git").mkdir()
    for d in (old, named, gitty):
        _age(d, 30)
    cfg = doctorpass.clean_setup({"clean": {"test_roots": [str(root)]}})
    doctorpass.clean(cfg, apply=True)
    assert not old.exists() and new.is_dir() and named.is_dir() and gitty.is_dir()


# ------------------------------------------------------------------ by hand: temp folders and processes


def test_remove_temp_only_own_mktemp_paths(proj, run, tmp_path, monkeypatch):
    assert run("init")[0] == 0
    tmp = tmp_path / "tmproot"
    tmp.mkdir()
    monkeypatch.setattr(doctorpass.tempfile, "gettempdir", lambda: str(tmp))
    mine = tmp / "lane.Ab12"
    (mine / "x").mkdir(parents=True)
    plain = tmp / "important"
    plain.mkdir()
    deep = mine / "x" / "a.Bc34"
    deep.mkdir()
    link = tmp / "link.Cd56"
    link.symlink_to(plain)
    res = {
        r["path"]: r
        for r in doctorpass.remove_temp(proj, [str(plain), str(deep), str(link), str(mine) + "/"])
    }
    assert res[str(plain)]["result"] == "refused" and plain.is_dir()
    assert res[str(deep)]["result"] == "refused"
    assert res[str(link)]["result"] == "refused" and link.is_symlink()
    assert res[str(mine) + "/"]["result"] == "removed" and not mine.exists()


def test_remove_temp_refuses_the_folder_you_stand_in(proj, run, tmp_path, monkeypatch):
    assert run("init")[0] == 0
    tmp = tmp_path / "tmproot"
    here = tmp / "lane.Ab12" / "sub"
    here.mkdir(parents=True)
    monkeypatch.setattr(doctorpass.tempfile, "gettempdir", lambda: str(tmp))
    monkeypatch.chdir(here)
    assert doctorpass.remove_temp(proj, [str(tmp / "lane.Ab12")])[0]["result"] == "refused"


def test_remove_temp_cli_exits_1_on_a_refusal(proj, run, tmp_path):
    assert run("init")[0] == 0
    code, out, _ = run("doctor", "remove-temp", str(tmp_path))
    assert code == 1 and "refused" in out


def _orphan(code: str) -> int:
    """A process that is not our child (as in real use): its parent shell exits at once, so it is never a
    zombie of the test that would still answer kill -0."""
    out = subprocess.run(
        ["sh", "-c", f'{sys.executable} -c "{code}" >/dev/null 2>&1 & echo $!'],
        capture_output=True,
        text=True,
    )
    return int(out.stdout.strip())


def _gone(pid: int) -> bool:
    return not doctorpass._alive(pid)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_stop_pids_stops_exactly_the_given_processes():
    keep = _orphan("import time; time.sleep(60)")
    stop = _orphan("import time; time.sleep(60)")
    try:
        res = doctorpass.stop_pids([str(stop), f"{keep} {stop}", "abc", str(os.getpid())])
        assert [r["result"] for r in res] == ["stopped", "refused", "refused", "refused"]
        assert _gone(stop) and not _gone(keep)
        assert doctorpass.stop_pids([str(stop)])[0]["result"] == "not running"
    finally:
        doctorpass.stop_pids([str(keep)], wait=1)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_stop_pids_kills_one_that_ignores_term():
    pid = _orphan("import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)")
    time.sleep(0.5)  # the handler is set
    res = doctorpass.stop_pids([str(pid)], wait=0.4)
    assert res[0]["result"] == "stopped" and _gone(pid)


def test_at_is_utc_text(ws):
    at = _pass(ws)["at"]
    assert datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) <= datetime.now(UTC)


def test_a_failing_address_shows_only_its_host_on_the_ticket(ws):
    doctorpass.save_setup(
        ws, {**SETUP, "urls": [{"name": "h", "label": "Health", "url": "https://x.example/t0k3n/h"}]}
    )
    tid = _pass(ws, http={"https://x.example/t0k3n/h": 500})["opened"][0]["ticket"]
    note = tickets.load(ws, tid)["note"]
    assert "x.example gave 500" in note and "t0k3n" not in note


def test_a_last_pass_in_the_future_is_not_believed(ws, run):
    _pass(ws)
    old = doctorpass.last(ws)
    old["last_pass"]["at"] = "2099-01-01T00:00:00Z"
    doctorpass.net.write_json(doctorpass._path(ws), old)
    assert doctorpass.due(ws)
    d = json.loads(run("doctor", "--json")[1])
    assert not next(r for r in d["checks"] if r["name"] == "scheduled checks")["ok"]


def test_setup_is_a_person_s_step(ws, run, tmp_path, monkeypatch):
    f = tmp_path / "s.json"
    f.write_text(json.dumps(SETUP))
    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    assert run("doctor", "setup", str(f))[0] == 2
    assert run("doctor", "setup", "--off")[0] == 2 and doctorpass.setup(ws)
    assert run("doctor", "setup")[0] == 0  # showing it is fine


def test_build_output_behind_a_link_is_never_removed(repo, tmp_path, monkeypatch):
    main, copies = repo
    outside = tmp_path / "elsewhere"
    (outside / "target").mkdir(parents=True)
    (outside / "target" / "CACHEDIR.TAG").write_text("cache tag")
    (copies / "dirty" / "relay").symlink_to(outside, target_is_directory=True)
    _age(copies / "dirty", 30)
    monkeypatch.setattr(doctorpass, "process_dirs", lambda: [])
    cfg = doctorpass.clean_setup({"clean": {"repos": [str(main)], "worktree_roots": [str(copies)]}})
    doctorpass.clean(cfg, apply=True)
    assert (outside / "target" / "CACHEDIR.TAG").is_file()


# ------------------------------------------------------------------ repeats that stopped (ORCH-119)

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def _rep(tid, next_run, last_run=None, status="open", **more):
    a = {"recurring": True, "cron": "*/15 * * * *", "next_run": next_run, **more}
    if last_run:
        a["last_run"] = last_run
    return {"id": tid, "key": "DM1-9", "title": "Demo update", "status": status, "ext": {"automation": a}}


def test_a_repeat_late_by_more_than_its_slack_is_overdue():
    on_time = _rep("t_a", "2026-11-17T11:45:00Z", "2026-11-17T11:30:00Z")  # 15 min late: fine
    late = _rep("t_b", "2026-11-17T11:30:00Z", "2026-11-17T11:15:00Z")  # 30 min late, last run 45 min ago
    got = doctorpass.overdue_repeats([on_time, late], NOW, 30)
    assert [r["ticket"] for r in got] == ["t_b"]


def test_a_slow_repeat_gets_one_interval_capped_at_a_day():
    hourly = _rep("t_h", "2026-11-17T11:00:00Z", "2026-11-17T10:00:00Z")  # 1 h late, 1 h interval: overdue
    weekly = _rep("t_w", "2026-11-16T13:00:00Z", "2026-11-09T13:00:00Z")  # 23 h late: not yet
    weekly_late = _rep("t_x", "2026-11-16T11:00:00Z", "2026-11-09T11:00:00Z")  # a day late: overdue
    hourly_ok = _rep("t_k", "2026-11-17T11:30:00Z", "2026-11-17T10:30:00Z")  # 30 min late of an hour
    got = doctorpass.overdue_repeats([hourly, weekly, weekly_late, hourly_ok], NOW, 30)
    assert sorted(r["ticket"] for r in got) == ["t_h", "t_x"]


def test_paused_closed_unplanned_and_not_repeating_are_left_out():
    old = "2026-11-10T00:00:00Z"
    rows = [
        _rep("t_p", old, paused=True),
        _rep("t_d", old, status="dropped"),
        _rep("t_n", None),
        {"id": "t_r", "status": "open", "ext": {"automation": {"cron": "* * * * *", "last_run": old}}},
        _rep("t_f", "not a time"),
        {"id": "t_plain", "status": "open"},
        _rep("t_done", old, status="done"),  # a finished repeat still runs again: counted
    ]
    assert [r["ticket"] for r in doctorpass.overdue_repeats(rows, NOW, 30)] == ["t_done"]


def test_the_pass_opens_one_ticket_for_a_stopped_repeat(ws):
    rows = [_rep("t_b", "2026-11-17T11:00:00Z", "2026-11-17T10:45:00Z")]
    res = doctorpass.run_pass(ws, sim={**FINE, "repeats": rows}, cleanup=False, now=NOW)
    assert res["problems"] == ["repeat-t_b"]
    assert _titles(ws) == ["Repeat stopped: Demo update"]
    t = tickets.load(ws, res["opened"][0]["ticket"])
    assert "2026-11-17 11:00 UTC" in t["note"] and "2026-11-17 10:45 UTC" in t["note"]
    again = doctorpass.run_pass(ws, sim={**FINE, "repeats": rows}, cleanup=False, now=NOW)
    assert again["opened"] == [] and len(_titles(ws)) == 1


def test_the_pass_reads_repeats_from_the_real_tickets(ws):
    t = tickets.create(ws, "Report watcher", "human:owner")
    a = {"recurring": True, "cron": "*/15 * * * *", "next_run": "2026-11-17T10:00:00Z"}
    tickets.ext_set(ws, t["id"], "automation", json.dumps(a), "human:owner")
    res = doctorpass.run_pass(ws, sim=FINE, cleanup=False, now=NOW)
    assert res["problems"] == [f"repeat-{t['id']}"]
    later = datetime(2026, 11, 17, 10, 10, tzinfo=UTC)  # before the planned time passed long: nothing
    assert doctorpass.checks(doctorpass.setup(ws), doctorpass.Probes(ws, FINE, later), {}) == []


def test_late_min_comes_from_the_setup(ws):
    doctorpass.save_setup(ws, {**SETUP, "repeats": {"late_min": 120}})
    rows = [_rep("t_b", "2026-11-17T11:00:00Z", "2026-11-17T10:45:00Z")]  # 1 h late < 2 h
    assert doctorpass.run_pass(ws, sim={**FINE, "repeats": rows}, cleanup=False, now=NOW)["problems"] == []


# ------------------------------------------------------------------ weekly account use (ORCH-119)

ACC = {"command": ["cswap", "list", "--json"], "cap_pct": 95}


def _switcher(*pcts):
    return {
        "schemaVersion": 1,
        "accounts": [
            {"number": i, "usage": {"sevenDay": {"pct": p, "resetsAt": f"2026-11-1{8 + i}T20:00:00+00:00"}}}
            for i, p in enumerate(pcts)
        ],
    }


def test_week_use_reads_both_shapes_and_skips_the_rest():
    assert [w["pct"] for w in doctorpass.week_use(_switcher(100.0, 96))] == [100.0, 96.0]
    own = {"accounts": [{"week_pct": 97, "week_resets_at": "2026-11-18T20:00:00Z"}, {"week_pct": "x"}]}
    assert [w["pct"] for w in doctorpass.week_use(own)] == [97.0]
    assert doctorpass.week_use([{"week_pct": 50, "disabled": True}, {"usage": None}, 3]) == []
    assert doctorpass.week_use(None) == [] and doctorpass.week_use("text for people") == []


def test_every_account_used_up_opens_one_ticket(ws):
    doctorpass.save_setup(ws, {**SETUP, "accounts": ACC})
    res = _pass(ws, accounts=_switcher(100.0, 95.0))
    assert res["problems"] == ["accounts-week"]
    t = tickets.load(ws, res["opened"][0]["ticket"])
    assert t["title"] == "Every account has used up its week"
    assert "100%, 95%" in t["note"] and "2026-11-18 20:00 UTC" in t["note"]


def test_one_account_with_room_or_no_reading_is_no_problem(ws):
    doctorpass.save_setup(ws, {**SETUP, "accounts": ACC})
    assert _pass(ws, accounts=_switcher(100.0, 94.0))["problems"] == []
    assert _pass(ws, accounts=None)["problems"] == []
    assert _pass(ws, accounts={"accounts": []})["problems"] == []


def test_without_an_account_command_nothing_is_read(ws):
    assert "accounts" not in doctorpass.setup(ws)
    assert _pass(ws, accounts=_switcher(100.0))["problems"] == []


def test_the_account_command_runs_without_a_shell(ws, tmp_path):
    out = tmp_path / "use.json"
    out.write_text(json.dumps({"accounts": [{"week_pct": 99}, {"week_pct": 98}]}))
    code = f"import sys; sys.stdout.write(open({str(out)!r}).read())"
    doctorpass.save_setup(ws, {**SETUP, "accounts": {"command": [sys.executable, "-c", code]}})
    p = doctorpass.Probes(ws, FINE)
    assert [
        w["pct"] for w in doctorpass.week_use(p.accounts(doctorpass.setup(ws)["accounts"]["command"]))
    ] == [
        99.0,
        98.0,
    ]
    assert p.accounts(["no-such-command-orch-119"]) is None
    assert (
        p.accounts([sys.executable, "-c", "print('Account 1: 99%')"]) is None
    )  # text for people is not read
    assert p.accounts([sys.executable, "-c", "raise SystemExit(3)"]) is None


@pytest.mark.parametrize(
    "bad",
    [
        {"accounts": {"command": "cswap list --json"}},
        {"accounts": {"command": []}},
        {"accounts": {"command": ["cswap"], "cap_pct": 0}},
        {"accounts": {"command": ["cswap"], "other": 1}},
        {"repeats": {"late_min": 1}},
        {"repeats": {"every": 5}},
    ],
)
def test_a_bad_repeats_or_accounts_setup_is_refused(bad):
    with pytest.raises(doctorpass.Refused):
        doctorpass.clean_setup({**SETUP, **bad})
