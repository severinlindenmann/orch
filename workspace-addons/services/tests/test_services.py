"""orch services: records, commands and refusals with a fake platform driver (no launchctl/systemctl here)."""

import json
import plistlib

import pytest
from conftest import CONTRACTS, WID, jrun, validator

SCHEMA = CONTRACTS / "addons" / "services" / "service.schema.json"


def _record(ws, sid):
    return json.loads((ws / ".orch/addons/services/services" / f"{sid}.json").read_text(encoding="utf-8"))


def _add(cli, sid="web", *extra):
    return jrun(cli, "add", "Web preview", "--id", sid, *extra, "--", "python3", "-m", "http.server", "8000")


def test_example_and_written_record_match_the_schema(cli, ws):
    v = validator(SCHEMA)
    example = json.loads((CONTRACTS / "addons/services/files/web-preview.json").read_text(encoding="utf-8"))
    assert not list(v.iter_errors(example))
    code, out = _add(cli, "web", "--port", "8000", "--ticket", "DM1-12", "--auto")
    assert code == 0, out
    rec = _record(ws, "web")
    assert not [e.message for e in v.iter_errors(rec)]
    assert rec["command"] == ["python3", "-m", "http.server", "8000"]
    assert rec["made_by"] == {"ticket": "DM1-12"} and rec["port"] == 8000 and rec["auto"] is True
    assert rec["cwd"] == "."


def test_add_is_stopped_until_started_and_the_whole_cycle_works(cli, ws, fake):
    code, out = _add(cli)
    assert code == 0 and out["service"]["state"] == "stopped"
    assert "orch services start web" in out["next"]
    spec = fake.entries["web"]["spec"]
    assert spec.argv[0].endswith("python3") and spec.argv[0].startswith("/")  # full path for the platform
    assert spec.cwd == ws.resolve() and spec.log == ws / ".orch/addons/services/logs/web.log"
    assert fake.entry_path(spec).is_file()

    code, out = jrun(cli, "start", "web")
    assert code == 0 and out["service"]["state"] == "running" and out["service"]["since"].endswith("Z")
    code, out = jrun(cli, "list")
    row = out["services"][0]
    assert row["state"] == "running" and row["pid"] == 4242 and row["auto"] is False
    code, out = jrun(cli, "stop", "web")
    assert code == 0 and out["service"]["state"] == "stopped" and out["service"]["since"].endswith("Z")
    code, out = jrun(cli, "restart", "web")
    assert code == 0 and out["service"]["state"] == "running"

    code, out = jrun(cli, "auto", "web", "on")
    assert code == 0 and out["service"]["auto"] is True and fake.entries["web"]["auto"] is True
    assert _record(ws, "web")["auto"] is True
    code, out = jrun(cli, "auto", "web", "off")
    assert code == 0 and fake.entries["web"]["auto"] is False and _record(ws, "web")["auto"] is False

    log = ws / ".orch/addons/services/logs/web.log"
    log.write_text("serving\n", encoding="utf-8")
    code, out = jrun(cli, "remove", "web")
    assert code == 0 and out["removed"] == "web"
    assert "web" not in fake.entries and not fake.entry_path(spec).exists()
    assert not (ws / ".orch/addons/services/services/web.json").exists()
    assert (
        log.read_text(encoding="utf-8") == "serving\n"
    )  # the log stays until the id is added again (ORCH-1131)
    assert [c[0] for c in fake.calls] == ["install", "start", "stop", "restart", "auto", "auto", "uninstall"]


def test_a_re_added_id_starts_with_an_empty_log(cli, ws):
    """ORCH-1131: a new service must not show the removed one's lines (maybe secrets) as its own."""
    assert _add(cli)[0] == 0
    log = ws / ".orch/addons/services/logs/web.log"
    log.write_text("old line\n", encoding="utf-8")
    assert jrun(cli, "remove", "web")[0] == 0
    assert log.read_text(encoding="utf-8") == "old line\n"  # remove keeps it
    code, out = _add(cli)
    assert code == 0, out
    assert not log.exists() or log.read_text(encoding="utf-8") == ""
    code, out = jrun(cli, "log", "web")
    assert code == 0 and "old line" not in json.dumps(out)
    kept = list((ws / ".orch/addons/services/logs/removed").glob("web-*.log"))
    assert len(kept) == 1 and kept[0].read_text(encoding="utf-8") == "old line\n"
    # a second round keeps both old logs apart
    log.write_text("second\n", encoding="utf-8")
    assert jrun(cli, "remove", "web")[0] == 0
    code, out = _add(cli)
    assert (
        code == 0 and "empty log" in out["next"] and ".orch/addons/services/logs/removed/web-" in out["next"]
    )
    texts = sorted(
        p.read_text(encoding="utf-8") for p in (ws / ".orch/addons/services/logs/removed").glob("web-*.log")
    )
    assert texts == ["old line\n", "second\n"]


