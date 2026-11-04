import json

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
    assert ["ticket", "status", "t_wake001", "active"] in [c["args"] for c in cs]
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
    assert "# start 2026-11-04T08:00:00Z" in log and "agent ran" in log and "# end 2026-11-04T08:01:00Z exit 0" in log


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
