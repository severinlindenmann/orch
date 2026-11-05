import json
from datetime import UTC, datetime

from conftest import T, add_ticket, calls

from orch_scheduler.loop import Scheduler
from orch_scheduler.runner import load_state


def finish(s, now):
    s.runner.reap(now, wait=True)


def test_wake_runs_agent_once(ws):
    add_ticket(ws, "t_wake001", status="waiting", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"})
    s = Scheduler(ws)
    assert s.tick(T(7, 59)) == []
    assert s.tick(T(8, 1)) == ["t_wake001"]
    finish(s, T(8, 2))
    ran = (ws / "ran-t_wake001.txt").read_text()
    assert "Continue orch ticket t_wake001" in ran and ".agents/skills/orch/SKILL.md" in ran
    t = json.loads((ws / ".orch/tickets/t_wake001.json").read_text())
    assert t["waiting_on"] is None and t["status"] == "active"
    cs = calls(ws)
    assert ["ticket", "status", "t_wake001", "active"] in [c["args"] for c in cs]
    assert [c["args"][0] for c in cs].count("log") == 2  # started + finished
    assert all(c["by"] == "agent:scheduler" for c in cs if c["args"][0] == "log")
    assert s.tick(T(8, 5)) == []  # not again
    st = load_state(ws)["t_wake001"]
    assert st["last_exit"] == 0 and st["last_log"].startswith("t_wake001-")


def test_log_has_start_end_exit(ws):
    add_ticket(ws, "t_wake002", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"})
    s = Scheduler(ws)
    s.tick(T(8, 0))
    finish(s, T(8, 1))
    log = next((ws / ".orch/addons/scheduler/logs").glob("t_wake002-*.log")).read_text()
    assert "# start 2026-11-04T08:00:00Z" in log and "agent ran" in log and " exit 0" in log
    # the footer carries the real end time, not the pass start time passed to reap()
    end = next(line for line in log.splitlines() if line.startswith("# end "))
    stamp = datetime.strptime(end.split()[2], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert abs((datetime.now(UTC) - stamp).total_seconds()) < 120


def test_done_ticket_not_woken(ws):
    add_ticket(ws, "t_wake003", status="done", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"})
    assert Scheduler(ws).tick(T(9)) == []


def test_recurring_cron_and_catch_up(ws):
    add_ticket(ws, "t_rec00001", created_at="2026-11-01T00:00:00Z",
               ext={"scheduler": {"recurring": True, "cron": "0 7 * * *"}})
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
    (ws / ".orch/config.toml").write_text(f"[scheduler]\nagent = '{sys.executable} {slow} {{prompt}}'\n")
    add_ticket(ws, "t_rec00002", ext={"scheduler": {"recurring": True, "cron": "* * * * *"}})
    s = Scheduler(ws)
    assert s.tick(T(8, 0)) == ["t_rec00002"]
    assert s.tick(T(8, 1)) == []  # recurring is due again but still running
    finish(s, T(8, 2))
    assert s.tick(T(8, 3)) == ["t_rec00002"]
    finish(s, T(8, 4))


def test_stale_lock_is_ignored(ws):
    add_ticket(ws, "t_wake005", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"})
    (ws / ".orch/addons/scheduler/locks").mkdir(parents=True)
    (ws / ".orch/addons/scheduler/locks/t_wake005.lock").write_text("999999")
    s = Scheduler(ws)
    assert s.tick(T(8, 0)) == ["t_wake005"]
    finish(s, T(8, 1))


def test_agent_exit_code_and_missing_command(ws):
    (ws / ".orch/config.toml").write_text("[scheduler]\nagent = 'no-such-agent-xyz {prompt}'\n")
    add_ticket(ws, "t_wake006", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"})
    s = Scheduler(ws)
    assert s.tick(T(8, 0)) == []
    assert load_state(ws)["t_wake006"]["last_exit"] == 127
    assert not (ws / ".orch/addons/scheduler/locks/t_wake006.lock").exists()


def test_ticket_agent_override_by_name(ws, tmp_path):
    import sys
    other = tmp_path / "other.py"
    other.write_text("open('other.txt', 'w').close()")
    cfg = ws / ".orch/config.toml"
    cfg.write_text(cfg.read_text() + f"[scheduler.agents]\nother = '{sys.executable} {other} {{prompt}}'\n")
    add_ticket(ws, "t_wake007", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"}, ext={"scheduler": {"agent": "other"}})
    s = Scheduler(ws)
    s.tick(T(8, 0))
    finish(s, T(8, 1))
    assert (ws / "other.txt").exists()


def test_cli_run_once_subprocess(ws):
    from orch_scheduler.cli import main
    add_ticket(ws, "t_wake008", waiting_on={"kind": "time", "until": "2020-01-01T00:00:00Z"})
    assert main(["--dir", str(ws), "run", "--once"]) == 0
    assert (ws / "ran-t_wake008.txt").exists()


def test_ticket_cannot_supply_raw_command(ws, tmp_path):
    import sys
    evil = tmp_path / "evil.py"
    evil.write_text("open('evil.txt', 'w').close()")
    add_ticket(ws, "t_wake010", waiting_on={"kind": "time", "until": "2026-11-04T08:00:00Z"},
               ext={"scheduler": {"agent": f"{sys.executable} {evil} {{prompt}}"}})
    s = Scheduler(ws)
    s.tick(T(8, 0))
    finish(s, T(8, 1))
    assert not (ws / "evil.txt").exists() and (ws / "ran-t_wake010.txt").exists()


def test_invalid_ticket_id_skipped(ws):
    (ws / ".orch/tickets/t_bad.json").write_text(
        json.dumps({"id": "t_../../escape", "status": "open", "waiting_on": "2026-11-04T08:00:00Z"}))
    assert Scheduler(ws).tick(T(9)) == []


def test_cron_writes_last_run_to_ext_and_not_again(ws):
    add_ticket(ws, "t_rec00003", ext={"scheduler": {"recurring": True, "cron": "0 7 * * *"}},
               created_at="2026-11-04T00:00:00Z")
    s = Scheduler(ws)
    assert s.tick(T(7, 1)) == ["t_rec00003"]
    finish(s, T(7, 2))
    t = json.loads((ws / ".orch/tickets/t_rec00003.json").read_text())
    assert t["ext"]["scheduler"]["last_run"] == "2026-11-04T07:01:00Z" and t["ext"]["scheduler"]["cron"] == "0 7 * * *"
    assert s.tick(T(9, 0)) == []


def test_not_recurring_flag_means_no_cron_run(ws):
    add_ticket(ws, "t_rec00004", ext={"scheduler": {"recurring": False, "cron": "* * * * *"}})
    assert Scheduler(ws).tick(T(8)) == []


def test_other_waits_are_not_woken(ws):
    add_ticket(ws, "t_wait0001", status="waiting", waiting_on={"kind": "question", "ref": "q1"})
    add_ticket(ws, "t_wait0002", status="waiting", waiting_on={"kind": "time", "until": "2026-11-04T09:00:00Z"})
    assert Scheduler(ws).tick(T(8)) == []


def test_loop_exits_when_not_active(ws):
    (ws / "inactive").write_text("1")
    add_ticket(ws, "t_wake011", waiting_on={"kind": "time", "until": "2020-01-01T00:00:00Z"})
    Scheduler(ws).run_forever(sleep=lambda _: (_ for _ in ()).throw(AssertionError("kept running")))
    assert not (ws / "ran-t_wake011.txt").exists()