def test_a_new_id_says_nothing_about_an_old_log(cli):
    code, out = _add(cli)
    assert code == 0 and "empty log" not in out["next"]


def test_add_with_start_runs_at_once(cli, fake):
    code, out = _add(cli, "web", "--start")
    assert code == 0 and out["service"]["state"] == "running" and "running" in out["next"]


class _Clock:
    """A clock the settle wait sleeps on, so a 90 second wait costs no time."""

    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, n):
        self.t += n


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr("orch_services.cli.time.monotonic", c.monotonic)
    monkeypatch.setattr("orch_services.cli.time.sleep", c.sleep)
    return c


def test_slow_start_is_waited_for(cli, fake, clock):
    _add(cli)
    fake.start_polls = 50  # about 25 s of launching
    code, out = jrun(cli, "start", "web")
    assert code == 0 and out["service"]["state"] == "running" and out["next"] == "Started Web preview."


def test_start_that_is_still_launching_says_so(cli, fake, clock):
    _add(cli)
    fake.start_polls = 10_000
    code, out = jrun(cli, "start", "web")
    assert code == 0 and "still starting" in out["next"] and "did not stay" not in out["next"]
    assert clock.t >= 90


def test_start_that_never_comes_up_fails_after_a_short_wait(cli, fake, clock):
    _add(cli)
    fake.start_dies = True
    code, out = jrun(cli, "start", "web")
    assert code == 0 and "did not stay running" in out["next"]
    assert 10 <= clock.t < 20  # a few seconds of grace (uv run builds its env first), then the answer


def _flapping(fake, sid, script):
    """The platform starts a job that exits at once again and again (launchd KeepAlive): each status read takes the
    next (running, pid, starting) of the script; the last one repeats."""
    from orch_services.drivers import Status

    plain, left = fake.status, list(script)

    def status(spec):
        if spec.sid != sid:
            return plain(spec)
        on, pid, starting = left.pop(0) if len(left) > 1 else left[0]
        return Status(running=on, pid=pid, starting=starting)

    fake.status = status


@pytest.mark.parametrize("how", ["add", "start"])
def test_a_job_that_exits_at_once_is_never_called_running(cli, fake, clock, how):
    # ORCH-1634: one read landed while launchd had started the job again for a moment and said "it is running"
    if how == "start":
        _add(cli)
    _flapping(fake, "web", [(True, 101, False), (True, 102, False)])  # a new pid: it died and came back
    code, out = _add(cli, "web", "--start") if how == "add" else jrun(cli, "start", "web")
    assert code == 0 and "did not stay running" in out["next"] and "is running" not in out["next"]


@pytest.mark.parametrize("how", ["add", "start"])
def test_a_job_seen_up_and_then_relaunching_did_not_stay(cli, fake, clock, how):
    # ORCH-1634: after the job exited, launchd showed it as launching again and start said "still starting"
    if how == "start":
        _add(cli)
    _flapping(fake, "web", [(True, 101, False), (False, None, True)])
    code, out = _add(cli, "web", "--start") if how == "add" else jrun(cli, "start", "web")
    assert code == 0 and "did not stay running" in out["next"] and "still starting" not in out["next"]
    assert clock.t < 10


def test_a_job_the_platform_keeps_starting_again_did_not_stay(cli, fake, clock):
    # never caught alive, but launchd's `runs` went up twice: it exits at once, it is not a slow start
    _add(cli)
    _flapping(fake, "web", [(False, None, True)])
    reads = iter(range(1, 1000))
    fake.runs = lambda spec: 5 + next(reads) // 4  # 5 before the start, then up by one every few reads
    code, out = jrun(cli, "start", "web")
    assert code == 0 and "did not stay running" in out["next"] and "still starting" not in out["next"]


def test_a_job_that_stays_up_is_running_after_the_hold(cli, fake, clock):
    code, out = _add(cli, "web", "--start")
    assert code == 0 and out["next"].startswith("Added Web preview; it is running.") and clock.t >= 2


