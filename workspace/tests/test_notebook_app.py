"""The small orch app on the notebook (ORCH-649): connect, ways in, rules on the notebook, at most once,
self-check."""

import json
import os
import sys
import time

import pytest

from orch import cli
from orch import notebook_app as app
from orch.errors import Refused

PY = sys.executable


@pytest.fixture
def nbhome(tmp_path, monkeypatch):
    h = tmp_path / "nbhome"
    monkeypatch.setenv("ORCH_NOTEBOOK_HOME", str(h))
    for d in ("ways", "skills", "done", "running"):
        (h / d).mkdir(parents=True)
    (h / "connection.json").write_text(
        json.dumps(
            {
                "url": "https://relay.test",
                "notebook": "nb_abcdefghij",
                "token": "orn_" + "x" * 43,
                "workspace": "Pilatus",
            }
        )
    )
    return h


def way(h, slug, actions, selfcheck=None, files=None, name=None):
    d = h / "ways" / slug
    d.mkdir()
    for n, text in (files or {}).items():
        (d / n).write_text(text)
    lines = [f'name = "{name or slug.title()}"']
    if selfcheck:
        lines.append("selfcheck = " + json.dumps(selfcheck))
    lines.append("[actions]")
    lines += [f"{a} = {json.dumps(v)}" for a, v in actions.items()]
    (d / "way.toml").write_text("\n".join(lines) + "\n")
    return d


def ask(way_, action, args=None, aid="m_ask0000000000001", expires=3600):
    return {
        "id": aid,
        "type": "notebook",
        "from": "ws_aaaaaaaaaa",
        "to": "nb_abcdefghij",
        "body": {
            "notebook": {
                "kind": "ask",
                "way": way_,
                "action": action,
                "args": args or {},
                "expires_at": app._iso(time.time() + expires),
            }
        },
    }


ECHO = "import json, sys\nd = json.load(sys.stdin)\nprint('Found: ' + d['args'].get('words', ''))\n"


def test_ping_and_listed_action(nbhome):
    way(nbhome, "notes", {"find": [PY, "./find.py"]}, files={"find.py": ECHO})
    conn = app.connection(nbhome)
    r = app.answer(ask("notebook", "ping"), conn, nbhome)
    assert r["ok"] and "Notebook here" in r["text"] and "1 ways in" in r["text"]
    r = app.answer(ask("notes", "find", {"words": "budget"}), conn, nbhome)
    assert r == {"ok": True, "text": "Found: budget\n"}


def test_only_listed_ways_and_actions_run(nbhome):
    way(nbhome, "notes", {"find": [PY, "./find.py"]}, files={"find.py": ECHO})
    conn = app.connection(nbhome)
    assert "no way in called mail" in app.answer(ask("mail", "find"), conn, nbhome)["refused"]
    assert "does not offer send" in app.answer(ask("notes", "send"), conn, nbhome)["refused"]
    assert not app.answer(ask("notes", "find", expires=-5), conn, nbhome)["ok"]


def test_command_stays_inside_its_folder(nbhome, tmp_path):
    outside = tmp_path / "evil.py"
    outside.write_text("print('ran')")
    way(nbhome, "notes", {"find": [PY, "./find.py"], "up": ["../../evil.py"]}, files={"find.py": ECHO})
    r = app.answer(ask("notes", "up"), app.connection(nbhome), nbhome)
    assert not r["ok"] and "could not be started" in r["refused"]


def test_text_only_size_secrets_time(nbhome, monkeypatch):
    way(
        nbhome,
        "w",
        {
            "bin": [PY, "-c", "import sys; sys.stdout.buffer.write(b'\\xff\\xfe')"],
            "nul": [PY, "-c", "print('a\\x00b')"],
            "big": [PY, "-c", "import sys; sys.stdout.write('x' * 200000)"],
            "secret": [PY, "-c", "print('api_key = sk-ant-api03-' + 'A' * 90)"],
            "fail": [PY, "-c", "import sys; sys.exit(3)"],
            "slow": [PY, "-c", "import time; time.sleep(30)"],
        },
    )
    monkeypatch.setattr(app, "TIMEOUT", 1)
    conn = app.connection(nbhome)
    got = {a: app.answer(ask("w", a), conn, nbhome) for a in ("bin", "nul", "big", "secret", "fail")}
    assert "not text" in got["bin"]["refused"] and "not text" in got["nul"]["refused"]
    assert "64 KB" in got["big"]["refused"]
    assert got["secret"]["refused"] == app.SECRET_REFUSED and "sk-ant" not in json.dumps(got["secret"])
    assert "code 3" in got["fail"]["refused"]
    t0 = time.time()
    code, _ = app.run_command(
        [PY, "-c", "import time; time.sleep(30)"], nbhome / "ways" / "w", {}, nbhome, timeout=1
    )
    assert code == -1 and time.time() - t0 < 10


