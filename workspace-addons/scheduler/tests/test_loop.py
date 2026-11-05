import json
from datetime import UTC, datetime

from conftest import T, add_ticket, calls

from orch_scheduler.loop import Scheduler
from orch_scheduler.runner import load_state


def finish(s, now):
    s.runner.reap(now, wait=True)


def test_wake_at_runs_agent_once(ws):
    add_ticket(ws, "t_wake001", status="waiting", wake_at="2026-11-04T08:00:00Z")
    s = Scheduler(ws)
    assert s.tick(T(7, 59)) == []
    assert s.tick(T(8, 1)) == ["t_wake001"]
    finish(s, T(8, 2))
    ran = (ws / "ran-t_wake001.txt").read_text()
    assert "Continue orch ticket t_wake001" in ran and ".agents/skills/orch/SKILL.md" in ran
    t = json.loads((ws / ".orch/tickets/t_wake001.json").read_text())
    assert t["wake_at"] is None and t["status"] == "active"
    cs = calls(ws)
    assert ["wait", "t_wake001", "--clear"] in [c["args"] for c in cs]
    assert [c["args"][0] for c in cs].count("log") == 2  # started + finished
    assert all(c["by"] == "agent:scheduler" for c in cs if c["args"][0] == "log")
    assert s.tick(T(8, 5)) == []  # not again
    st = load_state(ws)["t_wake001"]
    assert st["last_exit"] == 0 and st["last_log"].startswith("t_wake001-")


