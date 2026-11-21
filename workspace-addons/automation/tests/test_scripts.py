"""Scripts: a repeat that runs a command from the local settings instead of an agent (ORCH-20)."""

import json
import sys
import time

import pytest
from conftest import T, add_ticket, calls, runs_started

from orch_automation import actions, cli, scripts
from orch_automation.loop import Scheduler
from orch_automation.runner import load_state


@pytest.fixture(autouse=True)
def allowed_list_here(tmp_path, monkeypatch):
    """The per-computer list of allowed scripts, in this test's own folder (never the orch home)."""
    monkeypatch.setattr(scripts, "_allowed_path", lambda: tmp_path / "allowed.json")


@pytest.fixture(autouse=True)
def runner_in_a_thread(ws, monkeypatch):
    """The background `orch automation script run` as a thread of this process, so it sees the test's patches.
    (The real spawn's command line is checked in test_the_background_runner_command.)"""
    import threading

    threads = []

    def start(root, tid, member=None):
        extra = ["--name", member] if member else []
        th = threading.Thread(
            target=cli.main, args=(["--dir", str(root), "script", "run", tid, *extra],), daemon=True
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
    """Finished lines only: a line still being appended (no newline yet) is not read (ORCH-489)."""
    p = ws / ".orch/addons/automation/runs.jsonl"
    text = p.read_text() if p.exists() else ""
    return [json.loads(x) for x in text[: text.rfind("\n") + 1].splitlines()]


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
    assert ".orch/" not in q["text"] and "boom-output.txt" in q["text"]
    assert "broken" in (ws / "attached.txt").read_text()
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
    go_on = ws / "go_on"
    slow = ws / "slow.py"
    slow.write_text(f"import os, time\nwhile not os.path.exists({str(go_on)!r}):\n    time.sleep(0.05)\n")
    scripts.add(ws, "slow", [sys.executable, str(slow)])
    repeat_ticket(ws, "t_scr00004", "slow")
    s = Scheduler(ws)
    s.tick(T(8, 0))
    assert wait_for(lambda: scripts.busy(ws, "t_scr00004"))
    s.tick(T(8, 5))  # due again while the first still runs: nothing new
    go_on.write_text("")
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


# ---- the dashboard's Allow this script ---------------------------------------------------------------------


def test_review_shows_the_command_and_binds_the_key(ws, agent):
    scripts.add(ws, "watch", ["echo", "hi there"])
    repeat_ticket(ws, "t_scr00011", "watch")
    r = actions.review(ws, "allow-script", "t_scr00011")
    k = scripts.key(ws, "watch", ["echo", "hi there"])
    assert r["target"] == f"automation:t_scr00011:{k}"
    assert r["review"]["value"] == "echo 'hi there'" and "without a helper" in r["review"]["body"]
    assert actions.review(ws, "run", "t_scr00011") == {"target": None, "review": None}


def test_allow_script_from_the_dashboard_allows_only_what_was_shown(ws, agent, monkeypatch):
    scripts.add(ws, "watch", ["true"])
    repeat_ticket(ws, "t_scr00012", "watch")
    k = scripts.key(ws, "watch", ["true"])
    with pytest.raises(actions.Bad, match="Only a person"):  # an agent calling act itself
        actions.act(ws, "allow-script", "t_scr00012", value=k)
    monkeypatch.setattr(
        scripts, "an_agent", lambda: None
    )  # the dashboard runs it without the agent's variables
    with pytest.raises(actions.Bad, match="Look at the command again"):
        actions.act(ws, "allow-script", "t_scr00012", value="bad")
    with pytest.raises(actions.Bad, match="changed"):
        actions.act(ws, "allow-script", "t_scr00012", value="0" * 64)
    assert actions.act(ws, "allow-script", "t_scr00012", value=k)["allowed"] is True
    assert scripts.command(ws, "watch") == ["true"]
    with pytest.raises(actions.Bad, match="already allowed"):
        actions.review(ws, "allow-script", "t_scr00012")


def test_the_automation_tab_offers_allow_until_the_script_is_allowed(ws, agent, monkeypatch):
    from orch_automation.view import build

    scripts.add(ws, "watch", ["true"])
    repeat_ticket(ws, "t_scr00013", "watch")

    from test_view import check

    def row():
        v = build(ws, T(8))
        check(v)  # the view still matches the dashboard's block schema
        (table,) = [b for b in v["blocks"] if b.get("type") == "table"]
        (r,) = table["rows"]
        return r

    r = row()
    assert r["subtitle"] == "Runs watch"
    assert r["actions"][0] == {
        "label": "Allow this script",
        "action": {
            "op": "addon.act",
            "args": {"verb": "allow-script", "target": "t_scr00013", "review": True},
        },
    }
    monkeypatch.setattr(scripts, "an_agent", lambda: None)
    actions.act(ws, "allow-script", "t_scr00013", value=scripts.key(ws, "watch", ["true"]))
    assert row()["actions"][0]["label"] == "Start now"


def test_cli_act_proof_target_prints_the_review(ws, agent, capsys):
    scripts.add(ws, "watch", ["true"])
    repeat_ticket(ws, "t_scr00014", "watch")
    assert cli.main(["--dir", str(ws), "act", "allow-script", "t_scr00014", "--proof-target"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["target"].endswith(scripts.key(ws, "watch", ["true"])) and out["review"]["title"]


def test_the_shown_command_maps_back_to_one_argv():
    assert scripts.shown(["rm -rf ~"]) != scripts.shown(["rm", "-rf", "~"])
    import shlex

    for argv in (["rm -rf ~"], ["a", "b c", "it's"], ["python3", "-c", "print(1)"]):
        assert shlex.split(scripts.shown(argv)) == argv


# ---- one repeat for a group of scripts, each on its own plan (ORCH-348) ------------------------------------


def group_ticket(ws, tid, group, **kw):
    return add_ticket(
        ws, tid, ext={"automation": {"recurring": True, "cron": "*/5 * * * *", "group": group}}, **kw
    )


def test_a_group_runs_each_script_on_its_own_plan(ws, person):
    for n in ("fast", "slow"):
        scripts.add(ws, n, py(f"open({str(ws / n)!r}, 'a').write('x')"))
    group_ticket(ws, "t_grp00001", {"fast": "*/5 * * * *", "slow": "0 * * * *"})
    s = Scheduler(ws)
    assert s.tick(T(8, 1)) == ["t_grp00001"]  # both due at 08:00
    assert wait_for(lambda: len(history_rows(ws)) == 2)
    assert {r["script"] for r in history_rows(ws)} == {"fast", "slow"}
    assert runs_started(ws) == []
    assert wait_for(lambda: not scripts.busy(ws, "t_grp00001", "fast"))
    s.tick(T(8, 6))  # only fast is due again
    assert wait_for(lambda: len(history_rows(ws)) == 3)
    time.sleep(0.3)
    assert [r["script"] for r in history_rows(ws)][-1] == "fast" and len(history_rows(ws)) == 3
    assert (ws / "fast").read_text() == "xx" and (ws / "slow").read_text() == "x"
    assert s.tick(T(8, 7)) == []  # nothing due
    assert tk(ws, "t_grp00001")["ext"]["automation"]["last_run"] == "2026-11-04T08:06:00Z"
    logs = list((ws / ".orch/run/logs").glob("t_grp00001-script-fast-*.log"))
    assert logs


def test_a_slow_script_of_a_group_never_holds_back_the_others(ws, person):
    go_on = ws / "go_on"
    slow = ws / "slow.py"
    slow.write_text(f"import os, time\nwhile not os.path.exists({str(go_on)!r}):\n    time.sleep(0.05)\n")
    scripts.add(ws, "slow", [sys.executable, str(slow)])
    scripts.add(ws, "fast", py(f"open({str(ws / 'fast')!r}, 'a').write('x')"))
    group_ticket(ws, "t_grp00002", {"fast": "*/5 * * * *", "slow": "*/5 * * * *"})
    s = Scheduler(ws)
    s.tick(T(8, 1))
    assert wait_for(lambda: scripts.busy(ws, "t_grp00002", "slow"))
    assert wait_for(lambda: (ws / "fast").exists() and not scripts.busy(ws, "t_grp00002", "fast"))
    s.tick(T(8, 6))  # slow still runs: only fast starts again
    assert wait_for(lambda: (ws / "fast").read_text() == "xx")
    go_on.write_text("")
    assert wait_for(lambda: not scripts.busy(ws, "t_grp00002", "slow"))
    time.sleep(0.3)
    assert [r["script"] for r in history_rows(ws)].count("slow") == 1


def test_a_failing_script_of_a_group_asks_once_with_its_name(ws, person):
    scripts.add(ws, "boom", py("import sys; sys.exit(4)"))
    group_ticket(ws, "t_grp00003", {"boom": "*/5 * * * *"})
    Scheduler(ws).tick(T(8, 0))
    assert wait_for(lambda: tk(ws, "t_grp00003").get("questions"))
    (q,) = tk(ws, "t_grp00003")["questions"]
    assert "boom" in q["text"] and "exit code 4" in q["text"]


def test_a_group_with_a_script_not_set_up_here_asks(ws, person):
    group_ticket(ws, "t_grp00004", {"gone": "*/5 * * * *"})
    Scheduler(ws).tick(T(8, 0))
    (q,) = tk(ws, "t_grp00004")["questions"]
    assert "gone" in q["text"] and "no script named gone" in q["text"]


def test_a_group_entry_with_a_command_or_a_bad_rule_is_ignored(ws, person):
    out = ws / "ran.txt"
    scripts.add(ws, "watch", py(f"open({str(out)!r}, 'w')"))
    group_ticket(ws, "t_grp00005", {"rm -rf ~": "*/5 * * * *", "watch": "not a rule"})
    assert Scheduler(ws).tick(T(8, 0)) == []
    time.sleep(0.3)
    assert not out.exists()


def test_cli_makes_a_group_and_lists_one_repeat(ws, person, capsys):
    for n in ("watcher", "reviewer", "tester"):
        assert cli.main(["--dir", str(ws), "script", "add", n, "--", "true"]) == 0
    add_ticket(ws, "t_grp00006")
    args = ["--dir", str(ws), "repeat", "t_grp00006", "every 5 minutes", "--script", "watcher"]
    args += ["--script", "reviewer=every 15 minutes", "--script", "tester=daily 06:30", "--json"]
    capsys.readouterr()
    assert cli.main(args) == 0
    res = json.loads(capsys.readouterr().out)
    a = tk(ws, "t_grp00006")["ext"]["automation"]
    assert a["group"] == {"watcher": "*/5 * * * *", "reviewer": "*/15 * * * *", "tester": "30 6 * * *"}
    assert "script" not in a and res["group"] == a["group"]
    rows = cli.describe(ws)
    assert {r["ticket"] for r in rows} == {"t_grp00006"}
    assert [r["kind"] for r in rows].count("repeat") == 1  # one repeat, plus a row per script (own plan)
    bad = ["--dir", str(ws), "repeat", "t_grp00006", "every 5 minutes", "--script", "watcher"]
    assert cli.main([*bad, "--script", "nope=every 15 minutes"]) == 2
    assert cli.main([*bad, "--script", "reviewer=whenever"]) == 2
    # one script on the repeat's own plan is a plain script repeat again
    assert cli.main(bad) == 0
    a = tk(ws, "t_grp00006")["ext"]["automation"]
    assert a["script"] == "watcher" and "group" not in a


def test_cli_script_run_name_runs_one_script_of_the_group(ws, person, capsys):
    scripts.add(ws, "watch", py("print('done')"))
    group_ticket(ws, "t_grp00007", {"watch": "*/5 * * * *"})
    assert cli.main(["--dir", str(ws), "script", "run", "t_grp00007", "--name", "watch", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ticket": "t_grp00007", "exit": 0}
    assert history_rows(ws)[0]["script"] == "watch"
    assert cli.main(["--dir", str(ws), "script", "run", "t_grp00007", "--name", "other"]) == 2


def test_the_background_runner_command_of_a_group_script(ws):
    argv = scripts.runner_argv(ws, "t_grp00008", "watch")
    assert argv[4:] == ["--dir", str(ws), "script", "run", "t_grp00008", "--name", "watch"]


def test_start_now_runs_every_script_of_the_group(ws, person):
    for n in ("a", "b"):
        scripts.add(ws, n, py(f"open({str(ws / n)!r}, 'w')"))
    group_ticket(ws, "t_grp00009", {"a": "0 6 * * *", "b": "0 7 * * *"})
    r = actions.act(ws, "run", "t_grp00009")
    assert r["result"] == "started"
    assert wait_for(lambda: (ws / "a").exists() and (ws / "b").exists())


def test_the_tab_offers_allow_for_the_first_script_of_a_group_not_allowed(ws, agent, monkeypatch):
    scripts.add(ws, "a", ["true"])
    scripts.add(ws, "b", ["echo", "b"])
    monkeypatch.setattr(scripts, "an_agent", lambda: None)
    scripts.allow(ws, "a", scripts.key(ws, "a", ["true"]))
    group_ticket(ws, "t_grp00010", {"a": "*/5 * * * *", "b": "*/5 * * * *"})
    r = actions.review(ws, "allow-script", "t_grp00010")
    assert r["review"]["value"] == "echo b"
    key = r["target"].rsplit(":", 1)[1]
    actions.act(ws, "allow-script", "t_grp00010", value=key)
    assert scripts.command(ws, "b") == ["echo", "b"]


def test_a_quiet_group_still_records_its_pass(ws, person):
    scripts.add(ws, "daily", ["true"])
    group_ticket(ws, "t_grp00011", {"daily": "30 6 * * *"})
    s = Scheduler(ws)
    s.tick(T(6, 31))  # first pass: the daily one is due once
    assert s.tick(T(8, 1)) == []  # the repeat looks every 5 minutes; nothing due
    assert tk(ws, "t_grp00011")["ext"]["automation"]["last_run"] == "2026-11-04T08:01:00Z"
    assert s.tick(T(8, 2)) == []  # between two passes: not even looked at
    assert tk(ws, "t_grp00011")["ext"]["automation"]["last_run"] == "2026-11-04T08:01:00Z"


def test_cli_script_run_without_name_runs_the_whole_group(ws, person, capsys):
    for n in ("a", "b"):
        scripts.add(ws, n, py(f"open({str(ws / n)!r}, 'a').write('x')"))
    group_ticket(ws, "t_grp00020", {"a": "*/5 * * * *", "b": "0 * * * *"})
    assert cli.main(["--dir", str(ws), "script", "run", "t_grp00020", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "ticket": "t_grp00020",
        "exit": 0,
        "scripts": {"a": 0, "b": 0},
    }
    assert {r["script"] for r in history_rows(ws)} == {"a", "b"}


def test_cli_script_run_of_a_group_fails_when_one_script_fails(ws, person, capsys):
    scripts.add(ws, "ok", py("pass"))
    scripts.add(ws, "bad", py("raise SystemExit(3)"))
    group_ticket(ws, "t_grp00021", {"ok": "*/5 * * * *", "bad": "0 * * * *"})
    assert cli.main(["--dir", str(ws), "script", "run", "t_grp00021", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["scripts"] == {"bad": 3, "ok": 0}


def test_list_shows_each_script_of_a_group_with_its_own_plan(ws, person, capsys):
    group_ticket(ws, "t_grp00022", {"fast": "*/5 * * * *", "slow": "0 6 * * *"})
    assert cli.main(["--dir", str(ws), "list", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    by = {r["script"]: r for r in rows if r["kind"] == "script"}
    assert by["fast"]["cron"] == "*/5 * * * *" and by["slow"]["cron"] == "0 6 * * *"
    assert cli.main(["--dir", str(ws), "list"]) == 0
    assert "script slow" in capsys.readouterr().out
