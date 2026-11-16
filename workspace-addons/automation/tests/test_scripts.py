"""Scripts: a repeat that runs a command from this computer's settings instead of an agent (ORCH-20)."""

import json
import sys
import time

import pytest
from conftest import T, add_ticket, calls, runs_started

from orch_automation import actions, cli, scripts
from orch_automation.loop import Scheduler
from orch_automation.runner import load_state


@pytest.fixture(autouse=True)
def approvals_here(tmp_path, monkeypatch):
    """The per-computer approvals file, in this test's own folder (never the orch home)."""
    monkeypatch.setattr(scripts, "_approvals_path", lambda: tmp_path / "approvals.json")


@pytest.fixture(autouse=True)
def runner_in_a_thread(ws, monkeypatch):
    """The background `orch automation script run` as a thread of this process, so it sees the test's patches.
    (The real spawn's command line is checked in test_the_background_runner_command.)"""
    import threading

    threads = []

    def start(root, tid):
        th = threading.Thread(
            target=cli.main, args=(["--dir", str(root), "script", "run", tid],), daemon=True
        )
        th.start()
        threads.append(th)

    monkeypatch.setattr(scripts, "_start_runner", start)
    yield
    for th in threads:
        th.join(timeout=30)


@pytest.fixture
def person(monkeypatch):
    monkeypatch.setattr(scripts, "an_agent", lambda: None)


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setattr(scripts, "an_agent", lambda: "claude")


def tk(ws, tid):
    return json.loads((ws / f".orch/tickets/{tid}.json").read_text())


def history_rows(ws):
    p = ws / ".orch/addons/automation/runs.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def wait_for(cond, secs=20):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def repeat_ticket(ws, tid, name, **kw):
    return add_ticket(
        ws, tid, ext={"automation": {"recurring": True, "cron": "*/5 * * * *", "script": name}}, **kw
    )


# ---- settings and the trust rule ------------------------------------------------------------------------


def test_a_person_adds_a_script_and_it_is_allowed(ws, person):
    scripts.add(ws, "watch", py("print('hi')") + ["a b", 'q"uote'])
    assert scripts.load(ws) == {"watch": py("print('hi')") + ["a b", 'q"uote']}
    assert scripts.command(ws, "watch") == py("print('hi')") + ["a b", 'q"uote']


def test_an_agents_script_waits_for_a_person(ws, agent, monkeypatch):
    scripts.add(ws, "watch", py("print('hi')"))
    assert scripts.defined(ws, "watch") and scripts.command(ws, "watch") is None
    with pytest.raises(scripts.ScriptError, match="Only a person"):
        scripts.allow(ws, "watch", scripts.key(ws, "watch", py("print('hi')")))
    monkeypatch.setattr(scripts, "an_agent", lambda: None)
    with pytest.raises(scripts.ScriptError, match="changed"):
        scripts.allow(ws, "watch", "0" * 64)
    scripts.allow(ws, "watch", scripts.key(ws, "watch", py("print('hi')")))
    assert scripts.command(ws, "watch") == py("print('hi')")


def test_a_changed_command_asks_again(ws, person):
    scripts.add(ws, "watch", py("print(1)"))
    cfg = ws / ".orch/config.toml"
    cfg.write_text(cfg.read_text().replace("print(1)", "print(2)"))
    assert scripts.defined(ws, "watch") and scripts.command(ws, "watch") is None


def test_a_script_written_into_the_settings_by_hand_or_git_is_not_run(ws):
    (ws / ".orch/config.toml").write_text('[automation.scripts.evil]\ncommand = ["rm", "-rf", "/"]\n')
    assert scripts.defined(ws, "evil") and scripts.command(ws, "evil") is None


def test_names_commands_and_files_are_checked(ws, person):
    for bad in ("Bad", "1x", "a b", "x" * 33):
        with pytest.raises(scripts.ScriptError):
            scripts.add(ws, bad, ["true"])
    with pytest.raises(scripts.ScriptError):
        scripts.add(ws, "empty", [])
    scripts.add(ws, "one", ["true"])
    with pytest.raises(scripts.ScriptError, match="exists already"):
        scripts.add(ws, "one", ["false"])
    (ws / ".orch/config.toml").write_text("not toml [[[")
    with pytest.raises(scripts.ScriptError, match="cannot be read"):
        scripts.add(ws, "two", ["true"])
    assert scripts.load(ws) == {}