def test_log_has_start_end_exit(ws):
    add_ticket(ws, "t_wake002", wake_at="2026-11-04T08:00:00Z")
    s = Scheduler(ws)
    s.tick(T(8, 0))
    finish(s, T(8, 1))
    log = next((ws / ".orch/scheduler/logs").glob("t_wake002-*.log")).read_text()
    assert "# start 2026-11-04T08:00:00Z" in log and "agent ran" in log and " exit 0" in log
    # the footer carries the real end time, not the pass start time passed to reap()
    end = next(line for line in log.splitlines() if line.startswith("# end "))
    stamp = datetime.strptime(end.split()[2], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert abs((datetime.now(UTC) - stamp).total_seconds()) < 120


def test_done_ticket_not_woken(ws):
    add_ticket(ws, "t_wake003", status="done", wake_at="2026-11-04T08:00:00Z")
    assert Scheduler(ws).tick(T(9)) == []


def test_recurring_cron_and_catch_up(ws):
    add_ticket(ws, "t_rec00001", type="recurring", created_at="2026-11-01T00:00:00Z",
               ext={"scheduler": {"cron": "0 7 * * *"}})
    s = Scheduler(ws)
    assert s.tick(T(8, 0, d=4)) == ["t_rec00001"]  # 3 missed days -> one run
    finish(s, T(8, 1, d=4))
    assert s.tick(T(8, 2, d=4)) == []
    assert load_state(ws)["t_rec00001"]["next_run"] == "2026-11-05T07:00:00Z"
    assert s.tick(T(7, 1, d=5)) == ["t_rec00001"]
    finish(s, T(7, 2, d=5))


def test_one_run_per_ticket(ws, tmp_path):
    slow = tmp_path / "slow.py"
    slow.write_text("import time; time.sleep(1.5)")
    import sys
    (ws / ".orch/scheduler/config.toml").write_text(f"agent = '{sys.executable} {slow} {{prompt}}'\n")
    add_ticket(ws, "t_rec00002", type="recurring", ext={"scheduler": {"cron": "* * * * *"}})
    s = Scheduler(ws)
    assert s.tick(T(8, 0)) == ["t_rec00002"]
    assert s.tick(T(8, 1)) == []  # recurring is due again but still running
    finish(s, T(8, 2))
    assert s.tick(T(8, 3)) == ["t_rec00002"]
    finish(s, T(8, 4))


def test_stale_lock_is_ignored(ws):
    add_ticket(ws, "t_wake005", wake_at="2026-11-04T08:00:00Z")
    (ws / ".orch/scheduler/locks").mkdir(parents=True)
    (ws / ".orch/scheduler/locks/t_wake005.lock").write_text("999999")
    s = Scheduler(ws)
    assert s.tick(T(8, 0)) == ["t_wake005"]
    finish(s, T(8, 1))


def test_agent_exit_code_and_missing_command(ws):
    (ws / ".orch/scheduler/config.toml").write_text("agent = 'no-such-agent-xyz {prompt}'\n")
    add_ticket(ws, "t_wake006", wake_at="2026-11-04T08:00:00Z")
    s = Scheduler(ws)
    assert s.tick(T(8, 0)) == []
    assert load_state(ws)["t_wake006"]["last_exit"] == 127
    assert not (ws / ".orch/scheduler/locks/t_wake006.lock").exists()


def test_ticket_agent_override_by_name(ws, tmp_path):
    import sys
    other = tmp_path / "other.py"
    other.write_text("open('other.txt', 'w').close()")
    cfg = ws / ".orch/scheduler/config.toml"
    cfg.write_text(cfg.read_text() + f"[agents]\nother = '{sys.executable} {other} {{prompt}}'\n")
    add_ticket(ws, "t_wake007", wake_at="2026-11-04T08:00:00Z", ext={"scheduler": {"agent": "other"}})
    s = Scheduler(ws)
    s.tick(T(8, 0))
    finish(s, T(8, 1))
    assert (ws / "other.txt").exists()


def test_cli_run_once_subprocess(ws):
    from orch_scheduler.cli import main
    add_ticket(ws, "t_wake008", wake_at="2020-01-01T00:00:00Z")
    assert main(["--dir", str(ws), "run", "--once"]) == 0
    assert (ws / "ran-t_wake008.txt").exists()


def test_ticket_cannot_supply_raw_command(ws, tmp_path):
    import sys
    evil = tmp_path / "evil.py"
    evil.write_text("open('evil.txt', 'w').close()")
    add_ticket(ws, "t_wake010", wake_at="2026-11-04T08:00:00Z",
               ext={"scheduler": {"agent": f"{sys.executable} {evil} {{prompt}}"}})
    s = Scheduler(ws)
    s.tick(T(8, 0))
    finish(s, T(8, 1))
    assert not (ws / "evil.txt").exists() and (ws / "ran-t_wake010.txt").exists()


def test_invalid_ticket_id_skipped(ws):
    (ws / ".orch/tickets/t_bad.json").write_text(
        json.dumps({"id": "t_../../escape", "status": "open", "wake_at": "2026-11-04T08:00:00Z"}))
    assert Scheduler(ws).tick(T(9)) == []


# -- draft superagent: S1 wake order, S2 pending, S3 env, S4 alive, S5 failed ---------------------
def _slow_cfg(ws, tmp_path, secs=1.5):
    import sys
    slow = tmp_path / "slow.py"
    slow.write_text(f"import time; time.sleep({secs})")
    (ws / ".orch/scheduler/config.toml").write_text(f"agent = '{sys.executable} {slow} {{prompt}}'\n")


def test_wake_clears_through_cli_after_start(ws):
    add_ticket(ws, "t_wake020", status="waiting", wake_at="2026-11-04T08:00:00Z")
    s = Scheduler(ws)
    assert s.tick(T(8, 1)) == ["t_wake020"]
    finish(s, T(8, 2))
    names = [c["args"][0] for c in calls(ws)]
    i_log = next(i for i, c in enumerate(calls(ws)) if c["args"][0] == "log")
    assert ["wait", "t_wake020", "--clear"] in [c["args"] for c in calls(ws)]
    assert calls(ws)[i_log]["args"][0] == "log" and names.index("wait") > i_log  # started first, cleared after
    assert json.loads((ws / ".orch/tickets/t_wake020.json").read_text())["wake_at"] is None


def test_wake_stays_set_if_start_fails(ws):
    (ws / ".orch/scheduler/config.toml").write_text("agent = 'no-such-agent-xyz {prompt}'\n")
    add_ticket(ws, "t_wake021", status="waiting", wake_at="2026-11-04T08:00:00Z")
    s = Scheduler(ws)
    assert s.tick(T(8, 1)) == []
    t = json.loads((ws / ".orch/tickets/t_wake021.json").read_text())
    assert t["wake_at"] == "2026-11-04T08:00:00Z" and t["status"] == "waiting"
    assert "wait" not in [c["args"][0] for c in calls(ws)]


def test_pending_wake_while_running_starts_after_reap(ws, tmp_path):
    _slow_cfg(ws, tmp_path)
    add_ticket(ws, "t_rec00030", type="recurring", ext={"scheduler": {"cron": "* * * * *"}})
    s = Scheduler(ws)
    assert s.tick(T(8, 0)) == ["t_rec00030"]
    t = json.loads((ws / ".orch/tickets/t_rec00030.json").read_text())
    t["wake_at"] = "2026-11-04T08:00:30Z"
    (ws / ".orch/tickets/t_rec00030.json").write_text(json.dumps(t))
    s.tick(T(8, 1))  # still running: wake recorded as pending, not lost
    assert load_state(ws)["t_rec00030"]["pending_wake"]
    finish(s, T(8, 2))
    assert s.tick(T(8, 2)) == ["t_rec00030"]
    assert not load_state(ws)["t_rec00030"].get("pending_wake")
    finish(s, T(8, 3))


def test_pending_wake_for_applied_answer(ws, tmp_path):
    _slow_cfg(ws, tmp_path)
    add_ticket(ws, "t_pend0031", status="active", wake_at="2026-11-04T08:00:00Z")
    s = Scheduler(ws)
    assert s.tick(T(8, 0)) == ["t_pend0031"]
    (ws / ".orch/secrets").mkdir()
    (ws / ".orch/secrets/relay.json").write_text("{}")
    (ws / "inbox.json").write_text(json.dumps(
        [{"id": "m1", "type": "answer", "applied": True, "ticket": "t_pend0031", "from": "ph_x", "body": {"answer": "yes"}}]))
    s.tick(T(8, 1))
    assert load_state(ws)["t_pend0031"]["pending_wake"]
    finish(s, T(8, 2))
    assert s.tick(T(8, 2)) == ["t_pend0031"]
    finish(s, T(8, 3))


def test_run_env_has_agent_and_ticket(ws, tmp_path):
    import sys
    a = tmp_path / "envagent.py"
    a.write_text("import os; open('env.txt','w').write(os.environ.get('ORCH_AGENT','')+' '+os.environ.get('ORCH_TICKET',''))")
    (ws / ".orch/scheduler/config.toml").write_text(f"agent = '{sys.executable} {a} {{prompt}}'\n")
    add_ticket(ws, "t_env00001", wake_at="2026-11-04T08:00:00Z")
    s = Scheduler(ws)
    s.tick(T(8, 1))
    finish(s, T(8, 2))
    assert (ws / "env.txt").read_text() == "1 t_env00001"


def test_alive_windows_does_not_use_os_kill(monkeypatch):
    import os

    from orch_scheduler import runner
    monkeypatch.setattr(runner.sys, "platform", "win32")
    monkeypatch.setattr(os, "kill", lambda *a: (_ for _ in ()).throw(AssertionError("os.kill on windows")))
    monkeypatch.setattr(runner, "_alive_windows", lambda pid: pid == 42, raising=False)
    assert runner._alive(42) is True and runner._alive(7) is False


def test_alive_posix_still_uses_kill():
    import os

    from orch_scheduler import runner
    assert runner._alive(os.getpid()) and not runner._alive(999999)


def test_failed_run_recorded_and_surfaced(ws, tmp_path):
    import sys
    a = tmp_path / "bad.py"
    a.write_text("import sys; print('Error: login expired, run claude /login'); sys.exit(1)")
    (ws / ".orch/scheduler/config.toml").write_text(f"agent = '{sys.executable} {a} {{prompt}}'\n")
    add_ticket(ws, "t_fail0001", wake_at="2026-11-04T08:00:00Z")
    s = Scheduler(ws)
    s.tick(T(8, 1))
    finish(s, T(8, 2))
    f = load_state(ws)["t_fail0001"]["failed"]
    assert f["exit"] == 1 and "login expired" in f["untrusted_tail"][-1]
    logs = [c["args"][2] for c in calls(ws) if c["args"][0] == "log"]
    assert "Run failed (exit 1). Details in the scheduler log." in logs


def test_success_clears_failed(ws):
    add_ticket(ws, "t_fail0002", wake_at="2026-11-04T08:00:00Z")
    from orch_scheduler.runner import update_state
    update_state(ws, "t_fail0002", failed={"exit": 1, "untrusted_tail": ["x"]})
    s = Scheduler(ws)
    s.tick(T(8, 1))
    finish(s, T(8, 2))
    assert "failed" not in load_state(ws)["t_fail0002"]


def test_failed_run_secret_not_in_ticket_and_redacted_in_state(ws, tmp_path):
    import sys
    a = tmp_path / "leak.py"
    a.write_text("print('Authorization: Bearer abc123def456')\n"
                 "print('clone https://bob:hunter2@example.com/x.git')\n"
                 "print('key sk-ant-api03-ABCDEFGHIJKLMNOP and ghp_ABCDEFGHIJKLMNOPQRSTUV')\n"
                 "print('blob ' + 'a1b2c3d4' * 6)\nraise SystemExit(3)")
    (ws / ".orch/scheduler/config.toml").write_text(f"agent = '{sys.executable} {a} {{prompt}}'\n")
    add_ticket(ws, "t_fail0003", wake_at="2026-11-04T08:00:00Z")
    s = Scheduler(ws)
    s.tick(T(8, 1))
    finish(s, T(8, 2))
    blob = json.dumps(calls(ws))
    for secret in ("abc123def456", "hunter2", "ABCDEFGHIJKLMNOP", "a1b2c3d4a1b2"):
        assert secret not in blob
    tail = " ".join(load_state(ws)["t_fail0003"]["failed"]["untrusted_tail"])
    for secret in ("abc123def456", "hunter2", "ABCDEFGHIJKLMNOP", "a1b2c3d4a1b2"):
        assert secret not in tail
    assert "[redacted]" in tail


def test_failed_start_backs_off_five_minutes(ws):
    (ws / ".orch/scheduler/config.toml").write_text("agent = 'no-such-agent-xyz {prompt}'\n")
    add_ticket(ws, "t_wake022", status="waiting", wake_at="2026-11-04T08:00:00Z")
    s = Scheduler(ws)
    s.tick(T(8, 1))
    n = len([c for c in calls(ws) if c["args"][0] == "log"])
    assert load_state(ws)["t_wake022"]["last_attempt"]
    s.tick(T(8, 4))  # inside 5 minutes: no new attempt
    assert len([c for c in calls(ws) if c["args"][0] == "log"]) == n
    s.tick(T(8, 7))  # after: tries again
    assert len([c for c in calls(ws) if c["args"][0] == "log"]) > n