def test_a_start_that_stops_names_the_last_log_line(cli, fake, clock, ws):
    # report r-1119-1255-ws-6: start said only "did not stay running"; the log held the reason
    _add(cli)
    fake.name = "launchd"
    plain = fake.start

    def dies_and_writes(spec):
        plain(spec)
        spec.log.parent.mkdir(parents=True, exist_ok=True)
        spec.log.write_text("shell-init: error\ngetcwd: Operation not permitted\n", encoding="utf-8")

    fake.start, fake.start_dies = dies_and_writes, True
    code, out = jrun(cli, "start", "web")
    assert code == 0 and "did not stay running" in out["next"]
    assert "Its log ends with: getcwd: Operation not permitted" in out["next"]
    assert "out of Documents, Desktop" in out["next"] and "orch services log web" in out["next"]


def test_an_old_log_line_is_not_given_as_the_reason(cli, fake, clock, ws):
    import os

    _add(cli)
    log = ws / ".orch/addons/services/logs/web.log"
    log.write_text("an error from last week\n", encoding="utf-8")
    os.utime(log, (1_000_000_000, 1_000_000_000))
    fake.start_dies = True
    code, out = jrun(cli, "start", "web")
    assert code == 0 and "did not stay running" in out["next"] and "last week" not in out["next"]


