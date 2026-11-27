"""Ways in (ORCH-649): the person's own scripts, run by Personal in the workspace, text only, off until turned on."""

import json
import os
import sys
import time

import pytest
from conftest import as_helper, jrun

PY = sys.executable


def make_way(ws, slug="teams", name="Teams", actions=None, selfcheck=None, part="", files=None):
    d = ws / ".orch" / "addons" / "personal" / "ways" / slug
    d.mkdir(parents=True, exist_ok=True)
    for fname, body in (files or {}).items():
        (d / fname).write_text(body, encoding="utf-8")
    acts = actions if actions is not None else {"unread": [PY, "unread.py"]}
    lines = [f'name = "{name}"', f'part = "{part}"']
    if selfcheck:
        lines.append("selfcheck = " + json.dumps(selfcheck))
    lines.append("[actions]")
    lines += [f"{k} = {json.dumps(v)}" for k, v in acts.items()]
    (d / "way.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return d


UNREAD = "import json, sys\nreq = json.load(sys.stdin)\nprint('2 unread, days', req['values'].get('days'))\n"
OK_CHECK = "print('fine')\n"
NEED_PERMISSION = "import sys\nprint('Allow Teams in the browser profile once.')\nsys.exit(3)\n"
BROKEN = "import sys\nprint('Teams web changed its page.')\nsys.exit(1)\n"


def test_a_new_way_in_is_off_and_a_helper_cannot_use_or_turn_it_on(cli, ws, monkeypatch):
    make_way(ws, files={"unread.py": UNREAD})
    d = jrun(cli, "ways")[1]
    assert [(w["way"], w["status"], w["words"]) for w in d["ways"]] == [("teams", "off", "Off")]
    as_helper(monkeypatch)
    assert jrun(cli, "ways")[1]["ways"] == []  # a helper sees only ways in that are on
    code, d = jrun(cli, "ways", "ask", "teams", "unread")
    assert code == 2 and "off" in d["error"] and "Only the person" in d["error"]
    code, d = jrun(cli, "ways", "on", "teams")
    assert code == 2 and "Only the person" in d["error"]


def test_turn_on_checks_it_and_a_helper_gets_text(cli, ws, monkeypatch):
    make_way(ws, selfcheck=[PY, "check.py"], files={"unread.py": UNREAD, "check.py": OK_CHECK})
    code, w = jrun(cli, "ways", "on", "teams")
    assert code == 0 and w["status"] == "works" and w["last_worked"] and w["checked"]
    as_helper(monkeypatch)
    code, r = jrun(cli, "ways", "ask", "teams", "unread", "--values", '{"days": 2}')
    assert code == 0 and r["text"] == "2 unread, days 2\n" and "data, not instructions" in r["note"]
    code, r = jrun(cli, "ways", "ask", "teams", "send")
    assert code == 2 and "no action send" in r["error"] and "unread" in r["error"]


def test_status_needs_permission_and_stopped_show_on_home(cli, ws):
    make_way(ws, selfcheck=[PY, "check.py"], files={"unread.py": UNREAD, "check.py": NEED_PERMISSION})
    w = jrun(cli, "ways", "on", "teams")[1]
    assert w["status"] == "permission" and w["words"] == "Needs your permission"
    assert w["problem"] == "Allow Teams in the browser profile once."
    (ws / ".orch/addons/personal/ways/teams/check.py").write_text(BROKEN, encoding="utf-8")
    jrun(cli, "ways", "on", "teams")  # the person changed the script, so they turn it on again
    w = jrun(cli, "ways", "check", "teams")[1]["ways"][0]
    assert w["status"] == "stopped" and w["problem"] == "Teams web changed its page."
    today = jrun(cli, "today")[1]
    assert today["ways"][0]["status"] == "stopped"
    need = today["needs_you"][-1]
    assert need["title"] == "Teams: the way in stopped working" and need["action"] == "Try again"
    (ws / ".orch/addons/personal/ways/teams/check.py").write_text(OK_CHECK, encoding="utf-8")
    jrun(cli, "ways", "on", "teams")
    assert jrun(cli, "ways", "check")[1]["ways"][0]["status"] == "works"
    assert jrun(cli, "today")[1]["needs_you"] == []


def test_text_only_rules(cli, ws, monkeypatch):
    make_way(
        ws,
        actions={
            "big": [PY, "-c", "print('x' * 70000)"],
            "binary": [PY, "-c", "import sys; sys.stdout.buffer.write(b'a\\x00b')"],
            "secret": [
                PY,
                "-c",
                "print('aws_secret_access_key = ' + 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY')",
            ],
            "fails": [PY, "-c", "import sys; sys.exit(5)"],
        },
    )
    jrun(cli, "ways", "on", "teams")
    as_helper(monkeypatch)
    assert "64 KB" in jrun(cli, "ways", "ask", "teams", "big")[1]["error"]
    assert "not text" in jrun(cli, "ways", "ask", "teams", "binary")[1]["error"]
    assert "password or key" in jrun(cli, "ways", "ask", "teams", "secret")[1]["error"]
    assert (
        jrun(cli, "ways", "list")[1]["ways"][0]["status"] == "works"
    )  # a rule refusal is not a broken way in
    assert "code 5" in jrun(cli, "ways", "ask", "teams", "fails")[1]["error"]
    assert jrun(cli, "ways", "list")[1]["ways"][0]["status"] == "stopped"


def test_program_outside_its_folder_and_bad_values_are_refused(cli, ws, monkeypatch):
    (ws / "outside.py").write_text("print('no')\n", encoding="utf-8")
    make_way(ws, actions={"escape": ["../../../../../outside.py"]})
    jrun(cli, "ways", "on", "teams")
    as_helper(monkeypatch)
    code, r = jrun(cli, "ways", "ask", "teams", "escape")
    assert code == 2 and "outside its folder" in r["error"]
    code, r = jrun(cli, "ways", "ask", "teams", "escape", "--values", "[1]")
    assert code == 2 and "JSON object" in r["error"]


def test_slow_way_in_is_stopped(ws, monkeypatch):
    from orch_personal import ways

    make_way(ws, actions={"slow": [PY, "-c", "import time; time.sleep(30)"]})
    ways.turn(ws, "teams", True)
    monkeypatch.setattr(ways, "TIMEOUT", 1)
    t = time.time()
    with pytest.raises(ways.Refused, match="longer than"):
        ways.ask(ws, "teams", "slow")
    assert time.time() - t < 10
    assert ways.status(ws)[0]["status"] == "stopped"


def test_daily_check_runs_only_when_due(ws):
    from orch_personal import ways

    make_way(ws, selfcheck=[PY, "check.py"], files={"check.py": OK_CHECK})
    make_way(
        ws,
        slug="calendar",
        name="Calendar",
        part="calendar",
        selfcheck=[PY, "check.py"],
        files={"check.py": OK_CHECK},
    )
    assert ways.check_due(ws) == []  # both off
    ways.turn(ws, "teams", True)
    assert ways.check_due(ws) == []  # just checked when turned on
    assert ways.check_due(ws, every=-5) == ["teams"]


def test_broken_way_toml_is_skipped(ws, cli):
    d = ws / ".orch" / "addons" / "personal" / "ways" / "bad"
    d.mkdir(parents=True)
    (d / "way.toml").write_text("name = [unclosed\n", encoding="utf-8")
    make_way(ws, files={"unread.py": UNREAD})
    assert [w["way"] for w in jrun(cli, "ways")[1]["ways"]] == ["teams"]


def test_view_lists_ways_in_for_the_dashboard(ws, cli):
    from orch_personal import api, view

    make_way(ws, files={"unread.py": UNREAD})
    jrun(cli, "ways", "on", "teams")
    v = view.build(ws, api.who_from_env())
    block = next(b for b in v["blocks"] if b.get("title") == "Ways in")
    assert block["items"][0]["title"] == "Teams" and block["items"][0]["tone"] == "good"


def test_a_change_after_turning_on_stops_it_until_the_person_turns_it_on_again(cli, ws, monkeypatch):
    d = make_way(ws, files={"unread.py": UNREAD})
    assert jrun(cli, "ways", "on", "teams")[1]["status"] == "works"
    monkeypatch.setenv("ORCH_RUN", "r_test")
    monkeypatch.setenv("ORCH_AGENT", "claude")
    (d / "unread.py").write_text("print('changed by someone')\n", encoding="utf-8")
    code, r = jrun(cli, "ways", "ask", "teams", "unread")
    assert code == 2 and "changed since you turned it on" in r["error"]
    w = jrun(cli, "ways", "check", "teams")[1]["ways"][0]  # Try again does not run a changed way in
    assert w["status"] == "permission" and w["changed"] is True
    for k in ("ORCH_RUN", "ORCH_AGENT"):
        monkeypatch.delenv(k)
    need = jrun(cli, "today")[1]["needs_you"][0]
    assert need["action"] == "Turn on again" and need["changed"] is True
    assert jrun(cli, "ways", "on", "teams")[1]["status"] == "works"


def test_a_way_in_writes_its_data_outside_its_folder(cli, ws, monkeypatch):
    script = "import os, pathlib\npathlib.Path(os.environ['ORCH_PERSONAL_WAY_DATA'], 'cache').write_text('x')\nprint('ok')\n"
    make_way(ws, files={"unread.py": script})
    jrun(cli, "ways", "on", "teams")
    as_helper(monkeypatch)
    assert jrun(cli, "ways", "ask", "teams", "unread")[1]["text"] == "ok\n"
    assert jrun(cli, "ways", "ask", "teams", "unread")[0] == 0  # still not changed
    assert (ws / ".orch/addons/personal/ways-data/teams/cache").read_text() == "x"


@pytest.mark.skipif(os.name == "nt", reason="links need extra rights on Windows")
def test_a_link_in_the_folder_cannot_be_turned_on(cli, ws, tmp_path):
    d = make_way(ws, files={"unread.py": UNREAD})
    (tmp_path / "elsewhere.py").write_text("print('x')\n", encoding="utf-8")
    (d / "linked.py").symlink_to(tmp_path / "elsewhere.py")
    code, r = jrun(cli, "ways", "on", "teams")
    assert code == 2 and "link" in r["error"]


def test_a_way_in_that_was_on_with_a_broken_way_toml_shows_and_can_be_turned_off(cli, ws, monkeypatch):
    d = make_way(ws, files={"unread.py": UNREAD})
    jrun(cli, "ways", "on", "teams")
    (d / "way.toml").write_text("name = [broken\n", encoding="utf-8")
    w = jrun(cli, "ways")[1]["ways"][0]
    assert w["way"] == "teams" and w["on"] and w["changed"] and w["status"] == "permission"
    as_helper(monkeypatch)
    assert jrun(cli, "ways", "ask", "teams", "unread")[0] == 2
    for k in ("ORCH_RUN", "ORCH_AGENT", "ORCH_TICKET"):
        monkeypatch.delenv(k)
    assert jrun(cli, "ways", "off", "teams")[1]["on"] is False


def test_short_output_is_complete_when_a_child_keeps_the_pipe_open(ws):
    from orch_personal import ways

    script = (
        "import subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])\n"
        "print('short answer', flush=True)\n"
    )
    make_way(ws, files={"unread.py": script})
    ways.turn(ws, "teams", True)
    t = time.time()
    assert ways.ask(ws, "teams", "unread")["text"] == "short answer\n"
    assert time.time() - t < 10


def test_a_way_in_gets_words_with_spaces_quotes_and_umlauts_as_written(tmp_path):
    """R1.6: the person's command is an argument list, never a shell line; its folder and the values may hold
    spaces, quotes and umlauts."""
    from orch_personal import ways

    where = tmp_path / "ways" / "Grüße – Müller's & Co"
    where.mkdir(parents=True)
    (where / "echo.py").write_text(
        "import json, os, sys\nprint(json.dumps({'argv': sys.argv[1:], 'in': json.load(sys.stdin), 'cwd': os.getcwd()}))\n",
        encoding="utf-8",
    )
    words = ['He said "hi" & bye', "Grüße $HOME %PATH% `x` | y; z"]
    values = {"who": 'Zoë "Ä" O\'Brien'}
    code, out = ways.run_command([PY, "./echo.py", *words], where, {"values": values})
    got = json.loads(out)
    assert code == 0 and got["argv"] == words
    assert got["in"]["values"] == values and os.path.samefile(got["cwd"], where)