def test_runs_with_a_small_environment_and_args_on_stdin(nbhome, monkeypatch):
    monkeypatch.setenv("SOME_TOKEN", "should-not-pass")
    way(
        nbhome,
        "w",
        {"env": [PY, "-c", "import os, sys, json; print(json.dumps(sorted(os.environ)) + sys.stdin.read())"]},
    )
    r = app.answer(ask("w", "env", {"q": "a b; rm -rf ~"}), app.connection(nbhome), nbhome)
    assert r["ok"] and "SOME_TOKEN" not in r["text"] and "ORCH_NOTEBOOK_SKILLS" in r["text"]
    assert '"q": "a b; rm -rf ~"' in r["text"]


def test_handle_runs_at_most_once_and_acks_after_the_reply(nbhome, monkeypatch):
    marker = nbhome / "count.txt"
    way(nbhome, "w", {"count": [PY, "-c", f"open({str(marker)!r}, 'a').write('x'); print('done')"]})
    calls = []

    def fake_call(conn, method, path, body=None, timeout=40):
        calls.append((path, body))
        return 201, {}

    monkeypatch.setattr(app, "_call", fake_call)
    conn = app.connection(nbhome)
    a = ask("w", "count")
    app.handle(a, conn, nbhome)
    app.handle(a, conn, nbhome)  # handed out again (at least once): the same reply, not a second run
    assert marker.read_text() == "x"
    sends = [b for p, b in calls if p == "/v1/notebook/send"]
    assert len(sends) == 2 and sends[0] == sends[1] and sends[0]["reply_to"] == a["id"]
    assert [p for p, _ in calls] == ["/v1/notebook/send", "/v1/notebook/ack"] * 2
    # a crash left the request "running": answered "not sure", never run again
    (nbhome / "running" / "m_ask0000000000009").write_text("x")
    app.handle(ask("w", "count", aid="m_ask0000000000009"), conn, nbhome)
    assert marker.read_text() == "x"
    assert calls[-2][1]["notebook"]["refused"] == app.NOT_SURE


def test_reply_not_taken_is_not_acked(nbhome, monkeypatch):
    way(nbhome, "w", {"x": [PY, "-c", "print(1)"]})
    calls = []

    def failing(conn, method, path, body=None, timeout=40):
        calls.append(path)
        e = Refused("relay away")
        e.status = 503
        raise e

    monkeypatch.setattr(app, "_call", failing)
    with pytest.raises(Refused):
        app.handle(ask("w", "x"), app.connection(nbhome), nbhome)
    assert calls == ["/v1/notebook/send"]


def test_self_check_and_status(nbhome, monkeypatch):
    way(
        nbhome,
        "teams",
        {"read": [PY, "-c", "print(1)"]},
        name="Teams",
        selfcheck=[PY, "-c", "import sys; print('The sign-in page showed'); sys.exit(1)"],
    )
    way(nbhome, "notes", {"find": [PY, "-c", "print(1)"]}, selfcheck=[PY, "-c", "print('ok')"])
    res = app.self_check(nbhome)
    by = {r["way"]: r for r in res}
    assert by["notebook"]["ok"] and by["notes"]["ok"] and not by["teams"]["ok"]
    assert by["teams"]["problem"] == "The sign-in page showed"
    sent = []
    monkeypatch.setattr(app, "_call", lambda conn, m, p, b=None, timeout=40: sent.append((p, b)) or (201, {}))
    r = app.answer(ask("notebook", "check"), app.connection(nbhome), nbhome)
    assert r["text"] == "Stopped working: Teams."
    assert sent[0][0] == "/v1/notebook/send" and sent[0][1]["notebook"]["kind"] == "status"


def test_connect_checks_the_address_and_keeps_the_token_private(tmp_path, monkeypatch):
    h = tmp_path / "fresh"
    with pytest.raises(Refused, match="https"):
        app.connect("http://relay.example", "nc_" + "a" * 22, h)
    with pytest.raises(Refused, match="notebook code"):
        app.connect("https://relay.example", "pc_" + "a" * 22, h)
    seen = {}

    def fake(method, url, headers, body, timeout):
        seen.update(url=url, body=body)
        return 201, {
            "notebook_id": "nb_abcdefghij",
            "token": "orn_" + "y" * 43,
            "workspace": {"id": "ws_a", "name": "Pilatus"},
        }

    monkeypatch.setattr(app.net, "call_json", fake)
    c = app.connect("https://relay.example/", "nc_" + "a" * 22, h)
    assert seen["url"] == "https://relay.example/v1/notebook/pair" and "token" not in c
    if os.name == "posix":
        assert oct((h / "connection.json").stat().st_mode & 0o777) == "0o600"
        assert oct(h.stat().st_mode & 0o777) == "0o700"


def test_cli_status_needs_no_workspace(nbhome, capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["notebook", "status"]) == 0
    assert "Connected for Pilatus." in capsys.readouterr().out
    monkeypatch.setenv("ORCH_NOTEBOOK_HOME", str(tmp_path / "none"))
    assert cli.main(["notebook", "status"]) == 0
    assert "Not connected" in capsys.readouterr().out
    assert "notebook" not in __import__("orch.cli", fromlist=["x"]).build_parser(False, None).format_help()
