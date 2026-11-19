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
    assert not log.exists()  # the log goes with the service (ORCH-847)
    assert [c[0] for c in fake.calls] == ["install", "start", "stop", "restart", "auto", "auto", "uninstall"]


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
    assert clock.t < 10


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
    assert d["RunAtLoad"] is True and d["KeepAlive"] is True
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


def test_a_new_service_with_an_old_id_starts_with_an_empty_log(cli, ws, fake):
    # ORCH-847: a log left behind by an earlier service of the same id must not show as the new one's log
    log = ws / ".orch/addons/services/logs/web.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("old line from a removed service\n", encoding="utf-8")
    code, _out = _add(cli, "web")
    assert code == 0
    assert not log.exists() or log.read_text(encoding="utf-8") == ""