def test_other_settings_survive_add_and_remove(ws, person):
    cfg = ws / ".orch/config.toml"
    cfg.write_text('[workspace]\nagent = "claude"\n\n[automation]\ninterval = 30\n')
    scripts.add(ws, "one", ["true"])
    scripts.add(ws, "two", ["false"])
    assert scripts.remove(ws, "one") is True and scripts.remove(ws, "one") is False
    import tomllib

    t = tomllib.loads(cfg.read_text())
    assert t["workspace"]["agent"] == "claude" and t["automation"]["interval"] == 30
    assert list(t["automation"]["scripts"]) == ["two"]


# ---- the scheduler runs a script instead of an agent ----------------------------------------------------


def test_a_due_repeat_runs_its_script_not_an_agent(ws, person):
    out = ws / "ran.txt"
    scripts.add(ws, "watch", py(f"open({str(out)!r}, 'a').write('x')"))
    repeat_ticket(ws, "t_scr00001", "watch")
    s = Scheduler(ws)
    assert s.tick(T(8, 0)) == ["t_scr00001"]
    assert runs_started(ws) == []  # a script, not an agent run
    assert wait_for(lambda: out.exists() and history_rows(ws))
    (row,) = history_rows(ws)
    assert row["ticket"] == "t_scr00001" and row["exit"] == 0
    assert tk(ws, "t_scr00001")["ext"]["automation"]["last_run"] == "2026-11-04T08:00:00Z"
    assert wait_for(lambda: not scripts.busy(ws, "t_scr00001"))
    logs = list((ws / ".orch/run/logs").glob("t_scr00001-script-*.log"))
    assert len(logs) == 1


def test_a_failed_script_asks_once(ws, person):
    scripts.add(ws, "boom", py("import sys; print('broken'); sys.exit(3)"))
    repeat_ticket(ws, "t_scr00002", "boom")
    Scheduler(ws).tick(T(8, 0))
    assert wait_for(lambda: tk(ws, "t_scr00002").get("questions"))
    (q,) = tk(ws, "t_scr00002")["questions"]
    assert q["kind"] == "automation:failure" and "exit code 3" in q["text"]
    assert q["options"] == ["Try again", "Leave it"]
    assert wait_for(lambda: history_rows(ws)) and history_rows(ws)[0]["exit"] == 3


def test_a_script_not_allowed_here_runs_nothing_and_asks(ws, agent):
    out = ws / "ran.txt"
    scripts.add(ws, "watch", py(f"open({str(out)!r}, 'w')"))
    repeat_ticket(ws, "t_scr00003", "watch")
    Scheduler(ws).tick(T(8, 0))
    (q,) = tk(ws, "t_scr00003")["questions"]
    assert "not allowed on this computer" in q["text"]
    time.sleep(0.5)
    assert not out.exists() and runs_started(ws) == []


def test_one_run_per_ticket_at_a_time(ws, person):
    gate = ws / "gate"
    slow = ws / "slow.py"
    slow.write_text(f"import os, time\nwhile not os.path.exists({str(gate)!r}):\n    time.sleep(0.05)\n")
    scripts.add(ws, "slow", [sys.executable, str(slow)])
    repeat_ticket(ws, "t_scr00004", "slow")
    s = Scheduler(ws)
    s.tick(T(8, 0))
    assert wait_for(lambda: scripts.busy(ws, "t_scr00004"))
    s.tick(T(8, 5))  # due again while the first still runs: nothing new
    gate.write_text("")
    assert wait_for(lambda: not scripts.busy(ws, "t_scr00004") and history_rows(ws))
    time.sleep(0.5)
    assert len(history_rows(ws)) == 1


def test_a_finished_script_repeat_is_not_reopened(ws, person):
    scripts.add(ws, "watch", ["true"])
    repeat_ticket(ws, "t_scr00005", "watch", status="done")
    Scheduler(ws).tick(T(8, 0))
    assert tk(ws, "t_scr00005")["status"] == "done"
    assert not any(c["args"][:2] == ["ticket", "status"] for c in calls(ws))
    assert wait_for(lambda: history_rows(ws))