@pytest.fixture
def mac_documents(ws, tmp_path, monkeypatch):
    """Pretend to be a Mac whose ~/Documents holds the test workspace (a link, so the workspace stays where it is)."""
    from orch import macfolders

    home = tmp_path / "home"
    home.mkdir()
    (home / "Documents").symlink_to(ws.parent, target_is_directory=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Path.home() on Windows
    monkeypatch.setattr(macfolders, "_platform", lambda: "darwin")
    return home


def test_add_is_refused_in_a_mac_protected_folder(cli, fake, ws, mac_documents):
    # report r-1119-1255-ws-6: add accepted a workspace in ~/Documents and the launchd job died at once
    fake.name = "launchd"
    code, out = _add(cli, "web", "--start")
    assert (
        code == 2 and "in Documents" in out["error"] and "macOS does not let background jobs" in out["error"]
    )
    assert "~/code" in out["error"]
    assert fake.calls == [] and not (ws / ".orch/addons/services/services/web.json").exists()


def test_a_program_in_a_mac_protected_folder_is_refused(cli, fake, ws, tmp_path, monkeypatch):
    from orch import macfolders

    home = tmp_path / "home"
    (home / "Desktop").mkdir(parents=True)
    tool = home / "Desktop" / "serve"
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    tool.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Path.home() on Windows
    monkeypatch.setattr(macfolders, "_platform", lambda: "darwin")
    fake.name = "launchd"
    code, out = jrun(cli, "add", "Tool", "--id", "tool", "--", str(tool))
    assert code == 2 and "The program ~/Desktop/serve is in Desktop" in out["error"]


def test_other_casing_of_a_protected_folder_is_refused(tmp_path, monkeypatch):
    # ORCH-1867: ~/documents/work is ~/Documents/work on a case-insensitive Mac; nothing is installed or started
    from orch import macfolders

    from orch_services import cli as services_cli
    from orch_services import drivers

    home = tmp_path / "home"
    (home / "Documents" / "work").mkdir(parents=True)
    (home / "code").mkdir()
    other = home / "documents" / "work"
    if not (other.exists() and other.samefile(home / "Documents" / "work")):
        pytest.skip("this disk tells folder names apart by case")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Path.home() on Windows
    monkeypatch.setattr(macfolders, "_platform", lambda: "darwin")

    class Launchd:
        name = "launchd"

    def spec(cwd):
        return drivers.Spec("web", "Web", WID, ["/bin/echo"], cwd, tmp_path / "web.log", False)

    for cwd in (home / "Documents" / "work", other):
        with pytest.raises(services_cli.Refused, match="in Documents"):
            services_cli._refuse_protected(Launchd(), spec(cwd))
    services_cli._refuse_protected(Launchd(), spec(home / "CODE"))  # a distinct folder is fine


def test_start_is_refused_too_and_other_computers_are_not_asked(cli, fake, ws, mac_documents):
    code, out = _add(cli)  # the fake driver is no launchd: Linux and Windows have no such folders
    assert code == 0
    fake.name = "launchd"
    code, out = jrun(cli, "start", "web")
    assert code == 2 and "in Documents" in out["error"] and ("start", "web") not in fake.calls
    code, out = jrun(cli, "stop", "web")  # stopping and removing always work
    assert code == 0


def test_add_with_start_says_it_was_started(cli, fake, clock):
    fake.start_polls = 10_000
    code, out = _add(cli, "web", "--start")
    assert code == 0 and "was started and is still starting" in out["next"] and "Start it:" not in out["next"]
    fake.start_polls, fake.start_dies = 0, True
    code, out = _add(cli, "api", "--start")
    assert (
        code == 0
        and "started it, but it did not stay running" in out["next"]
        and "Start it:" not in out["next"]
    )


def test_act_verbs_match_the_commands(cli, fake, ws):
    _add(cli)
    for verb, check in (
        ("start", lambda: fake.entries["web"]["running"]),
        ("stop", lambda: not fake.entries["web"]["running"]),
        ("restart", lambda: fake.entries["web"]["running"]),
        ("auto-on", lambda: fake.entries["web"]["auto"]),
        ("auto-off", lambda: not fake.entries["web"]["auto"]),
    ):
        code, out = jrun(cli, "act", verb, "--by", "human:sev", "--", "web")
        assert code == 0, (verb, out)
        assert check(), verb
    code, out = jrun(cli, "act", "remove", "--by", "human:sev", "--", "web")
    assert code == 0 and "web" not in fake.entries


def test_unknown_fields_are_kept(cli, ws):
    _add(cli)
    p = ws / ".orch/addons/services/services/web.json"
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["health"] = {"url": "http://127.0.0.1:8000/"}
    p.write_text(json.dumps(rec), encoding="utf-8")
    assert jrun(cli, "auto", "web", "on")[0] == 0
    assert _record(ws, "web")["health"] == {"url": "http://127.0.0.1:8000/"}


def test_refusals_are_one_sentence_with_the_next_step(cli, ws, fake):
    cases = [
        (("add", "X", "--id", "Bad Id", "--", "python3"), "valid service id"),
        (("add", "X", "--id", "x", "--", "no-such-program-zz"), "Could not find the program"),
        (("add", "X", "--id", "x", "--cwd", "../out", "--", "python3"), "inside this workspace"),
        (("add", "X", "--id", "x", "--cwd", "missing", "--", "python3"), "does not exist"),
        (("add", "X", "--id", "x", "--port", "70000", "--", "python3"), "1 to 65535"),
        (("add", "X", "--id", "x", "--ticket", "NOPE-9", "--", "python3"), "doesn't exist"),
        (("add", "X", "--id", "x"), "Say which command"),
        (("start", "ghost"), "There is no service ghost"),
        (("log", "ghost"), "There is no service ghost"),
        (("stop", "ghost", "--", "x"), "Nothing goes after --"),
    ]
    for argv, words in cases:
        code, out = jrun(cli, *argv)
        assert code == 2 and words in out["error"], (argv, out)
    _add(cli)
    code, out = _add(cli)
    assert code == 2 and "already a service web" in out["error"]
    assert not (ws / ".orch/addons/services/services/x.json").exists()


def test_a_missing_platform_tool_refuses_in_one_sentence(cli, fake, ws):
    fake.unavailable = "systemctl is missing"
    code, out = _add(cli)
    assert code == 2
    assert out["error"] == "This computer cannot keep services running for you: systemctl is missing."
    assert not (ws / ".orch/addons/services/services/web.json").exists()
    code, out = jrun(cli, "list")  # the list still reads the records and says why nothing runs
    assert code == 0 and out["services"] == [] and "cannot keep services" in out["note"]


def test_text_output_and_refusal_on_stderr(cli):
    code, out, err = cli("list")
    assert code == 0 and "No services yet." in out
    code, out, err = cli("start", "ghost")
    assert code == 2 and err.startswith("Refused: There is no service ghost")


def test_log_masks_secrets_and_keeps_plain_lines(cli, ws, stored_keys):
    _add(cli)
    secret = "sk-ant-api03-" + "a1B2c3D4" * 6
    stored_keys["MY_TOKEN"] = "zq-stored-value-81723"
    log = ws / ".orch/addons/services/logs/web.log"
    log.write_text(
        "\n".join(
            [
                "starting server",
                f"using key {secret}",
                "API_KEY=hunter2hunter2hunter2",
                "token from store zq-stored-value-81723 here",
                "listening on 8000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    code, out = jrun(cli, "log", "web")
    assert code == 0
    lines = out["lines"]
    text = "\n".join(lines)
    assert lines[0] == "starting server" and lines[-1] == "listening on 8000"
    for value in (secret, "hunter2hunter2hunter2", "zq-stored-value-81723"):
        assert value not in text
    assert all("••••••" in ln for ln in lines[1:4]), lines
    code, out = jrun(cli, "log", "web", "--lines", "2")
    assert len(out["lines"]) == 2 and out["lines"][-1] == "listening on 8000"
    code, out, _ = cli("log", "web", "--lines", "1")
    assert out.strip() == "listening on 8000"


def test_log_masks_only_the_secret_part_of_a_line(cli, ws, stored_keys):
    """ORCH-933: a key=value secret hides the value, not the whole line (the rest of the log stays useful)."""
    _add(cli)
    stored_keys["MY_TOKEN"] = "zq-stored-value-81723"
    log = ws / ".orch/addons/services/logs/web.log"
    written = [
        "tick 5 password=hunter2isverylong123 TOKEN=abcDEF123456ghiJKL789",
        "tick 6 API_KEY=hunter2hunter2hunter2 done",
        "tick 7 all good [hidden]",
    ]
    log.write_text("\n".join(written) + "\n", encoding="utf-8")
    code, out = jrun(cli, "log", "web")
    assert code == 0
    assert out["lines"] == [
        "tick 5 password=•••••• TOKEN=••••••",
        "tick 6 API_KEY=•••••• done",
        "tick 7 all good [hidden]",
    ], out["lines"]


def test_log_mask_never_shows_part_of_a_value(cli, ws, stored_keys):
    """ORCH-933 review: a quoted value with spaces is hidden whole; dots put in for display never make a stored
    key value appear (a literal [hidden] in the log next to its parts)."""
    _add(cli)
    stored_keys["ODD_KEY"] = "abc••••••def-81723"
    log = ws / ".orch/addons/services/logs/web.log"
    written = [
        'tick 8 password="correct horse battery staple" done',
        "tick 9 password=x1y2z3w4v5 abc[hidden]def-81723",
    ]
    log.write_text("\n".join(written) + "\n", encoding="utf-8")
    code, out = jrun(cli, "log", "web")
    assert code == 0
    text = "\n".join(out["lines"])
    for part in ("horse", "battery", "staple", "abc••••••def"):
        assert part not in text, out["lines"]
    assert out["lines"][0] == "tick 8 password=•••••• done", out["lines"]


def test_log_line_with_a_stored_key_is_hidden_whole(cli, ws, stored_keys):
    """ORCH-933 review: a stored value that itself holds key=value is never cut into shown pieces."""
    _add(cli)
    stored_keys["COMBO"] = "leftpart-81723 password=hunter2isverylong123 rightpart-81723"
    log = ws / ".orch/addons/services/logs/web.log"
    log.write_text(
        "tick 10 leftpart-81723 password=hunter2isverylong123 rightpart-81723\ntick 11 fine\n",
        encoding="utf-8",
    )
    code, out = jrun(cli, "log", "web")
    assert code == 0
    assert out["lines"] == ["••••••", "tick 11 fine"], out["lines"]


def test_view_is_a_valid_page(cli, ws):
    _add(cli, "web", "--start")
    _code, out, _ = cli("view", "--json")
    view = json.loads(out)
    v = validator(CONTRACTS / "addon-view.schema.json")
    assert not [e.message for e in v.iter_errors(view)]
    assert view["blocks"][0]["groups"][0]["items"][0]["title"] == "Web preview"


def test_launchd_plist_quotes_every_path(ws):
    from orch_services.drivers import Spec, launchd

    spec = Spec(
        sid="web",
        name="Web <preview> & co",
        workspace_id=WID,
        argv=["/usr/bin/python3", "-c", "print('a b & <c>')"],
        cwd=ws,
        log=ws / ".orch/addons/services/logs/web.log",
        auto=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    raw = launchd.render(spec)
    d = plistlib.loads(raw)
    assert d["Label"] == f"ch.orch.svc.{WID}.web"
    assert d["ProgramArguments"] == spec.argv and d["WorkingDirectory"] == str(ws)
    assert d["StandardOutPath"] == d["StandardErrorPath"] == str(spec.log)
    assert d["RunAtLoad"] is True
    assert d["KeepAlive"] == {"SuccessfulExit": False}  # after a crash only; exit 0 stays stopped (ORCH-1844)
    assert "wörk space" in d["WorkingDirectory"] and b"&amp;" in raw
    assert launchd.Launchd().entry_path(spec).name == f"ch.orch.svc.{WID}.web.plist"


def test_systemd_unit_quotes_and_escapes(ws):
    from orch_services.drivers import Spec, systemd

    spec = Spec(
        sid="web",
        name="Web 100%",
        workspace_id=WID,
        argv=["/usr/bin/python3", "-c", 'print("a b $HOME 50%")', "back\\slash"],
        cwd=ws,
        log=ws / ".orch/addons/services/logs/web.log",
        auto=False,
        env={"PATH": "/usr/bin:/bin"},
    )
    unit = systemd.render(spec)
    assert 'ExecStart="/usr/bin/python3" "-c" "print(\\"a b $$HOME 50%%\\")" "back\\\\slash"' in unit
    assert f"WorkingDirectory={ws}\n" in unit and "wörk space" in unit
    assert f"StandardOutput=append:{spec.log}\n" in unit and "Restart=on-failure" in unit
    assert "Description=Web 100%% (orch service)" in unit
    assert "User=" not in unit and "sudo" not in unit
    assert systemd.unit_name(spec) == f"orch-svc-{WID}-web.service"


def test_a_service_whose_program_is_gone_can_still_be_stopped_and_removed(cli, ws, fake):
    _add(cli, "web", "--start")
    p = ws / ".orch/addons/services/services/web.json"
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["command"] = ["gone-program-zz"]
    p.write_text(json.dumps(rec), encoding="utf-8")
    assert jrun(cli, "list")[1]["services"][0]["state"] == "running"
    assert jrun(cli, "stop", "web")[0] == 0
    code, out = jrun(cli, "start", "web")
    assert code == 2 and "Could not find the program gone-program-zz" in out["error"]
    assert jrun(cli, "remove", "web")[0] == 0 and not p.exists()


def test_a_secret_in_the_command_is_refused_and_never_shown(cli, ws, fake):
    token = "sk-ant-api03-" + "Zx9Yw8Vu" * 6
    code, out = jrun(cli, "add", "Bot", "--id", "bot", "--", "python3", "bot.py", "--token", token)
    assert code == 2 and "orch secret exec" in out["error"] and token not in json.dumps(out)
    assert not (ws / ".orch/addons/services/services/bot.json").exists() and "bot" not in fake.entries
    _add(cli)  # a record edited by hand afterwards: the word is hidden in every answer
    p = ws / ".orch/addons/services/services/web.json"
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["command"] = ["python3", "bot.py", token]
    p.write_text(json.dumps(rec), encoding="utf-8")
    code, out = jrun(cli, "list")
    assert out["services"][0]["command"] == ["python3", "bot.py", "••••••"]
    for argv in (("start", "web"), ("act", "stop", "--", "web")):
        code, out = jrun(cli, *argv)
        assert code == 0 and token not in json.dumps(out)


def test_hidden_words_cannot_slip_past_the_scan(cli, ws, stored_keys):
    stored_keys["SPLIT"] = "alpha-part-91 beta-part-37"
    _add(cli)
    p = ws / ".orch/addons/services/services/web.json"
    rec = json.loads(p.read_text(encoding="utf-8"))
    token = "sk-ant-api03-" + "Qq7Rr6Ss" * 6
    rec["command"] = ["python3", "x\ny", token, "alpha-part-91", "beta-part-37"]
    p.write_text(json.dumps(rec), encoding="utf-8")
    shown = json.dumps(jrun(cli, "list")[1])
    for word in ("x\\ny", token, "alpha-part-91", "beta-part-37"):
        assert word not in shown
    stored_keys["SPAN"] = "gamma-part-55\ndelta-part-73"  # a stored value over two lines of the log
    log = ws / ".orch/addons/services/logs/web.log"
    log.write_text("ok line\ngamma-part-55\ndelta-part-73\n", encoding="utf-8")
    lines = jrun(cli, "log", "web")[1]["lines"]
    assert "gamma-part-55" not in lines and "delta-part-73" not in lines


def test_add_says_why_even_when_a_word_also_looks_like_a_secret(cli, monkeypatch):
    # ORCH-853: a moved workspace (keys bound to the old folder) plus one flagged word said "holds a secret"
    from orch import keystore, phone_results

    monkeypatch.setattr(phone_results, "value_hider", lambda root: None)

    def refused(root):
        raise keystore.Refused("Refused: this folder's saved keys still belong to /old/ws (moved).")

    monkeypatch.setattr(keystore, "all_needles", refused)
    code, out = jrun(
        cli, "add", "Web", "--id", "web", "--", "python3", "app.py", "password: hunter2-long-value"
    )
    assert code == 2
    assert out["error"] == (
        "Could not compare the command with this workspace's stored keys, because "
        "this folder's saved keys still belong to /old/ws (moved)."
    )


def test_add_says_why_when_the_stored_keys_cannot_be_read(cli, monkeypatch):
    # ORCH-371 bug 10: a harmless command was refused as "holds a secret" when the key store could not be read
    from orch import keystore, phone_results

    monkeypatch.setattr(phone_results, "value_hider", lambda root: None)

    def refused(root):
        raise keystore.Refused("This is a test install outside the test folder.")

    monkeypatch.setattr(keystore, "all_needles", refused)
    code, out = jrun(cli, "add", "Web", "--id", "web", "--", "python3", "-m", "http.server")
    assert code == 2
    assert out["error"] == (
        "Could not compare the command with this workspace's stored keys, because This is a test install outside the test folder."
    )


def test_stop_on_a_stopped_service_says_it_is_already_stopped(cli, fake):
    _add(cli)
    code, out = jrun(cli, "stop", "web")
    assert (
        code == 0
        and out["next"] == "Web preview is already stopped."
        and out["service"]["state"] == "stopped"
    )
    jrun(cli, "start", "web")
    code, out = jrun(cli, "stop", "web")
    assert out["next"] == "Stopped Web preview."


def test_the_log_of_an_adopted_job_without_a_log_file_says_orch_keeps_none(ws):
    from orch_services.cli import no_log_text

    rec = {"id": "j", "name": "Job", "adopted": {"kind": "launchd", "entry": "com.x.job", "path": None}}
    assert no_log_text(rec) == "orch keeps no log for this job."
    assert no_log_text({"id": "w", "name": "Web", "adopted": None}) == "Web has not written anything yet."


def test_a_new_service_with_a_removed_ones_id_starts_with_an_empty_log(cli, ws, fake):
    _add(cli)
    log = ws / ".orch/addons/services/logs/web.log"
    log.write_text("/bin/sh: old/run.sh: Operation not permitted\n", encoding="utf-8")
    assert jrun(cli, "remove", "web")[0] == 0
    _add(cli)
    assert jrun(cli, "log", "web")[1]["lines"] == []


def test_stopping_the_regular_check_says_the_running_services_keep_running(cli, fake, monkeypatch):
    # ORCH-935 point 2: turning Services off said only "The regular check stopped." while the jobs kept running
    from orch_services import service

    monkeypatch.setattr(service, "stop", lambda root: True)
    assert _add(cli, "web", "--start")[0] == 0
    assert _add(cli, "api")[0] == 0  # added, not started
    code, out, _err = cli("stop")
    assert code == 0
    assert out.splitlines() == [
        "The regular check stopped.",
        "1 service keeps running on this computer; orch does not watch it while the check is off.",
    ]
    code, out, _err = cli("stop", "--json")
    assert json.loads(out)["still_running"] == 1


def test_important_marks_the_record_only_and_the_act_verbs_take_it(cli, ws, fake):
    # ORCH-641: a job the person relies on; only the record changes, the job keeps running as it is
    code, out = jrun(
        cli,
        "add",
        "Private network forwarder",
        "--id",
        "fwd",
        "--start",
        "--",
        "python3",
        "-m",
        "http.server",
        "8000",
    )
    assert code == 0, out
    code, out = jrun(cli, "important", "fwd", "on")
    assert code == 0 and out["service"]["important"] is True and "asks once" in out["next"]
    assert _record(ws, "fwd")["important"] is True and out["service"]["state"] == "running"
    code, out = jrun(cli, "act", "important-off", "--", "fwd")
    assert code == 0 and out["service"]["important"] is False
    assert _record(ws, "fwd")["important"] is False
    code, out = jrun(cli, "list")
    assert out["services"][0]["important"] is False


def test_important_works_without_a_working_service_tool(cli, ws, fake, monkeypatch):
    # #2301: only the record changes, yet it saved the change and then reported the tool's refusal
    from orch_services.store import Refused

    assert jrun(cli, "add", "Forwarder", "--id", "fwd", "--", "python3", "-V")[0] == 0

    def broken():
        raise Refused("The service tool of this computer does not answer.")

    monkeypatch.setattr(fake, "check", broken)
    code, out = jrun(cli, "important", "fwd", "on")
    assert code == 0, out
    assert out["service"]["important"] is True and "asks once" in out["next"]
    assert _record(ws, "fwd")["important"] is True


# ---- edges found by the coverage run (ORCH: services test coverage)


def test_an_unreadable_record_is_skipped_in_list_and_named_on_get(cli, ws, fake):
    _add(cli)
    d = ws / ".orch/addons/services/services"
    (d / "broken.json").write_text("{not json", encoding="utf-8")
    (d / "other.json").write_text(
        json.dumps({"schema": "orch.services.service/1", "id": "wrong"}), encoding="utf-8"
    )
    code, out, _err = cli("list")
    assert code == 0 and "web  Web preview" in out
    assert "2 file(s) in .orch/addons/services/services could not be read and are skipped." in out
    code, out = jrun(cli, "start", "broken")
    assert code == 2 and "Fix or delete .orch/addons/services/services/broken.json" in out["error"]


def test_an_empty_workspace_lists_no_services(cli):
    code, out, _err = cli("list")
    assert code == 0 and out.splitlines()[0] == "No services yet."


def test_outside_a_workspace_says_how_to_start(tmp_path, fake, capsys, monkeypatch):
    from orch_services.cli import main

    empty = tmp_path / "kein Ordner ä"
    empty.mkdir()
    monkeypatch.setenv("ORCH_ROOT", str(empty))
    assert main(["list", "--json"]) == 2
    assert "Run orch init first" in json.loads(capsys.readouterr().out)["error"]


def test_a_workspace_without_an_id_says_how_to_get_one(cli, ws):
    (ws / ".orch" / ".local-id").write_text("x\n", encoding="utf-8")
    code, out = _add(cli)
    assert code == 2 and "orch addon add services" in out["error"]


def test_cwd_given_as_a_full_path_inside_the_workspace_is_kept_relative(cli, ws):
    sub = ws / "web app" / "Jörg"
    sub.mkdir(parents=True)
    code, out = _add(cli, "web", "--cwd", str(sub))
    assert code == 0, out
    assert _record(ws, "web")["cwd"] == "web app/Jörg"


def test_cwd_as_a_full_path_outside_the_workspace_is_refused(cli, ws, tmp_path):
    code, out = _add(cli, "web", "--cwd", str(tmp_path))
    assert code == 2 and "inside this workspace" in out["error"]


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="a backslash is a folder separator there")
def test_a_backslash_in_a_folder_name_is_refused_elsewhere(cli, ws):
    (ws / "a\\b").mkdir()
    code, out = _add(cli, "web", "--cwd", "a\\b")
    assert code == 2 and "inside this workspace" in out["error"]


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows paths")
def test_windows_folders_with_backslashes_are_taken(cli, ws):
    # a person on Windows writes C:\Users\Jörg\work space\web app or web app\src (both were refused before)
    (ws / "web app" / "src").mkdir(parents=True)
    code, out = _add(cli, "web", "--cwd", str(ws / "web app"))
    assert code == 0, out
    assert _record(ws, "web")["cwd"] == "web app"
    code, out = _add(cli, "api", "--cwd", "web app\\src")
    assert code == 0, out
    assert _record(ws, "api")["cwd"] == "web app/src"


def test_state_files_that_are_not_an_object_or_a_time_read_as_empty(ws):
    from orch_services import store

    p = store.state_path(ws, "web")
    p.parent.mkdir(parents=True)
    p.write_text("[1, 2]", encoding="utf-8")
    assert store.read_state(ws, "web") == {}
    store.update_state(ws, "web", since="yesterday")
    assert store.last_change(ws, "web") is None
    store.mark(ws, "web", running=True)
    assert store.read_state(ws, "web")["running"] is True and store.last_change(ws, "web")


def test_a_platform_tool_that_is_missing_or_hangs_is_one_sentence(monkeypatch):
    import subprocess

    from orch_services import drivers
    from orch_services.store import Refused

    with pytest.raises(drivers.Unavailable, match="no-such-tool-zz is missing"):
        drivers.run_tool(["/nowhere/no-such-tool-zz"])

    def hang(*a, **k):
        raise subprocess.TimeoutExpired(a[0], 5)

    monkeypatch.setattr(drivers.subprocess, "run", hang)
    with pytest.raises(Refused, match=r"launchctl did not answer within 5 seconds\. Try again"):
        drivers.run_tool(["/bin/launchctl", "print"], timeout=5)


def test_a_failed_tool_names_its_last_line_and_the_next_step():
    import subprocess

    from orch_services import drivers

    cp = subprocess.CompletedProcess([], 1, "", "warning: x\nAccess is denied.\n")
    assert str(drivers.tool_failed("start it", cp)) == (
        "Could not start it (Access is denied.). Run orch services list and try again."
    )
    quiet = subprocess.CompletedProcess([], 1, "", "")
    assert (
        str(drivers.tool_failed("stop it", quiet))
        == "Could not stop it. Run orch services list and try again."
    )


def test_an_unknown_computer_says_it_is_not_supported(monkeypatch):
    from orch_services import drivers

    monkeypatch.setattr(drivers.sys, "platform", "freebsd14")
    with pytest.raises(drivers.Unavailable, match="only macOS, Linux and Windows"):
        drivers.get()