def test_start_now_runs_the_script(ws, person):
    out = ws / "ran.txt"
    scripts.add(ws, "watch", py(f"open({str(out)!r}, 'w')"))
    repeat_ticket(ws, "t_scr00006", "watch")
    res = actions.act(ws, "run", "t_scr00006")
    assert res["result"] == "started" and runs_started(ws) == []
    assert wait_for(out.exists)


def test_a_ticket_with_a_command_as_script_runs_nothing(ws, person):
    add_ticket(
        ws,
        "t_scr00007",
        ext={"automation": {"recurring": True, "cron": "*/5 * * * *", "script": "rm -rf /"}},
    )
    Scheduler(ws).tick(T(8, 0))
    assert runs_started(ws) == ["t_scr00007"]  # not a script name: the ticket is a normal agent repeat
    assert not (ws / ".orch/run/logs").exists() or not list((ws / ".orch/run/logs").glob("*-script-*"))


def test_a_command_that_cannot_be_shown_is_never_allowed(ws, person):
    scripts.add(ws, "multi", py("import os\nprint(1)"))
    assert scripts.defined(ws, "multi") and scripts.command(ws, "multi") is None


# ---- CLI --------------------------------------------------------------------------------------------------


def test_cli_add_repeat_list_remove(ws, person, capsys):
    assert cli.main(["--dir", str(ws), "script", "add", "watch", "--", "echo", "hi"]) == 0
    add_ticket(ws, "t_scr00008")
    assert cli.main(["--dir", str(ws), "repeat", "t_scr00008", "every 5 minutes", "--script", "watch"]) == 0
    a = tk(ws, "t_scr00008")["ext"]["automation"]
    assert a["script"] == "watch" and a["recurring"] is True
    assert cli.main(["--dir", str(ws), "repeat", "t_scr00008", "every 5 minutes", "--script", "nope"]) == 2
    assert (
        cli.main(
            ["--dir", str(ws), "repeat", "t_scr00008", "daily 07:00", "--script", "watch", "--agent", "x"]
        )
        == 2
    )
    capsys.readouterr()
    assert cli.main(["--dir", str(ws), "script", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [
        {"script": "watch", "command": ["echo", "hi"], "allowed": True}
    ]
    assert cli.main(["--dir", str(ws), "script", "remove", "watch"]) == 0
    assert cli.main(["--dir", str(ws), "script", "remove", "watch"]) == 2


def test_cli_agent_add_shows_the_key_and_a_person_allows(ws, agent, monkeypatch, capsys):
    assert cli.main(["--dir", str(ws), "script", "add", "watch", "--json", "--", "true"]) == 0
    capsys.readouterr()
    cli.main(["--dir", str(ws), "script", "list", "--json"])
    (row,) = json.loads(capsys.readouterr().out)
    assert row["allowed"] is False and len(row["key"]) == 64
    assert cli.main(["--dir", str(ws), "script", "allow", "watch", "--key", row["key"]]) == 2  # an agent
    monkeypatch.setattr(scripts, "an_agent", lambda: None)
    assert cli.main(["--dir", str(ws), "script", "allow", "watch", "--key", row["key"]]) == 0
    assert scripts.command(ws, "watch") == ["true"]


def test_cli_script_run_waits_and_reports(ws, person, capsys):
    scripts.add(ws, "watch", py("print('done')"))
    repeat_ticket(ws, "t_scr00009", "watch")
    assert cli.main(["--dir", str(ws), "script", "run", "t_scr00009", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ticket": "t_scr00009", "exit": 0}
    assert history_rows(ws)[0]["exit"] == 0
    assert "t_scr00009" not in load_state(ws) or "script_pid" not in load_state(ws)["t_scr00009"]


def test_the_background_runner_command(ws):
    argv = scripts.runner_argv(ws, "t_scr00010")
    assert argv[0] == sys.executable and argv[1:4] == ["-P", "-m", "orch_automation"]
    assert argv[4:] == ["--dir", str(ws), "script", "run", "t_scr00010"]
